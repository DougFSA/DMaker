"""Comando ffmpeg da troca de voz: a fala convertida somada ao fundo original, no vídeo ou áudio de origem.

Funções puras: recebem dados e devolvem o comando. O fundo (música, ambiente) entra como saiu do isolamento,
sem passar pelo modelo de voz; só a fala é a convertida.
"""

from __future__ import annotations

from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from .dub import MIX_SAMPLE_RATE
from .speech_edit import FASTSTART_CONTAINERS, VIDEO_AUDIO_ARGS
from .voice import encoder_args

# Limitador a -1 dBFS (0,891 linear), como o da dublagem: fala e fundo somados podem passar de 0 dBFS, e o
# `level=disabled` impede que ele renormalize o volume sozinho. `latency=1` compensa os 5 ms de antecipação
# do limitador, que sem isso atrasariam o som em relação à imagem.
LIMITER = "alimiter=limit=0.891:level=disabled:latency=1"

# Recorte de vídeo exige recodificar: com `-c:v copy` o corte cai no quadro-chave anterior e a imagem sairia
# adiantada em relação ao som. CRF 18 é visualmente sem perda; `veryfast` mantém o tempo de espera baixo.
CUT_VIDEO_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def _stereo_48k() -> str:
    """Mesma taxa, formato e canais nos dois ramos, que o amix exige iguais (a fala mono vira estéreo)."""
    return f"aresample={MIX_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"


def voice_swap_graph(voice_input: int, background_input: int, duration: float, gain_db: float = 0.0) -> str:
    """Grafo da mixagem; a saída é `[out]`, com `duration` segundos.

    `normalize=0` soma sem dividir por 2 (o amix padrão baixaria fundo e fala pela metade); o limitador
    cobre o caso de fala e fundo somados passarem de 0 dBFS; `apad` e `atrim` fixam a duração para a
    imagem e o som terminarem juntos.
    """
    return ";".join(
        [
            f"[{background_input}:a]{_stereo_48k()}[background]",
            f"[{voice_input}:a]volume={gain_db:.2f}dB,{_stereo_48k()}[voice]",
            f"[background][voice]amix=inputs=2:duration=first:normalize=0,{LIMITER},"
            f"apad=whole_dur={duration:.3f},atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[out]",
        ]
    )


def voice_swap_command(
    source: Path,
    voice: Path,
    background: Path,
    out: Path,
    duration: float,
    gain_db: float = 0.0,
    has_video: bool = False,
    cut_start: float | None = None,
) -> FFmpegCommand:
    """Grava `out` com o fundo mais a fala convertida; com vídeo, mantém a imagem do original.

    `cut_start` é o início (s) do trecho quando só uma parte do arquivo foi convertida; `None` é o arquivo
    inteiro, em que a imagem passa sem recodificar (rápido e sem perda). No trecho o vídeo é recortado e
    recodificado, para a imagem e a fala convertida começarem juntas.
    """
    args: list[str] = []
    if has_video:
        if cut_start:
            args += ["-ss", f"{cut_start:.3f}"]
        if cut_start is not None:
            args += ["-t", f"{duration:.3f}"]  # o trecho; no arquivo inteiro a imagem define o fim
        args += ["-i", str(source)]  # índice 0
    first_audio = 1 if has_video else 0
    args += ["-i", str(background), "-i", str(voice)]
    args += ["-filter_complex", voice_swap_graph(first_audio + 1, first_audio, duration, gain_db)]
    if has_video:
        video_args = ["-c:v", "copy"] if cut_start is None else CUT_VIDEO_ARGS
        args += ["-map", "0:v:0", *video_args, "-map", "[out]", *VIDEO_AUDIO_ARGS]
        if out.suffix.lower() in FASTSTART_CONTAINERS:
            args += [
                "-movflags",
                "+faststart",
            ]  # o índice no começo deixa o arquivo tocar antes de baixar inteiro
    else:
        args += ["-map", "[out]", *encoder_args(out)]
    return FFmpegCommand([*args, str(out)], label="troca de voz", total=duration)
