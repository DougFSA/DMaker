"""Áudio da prévia da linha do tempo: o som do projeto como o render o faz, num arquivo leve para o navegador.

A interface toca UM áudio preso ao relógio da linha do tempo (todo `<video>` fica mudo). Este serviço faz esse
arquivo com o mesmo grafo de áudio do render, sem gerar vídeo: fatias das faixas externas por corte, partes
das fontes, sincronia, volumes, música com `spans` e fades, narração, `mute_clips`, trilhas mudas e
`audio_mode`. Cada trecho vira um pedaço de WAV em cache (pelo que muda o som dele), então editar um corte
refaz só aquele pedaço; a mixagem inteira fica em cache pelo hash da parte de áudio da spec.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..domain.brand import load_theme
from ..domain.presets import get_preset
from ..domain.spec import ClipSegment, Project, Segment, VideoOverlay
from ..domain.timeline import transitions_of
from ..domain.tracks import apply_track_state
from ..filtergraph.pip import ResolvedVideoOverlay
from ..filtergraph.preview_audio import clip_audio_piece, preview_encode_args, silence_piece
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from ..voice.lexicon_store import LexiconStore
from ..voice.library import VoiceLibrary
from .assembly import LoudnessMeter, VoiceLevelMeter, audio_only_graph, graph_args, plan_loudness
from .context import Prober, RenderContext, RenderOptions
from .isolation import IsolationService
from .layout import ProjectLayout, project_layout
from .missing import MissingMedia, media_references
from .narration import NarrationService
from .segments import PreparedSegment, cache_key, isolate_camera_audio
from .sfx import SfxTrack, leveled_effects
from .sync import OffsetFinder
from .track_slices import track_slices
from .voicefiles import PreparedVoiceFile, prepare_voice_files
from .voiceover import PreparedVoiceover, VoiceoverPreparer, narration_text

PREVIEW_AUDIO_VERSION = "pa1"  # muda quando a receita da prévia muda (invalida os pedaços e as mixagens)
KEEP_MIXES_PER_PROJECT = 4  # mixagens antigas de um projeto que sobram no cache
PIECE_MAX_AGE_DAYS = 14  # pedaço que ninguém usa há tanto tempo sai do cache

NarratorFactory = Callable[[FFmpegRunner], NarrationService]


@dataclass(frozen=True)
class PreviewAudio:
    """A mixagem pronta: o arquivo, a chave de cache dela, a duração e o que ficou de fora (avisos)."""

    path: Path
    key: str
    duration: float
    warnings: tuple[str, ...] = ()


def piece_recipe(segment: Segment) -> dict:
    """Tudo que muda o som de UM trecho (e só isso): a cor, o enquadramento e o texto não entram, para
    mexer neles não refazer o áudio. A transição é da montagem, não do pedaço."""
    if isinstance(segment, ClipSegment):
        return segment.model_dump(
            mode="json",
            include={
                "type",
                "src",
                "source",
                "start",
                "end",
                "speed",
                "volume",
                "mute",
                "fade_in",
                "fade_out",
                "audio_fade",
                "audio_mode",
            },
        )
    return {"type": segment.type, "duration": getattr(segment, "duration", None)}


def mix_recipe(project: Project) -> dict:
    """A parte da spec que decide o som da mixagem inteira: os trechos com a transição de cada um, as fontes,
    o bloco `audio` e as sobreposições que soam (PiP com som e as que disparam um efeito sonoro)."""
    sounding = [
        overlay.model_dump(mode="json")
        for overlay in project.overlays
        if isinstance(overlay, VideoOverlay) or getattr(overlay, "sound", None)
    ]
    return {
        "timeline": [
            {
                "piece": piece_recipe(segment),
                "transition": segment.transition.model_dump(mode="json") if segment.transition else None,
            }
            for segment in project.timeline
        ],
        "sources": {name: ref.model_dump(mode="json") for name, ref in project.sources.items()},
        "audio": project.audio.model_dump(mode="json"),
        "overlays": sounding,
    }


def file_stamp(path: Path) -> list | None:
    """Data e tamanho do arquivo: trocar o conteúdo muda a chave. None se ele não está no disco."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return [str(path), stat.st_mtime_ns, stat.st_size]


def without_missing_audio(project: Project, missing: MissingMedia) -> Project:
    """A spec sem a música e as locuções cujo arquivo sumiu: a prévia toca o resto em vez de falhar (o
    trecho aparece marcado na linha do tempo). Faixas externas e câmeras ausentes viram silêncio na hora."""
    audio = project.audio
    music = audio.music
    if music is not None and missing.covers(project.resolve(music.src)):
        music = None
    voiceover = [clip for clip in audio.voiceover if not missing.covers(project.resolve(clip.src))]
    if music is audio.music and len(voiceover) == len(audio.voiceover):
        return project
    trimmed = project.model_copy(
        update={"audio": audio.model_copy(update={"music": music, "voiceover": voiceover})}
    )
    trimmed.base_dir = project.base_dir
    return trimmed


class PreviewAudioBuilder:
    """Faz (ou acha no cache) a mixagem de áudio da prévia de um projeto. Tudo que toca o mundo entra por
    injeção: o runner do ffmpeg, o probe, o achador de deslocamento, a biblioteca de vozes e o serviço de
    narração (que aqui só lê o cache: nunca sintetiza)."""

    def __init__(
        self,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        offset_finder: OffsetFinder | None = None,
        library: VoiceLibrary | None = None,
        narrator: NarratorFactory | None = None,
        isolator: IsolationService | None = None,
        cache_dir: Path | None = None,
        jobs_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.runner: FFmpegRunner = runner or SubprocessRunner(quiet=True)
        self.prober = prober
        self.offset_finder = offset_finder
        self.library = library or VoiceLibrary()
        self.narrator_factory = narrator or default_narrator
        self.isolator = isolator
        self.cache_dir = cache_dir or config.PREVIEW_AUDIO_DIR
        self.jobs_dir = jobs_dir or config.JOBS_DIR
        self.log = log or (lambda message: None)
        self._narrator: NarrationService | None = None

    # ---------- chave e cache ----------

    def _narration(self) -> NarrationService:
        if self._narrator is None:
            self._narrator = self.narrator_factory(self.runner)
        return self._narrator

    def narration_durations(self, project: Project) -> list[float | None]:
        """Duração real das narrações já sintetizadas (None = ainda não): a prévia só usa as que existem."""
        if not project.audio.narration:
            return []
        return VoiceoverPreparer(self.library).cached_durations(project, self._narration())

    def key(self, project: Project) -> str:
        """Hash da parte de áudio da spec, dos arquivos que ela usa (data e tamanho) e das narrações já em
        cache: o que não muda o som (cor, texto, legendas) não muda a chave."""
        project = apply_track_state(project)
        base = project.base_dir
        stamps = [file_stamp(project.resolve(raw)) for raw, _ in media_references(project)]
        scripts = [
            file_stamp(project.resolve(narration.script))
            for narration in project.audio.narration
            if narration.script
        ]
        return cache_key(
            PREVIEW_AUDIO_VERSION,
            mix_recipe(project),
            stamps,
            scripts,
            file_stamp(base / "sync.json") if base else None,  # o deslocamento calculado das fontes
            self.narration_durations(project),
        )

    def mix_path(self, name: str, key: str) -> Path:
        return self.cache_dir / f"{name}__{key}.m4a"

    def cached(self, name: str, key: str) -> PreviewAudio | None:
        """A mixagem do projeto `name` no cache, se já existe para a chave."""
        path = self.mix_path(name, key)
        notes = path.with_suffix(".json")
        if not path.exists() or not notes.exists():
            return None
        try:
            data = json.loads(notes.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return PreviewAudio(path, key, float(data["duration"]), tuple(data.get("warnings", [])))

    # ---------- a mixagem ----------

    def build(self, project: Project, key: str | None = None) -> PreviewAudio:
        """Mixa o áudio do projeto (reaproveitando o que já está em cache) e devolve o arquivo."""
        key = key or self.key(project)
        ready = self.cached(project.name, key)
        if ready is not None:
            return ready
        project = apply_track_state(project)
        missing = MissingMedia.scan(project)
        project = without_missing_audio(project, missing)
        layout = project_layout(project, self.prober, self.offset_finder, missing)
        if layout.total <= 0:
            raise ValueError("o projeto não tem duração: não há áudio para a prévia")
        job_dir = self.jobs_dir / f"{project.name}_preview_audio"
        job_dir.mkdir(parents=True, exist_ok=True)
        pieces_dir = self.cache_dir / "pieces"
        pieces_dir.mkdir(parents=True, exist_ok=True)
        self._drop_old_pieces(pieces_dir)

        ctx = self._context(layout, job_dir, pieces_dir)
        prepared = self._pieces(ctx, layout, missing)
        transitions = transitions_of(layout.project.timeline)
        total = layout.total
        voiceovers = self._voiceovers(ctx)
        voice_files = self._voice_files(ctx)
        pips = self._pip_audio(ctx, total, missing)
        music = ctx.project.audio.music
        music_path = ctx.project.resolve(music.src) if music else None
        sfx = self._effects(ctx, prepared, transitions, layout, total, voiceovers, pips, voice_files)

        plan = plan_loudness(
            ctx, LoudnessMeter(), prepared, transitions, music_path, total, voiceovers, pips, sfx, voice_files
        )
        inputs, lines, aout = audio_only_graph(
            ctx,
            prepared,
            transitions,
            music_path,
            total,
            voiceovers,
            pips,
            sfx=sfx,
            voice_files=voice_files,
            include_norm=plan.normalize,
            measured=plan.measured,
        )
        out = self.mix_path(project.name, key)
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = out.with_name(f"{out.stem}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}{out.suffix}")
        args = [
            *graph_args(ctx, inputs, lines, "preview_audio.txt"),
            "-map",
            aout,
            *preview_encode_args(total, staging),
        ]
        self.log("mixagem do áudio da prévia")
        try:
            ctx.runner.run(FFmpegCommand(args, label="mixagem da prévia", total=total, cwd=job_dir))
            staging.replace(out)
        finally:
            staging.unlink(missing_ok=True)
        warnings = tuple(ctx.warnings)
        out.with_suffix(".json").write_text(
            json.dumps({"duration": total, "warnings": list(warnings)}, ensure_ascii=False), encoding="utf-8"
        )
        self._drop_old_mixes(project.name, keep=out)
        return PreviewAudio(out, key, total, warnings)

    def _context(self, layout: ProjectLayout, job_dir: Path, pieces_dir: Path) -> RenderContext:
        project = layout.project
        preset = get_preset(project.output.preset)
        return RenderContext(
            project=project,
            options=RenderOptions(quiet=True, thumbnail=False),
            theme=load_theme(project.brand, project.theme),
            preset=preset,
            fps=project.output.fps or preset.fps,
            job_dir=job_dir,
            cache_dir=pieces_dir,
            runner=self.runner,
            prober=self.prober,
            isolator=self.isolator,
            log=self.log,
            session=layout.session,
        )

    # ---------- pedaços: o som de cada trecho ----------

    def _pieces(
        self, ctx: RenderContext, layout: ProjectLayout, missing: MissingMedia
    ) -> list[PreparedSegment]:
        """Um WAV por trecho, do cache ou recém-gerado. O que a spec pede e o disco não tem vira silêncio."""
        prepared = []
        count = len(layout.project.timeline)
        for index, (segment, source, duration) in enumerate(
            zip(layout.project.timeline, layout.sources, layout.durations, strict=True)
        ):
            audible = (
                isinstance(segment, ClipSegment)
                and source.path is not None
                and source.info is not None
                and not missing.covers(source.path)
            )
            if audible:
                out, command = self._clip_piece(ctx, index, segment, source, duration, missing)
            else:
                key = cache_key(PREVIEW_AUDIO_VERSION, "silence", f"{duration:.3f}")
                out = ctx.cache_dir / f"{key}.wav"
                command = None if out.exists() else silence_piece(duration, out)
            if command is not None:
                self.log(f"áudio do trecho {index + 1}/{count}")
                ctx.runner.run(command)
            else:
                os.utime(out)  # em uso: o pedaço não é apagado por velho
            prepared.append(PreparedSegment(index, segment, duration, out, None, None))
        return prepared

    def _clip_piece(
        self, ctx, index, segment, source, duration, missing
    ) -> tuple[Path, FFmpegCommand | None]:
        info = source.info
        in_point = source.in_point(segment.start) if segment.source else segment.start
        tracks = ()
        if segment.source:
            tracks = tuple(
                piece
                for piece in track_slices(ctx.project.audio.tracks, ctx.session, segment)
                if not missing.covers(piece.path)
            )
        camera_audio = isolate_camera_audio(index, segment, source, in_point, duration, ctx)
        key = cache_key(
            PREVIEW_AUDIO_VERSION,
            piece_recipe(segment),
            str(source.path),
            source.stat_key(),
            source.audio_stream,
            in_point,
            f"{duration:.3f}",
            [(str(t.path), t.in_point, t.volume, t.audio_stream, file_stamp(t.path)) for t in tracks],
            camera_audio.key if camera_audio else None,  # o nome carrega a chave dos stems
        )
        out = ctx.cache_dir / f"{key}.wav"
        if out.exists():
            return out, None
        if camera_audio is not None:
            camera_audio.isolate()  # separa a voz (ou o fundo) só se o pedaço precisa ser feito
        command = clip_audio_piece(
            segment,
            info,
            source.path,
            duration,
            out,
            in_point=in_point,
            tracks=tracks,
            audio_stream=source.audio_stream,
            camera_audio=camera_audio.path if camera_audio else None,
        )
        return out, command

    # ---------- voz, PiP e efeitos ----------

    def _voiceovers(self, ctx: RenderContext) -> list[PreparedVoiceover]:
        """As narrações já sintetizadas, na posição de cada uma. A que ainda não foi falada fica de fora (a prévia
        não espera uma síntese de minutos): o aviso diz qual."""
        project = ctx.project
        prepared: list[PreparedVoiceover] = []
        if not project.audio.narration:
            return prepared
        service = self._narration()
        for index, narration in enumerate(project.audio.narration, 1):
            try:
                text = narration_text(project, narration)
                voice = self.library.get(narration.voice) if narration.voice else None
                settings = {
                    "language": narration.language,
                    "speed": narration.speed,
                    "instruct": narration.instruct,
                    "seed": narration.seed,
                }
                duration = service.cached_duration(text, voice, brand=project.brand, **settings)
                if duration is None:
                    ctx.warn(f"A narração {index} ainda não foi sintetizada e fica fora da prévia.")
                    continue
                out = ctx.job_dir / f"narration_{index}.wav"
                result = service.render(text, out, voice, brand=project.brand, **settings)
            except (OSError, ValueError, RuntimeError) as exc:
                ctx.warn(f"A narração {index} não entrou na prévia: {exc}")
                continue
            prepared.append(
                PreparedVoiceover(result.path, narration.start, narration.volume, result.duration)
            )
        return prepared

    def _voice_files(self, ctx: RenderContext) -> list[PreparedVoiceFile]:
        try:
            return prepare_voice_files(ctx.project, self.prober)
        except (OSError, ValueError) as exc:
            ctx.warn(f"As locuções não entraram na prévia: {exc}")
            return []

    def _pip_audio(
        self, ctx: RenderContext, total: float, missing: MissingMedia
    ) -> list[ResolvedVideoOverlay]:
        """Os PiPs com som, só com o que a mixagem lê deles (arquivo, ponto de entrada, instante e volume): o
        quadro, a máscara e a moldura não importam para o áudio."""
        pips = []
        for overlay in ctx.project.overlays:
            if not isinstance(overlay, VideoOverlay) or overlay.volume <= 0:
                continue
            if overlay.source:
                source = ctx.session.get(overlay.source)
                if source is None or source.path is None or source.info is None:
                    continue
                path, info = source.path, source.info
                in_point, audio_stream = source.in_point(overlay.offset), source.audio_stream
            else:
                path = ctx.project.resolve(overlay.src or "")
                if not path.exists():
                    continue
                info, in_point, audio_stream = ctx.prober(path), overlay.offset, 0
            end = min(overlay.end if overlay.end is not None else total, total)
            if missing.covers(path) or not info.has_audio or end <= overlay.start:
                continue
            pips.append(
                ResolvedVideoOverlay(
                    overlay, path, in_point, overlay.start, end, 0, 0, Path(), None, 0, audio_stream, True
                )
            )
        return pips

    def _effects(
        self, ctx, prepared, transitions, layout, total, voiceovers, pips, voice_files
    ) -> list[SfxTrack]:
        try:
            return leveled_effects(
                ctx,
                VoiceLevelMeter(),
                prepared,
                transitions,
                layout.spans,
                total,
                voiceovers,
                pips,
                voice_files,
            )
        except (OSError, ValueError, KeyError) as exc:  # efeito que não existe: a prévia segue sem ele
            ctx.warn(f"Os efeitos sonoros não entraram na prévia: {exc}")
            return []

    # ---------- limpeza do cache ----------

    def _drop_old_mixes(self, name: str, keep: Path) -> None:
        mixes = sorted(self.cache_dir.glob(f"{name}__*.m4a"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in [m for m in mixes if m != keep][KEEP_MIXES_PER_PROJECT - 1 :]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)

    @staticmethod
    def _drop_old_pieces(pieces_dir: Path) -> None:
        limit = time.time() - PIECE_MAX_AGE_DAYS * 86400
        for piece in pieces_dir.glob("*.wav"):
            try:
                if piece.stat().st_mtime < limit:
                    piece.unlink()
            except OSError:
                continue


def default_narrator(runner: FFmpegRunner) -> NarrationService:
    """Serviço real de narração: o sintetizador compartilhado do processo. A prévia só lê o cache dele, então
    o modelo de voz nem chega a carregar."""
    from .voices import shared_synthesizer

    return NarrationService(shared_synthesizer(), runner, lexicons=LexiconStore().for_brand)
