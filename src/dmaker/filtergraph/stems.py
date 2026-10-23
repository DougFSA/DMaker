"""Comandos de áudio do isolamento vocal: extração para o separador e conversão dos stems exportados."""

from __future__ import annotations

from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from .voice import encoder_args

# O htdemucs foi treinado com estéreo a 44,1 kHz: extrair já nesse formato evita reamostrar depois, e
# mono vira estéreo duplicando o canal. PCM 16 bits basta: a fonte costuma ser AAC/MP3 de 16 bits.
SEPARATION_SAMPLE_RATE = 44100


def extract_for_separation(
    src: Path,
    out: Path,
    start: float | None = None,
    end: float | None = None,
    audio_stream: int = 0,
    label: str = "extração do áudio",
) -> FFmpegCommand:
    """Áudio do trecho `start`..`end` (segundos no arquivo; sem eles, o arquivo todo) como WAV estéreo."""
    args: list[str] = []
    if start:
        args += ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-t", f"{end - (start or 0.0):.3f}"]
    args += ["-i", str(src), "-map", f"0:a:{audio_stream}", "-vn", "-ac", "2"]
    args += ["-ar", str(SEPARATION_SAMPLE_RATE), "-c:a", "pcm_s16le", str(out)]
    total = None if end is None else end - (start or 0.0)
    return FFmpegCommand(args, label=label, total=total)


def convert_stem(src: Path, out: Path, label: str = "conversão do stem") -> FFmpegCommand:
    """Reencoda um stem WAV no formato da extensão de `out` (.wav, .mp3 ou .m4a)."""
    return FFmpegCommand(["-i", str(src), "-vn", *encoder_args(out), str(out)], label=label)
