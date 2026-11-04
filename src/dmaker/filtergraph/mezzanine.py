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

from ..domain.audio_shift import shifted_window
from ..domain.spec import ClipSegment, ColorAdjust, Reframe
from ..media.ffmpeg import FFmpegCommand
from ..media.probe import MediaInfo
from .common import AUDIO_FMT_MEZZ, Inputs, atempo_chain, audio_edge_fades, fade_chains
from .duck import duck_filters
from .encode import mezzanine_output_args
from .finish import post_video_lines
from .mix import pan_filter
from .reframe import reframe_graph


def _audio_fades(fade_in: float, fade_out: float, duration: float) -> list[str]:
    return fade_chains(fade_in, fade_out, duration)[1]


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
    pan: float = 0.0
    # curvas do Auto Duck que abaixam esta faixa neste clipe: pontos (segundos de fonte desde o início do trecho, dB); vazio
    # sem regra, e então o ramo de áudio é o de sempre
    duck: tuple[tuple[tuple[float, float], ...], ...] = ()


def _audio_source_chain(
    in_point: float,
    volume: float,
    length: float,
    pan: float = 0.0,
    pad: bool = False,
    duck: tuple[tuple[tuple[float, float], ...], ...] = (),
) -> list[str]:
    """Alinha uma fonte de áudio ao início do trecho: atraso quando ela começa depois, ganho, equilíbrio e formato.
    `pad` completa com silêncio o que a fonte não tem até `length`: um som deslocado pode acabar antes da imagem, e
    o áudio do trecho tem que durar o mesmo que o vídeo para a montagem seguinte não perder o sincronismo."""
    chain = ["asetpts=PTS-STARTPTS"]
    if in_point < 0:
        chain.append(f"adelay={int(round(-in_point * 1000))}:all=1")
    if volume != 1:
        chain.append(f"volume={volume:.3f}")
    balance = pan_filter(pan)
    if balance:
        chain.append(balance)
    for curve in duck:  # depois do atraso: `t` é o instante do trecho, em segundos de fonte
        chain += duck_filters(curve)
    if pad:
        chain.append("apad")
    chain.append(f"atrim=0:{length:.3f}")
    chain.append(AUDIO_FMT_MEZZ)
    return chain


def uses_camera_audio(seg: ClipSegment, info: MediaInfo) -> bool:
    """O som da própria câmera entra no trecho: o arquivo tem áudio e o trecho não está mudo nem a volume zero."""
    return info.has_audio and not seg.mute and seg.volume > 0


def clip_audio_lines(
    inputs: Inputs,
    lines: list[str],
    seg: ClipSegment,
    info: MediaInfo,
    duration: float,
    length: float,
    *,
    source_index: int,
    tracks: tuple[TrackSlice, ...] = (),
    audio_stream: int = 0,
    camera_audio: Path | None = None,
    src: Path | None = None,
    in_point: float = 0.0,
    camera_lead: float = 0.0,
) -> None:
    """Acrescenta a `lines` o ramo de áudio do trecho, terminado em `[aout]`: câmera (se houver e não estiver
    muda) + faixas externas, tudo alinhado ao início do trecho, com velocidade e fades. `source_index` é a
    entrada do arquivo do clipe. É a mesma receita para o mezanino do render e para o áudio da prévia
    (`filtergraph/preview_audio.py`), que por isso soam iguais.

    Com `audio_offset` o som anda em relação à imagem, então sai de uma entrada própria do arquivo `src`, lida a
    partir de onde o som deslocado começa (`in_point` é o ponto da fonte em que a imagem começa); `camera_lead` é o
    silêncio que antecede um `camera_audio` já recortado (som isolado) cujo início cai antes do começo do arquivo."""
    afades = _audio_fades(seg.fade_in, seg.fade_out, duration)
    afades += audio_edge_fades(seg.audio_fade, duration)
    voices: list[str] = []
    if uses_camera_audio(seg, info):
        lead = 0.0
        if camera_audio is not None:
            index = inputs.add(camera_audio, "-t", f"{length:.3f}")
            camera = f"[{index}:a:0]"
            lead = camera_lead
        elif seg.audio_offset and src is not None:
            window = shifted_window(in_point, seg.speed, seg.audio_offset)
            index = inputs.add(src, "-ss", f"{window.read_from:.3f}", "-t", f"{length:.3f}")
            camera = f"[{index}:a:{audio_stream}]"
            lead = window.lead
        else:
            camera = f"[{source_index}:a:{audio_stream}]"
        chain = _audio_source_chain(-lead, seg.volume, length, seg.pan, pad=bool(seg.audio_offset))
        lines.append(camera + ",".join(chain) + "[mz_cam]")
        voices.append("[mz_cam]")
    for k, track in enumerate(tracks):
        idx = inputs.add(track.path, "-ss", f"{max(track.in_point, 0):.3f}", "-t", f"{length:.3f}")
        chain = _audio_source_chain(
            min(track.in_point, 0.0), track.volume, length, track.pan, duck=track.duck
        )
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
    camera_audio: Path | None = None,
    camera_lead: float = 0.0,
    backdrop: Path | None = None,
    reframe: Reframe | None = None,
    has_brand: bool = False,
    look: ColorAdjust | None = None,
    label: str = "trecho",
) -> FFmpegCommand:
    """`in_point` é o tempo no arquivo onde o trecho começa (padrão: seg.start, para arquivo avulso);
    `tracks` são faixas externas sincronizadas misturadas ao áudio da câmera; `camera_audio` é um áudio
    já recortado no trecho (começa no `in_point`) que substitui o da câmera, como a voz isolada;
    `backdrop` é o PNG de fundo do modo brand; `reframe` substitui o enquadramento da spec; `look` é o
    acabamento (cor e efeitos) do look que vale no trecho, já resolvido."""
    reframe = reframe or seg.reframe
    inputs = Inputs()
    start = seg.start if in_point is None else in_point
    length = max(duration * seg.speed, 0.01)  # tempo de fonte que o trecho consome
    inputs.add(src, "-ss", f"{max(start, 0):.3f}", "-t", f"{length:.3f}")
    backdrop_label = f"[{inputs.add_looped_image(backdrop, fps, duration)}:v]" if backdrop else None

    lines = [f"[0:v]setpts=(PTS-STARTPTS)/{seg.speed:.5g},fps={fps:g}[mz_v0]"]
    lines.append(
        reframe_graph("[mz_v0]", "[mz_v1]", info.width, info.height, W, H, reframe, has_brand, backdrop_label)
    )
    lines += post_video_lines(
        "[mz_v1]", "[vout]", seg.color, look, seg.fade_in, seg.fade_out, duration, (W, H), fps
    )
    clip_audio_lines(
        inputs,
        lines,
        seg,
        info,
        duration,
        length,
        source_index=0,
        tracks=tracks,
        audio_stream=audio_stream,
        camera_audio=camera_audio,
        src=src,
        in_point=start,
        camera_lead=camera_lead,
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
    *,
    look: ColorAdjust | None = None,
    size: tuple[int, int] | None = None,
) -> FFmpegCommand:
    """Imagem já no tamanho de saída, parada pela duração do trecho. `size` (largura, altura) é preciso quando há
    efeito de acabamento no look ou na cor."""
    inputs = Inputs()
    inputs.add_looped_image(png, fps, duration)
    inputs.add_silence(duration)
    lines = post_video_lines("[0:v]", "[vout]", segment_color, look, fade_in, fade_out, duration, size, fps)
    lines.append(f"[1:a]{AUDIO_FMT_MEZZ}[aout]")
    return _finish(inputs, lines, fps, duration, out, label)


def matte_mezzanine(
    frames: Iterable[bytes],
    src: Path,
    start: float,
    length: float,
    W: int,
    H: int,
    fps: float,
    out: Path,
    *,
    has_audio: bool = True,
    audio_stream: int = 0,
    label: str = "recorte",
) -> FFmpegCommand:
    """Fonte com o fundo trocado: os quadros recortados vêm pelo stdin e o áudio do mesmo intervalo do
    arquivo original. O resultado substitui o arquivo fonte no resto do pipeline (corte, velocidade,
    enquadramento e cor continuam no mezanino normal)."""
    inputs = Inputs()
    inputs.add("pipe:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps:g}")
    lines = ["[0:v]format=yuv420p[vout]"]
    if has_audio:
        idx = inputs.add(src, "-ss", f"{max(start, 0):.3f}", "-t", f"{length:.3f}")
        lines.append(f"[{idx}:a:{audio_stream}]asetpts=PTS-STARTPTS,{AUDIO_FMT_MEZZ}[aout]")
    else:
        lines.append(f"[{inputs.add_silence(length)}:a]{AUDIO_FMT_MEZZ}[aout]")
    return _finish(inputs, lines, fps, length, out, label, frames=frames)


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
    *,
    look: ColorAdjust | None = None,
) -> FFmpegCommand:
    """Quadros RGB24 de WxH vindos do stdin (movimento renderizado com precisão sub-pixel)."""
    inputs = Inputs()
    inputs.add("pipe:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps:g}")
    inputs.add_silence(duration)
    lines = post_video_lines("[0:v]", "[vout]", segment_color, look, fade_in, fade_out, duration, (W, H), fps)
    lines.append(f"[1:a]{AUDIO_FMT_MEZZ}[aout]")
    return _finish(inputs, lines, fps, duration, out, label, frames=frames)
