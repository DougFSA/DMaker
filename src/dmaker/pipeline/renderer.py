"""Orquestração do render: fontes -> mezaninos -> legendas -> camada de texto -> montagem -> saída."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import config
from ..config import ensure_dirs
from ..domain.audiogram import project_has_voice
from ..domain.brand import load_theme
from ..domain.infographics import resolve_infographic
from ..domain.presets import Preset, get_preset
from ..domain.sfx import plan_sfx
from ..domain.spec import HtmlOverlay, Project
from ..domain.timeline import segment_duration, timeline_spans, timeline_total, transitions_of
from ..domain.tracks import apply_track_state
from ..media.browser import BrowserUnavailable
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner, RecordingRunner, SubprocessRunner, format_cmd
from ..media.matting import Matter, RvmMatter
from ..media.probe import probe
from ..voice.library import VoiceLibrary
from .assembly import (
    LoudnessMeter,
    MasterEffectMeter,
    VoiceLevelMeter,
    build_assembly,
    plan_loudness,
    plan_master_effects,
)
from .audio_effects import effect_processor, processed_music, processed_pips, processed_voiceovers
from .auto_duck import DuckInputs, begin_ducks, finish_ducks, project_track_origin
from .captions import CaptionPipeline, TranscriberFactory, default_transcriber_factory
from .carrier_tracks import CarrierInputs, Deferred, install_carrier_tracks
from .context import Prober, RenderContext, RenderOptions, RenderResult
from .generated_sounds import check_generated_files
from .html_layer import HtmlLayerBuilder, has_html_overlays, resolve_html_source
from .isolation import IsolationService
from .lint import lint
from .narration import NarrationService
from .output_kinds import register_output_kind
from .person_layer import PersonLayerBuilder
from .segments import MezzanineBuilder
from .sfx import SfxTrack, leveled_effects, resolve_files
from .sources import expand_parts, resolve_session, resolve_sources
from .sync import OffsetFinder, SyncResolver, ffmpeg_offset_finder
from .textlayer import build_text_layer
from .voicefiles import prepare_voice_files, voice_file_playtimes
from .voiceover import VoiceoverPreparer, known_voices, overrun_warnings, voice_spans


class RenderPipeline:
    """Recebe as dependências por injeção: runner do ffmpeg, probe e transcritor são trocáveis nos testes."""

    def __init__(
        self,
        project: Project,
        options: RenderOptions | None = None,
        *,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        transcriber_factory: TranscriberFactory = default_transcriber_factory,
        mezzanines: MezzanineBuilder | None = None,
        person_layers: PersonLayerBuilder | None = None,
        html_layers: HtmlLayerBuilder | None = None,
        cache_dir: Path | None = None,
        jobs_dir: Path | None = None,
        output_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
        offset_finder: OffsetFinder | None = None,
        matter: Matter | None = None,
        narrator: NarrationService | None = None,
        isolator: IsolationService | None = None,
        voice_library: VoiceLibrary | None = None,
    ):
        self.project = project
        self.options = options or RenderOptions()
        if runner is None:
            runner = RecordingRunner() if self.options.dry_run else SubprocessRunner(quiet=self.options.quiet)
        self.runner = runner
        self.prober = prober
        self.matter = matter or RvmMatter()
        self.mezzanines = mezzanines or MezzanineBuilder()
        self.person_layers = person_layers or PersonLayerBuilder()
        self.html_layers = html_layers or HtmlLayerBuilder()
        self.narrator = narrator
        self.isolator = isolator
        self.voiceover = VoiceoverPreparer(voice_library)
        self.captions = CaptionPipeline(transcriber_factory)
        self.loudness = LoudnessMeter()
        self.master_meter = MasterEffectMeter()
        self.voice_level = VoiceLevelMeter()
        self.log = log or (lambda message: None)
        self.sync = SyncResolver(
            offset_finder or ffmpeg_offset_finder(self.runner), self.log, prober=self.prober
        )
        self.cache_dir = cache_dir or config.MEZ_DIR
        self.jobs_dir = jobs_dir or config.JOBS_DIR
        self.output_dir = output_dir or config.OUTPUT_DIR

    # ---------- preparação ----------

    def _context(self) -> RenderContext:
        ensure_dirs()
        p, o = self.project, self.options
        theme = load_theme(p.brand, p.theme)
        preset = get_preset(o.preset or p.output.preset)
        if o.preview:
            preset = preset.preview()
        job_dir = self.jobs_dir / (p.name + ("_preview" if o.preview else ""))
        job_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return RenderContext(
            project=p,
            options=o,
            theme=theme,
            preset=preset,
            fps=p.output.fps or preset.fps,
            job_dir=job_dir,
            cache_dir=self.cache_dir,
            runner=self.runner,
            prober=self.prober,
            matter=self.matter,
            narrator=self.narrator,
            isolator=self.isolator,
            log=self.log,
        )

    def _output_path(self, preset: Preset) -> Path:
        p, o = self.project, self.options
        if o.out:
            return Path(o.out).resolve()
        if p.output.path and not o.preview:
            return p.resolve(p.output.path)
        suffix = "__preview" if o.preview else ""
        return self.output_dir / f"{p.name}__{preset.id.replace('/', '-')}{suffix}.mp4"

    # ---------- execução ----------

    def run(self) -> RenderResult:
        if self.project.multicam is not None:
            raise ValueError(
                f"bloco multicam em timeline[{self.project.multicam.at}] ainda não planejado: rode plan_multicam"
            )
        ctx = self._context()
        p, o = ctx.project, ctx.options

        ctx.log(
            f"render {p.name}: {ctx.preset.id} {ctx.width}x{ctx.height}" + (" (preview)" if o.preview else "")
        )
        p = apply_track_state(p)  # mudo/oculto por trilha da interface, paridade com o Shotcut
        p = self._sliced(p, o, ctx)
        resolution = self.sync.resolve(p, (p.base_dir or ctx.job_dir) / "sync.json")
        ctx.warnings.extend(resolution.warnings)
        ctx.session = resolve_session(p, ctx.prober, resolution.offsets, resolution.parts)
        track_origin = project_track_origin(p)  # antes de as fontes com `parts` virarem várias faixas
        p, _origin = expand_parts(p, ctx.session, resolution.parts, ctx.log)
        ctx.project = p
        sources = resolve_sources(p, ctx.prober, ctx.session)
        infos = [s.info for s in sources]
        transitions = transitions_of(p.timeline)
        durations = [
            segment_duration(seg, src.info, src.offset) for seg, src in zip(p.timeline, sources, strict=True)
        ]
        total = timeline_total(durations, transitions)
        ctx.warnings.extend(
            lint(
                p,
                ctx.theme,
                ctx.preset,
                total,
                durations,
                infos,
                [s.offset for s in sources],
                known_voices=known_voices(p, self.voiceover.library),
                voiceover_playtimes=voice_file_playtimes(p, self.prober),
            )
        )

        # um som que não existe falha agora, e não depois de minutos de mezaninos; a composição em HTML também
        resolve_files(p, plan_sfx(p, timeline_spans(durations, transitions)))
        check_generated_files(p)
        self._check_html(ctx)

        # o que não depende dos mezaninos fica pronto antes deles: o Auto Duck mede a chave de uma faixa externa de fundo
        # (que abaixa dentro do mezanino) na narração, nas vozes gravadas e na música já processadas
        # (o Vocoder que ouve outra trilha precisa dela já na hora de processar o item, então a passada prévia é instalada antes)
        spoken = self.voiceover.prepare(ctx)
        music_file = self._music_path()
        voiceovers_of = Deferred(lambda: processed_voiceovers(ctx, spoken), "a narração")
        voice_files_of = Deferred(
            lambda: prepare_voice_files(p, self.prober, effect_processor(ctx)), "a voz gravada"
        )
        music_of = Deferred(lambda: processed_music(ctx, music_file), "a música")
        install_carrier_tracks(
            ctx,
            CarrierInputs(
                timeline_spans(durations, transitions),
                sources,
                total,
                track_origin,
                voiceovers_of,
                voice_files_of,
                music_of,
            ),
        )
        voiceovers, voice_files, music_path = voiceovers_of(), voice_files_of(), music_of()
        begin_ducks(
            ctx,
            DuckInputs(
                timeline_spans(durations, transitions),
                sources,
                total,
                track_origin,
                voiceovers,
                voice_files,
                music_path,
            ),
        )
        prepared = self.mezzanines.prepare(ctx, sources)
        pending = sum(1 for item in prepared if item.command is not None)
        ctx.log(f"trechos: {len(prepared)} ({pending} a gerar, {len(prepared) - pending} em cache)")
        self.mezzanines.build(ctx, prepared)
        durations = [item.duration for item in prepared]
        total = timeline_total(durations, transitions)
        spans = timeline_spans(durations, transitions)
        tones = [item.tone for item in prepared]
        ctx.warnings.extend(overrun_warnings(voiceovers, total))

        if p.captions and p.captions.enabled and not o.no_captions:
            ctx.log(
                "legendas: "
                + ("transcrição automática" if p.captions.source == "auto" else p.captions.source)
            )
        captions = self.captions.produce(ctx, sources, prepared, transitions, voiceovers, voice_files)
        guides = o.guides if o.guides is not None else p.output.guides
        has_voice = project_has_voice(p, [bool(info and info.has_audio) for info in infos])
        layer = build_text_layer(
            ctx, total, spans, tones, captions.cues if captions else None, guides, has_voice
        )
        layer.doc.write(ctx.job_dir / "overlay.ass")
        if layer.has_behind_text:
            layer.behind_doc.write(ctx.job_dir / "overlay_behind.ass")
        processed_pips(ctx, layer.video_overlays)

        sfx = self._effects(
            ctx, prepared, transitions, spans, total, voiceovers, layer.video_overlays, voice_files
        )
        measured, normalize, visual_gain = self._loudness(
            ctx,
            prepared,
            transitions,
            music_path,
            total,
            voiceovers,
            layer.video_overlays,
            sfx,
            voice_files,
        )
        out_path = self._output_path(ctx.preset)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        html = self._html_layers(ctx, layer.html_overlays)
        people = self._person_layers(ctx, prepared, transitions, layer.behind_intervals)
        assembly = build_assembly(
            ctx,
            prepared,
            transitions,
            total,
            layer,
            music_path,
            measured,
            normalize,
            out_path,
            voiceovers,
            provenance=self._provenance(ctx, voiceovers, total),
            sfx=sfx,
            voice_files=voice_files,
            visual_gain_db=visual_gain,
            person_layers=[item.layer for item in people],
            html_layers=[item.layer for item in html],
        )
        (ctx.job_dir / "graph.txt").write_text(";".join(assembly.graph), encoding="utf-8")
        (ctx.job_dir / "graph.pretty.txt").write_text(";\n".join(assembly.graph), encoding="utf-8")
        ctx.log("montagem final")
        ctx.runner.run(assembly.command)
        ctx.log(f"pronto: {out_path}")

        commands = [format_cmd(c) for c in getattr(ctx.runner, "commands", [])]
        (ctx.job_dir / "cmd.txt").write_text("\n\n".join(commands), encoding="utf-8")
        thumbnail = self._thumbnail(ctx, out_path, total)
        return RenderResult(
            output=out_path,
            duration=total,
            preset=ctx.preset,
            warnings=ctx.warnings,
            thumbnail=thumbnail,
            captions_file=captions.file if captions else None,
            commands=commands,
            job_dir=ctx.job_dir,
            size_bytes=out_path.stat().st_size if out_path.exists() and not o.dry_run else 0,
        )

    def _check_html(self, ctx: RenderContext) -> None:
        """Composição que não existe, ou navegador que não está instalado, falha agora e não depois dos mezaninos.
        No dry-run nada é renderizado, então o navegador não faz falta."""
        if not has_html_overlays(ctx.project):
            return
        for overlay in ctx.project.overlays:
            if isinstance(overlay, HtmlOverlay):
                resolve_html_source(ctx.project, resolve_infographic(overlay, ctx.project).src)
        reason = None if ctx.options.dry_run else self.html_layers.unavailable_reason()
        if reason:
            raise BrowserUnavailable(f"O projeto tem composição HTML e o navegador não está pronto. {reason}")

    def _html_layers(self, ctx, overlays):
        """Renderiza (ou pega do cache) o vídeo com alfa de cada composição em HTML."""
        layers = self.html_layers.prepare(ctx, overlays)
        if layers:
            pending = sum(1 for item in layers if item.commands)
            ctx.log(
                f"composições html: {len(layers)} ({pending} a renderizar, {len(layers) - pending} em cache)"
            )
            self.html_layers.build(ctx, layers)
        return layers

    def _person_layers(self, ctx, prepared, transitions, intervals):
        """Recorta a pessoa só nos intervalos de texto `behind-person` (a camada que passa por cima do texto)."""
        people = self.person_layers.prepare(ctx, prepared, transitions, intervals)
        if people:
            pending = sum(1 for item in people if item.commands)
            ctx.log(
                f"pessoa atrás do texto: {len(people)} intervalo(s) ({pending} a recortar, "
                f"{len(people) - pending} em cache), modelo {self.person_layers.model_for(ctx)}"
            )
            self.person_layers.build(ctx, people)
        return people

    @staticmethod
    def _sliced(project: Project, options: RenderOptions, ctx: RenderContext) -> Project:
        """Render parcial: mantém só os trechos pedidos, sem sobreposições nem legendas (tempos absolutos
        deixariam de bater). Serve para revisar cortes de um vídeo longo sem renderizar tudo."""
        if options.segments is None:
            return project
        first, last = options.segments
        if first < 0 or last >= len(project.timeline) or first > last:
            raise ValueError(
                f"segmentos {first}-{last} fora da linha do tempo (0 a {len(project.timeline) - 1})"
            )
        ctx.log(f"render parcial: trechos {first} a {last} (sem sobreposições, legendas e narração)")
        sliced = project.model_copy(
            update={
                "timeline": project.timeline[first : last + 1],
                "overlays": [],
                "captions": None,
                "audio": project.audio.model_copy(
                    update={"narration": [], "voiceover": [], "sfx": []}
                ),  # tempos absolutos não valem no recorte
            }
        )
        sliced.base_dir = project.base_dir
        sliced.timeline[0] = sliced.timeline[0].model_copy(update={"transition": None})
        return sliced

    def _music_path(self) -> Path | None:
        music = self.project.audio.music
        if not music:
            return None
        path = self.project.resolve(music.src)
        if not path.exists():
            raise FileNotFoundError(f"Música não encontrada: {music.src}")
        return path

    @staticmethod
    def _provenance(ctx: RenderContext, voiceovers, total: float) -> str:
        """Etiqueta de procedência do vídeo: onde a narração sintetizada toca na saída final.

        Vazia sem narração ou com a marca desligada; os trechos são os de cada narração (início e duração),
        cortados no fim do vídeo, o que já é exato porque a narração entra inteira na mixagem.
        """
        if ctx.narrator is None or not voiceovers:
            return ""
        return ctx.narrator.provenance(voice_spans(voiceovers), total)

    def _effects(
        self, ctx, prepared, transitions, spans, total, voiceovers, video_overlays=(), voice_files=()
    ) -> list[SfxTrack]:
        """Efeitos sonoros do projeto, com o nível acertado contra a voz (ver `leveled_effects`)."""
        return leveled_effects(
            ctx,
            self.voice_level,
            prepared,
            transitions,
            spans,
            total,
            voiceovers,
            video_overlays,
            voice_files,
        )

    def _loudness(
        self,
        ctx,
        prepared,
        transitions,
        music_path,
        total,
        voiceovers,
        video_overlays=(),
        sfx=(),
        voice_files=(),
    ) -> tuple[dict | None, bool, float]:
        """A medição, se normaliza e o ganho que a normalização dá (ver `plan_loudness`). Antes dela, mede a
        mistura que cada efeito do master pede, para a medição do loudness já enxergar o master pronto."""
        finish_ducks(ctx, music_path, total, voiceovers, sfx, voice_files)
        plan_master_effects(
            ctx,
            self.master_meter,
            prepared,
            transitions,
            music_path,
            total,
            voiceovers,
            video_overlays,
            sfx,
            voice_files,
        )
        plan = plan_loudness(
            ctx,
            self.loudness,
            prepared,
            transitions,
            music_path,
            total,
            voiceovers,
            video_overlays,
            sfx,
            voice_files,
        )
        return plan.measured, plan.normalize, plan.gain_db

    def _thumbnail(self, ctx: RenderContext, out_path: Path, total: float) -> Path | None:
        if not ctx.options.thumbnail or ctx.options.dry_run:
            return None
        at = ctx.project.output.thumbnail_at
        t = at if at is not None else min(total * 0.15, max(total - 0.1, 0))
        thumb = out_path.with_suffix(".jpg")
        args = ["-ss", f"{t:.3f}", "-i", str(out_path), "-frames:v", "1", "-q:v", "2", str(thumb)]
        ctx.runner.run(FFmpegCommand(args, label="thumbnail"))
        return thumb


# o renderizador do tipo `video`: quem pede `create_renderer(...)` com um preset de plataforma chega aqui
register_output_kind("video", RenderPipeline)
