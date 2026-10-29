"""Comandos do áudio da prévia da linha do tempo: um arquivo leve com o som do vídeo como o render o faz.

A prévia no navegador toca UM áudio, mixado no servidor, em vez de abrir um elemento por faixa (o Chrome
trava a partir de seis conexões ao mesmo tempo). O som de cada trecho sai do mesmo ramo de áudio do
mezanino do render (`clip_audio_lines`), só que sem o vídeo: são os "pedaços" (um WAV por trecho, guardados
em cache pelo que muda o som do trecho). A montagem dos pedaços com transições, voz, música e normalização
é o grafo de áudio do render (`filtergraph/audio.py`); aqui ficam só o pedaço e a codificação final.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.spec import ClipSegment
from ..media.ffmpeg import FFmpegCommand
from ..media.probe import MediaInfo
from .common import Inputs
from .mezzanine import TrackSlice, clip_audio_lines, uses_camera_audio

# AAC a 96 kbps estéreo: transparente para conferir corte e mixagem, ~700 KB por minuto. O AAC toca em
# qualquer navegador (o Opus não toca no Safari) e dispensa uma segunda codificação no servidor.
PREVIEW_AUDIO_BITRATE = "96k"
# o pedaço é um WAV de 16 bits como o áudio do mezanino: o grafo de montagem recebe o mesmo formato
PIECE_CODEC = ["-c:a", "pcm_s16le"]


def clip_audio_piece(
    seg: ClipSegment,
    info: MediaInfo,
    src: Path,
    duration: float,
    out: Path,
    *,
    in_point: float,
    tracks: tuple[TrackSlice, ...] = (),
    audio_stream: int = 0,
    camera_audio: Path | None = None,
    label: str = "áudio do trecho",
) -> FFmpegCommand:
    """O som de um trecho de clipe, `duration` segundos na linha do tempo final. O arquivo do clipe só é
    aberto quando a câmera soa e não vem de um áudio já isolado (`camera_audio`)."""
    inputs = Inputs()
    length = max(duration * seg.speed, 0.01)  # tempo de fonte que o trecho consome
    source_index = -1
    if uses_camera_audio(seg, info) and camera_audio is None:
        source_index = inputs.add(src, "-ss", f"{max(in_point, 0):.3f}", "-t", f"{length:.3f}")
    lines: list[str] = []
    clip_audio_lines(
        inputs,
        lines,
        seg,
        info,
        duration,
        length,
        source_index=source_index,
        tracks=tracks,
        audio_stream=audio_stream,
        camera_audio=camera_audio,
    )
    args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[aout]", *PIECE_CODEC, str(out)]
    return FFmpegCommand(args, label=label, total=duration)


def silence_piece(duration: float, out: Path, label: str = "silêncio do trecho") -> FFmpegCommand:
    """Imagem e cartão não têm som: o pedaço é silêncio da duração do trecho."""
    inputs = Inputs()
    inputs.add_silence(duration)
    args = [*inputs.args, "-map", "0:a", *PIECE_CODEC, str(out)]
    return FFmpegCommand(args, label=label, total=duration)


def preview_encode_args(total: float, out: Path) -> list[str]:
    """Saída da mixagem da prévia: AAC em MP4 com o índice no início (`faststart`), para o navegador pular
    para qualquer ponto sem baixar o arquivo inteiro; 48 kHz estéreo como o resto da mixagem."""
    return [
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        PREVIEW_AUDIO_BITRATE,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-t",
        f"{total:.3f}",
        "-movflags",
        "+faststart",
        str(out),
    ]
