"""O quadro de um projeto num instante, renderizado pelo pipeline de verdade (para o editor mostrar o resultado).

O editor desenha uma composição aproximada na tela e, quando a pessoa solta um gesto, pede este quadro: o mesmo
que o render faria naquele instante, na resolução da prévia e sem áudio. Para ser rápido ele não monta o vídeo:
só os trechos que aparecem no instante têm o mezanino gerado (os de fora são apenas planejados), as composições
em HTML vão direto ao instante e o recorte da pessoa cobre só aquele quadro. O resto é o caminho do render:
as fontes, as sobreposições, a camada de texto e o grafo da montagem são os mesmos.

Fica de fora o que não existe sem chamar um modelo pesado ou sem áudio, e o quadro diz o quê (`notes`): a legenda
automática sem transcrição em cache (nada de Whisper aqui), a legenda da narração e o audiograma.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .. import config
from ..domain.presets import get_preset
from ..domain.spec import HtmlOverlay, Project, Transition
from ..domain.timeline import frame_range, instant_window, transitions_of
from ..domain.tracks import apply_track_state
from ..filtergraph.html_layer import ResolvedHtmlLayer
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner, SubprocessRunner, format_cmd
from ..media.html_render import HtmlRenderer
from ..media.html_site import composition_files
from ..media.matting import Matter, RvmMatter
from ..media.probe import probe
from .assembly import Assembly
from .audio_effects import effect_processor
from .captions import CaptionPipeline, TranscriberFactory, default_transcriber_factory
from .context import Prober, RenderContext, RenderOptions
from .html_layer import HtmlLayerBuilder, ResolvedHtmlOverlay
from .instant_assembly import build_instant_assembly
from .isolation import IsolationService
from .layout import ProjectLayout, project_layout
from .missing import media_references
from .person_layer import PersonLayerBuilder, PreparedPersonLayer
from .preview_audio import file_stamp
from .segments import MezzanineBuilder, PreparedSegment, cache_key
from .sync import OffsetFinder
from .textlayer import build_text_layer
from .voicefiles import prepare_voice_files

INSTANT_FRAME_VERSION = "q1"  # muda quando a receita do quadro muda (invalida os quadros em cache)
KEEP_FRAMES_PER_PROJECT = 24  # quadros antigos de um projeto que sobram no cache (um por gesto, em geral)
FRAME_EPSILON = 1e-6  # folga das contas de quadro: 0.1 * 30 dá 3.0000000000000004


@dataclass(frozen=True)
class InstantFrame:
    """O quadro pronto: o arquivo, a chave de cache, o instante exato que ele mostra (múltiplo do quadro) e o que
    o quadro não mostra."""

    path: Path
    key: str
    at: float
    notes: tuple[str, ...] = ()


class _Checkpointed:
    """O runner do ffmpeg com um ponto de parada antes de cada comando. Nada é morto à força (o mezanino grava
    direto no cache, e um arquivo pela metade ficaria lá): quem foi superado para entre um comando e o seguinte."""

    def __init__(self, inner: FFmpegRunner, checkpoint: Callable[[], None]) -> None:
        self.inner = inner
        self.checkpoint = checkpoint

    def run(self, command: FFmpegCommand) -> list[str]:
        self.checkpoint()
        return self.inner.run(command)

    def capture(self, args: list[str], label: str = "ffmpeg") -> str:
        self.checkpoint()
        return self.inner.capture(args, label)


def frame_index(t: float, fps: float) -> int:
    """O quadro do vídeo final mais perto do instante `t`: é o que o player mostra naquele instante."""
    return max(int(math.floor(t * fps + 0.5)), 0)


def shows_frame(start: float, end: float, index: int, fps: float) -> bool:
    """O intervalo [start, end) aparece no quadro `index` do vídeo final (a regra do texto e das composições)."""
    first, stop = frame_range(start, end, fps)
    return first <= index < stop


def instant_notes(project: Project, *, captions_found: bool, audiograms: bool) -> list[str]:
    """O que o quadro não traz, em linguagem de quem edita. Função pura: recebe o que o render achou."""
    notes: list[str] = []
    captions = project.captions
    if captions and captions.enabled and not captions_found:
        if captions.source == "narration":
            notes.append(
                "A legenda da narração não aparece neste quadro (a voz só existe depois de sintetizada)."
            )
        elif captions.source == "auto" and not (project.audio.mute_clips and not project.audio.voiceover):
            notes.append(
                "A legenda automática não aparece neste quadro: o projeto ainda não tem a transcrição guardada "
                "(ela é feita no primeiro render)."
            )
    if audiograms:
        notes.append("O audiograma não aparece neste quadro (ele depende do áudio).")
    return notes


class InstantFrameRenderer:
    """Faz (ou acha no cache) o quadro de um projeto num instante. Tudo que toca o mundo entra por injeção: o
    runner do ffmpeg, o probe, o achador de deslocamento, o transcritor (que aqui só lê o cache), o navegador das
    composições e o recortador da pessoa."""

    def __init__(
        self,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        *,
        offset_finder: OffsetFinder | None = None,
        transcriber_factory: TranscriberFactory = default_transcriber_factory,
        html_renderer: HtmlRenderer | None = None,
        matter: Matter | None = None,
        isolator: IsolationService | None = None,
        cache_dir: Path | None = None,
        frames_dir: Path | None = None,
        jobs_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.runner: FFmpegRunner = runner or SubprocessRunner(quiet=True)
        self.prober = prober
        self.offset_finder = offset_finder
        self.mezzanines = MezzanineBuilder()
        self.captions = CaptionPipeline(transcriber_factory)
        self.html_layers = HtmlLayerBuilder(html_renderer)
        self.person_layers = PersonLayerBuilder()
        self.matter = matter
        self.isolator = isolator
        self._cache_dir = cache_dir
        self._frames_dir = frames_dir
        self._jobs_dir = jobs_dir
        self.log = log or (lambda message: None)

    # ---------- onde as coisas ficam (lidas na hora do uso, os testes redirecionam o config) ----------

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir or config.MEZ_DIR

    @property
    def frames_dir(self) -> Path:
        return self._frames_dir or config.FRAMES_DIR

    @property
    def jobs_dir(self) -> Path:
        return self._jobs_dir or config.JOBS_DIR

    def frame_path(self, name: str, key: str) -> Path:
        return self.frames_dir / f"{name}__{key}.png"

    # ---------- chave e cache ----------

    def instant(self, project: Project, t: float) -> float:
        """O instante exato que o quadro pedido em `t` mostra: o do quadro mais perto, na grade do projeto."""
        fps = self._fps(project)
        return frame_index(t, fps) / fps

    @staticmethod
    def _fps(project: Project) -> float:
        return project.output.fps or get_preset(project.output.preset).fps

    def key(self, project: Project, t: float) -> str:
        """Hash da spec, do quadro pedido e dos arquivos que o quadro lê (data e tamanho): trocar um deles muda a
        chave. O que não muda a imagem nem o quadro não está aqui, e a mesma spec no mesmo instante dá a mesma."""
        project = apply_track_state(project)
        base = project.base_dir
        stamps = [file_stamp(project.resolve(raw)) for raw, _ in media_references(project)]
        stamps += self._html_stamps(project)
        for name in ("sync.json", "captions.auto.json"):  # o deslocamento das fontes e a transcrição em cache
            stamps.append(file_stamp(base / name) if base else None)
        captions = project.captions
        if captions and captions.source not in ("auto", "narration"):
            stamps.append(file_stamp(project.resolve(captions.source)))  # o arquivo de legendas
        theme = self._theme_signature(project)
        return cache_key(
            INSTANT_FRAME_VERSION,
            project.model_dump(mode="json"),
            frame_index(t, self._fps(project)),
            stamps,
            theme,
        )

    @staticmethod
    def _html_stamps(project: Project) -> list:
        """Os arquivos de cada composição em HTML do projeto: editar a página por fora tem que refazer o quadro."""
        stamps: list = []
        for overlay in project.overlays:
            if isinstance(overlay, HtmlOverlay) and overlay.src:
                source = project.resolve(overlay.src)
                try:
                    stamps.extend(file_stamp(path) for path in composition_files(source))
                except (FileNotFoundError, ValueError):
                    stamps.append(None)  # a composição não existe: o quadro falha com a mensagem dela
        return stamps

    @staticmethod
    def _theme_signature(project: Project) -> str:
        from ..domain.brand import load_theme

        theme = load_theme(project.brand, project.theme)
        return cache_key(
            theme.key,
            theme.colors,
            theme.fonts,
            theme.style,
            theme.captions,
            theme.cta,
            theme.rules,
            theme.looks,
            theme.card_layouts,
        )

    def cached(self, name: str, key: str) -> InstantFrame | None:
        """O quadro do projeto `name` no cache, se já existe para a chave."""
        path = self.frame_path(name, key)
        sidecar = path.with_suffix(".json")
        if not path.exists() or not sidecar.exists():
            return None
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return InstantFrame(path, key, float(data["at"]), tuple(data.get("notes", [])))

    # ---------- o quadro ----------

    def render(
        self,
        project: Project,
        t: float,
        key: str | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> InstantFrame:
        """Renderiza o quadro do instante `t` (ou o devolve do cache). `checkpoint` roda antes de cada comando do
        ffmpeg e pode levantar uma exceção para parar o trabalho (um pedido mais novo tomou o lugar)."""
        original = project
        key = key or self.key(original, t)
        ready = self.cached(original.name, key)
        if ready is not None:
            return ready
        project = apply_track_state(original)
        layout = project_layout(project, self.prober, self.offset_finder)
        # medir a sincronia grava o `sync.json`, que entra na chave: o quadro fica guardado sob a chave de depois,
        # a que o próximo pedido da mesma spec vai calcular, senão o primeiro quadro nunca seria reaproveitado
        key = self.key(original, t)
        if layout.total <= 0:
            raise ValueError("o projeto não tem duração: não há quadro para mostrar")

        preset = layout.preset.preview()
        fps = project.output.fps or layout.preset.fps
        index = frame_index(t, fps)
        last = max(math.ceil(layout.total * fps - FRAME_EPSILON) - 1, 0)
        notes: list[str] = []
        if index > last:
            index = last
            notes.append(
                f"O instante passa do fim do projeto ({layout.total:.2f} s): este é o último quadro."
            )
        at = index / fps

        job_dir = self.jobs_dir / f"{project.name}_frame"
        job_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        runner = _Checkpointed(self.runner, checkpoint) if checkpoint else self.runner
        ctx = RenderContext(
            project=layout.project,
            options=RenderOptions(preview=True, quiet=True, thumbnail=False),
            theme=layout.theme,
            preset=preset,
            fps=fps,
            job_dir=job_dir,
            cache_dir=self.cache_dir,
            runner=runner,
            prober=self.prober,
            matter=self.matter or RvmMatter(),
            isolator=self.isolator,
            log=self.log,
            session=layout.session,
        )
        transitions = transitions_of(layout.project.timeline)
        window = instant_window(layout.durations, transitions, index, fps)
        if window is None:
            raise ValueError(f"nenhum trecho aparece em {at:.2f} s")

        prepared = self._prepare(ctx, layout, window.first, window.last)
        self.log(f"quadro de {at:.2f} s: trechos {window.first + 1} a {window.last + 1}")
        # a voz já com os efeitos: é o que o render transcreve, e a chave das legendas em cache depende do arquivo
        voice_files = prepare_voice_files(layout.project, self.prober, effect_processor(ctx))
        captions = self.captions.produce_cached(ctx, layout.sources, voice_files)
        tones = [item.tone for item in prepared]
        text = build_text_layer(
            ctx,
            layout.total,
            layout.spans,
            tones,
            captions.cues if captions else None,
            layout.project.output.guides,
            has_voice=False,
        )
        notes += instant_notes(
            layout.project, captions_found=captions is not None, audiograms=bool(text.audiograms)
        )
        text.audiograms.clear()  # sem áudio não há o que desenhar
        text.doc.write(job_dir / "overlay.ass")
        if text.has_behind_text:
            text.behind_doc.write(job_dir / "overlay_behind.ass")

        html = self._html_stills(ctx, text.html_overlays, index, notes)
        people = self._person_layers(
            ctx, prepared, transitions, text.behind_intervals, index, window.first_frame
        )
        out = self.frame_path(project.name, key)
        staging = out.with_name(f"{out.stem}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}{out.suffix}")
        assembly = build_instant_assembly(
            ctx,
            window,
            [prepared[i].mezzanine for i in range(window.first, window.last + 1)],
            index,
            layout.total,
            text,
            html,
            [item.layer for item in people],
            staging,
        )
        self._run(ctx, assembly, staging, out)

        notes += [warning for warning in ctx.warnings if warning not in notes]
        out.with_suffix(".json").write_text(
            json.dumps({"at": at, "notes": notes}, ensure_ascii=False), encoding="utf-8"
        )
        self._drop_old_frames(project.name, keep=out)
        return InstantFrame(out, key, at, tuple(notes))

    # ---------- as etapas ----------

    def _prepare(
        self, ctx: RenderContext, layout: ProjectLayout, first: int, last: int
    ) -> list[PreparedSegment]:
        """Os trechos de `first` a `last` com o mezanino gerado (ou do cache); os outros só planejados.

        O plano dos de fora é um dry-run: dá a duração, o tom do fundo e o caminho do mezanino (o texto e a
        legenda precisam disso), sem gerar nada nem separar a voz de ninguém."""
        planning = replace(ctx, options=replace(ctx.options, dry_run=True))
        prepared = self.mezzanines.prepare(planning, layout.sources)
        window = self.mezzanines.prepare(ctx, layout.sources, only=range(first, last + 1))
        self.mezzanines.build(ctx, window)
        for item in window:
            prepared[item.index] = item
        return prepared

    def _html_stills(
        self, ctx: RenderContext, overlays: list[ResolvedHtmlOverlay], index: int, notes: list[str]
    ) -> list[ResolvedHtmlLayer]:
        """O quadro de cada composição em HTML que aparece neste quadro do vídeo."""
        active = [item for item in overlays if shows_frame(item.start, item.end, index, ctx.fps)]
        if not active:
            return []
        reason = self.html_layers.unavailable_reason()
        if reason:
            notes.append(f"A composição em HTML não aparece neste quadro: {reason}")
            return []
        stills = (self.html_layers.still(ctx, item, index) for item in active)
        return [layer for layer in stills if layer is not None]

    def _person_layers(
        self,
        ctx: RenderContext,
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        intervals: list[tuple[float, float]],
        index: int,
        first_frame: int,
    ) -> list[PreparedPersonLayer]:
        """A pessoa recortada até este quadro, quando um texto `behind-person` aparece nele.

        O recorte cobre da primeira linha da janela do quadro até ele: fora de transição é só o próprio quadro, e
        durante uma transição são os quadros dela até aqui (o recortador precisa ver o mesmo alinhamento dos
        trechos que a montagem vê)."""
        fps = ctx.fps
        wanted = (
            [(first_frame / fps, (index + 1) / fps)]
            if any(shows_frame(a, b, index, fps) for a, b in intervals)
            else []
        )
        people = self.person_layers.prepare(ctx, prepared, transitions, wanted)
        self.person_layers.build(ctx, people)
        return people

    @staticmethod
    def _run(ctx: RenderContext, assembly: Assembly, staging: Path, out: Path) -> None:
        (ctx.job_dir / "graph.txt").write_text(";".join(assembly.graph), encoding="utf-8")
        try:
            command = ctx.runner.run(assembly.command)
            (ctx.job_dir / "cmd.txt").write_text(
                format_cmd(command), encoding="utf-8"
            )  # para quem for depurar
            staging.replace(out)
        finally:
            staging.unlink(missing_ok=True)

    def _drop_old_frames(self, name: str, keep: Path) -> None:
        frames = sorted(self.frames_dir.glob(f"{name}__*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in [frame for frame in frames if frame != keep][KEEP_FRAMES_PER_PROJECT - 1 :]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
