"""Comandos que geram o mezanino (intermediário já no tamanho/fps de saída) de cada trecho.

Três formas de entrada:
- clipe de vídeo: corte, velocidade, reenquadramento e cor no próprio FFmpeg;
- imagem parada: PNG já no tamanho de saída, repetido pela duração;
- quadros gerados (Ken Burns sub-pixel): rawvideo RGB escrito no stdin do ffmpeg.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class TrackSlice:
    """Fatia de uma faixa de áudio externa alinhada ao trecho: `in_point` é o tempo no arquivo da faixa
    correspondente ao início do trecho (negativo quando a faixa ainda não tinha começado)."""

    path: Path
    in_point: float
    volume: float = 1.0
    audio_stream: int = 0


def _audio_source_chain(in_point: float, volume: float, length: float) -> list[str]:
    """Alinha uma fonte de áudio ao início do trecho: atraso quando ela começa depois, ganho e formato."""
    chain = ["asetpts=PTS-STARTPTS"]
    if in_point < 0:
        chain.append(f"adelay={int(round(-in_point * 1000))}:all=1")
    if volume != 1:
        chain.append(f"volume={volume:.3f}")
    chain.append(f"atrim=0:{length:.3f}")
    chain.append(AUDIO_FMT_MEZZ)
    return chain


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
    in_point: float | None = None,
    tracks: tuple[TrackSlice, ...] = (),
    audio_stream: int = 0,
    backdrop: Path | None = None,
    reframe: Reframe | None = None,
    has_brand: bool = False,
    label: str = "trecho",
) -> FFmpegCommand:
    """`in_point` é o tempo no arquivo onde o trecho começa (padrão: seg.start, para arquivo avulso);
    `tracks` são faixas externas sincronizadas misturadas ao áudio da câmera; `backdrop` é o PNG de fundo
    do modo brand; `reframe` substitui o enquadramento da spec."""
    reframe = reframe or seg.reframe
    post, afades = _post_chain(seg.color, seg.fade_in, seg.fade_out, duration)
    inputs = Inputs()
    start = seg.start if in_point is None else in_point
    length = max(duration * seg.speed, 0.01)  # tempo de fonte que o trecho consome
    inputs.add(src, "-ss", f"{max(start, 0):.3f}", "-t", f"{length:.3f}")
    backdrop_label = f"[{inputs.add_looped_image(backdrop, fps, duration)}:v]" if backdrop else None

    lines = [f"[0:v]setpts=(PTS-STARTPTS)/{seg.speed:.5g},fps={fps:g}[mz_v0]"]
    lines.append(
        reframe_graph("[mz_v0]", "[mz_v1]", info.width, info.height, W, H, reframe, has_brand, backdrop_label)
    )
    lines.append("[mz_v1]" + ",".join(post) + "[vout]")

    # áudio: câmera (se houver e não estiver muda) + faixas externas, tudo já alinhado ao trecho
    voices: list[str] = []
    if info.has_audio and not seg.mute and seg.volume > 0:
        lines.append(
            f"[0:a:{audio_stream}]" + ",".join(_audio_source_chain(0.0, seg.volume, length)) + "[mz_cam]"
        )
        voices.append("[mz_cam]")
    for k, track in enumerate(tracks):
        idx = inputs.add(track.path, "-ss", f"{max(track.in_point, 0):.3f}", "-t", f"{length:.3f}")
        chain = _audio_source_chain(min(track.in_point, 0.0), track.volume, length)
        lines.append(f"[{idx}:a:{track.audio_stream}]" + ",".join(chain) + f"[mz_trk{k}]")
        voices.append(f"[mz_trk{k}]")

    tail = ([atempo_chain(seg.speed)] if seg.speed != 1 else []) + [AUDIO_FMT_MEZZ] + afades
    if not voices:
        lines.append(f"[{inputs.add_silence(duration)}:a]{AUDIO_FMT_MEZZ}[aout]")
    elif len(voices) == 1:
        lines.append(voices[0] + ",".join(tail) + "[aout]")
    else:
        lines.append(
            "".join(voices)
            + f"amix=inputs={len(voices)}:duration=longest:dropout_transition=0:normalize=0,"
            + ",".join(tail)
            + "[aout]"
        )
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
