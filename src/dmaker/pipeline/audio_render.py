"""Render de um projeto cuja saída é um arquivo de áudio: o mesmo som do vídeo, sem imagem nenhuma.

A mixagem é a do render de vídeo (`filtergraph/audio.py`): ganho, narração, voz gravada, música com ducking, efeitos
sonoros e a normalização de loudness (`audio.target_lufs`). O que muda é a base e a saída: os trechos de vídeo (se o
projeto tem) viram só o som deles, pedaços de WAV iguais aos da prévia da linha do tempo, e um projeto sem trechos
usa um silêncio da duração dos itens de áudio. Nenhum mezanino de vídeo é feito, nenhum quadro é desenhado e o
comando do ffmpeg não leva codec de vídeo (`-vn`).

`AudioRenderPipeline.prepare` deixa tudo pronto (fontes, narração sintetizada, medida de loudness) e devolve um
`PreparedAudio`; `run` grava o arquivo da mixagem inteira, e a exportação múltipla (`pipeline/audio_export.py`)
parte do mesmo `PreparedAudio` para gravar regiões, trilhas e seleções.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config
from ..config import ensure_dirs
from ..domain.audio_metadata import ffmpeg_tags, merge_metadata
from ..domain.audio_presets import (
    AudioEncoding,
    AudioPreset,
    EncodingChoices,
    get_audio_preset,
    resolve_encoding,
)
from ..domain.brand import Theme, load_theme
from ..domain.outputs import frame_preset
from ..domain.spec import Project
from ..domain.timeline import transitions_of
from ..domain.tracks import apply_track_state, silenced_carrier_warnings
from ..filtergraph.audio import StemTaps
from ..filtergraph.audio_output import encode_args, format_filters
from ..filtergraph.common import Inputs
from ..filtergraph.pip import ResolvedVideoOverlay
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner, RecordingRunner, SubprocessRunner, format_cmd
from ..media.probe import probe
from ..voice.library import VoiceLibrary
from .assembly import (
    LoudnessMeter,
    LoudnessPlan,
    MasterEffectMeter,
    VoiceLevelMeter,
    audio_only_graph,
    graph_args,
    plan_loudness,
    plan_master_effects,
)
from .audio_duration import NOTHING_TO_PLAY, audio_extent
from .audio_effects import effect_processor, processed_music, processed_pips, processed_voiceovers
from .audio_lint import audio_output_warnings
from .auto_duck import DuckInputs, begin_ducks, finish_ducks, project_track_origin
from .carrier_tracks import CarrierInputs, Deferred, install_carrier_tracks
from .context import Prober, RenderContext, RenderOptions, RenderResult
from .layout import ProjectLayout, project_layout
from .missing import MissingMedia
from .narration import NarrationService
from .output_kinds import output_path_in, register_output_kind
from .preview_audio import PreviewAudioBuilder
from .segments import PreparedSegment
from .sfx import SfxTrack, leveled_effects
from .sync import OffsetFinder, ffmpeg_offset_finder
from .voicefiles import PreparedVoiceFile, prepare_voice_files
from .voiceover import PreparedVoiceover, VoiceoverPreparer, overrun_warnings, voice_spans

# as dependências que o render de áudio usa; as outras do `create_renderer` são do vídeo e ficam de fora
AUDIO_DEPENDENCIES = (
    "runner",
    "prober",
    "narrator",
    "isolator",
    "voice_library",
    "cache_dir",
    "jobs_dir",
    "output_dir",
    "log",
    "offset_finder",
    "overrides",
)


def encoding_for(
    project: Project, preset: AudioPreset, overrides: EncodingChoices | None = None
) -> AudioEncoding:
    """A codificação do arquivo: o padrão do preset, as escolhas de `output.audio_format` (só quando o preset
    exportado é o mesmo da spec, porque 24 bits do WAV não fazem sentido num MP3) e, por cima, as do pedido."""
    own = project.output.audio_format
    chosen = own.choices() if own is not None and _same_preset(project.output.preset, preset) else None
    if chosen is not None and overrides is not None:
        merged = {
            name: getattr(overrides, name) if getattr(overrides, name) is not None else getattr(chosen, name)
            for name in chosen.__dict__
        }
        return resolve_encoding(preset, EncodingChoices(**merged))
    return resolve_encoding(preset, overrides or chosen)


def _same_preset(spec_preset: str, preset: AudioPreset) -> bool:
    try:
        return get_audio_preset(spec_preset).id == preset.id
    except KeyError:
        return False


def output_tags(
    project: Project, theme: Theme, preset: AudioPreset, provenance: str = ""
) -> tuple[list[tuple[str, str]], list[str]]:
    """As etiquetas do arquivo (modelo da marca com a spec por cima) como pares do ffmpeg, e os avisos do que o formato
    não guarda. A etiqueta de procedência da voz sintetizada vai no comentário e não se perde por ele existir."""
    overrides = project.output.metadata.model_dump(exclude_none=True) if project.output.metadata else None
    tags = merge_metadata(theme.metadata, overrides)
    if provenance:
        tags["comment"] = f"{tags['comment']} | {provenance}" if tags.get("comment") else provenance
    pairs, ignored = ffmpeg_tags(preset, tags)
    warnings = [f"o {preset.name} não guarda estas etiquetas e elas ficam de fora: {', '.join(ignored)}."]
    return pairs, warnings if ignored else []


@dataclass
class PreparedAudio:
    """O projeto pronto para virar arquivo: tudo que a mixagem lê, já resolvido e medido."""

    ctx: RenderContext
    layout: ProjectLayout
    prepared: list[PreparedSegment]
    total: float
    voiceovers: list[PreparedVoiceover]
    voice_files: list[PreparedVoiceFile]
    pips: list[ResolvedVideoOverlay]
    sfx: list[SfxTrack]
    music_path: Path | None
    provenance: str = ""
    plans: dict[str, LoudnessPlan] = field(default_factory=dict)

    @property
    def project(self) -> Project:
        return self.ctx.project

    @property
    def transitions(self) -> list:
        return transitions_of(self.layout.project.timeline)


class AudioRenderPipeline:
    """Renderiza o áudio do projeto. Recebe as dependências por injeção, como o `RenderPipeline` de vídeo."""

    def __init__(
        self,
        project: Project,
        options: RenderOptions | None = None,
        *,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        narrator: NarrationService | None = None,
        isolator: Any = None,
        voice_library: VoiceLibrary | None = None,
        cache_dir: Path | None = None,
        jobs_dir: Path | None = None,
        output_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
        offset_finder: OffsetFinder | None = None,
        overrides: EncodingChoices | None = None,
    ):
        self.project = project
        self.options = options or RenderOptions()
        if runner is None:
            runner = RecordingRunner() if self.options.dry_run else SubprocessRunner(quiet=self.options.quiet)
        self.runner = runner
        self.prober = prober
        self.narrator = narrator
        self.isolator = isolator
        self.voiceover = VoiceoverPreparer(voice_library)
        self.log = log or (lambda message: None)
        self.jobs_dir = jobs_dir or config.JOBS_DIR
        self.output_dir = output_dir or config.OUTPUT_DIR
        self.offset_finder = offset_finder or ffmpeg_offset_finder(runner)
        self.overrides = overrides
        # os pedaços de WAV do som dos trechos são os da prévia da linha do tempo, no mesmo cache
        self.pieces = PreviewAudioBuilder(
            runner=runner,
            prober=prober,
            offset_finder=self.offset_finder,
            library=voice_library,
            isolator=isolator,
            cache_dir=cache_dir,
            jobs_dir=self.jobs_dir,
            log=self.log,
        )

    # ---------- qual arquivo ----------

    @property
    def preset(self) -> AudioPreset:
        return get_audio_preset(self.options.preset or self.project.output.preset)

    def encoding(self) -> AudioEncoding:
        return encoding_for(self.project, self.preset, self.overrides)

    def output_path(self) -> Path:
        project, options, preset = self.project, self.options, self.preset
        if options.out:
            return Path(options.out).resolve()
        if project.output.path and not options.preview:
            return project.resolve(project.output.path)
        suffix = "__preview" if options.preview else ""
        return output_path_in(self.output_dir, project.name, preset.id, suffix, preset.extension)

    # ---------- preparação ----------

    def prepare(self) -> PreparedAudio:
        """Resolve as fontes, sintetiza as narrações, mede as vozes e os efeitos: tudo que vem antes de gravar."""
        ensure_dirs()
        project = apply_track_state(self.project)
        theme = load_theme(project.brand, project.theme)
        job_dir = self.jobs_dir / (project.name + "_audio" + ("_preview" if self.options.preview else ""))
        job_dir.mkdir(parents=True, exist_ok=True)
        pieces_dir = self.pieces.cache_dir / "pieces"
        pieces_dir.mkdir(parents=True, exist_ok=True)
        layout = project_layout(project, self.prober, self.offset_finder)
        ctx = RenderContext(
            project=layout.project,
            options=self.options,
            theme=theme,
            preset=frame_preset(project.output.preset),
            fps=project.output.fps or 30,
            job_dir=job_dir,
            cache_dir=pieces_dir,
            runner=self.runner,
            prober=self.prober,
            narrator=self.narrator,
            isolator=self.isolator,
            log=self.log,
            session=layout.session,
        )
        ctx.warnings.extend(layout.warnings)
        ctx.log(f"render de áudio {project.name}: {self.preset.id}")
        # os efeitos de cada item (cadeia de efeitos) viram um arquivo processado em cache antes de tudo: a mixagem,
        # a duração e a exportação por trilha partem dele, como no render de vídeo e na prévia
        # (o Vocoder que ouve outra trilha precisa dela já na hora de processar o item, então a passada prévia é instalada antes)
        spoken = self.voiceover.prepare(ctx)
        total = layout.total
        if not layout.project.timeline:
            # a duração de uma narração não muda com a cadeia de efeitos (o processado troca só o arquivo)
            total = audio_extent(layout.project, self.prober, [item.duration for item in spoken])
        if total <= 0:
            raise ValueError(NOTHING_TO_PLAY)
        music = layout.project.audio.music
        music_file = layout.project.resolve(music.src) if music else None
        if music_file is not None and not music_file.exists():
            raise FileNotFoundError(f"Música não encontrada: {music.src}")
        voiceovers_of = Deferred(lambda: processed_voiceovers(ctx, spoken), "a narração")
        voice_files_of = Deferred(
            lambda: prepare_voice_files(layout.project, self.prober, effect_processor(ctx)), "a voz gravada"
        )
        music_of = Deferred(lambda: processed_music(ctx, music_file), "a música")
        ctx.warnings.extend(silenced_carrier_warnings(self.project))
        install_carrier_tracks(
            ctx,
            CarrierInputs(
                layout.spans,
                layout.sources,
                total,
                project_track_origin(project),
                voiceovers_of,
                voice_files_of,
                music_of,
            ),
        )
        voiceovers, voice_files = voiceovers_of(), voice_files_of()
        ctx.warnings.extend(audio_output_warnings(project, total))
        ctx.warnings.extend(overrun_warnings(voiceovers, total))
        # a música já processada entra antes dos pedaços: o Auto Duck mede a chave de uma faixa externa de fundo nela
        music_path = music_of()
        begin_ducks(
            ctx,
            DuckInputs(
                layout.spans,
                layout.sources,
                total,
                project_track_origin(project),
                voiceovers,
                voice_files,
                music_path,
            ),
        )
        prepared = self.pieces.pieces(ctx, layout, MissingMedia())
        pips = self.pieces.pip_audio(ctx, total, MissingMedia())
        processed_pips(ctx, pips)
        transitions = transitions_of(layout.project.timeline)
        sfx = leveled_effects(
            ctx, VoiceLevelMeter(), prepared, transitions, layout.spans, total, voiceovers, pips, voice_files
        )
        finish_ducks(ctx, music_path, total, voiceovers, sfx, voice_files)
        # a medida que cada efeito do master pede vem antes de qualquer grafo da mixagem, como no render de vídeo
        plan_master_effects(
            ctx,
            MasterEffectMeter(),
            prepared,
            transitions,
            music_path,
            total,
            voiceovers,
            pips,
            sfx,
            voice_files,
        )
        provenance = ""
        if ctx.narrator is not None and voiceovers:
            provenance = ctx.narrator.provenance(voice_spans(voiceovers), total)
        return PreparedAudio(
            ctx, layout, prepared, total, voiceovers, voice_files, pips, sfx, music_path, provenance
        )

    def loudness(self, job: PreparedAudio) -> LoudnessPlan:
        """A medição da mixagem inteira e o ganho que a normalização dá (uma vez por preparação)."""
        if "mix" not in job.plans:
            job.plans["mix"] = plan_loudness(
                job.ctx,
                LoudnessMeter(),
                job.prepared,
                job.transitions,
                job.music_path,
                job.total,
                job.voiceovers,
                job.pips,
                job.sfx,
                job.voice_files,
            )
        return job.plans["mix"]

    # ---------- a mixagem ----------

    def mix_graph(
        self,
        job: PreparedAudio,
        *,
        plan: LoudnessPlan | None,
        stems: StemTaps | None = None,
    ) -> tuple[Inputs, list[str], str]:
        """Entradas do ffmpeg, linhas do grafo e rótulo da saída: a mixagem do render. Com `plan`, já normalizada
        como sai do render de vídeo; sem ele, a mistura antes da normalização."""
        return audio_only_graph(
            job.ctx,
            job.prepared,
            job.transitions,
            job.music_path,
            job.total,
            job.voiceovers,
            job.pips,
            sfx=job.sfx,
            voice_files=job.voice_files,
            include_norm=bool(plan and plan.normalize),
            measured=plan.measured if plan else None,
            stems=stems,
        )

    def render_mix(self, job: PreparedAudio, out: Path, encoding: AudioEncoding) -> None:
        """Grava a mixagem inteira, normalizada, no formato do preset."""
        inputs, lines, aout = self.mix_graph(job, plan=self.loudness(job))
        tail = format_filters(encoding)
        if tail:
            lines.append(f"{aout}{','.join(tail)}[a_file]")
            aout = "[a_file]"
        tags, notes = output_tags(self.project, job.ctx.theme, encoding.preset, job.provenance)
        job.ctx.warnings.extend(notes)
        out.parent.mkdir(parents=True, exist_ok=True)
        args = [
            *graph_args(job.ctx, inputs, lines, "audio_mix.txt"),
            "-map",
            aout,
            *encode_args(encoding, tags, out, duration=job.total),
        ]
        job.ctx.log("gravando o áudio")
        job.ctx.runner.run(
            FFmpegCommand(args, label="mixagem do áudio", total=job.total, cwd=job.ctx.job_dir)
        )

    # ---------- o Renderer ----------

    def run(self) -> RenderResult:
        job = self.prepare()
        encoding = self.encoding()
        out_path = self.output_path()
        self.render_mix(job, out_path, encoding)
        commands = [format_cmd(c) for c in getattr(job.ctx.runner, "commands", [])]
        (job.ctx.job_dir / "cmd.txt").write_text("\n\n".join(commands), encoding="utf-8")
        job.ctx.log(f"pronto: {out_path}")
        return RenderResult(
            output=out_path,
            duration=job.total,
            preset=encoding.preset,
            warnings=job.ctx.warnings,
            commands=commands,
            job_dir=job.ctx.job_dir,
            size_bytes=out_path.stat().st_size if out_path.exists() and not self.options.dry_run else 0,
        )


def build_audio_renderer(project: Project, options: RenderOptions | None = None, **dependencies: Any):
    """A fábrica registrada para o tipo `audio`: usa as dependências que o render de áudio conhece."""
    known = {name: value for name, value in dependencies.items() if name in AUDIO_DEPENDENCIES}
    return AudioRenderPipeline(project, options, **known)


def _audio_qa(project: Project, **dependencies: Any):
    from .audio_qa import build_audio_report

    return build_audio_report(project, **dependencies)


register_output_kind("audio", build_audio_renderer, qa=_audio_qa)
