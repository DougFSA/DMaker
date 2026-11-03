"""Comando do ffmpeg que converte áudio bruto (PCM sem cabeçalho) num WAV: o "Import Raw Data" do Audacity.

Um arquivo sem cabeçalho não diz como ler os bytes, então quem importa diz: a codificação das amostras, a ordem dos
bytes, os canais e a taxa de amostragem. Funções puras; o `FFmpegRunner` do pipeline executa.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..media.ffmpeg import FFmpegCommand


@dataclass(frozen=True)
class RawEncoding:
    """Uma codificação de amostras brutas: o nome do demuxer do ffmpeg, os bytes por amostra e o codec do WAV."""

    label: str
    demuxer: str  # `{}` é trocado por `le` ou `be`; sem `{}` não há ordem de bytes
    bytes_per_sample: int
    wav_codec: str


# Os nomes são os da janela do Audacity. O WAV não tem PCM de 8 bits com sinal nem de 16 com sinal ausente, então
# `s8` e `u16` viram 16 bits com sinal, que guarda os mesmos valores sem perda.
RAW_ENCODINGS: dict[str, RawEncoding] = {
    "s8": RawEncoding("PCM de 8 bits com sinal", "s8", 1, "pcm_s16le"),
    "u8": RawEncoding("PCM de 8 bits sem sinal", "u8", 1, "pcm_u8"),
    "s16": RawEncoding("PCM de 16 bits com sinal", "s16{}", 2, "pcm_s16le"),
    "u16": RawEncoding("PCM de 16 bits sem sinal", "u16{}", 2, "pcm_s16le"),
    "s24": RawEncoding("PCM de 24 bits com sinal", "s24{}", 3, "pcm_s24le"),
    "s32": RawEncoding("PCM de 32 bits com sinal", "s32{}", 4, "pcm_s32le"),
    "f32": RawEncoding("Ponto flutuante de 32 bits", "f32{}", 4, "pcm_f32le"),
    "f64": RawEncoding("Ponto flutuante de 64 bits", "f64{}", 8, "pcm_f64le"),
    "ulaw": RawEncoding("U-Law (8 bits)", "mulaw", 1, "pcm_s16le"),
    "alaw": RawEncoding("A-Law (8 bits)", "alaw", 1, "pcm_s16le"),
}
BYTE_ORDERS = ("little", "big")
MAX_RAW_CHANNELS = 8


def raw_demuxer(encoding: str, byte_order: str) -> str:
    """O nome do demuxer do ffmpeg para a codificação e a ordem de bytes, com erro claro para o que não existe."""
    if encoding not in RAW_ENCODINGS:
        raise ValueError(f"codificação desconhecida: {encoding!r} (use {', '.join(RAW_ENCODINGS)})")
    if byte_order not in BYTE_ORDERS:
        raise ValueError(f"ordem de bytes desconhecida: {byte_order!r} (use {' ou '.join(BYTE_ORDERS)})")
    return RAW_ENCODINGS[encoding].demuxer.format("le" if byte_order == "little" else "be")


def raw_duration(
    size_bytes: int, encoding: str, channels: int, sample_rate: int, offset_bytes: int = 0
) -> float:
    """Quantos segundos de áudio o arquivo tem, contando a partir do deslocamento inicial."""
    frame = RAW_ENCODINGS[encoding].bytes_per_sample * channels
    return max(size_bytes - offset_bytes, 0) // frame / sample_rate


def raw_import_command(
    src: Path,
    dst: Path,
    *,
    encoding: str,
    byte_order: str,
    channels: int,
    sample_rate: int,
    offset_bytes: int = 0,
    duration: float | None = None,
) -> FFmpegCommand:
    """Lê o PCM bruto de `src` e grava um WAV em `dst`. `offset_bytes` pula o começo (um cabeçalho que o formato tem);
    `duration` importa só os primeiros segundos do que sobra (a "quantidade a importar" do Audacity). A amostra é
    gravada no mesmo tamanho que tinha, sem converter (nada se perde na importação)."""
    codec = RAW_ENCODINGS[encoding].wav_codec
    args = ["-f", raw_demuxer(encoding, byte_order), "-ar", str(sample_rate), "-ac", str(channels)]
    if offset_bytes:
        args += ["-skip_initial_bytes", str(offset_bytes)]
    args += ["-i", str(src), "-vn", "-c:a", codec]
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    args.append(str(dst))
    return FFmpegCommand(args, label="importando áudio bruto", total=duration)
