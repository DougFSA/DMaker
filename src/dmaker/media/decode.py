"""Decodificar o áudio de um arquivo qualquer (áudio ou vídeo) para um WAV de ponto flutuante, pelo `FFmpegRunner`.

É a porta de entrada das análises: um MP4, um MP3 ou um WAV de 24 bits viram o mesmo WAV de 32 bits flutuante, que
`media/wavio.py` lê sem perder nada (um estouro acima de 0 dBFS no meio da cadeia continua visível).
"""

from __future__ import annotations

from pathlib import Path

from .ffmpeg import FFmpegCommand, FFmpegRunner


def decode_to_wav(
    runner: FFmpegRunner,
    src: Path,
    dst: Path,
    *,
    start: float = 0.0,
    duration: float | None = None,
    stream: int = 0,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> Path:
    """Grava em `dst` o trecho de `src` (a faixa de áudio `stream`) como WAV de ponto flutuante de 32 bits.

    Sem `sample_rate` e `channels` o WAV leva os da fonte, que é o que as medidas pedem (reamostrar mexe no
    pico e esconde o estouro entre amostras). O `-ss` vem antes do `-i`: o ffmpeg pula direto, sem decodificar o
    começo de uma gravação longa."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = []
    if start > 0:
        args += ["-ss", f"{start:.6f}"]
    if duration is not None:
        args += ["-t", f"{max(duration, 0.0):.6f}"]
    args += ["-i", str(src), "-map", f"0:a:{stream}", "-vn", "-c:a", "pcm_f32le"]
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    if channels:
        args += ["-ac", str(channels)]
    args.append(str(dst))
    runner.run(FFmpegCommand(args, label=f"áudio para análise ({src.name})"))
    return dst
