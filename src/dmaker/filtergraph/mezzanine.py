"""Comandos que geram o mezanino (intermediário já no tamanho/fps de saída) de cada trecho.

Três formas de entrada:
- clipe de vídeo: corte, velocidade, reenquadramento e cor no próprio FFmpeg;
- imagem parada: PNG já no tamanho de saída, repetido pela duração;
- quadros gerados (Ken Burns sub-pixel): rawvideo RGB escrito no stdin do ffmpeg.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..domain.spec import ClipSegment, Reframe
from ..media.ffmpeg import FFmpegCommand
from ..media.probe import MediaInfo
from .common import AUDIO_FMT_MEZZ, Inputs, atempo_chain, color_chain, fade_chains
from .encode import mezzanine_output_args
from .reframe import reframe_graph


def _post_chain(
    segment_color, fade_in: float, fade_out: float, duration: float
) -> tuple[list[str], list[str]]:
    vfades, afades = fade_chains(fade_in, fade_out, duration)
    video = color_chain(segment_color) + vfades + ["format=yuv420p", "setsar=1"]
    return video, afades


def _finish(
    inputs: Inputs,
    lines: list[str],
    fps: float,
    duration: float,
    out: Path,
    label: str,
    frames: Iterable[bytes] | None = None,
) -> FFmpegCommand:
    args = inputs.args + ["-filter_complex", ";".join(lines), "-map", "[vout]", "-map", "[aout]"]
    args += mezzanine_output_args(fps, duration, str(out))
    return FFmpegCommand(args, label=label, total=duration, frames=frames)


def clip_mezzanine(
    seg: ClipSegment,
    info: MediaInfo,
    src: Path,
    duration: float,
    W: int,
    H: int,
    fps: float,
    out: Path,
    *,
    backdrop: Path | None = None,
    reframe: Reframe | None = None,
    has_brand: bool = False,
    label: str = "trecho",
) -> FFmpegCommand:
    """`backdrop` é o PNG de fundo do modo brand; `reframe` substitui o enquadramento da spec."""
    reframe = reframe or seg.reframe
    post, afades = _post_chain(seg.color, seg.fade_in, seg.fade_out, duration)
    inputs = Inputs()
    end = seg.end if seg.end is not None else info.duration
    inputs.add(src, "-ss", f"{seg.start:.3f}", "-t", f"{max(end - seg.start, 0.01):.3f}")
    has_voice = info.has_audio and not seg.mute and seg.volume > 0
    audio_label = "[0:a]" if has_voice else f"[{inputs.add_silence(duration)}:a]"
    backdrop_label = f"[{inputs.add_looped_image(backdrop, fps, duration)}:v]" if backdrop else None

    lines = [f"[0:v]setpts=(PTS-STARTPTS)/{seg.speed:.5g},fps={fps:g}[mz_v0]"]
    lines.append(
        reframe_graph("[mz_v0]", "[mz_v1]", info.width, info.height, W, H, reframe, has_brand, backdrop_label)
    )
    lines.append("[mz_v1]" + ",".join(post) + "[vout]")
    if has_voice:
        achain = ["asetpts=PTS-STARTPTS"]
        if seg.speed != 1:
            achain.append(atempo_chain(seg.speed))
        if seg.volume != 1:
            achain.append(f"volume={seg.volume:.3f}")
        lines.append("[0:a]" + ",".join(achain + [AUDIO_FMT_MEZZ] + afades) + "[aout]")
    else:
        lines.append(f"{audio_label}{AUDIO_FMT_MEZZ}[aout]")
    return _finish(inputs, lines, fps, duration, out, label)


def still_mezzanine(
    png: Path,
    segment_color,
    fade_in: float,
    fade_out: float,
    duration: float,
    fps: float,
    out: Path,
    label: str = "trecho",
) -> FFmpegCommand:
    """Imagem já no tamanho de saída, parada pela duração do trecho."""
    post, _ = _post_chain(segment_color, fade_in, fade_out, duration)
    inputs = Inputs()
    inputs.add_looped_image(png, fps, duration)
    inputs.add_silence(duration)
    lines = ["[0:v]" + ",".join(post) + "[vout]", f"[1:a]{AUDIO_FMT_MEZZ}[aout]"]
    return _finish(inputs, lines, fps, duration, out, label)


def frames_mezzanine(
    frames: Iterable[bytes],
    W: int,
    H: int,
    segment_color,
    fade_in: float,
    fade_out: float,
    duration: float,
    fps: float,
    out: Path,
    label: str = "trecho",
) -> FFmpegCommand:
    """Quadros RGB24 de WxH vindos do stdin (movimento renderizado com precisão sub-pixel)."""
    post, _ = _post_chain(segment_color, fade_in, fade_out, duration)
    inputs = Inputs()
    inputs.add("pipe:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps:g}")
    inputs.add_silence(duration)
    lines = ["[0:v]" + ",".join(post) + "[vout]", f"[1:a]{AUDIO_FMT_MEZZ}[aout]"]
    return _finish(inputs, lines, fps, duration, out, label, frames=frames)
