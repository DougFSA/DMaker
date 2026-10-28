"""Montagem final: linha do tempo + sobreposições + ASS + áudio -> um comando ffmpeg. Medição de loudness."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import FONTS_DIR
from ..domain.spec import Transition
from ..filtergraph.audio import audio_graph, loudnorm_measure_graph
from ..filtergraph.common import Inputs, ffq
from ..filtergraph.encode import encode_args, resolve_encoder
from ..filtergraph.overlays import image_overlay_graph
from ..filtergraph.pip import ResolvedVideoOverlay, pip_audio_graph, video_overlay_graph
from ..filtergraph.provenance import inherited_provenance_args
from ..filtergraph.sfx import SfxInput
from ..filtergraph.timeline import timeline_graph
from ..media.ffmpeg import FFmpegCommand, filter_complex_file_args, hardware_encoder
from .context import RenderContext
from .segments import PreparedSegment
from .textlayer import TextLayer
from .voiceover import PreparedVoiceover

SILENCE_LUFS = -60.0


def _relpath(target: Path, base: Path) -> str:
    try:
        return os.path.relpath(target, base).replace("\\", "/")
    except ValueError:  # unidades diferentes
        return str(target)


def _finite(value: object) -> float | None:
    try:
        f = float(str(value))
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _music_duration(ctx: RenderContext, music_path: Path | None) -> float | None:
    """Duração da música, só quando algum span usa `tail` (evita uma sondagem desnecessária)."""
    music = ctx.project.audio.music
    if music_path is None or music is None or not any(span.tail for span in music.spans):
        return None
    return ctx.prober(music_path).duration


def _audio_only_graph(
    ctx: RenderContext,
    prepared: list[PreparedSegment],
    transitions: list[Transition | None],
    music_path: Path | None,
    total: float,
    voiceovers: Sequence[PreparedVoiceover],
    video_overlays: Sequence[ResolvedVideoOverlay],
    include_music: bool = True,
    sfx: Sequence[SfxInput] = (),
) -> tuple[Inputs, list[str], str]:
    """Entradas e linhas do grafo só de áudio (sem normalização), com a mesma mixagem da montagem final."""
    inputs = Inputs()
    for item in prepared:
        inputs.add(item.mezzanine)
    graph = timeline_graph(
        len(prepared), [p.duration for p in prepared], transitions, ctx.fps, want_video=False
    )
    lines = list(graph.lines)
    # o áudio dos PiPs entra na medição como entra na mixagem final; sem ele a medida não vale
    pip_audio = pip_audio_graph(lines, inputs, list(video_overlays))
    aout = audio_graph(
        lines,
        inputs,
        graph.audio,
        ctx.project.audio,
        music_path,
        total,
        include_music=include_music,
        include_norm=False,
        extra_voices=pip_audio,
        music_duration=_music_duration(ctx, music_path),
        narrations=voiceovers,
        sfx=sfx,
    )
    return inputs, lines, aout


def _loudnorm_report(stderr: str) -> dict | None:
    """O último bloco JSON que o loudnorm imprime em modo de medição (None se não imprimiu nenhum)."""
    blocks = re.findall(r"\{[^{}]*\}", stderr)
    return json.loads(blocks[-1]) if blocks else None


@dataclass
class LoudnessMeasure:
    """Resultado da passada de medição do loudnorm (None = silêncio ou medição indisponível)."""

    values: dict | None

    @property
    def silent(self) -> bool:
        loudness = _finite(self.values.get("input_i")) if self.values else None
        return loudness is None or loudness < SILENCE_LUFS


class LoudnessMeter:
    """Roda só o grafo de áudio com loudnorm em modo de medição e lê o JSON do stderr."""

    def measure(
        self,
        ctx: RenderContext,
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        music_path: Path | None,
        total: float,
        voiceovers: Sequence[PreparedVoiceover] = (),
        video_overlays: Sequence[ResolvedVideoOverlay] = (),
        sfx: Sequence[SfxInput] = (),
    ) -> LoudnessMeasure:
        inputs, lines, aout = _audio_only_graph(
            ctx, prepared, transitions, music_path, total, voiceovers, video_overlays, sfx=sfx
        )
        lines.append(loudnorm_measure_graph(aout, ctx.project.audio.target_lufs))
        args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[ameas]", "-f", "null", "-"]
        stderr = ctx.runner.capture(args, label="medição de loudness")
        data = _loudnorm_report(stderr)
        if data is None:
            return LoudnessMeasure(None)
        (ctx.job_dir / "loudnorm.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        return LoudnessMeasure(data)


@dataclass(frozen=True)
class VoiceLevel:
    """Loudness integrado (LUFS) e pico verdadeiro (dBFS) da voz, antes da música, dos efeitos e da normalização."""

    loudness: float
    true_peak: float


class VoiceLevelMeter:
    """Mede a voz sozinha (áudio dos clipes, PiP e narração; sem música nem efeitos) com o loudnorm em modo de
    medição: é a régua que acerta o nível dos efeitos sonoros, definido em relação a ela."""

    def measure(
        self,
        ctx: RenderContext,
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        total: float,
        voiceovers: Sequence[PreparedVoiceover] = (),
        video_overlays: Sequence[ResolvedVideoOverlay] = (),
    ) -> VoiceLevel | None:
        """None quando não há voz (clipes mudos, só música) ou a medição não devolveu números."""
        inputs, lines, aout = _audio_only_graph(
            ctx, prepared, transitions, None, total, voiceovers, video_overlays, include_music=False
        )
        lines.append(loudnorm_measure_graph(aout, ctx.project.audio.target_lufs, "[vmeas]"))
        args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[vmeas]", "-f", "null", "-"]
        data = _loudnorm_report(ctx.runner.capture(args, label="medição da voz"))
        if data is None or LoudnessMeasure(data).silent:
            return None
        loudness, true_peak = _finite(data.get("input_i")), _finite(data.get("input_tp"))
        if loudness is None or true_peak is None:
            return None
        return VoiceLevel(loudness, true_peak)


@dataclass
class Assembly:
    command: FFmpegCommand
    graph: list[str]


def build_assembly(
    ctx: RenderContext,
    prepared: list[PreparedSegment],
    transitions: list[Transition | None],
    total: float,
    layer: TextLayer,
    music_path: Path | None,
    measured: dict | None,
    normalize: bool,
    out_path: Path,
    voiceovers: Sequence[PreparedVoiceover] = (),
    provenance: str = "",
    sfx: Sequence[SfxInput] = (),
) -> Assembly:
    """Comando final. O grafo vai em arquivo (graph.txt) e o ASS é referenciado por caminho relativo
    ao diretório do job, o que evita a escapada de `C:` nos filtros."""
    p, o = ctx.project, ctx.options
    inputs = Inputs()
    for item in prepared:
        inputs.add(item.mezzanine)
    graph = timeline_graph(
        len(prepared), [x.duration for x in prepared], transitions, ctx.fps, want_video=True
    )
    lines = list(graph.lines)
    cur_v = graph.video or ""
    cur_v = image_overlay_graph(
        lines,
        inputs,
        cur_v,
        layer.image_overlays,
        ctx.width,
        ctx.height,
        ctx.fps,
        total,
        ctx.scale,
        ctx.preset.safe,
    )
    cur_v, pip_audio = video_overlay_graph(
        lines,
        inputs,
        cur_v,
        layer.video_overlays,
        ctx.width,
        ctx.height,
        ctx.fps,
        total,
        ctx.scale,
        ctx.preset.safe,
    )
    if layer.has_text:
        lines.append(
            f"{cur_v}ass=filename={ffq('overlay.ass')}:fontsdir={ffq(_relpath(FONTS_DIR, ctx.job_dir))}[v_ass]"
        )
        cur_v = "[v_ass]"
    lines.append(f"{cur_v}format=yuv420p[vout]")
    aout = audio_graph(
        lines,
        inputs,
        graph.audio,
        p.audio,
        music_path,
        total,
        measured=measured,
        include_norm=normalize,
        extra_voices=pip_audio,
        music_duration=_music_duration(ctx, music_path),
        narrations=voiceovers,
        sfx=sfx,
    )

    quality = "draft" if o.preview else p.output.quality
    encoder = "x264" if o.preview else resolve_encoder(p.output.encoder, hardware_encoder())
    args = inputs.args + filter_complex_file_args("graph.txt") + ["-map", "[vout]", "-map", aout]
    args += encode_args(ctx.preset, quality, encoder, ctx.fps) + inherited_provenance_args(provenance)
    args += ["-shortest", str(out_path)]
    return Assembly(FFmpegCommand(args, label="montagem final", total=total, cwd=ctx.job_dir), lines)
