"""Leitura e escrita de WAV PCM 16 bits com a biblioteca padrão.

Existe para que o núcleo de voz não dependa do `soundfile` (que só o extra `voice` instala).
"""

from __future__ import annotations

import io
import struct
import wave
from pathlib import Path

import numpy as np

INT16_MAX = 32767


def write_wav_channels(path: Path, samples: np.ndarray, sample_rate: int) -> Path:
    """Grava amostras float (-1..1) de forma (quadros, canais) como int16; o que passa da faixa é limitado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = np.asarray(samples, dtype=np.float32)
    if frames.ndim != 2:
        raise ValueError("as amostras precisam ter a forma (quadros, canais)")
    pcm = np.round(np.clip(frames, -1.0, 1.0) * INT16_MAX).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(frames.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """Amostras float (-1..1) de forma (quadros, canais) como o conteúdo de um WAV de 16 bits, sem passar por arquivo.
    É o que a interface baixa para tocar uma janela do áudio; o que passa da faixa é limitado."""
    frames = np.asarray(samples, dtype=np.float32)
    if frames.ndim != 2:
        raise ValueError("as amostras precisam ter a forma (quadros, canais)")
    pcm = np.round(np.clip(frames, -1.0, 1.0) * INT16_MAX).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(frames.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def read_wav_channels(path: Path) -> tuple[np.ndarray, int]:
    """Lê um WAV PCM 16 bits e devolve (amostras float32 de forma (quadros, canais), taxa)."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(
                f"{path.name}: só WAV de 16 bits é suportado (recebi {handle.getsampwidth() * 8})"
            )
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / INT16_MAX
    return pcm.reshape(-1, channels), sample_rate


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> Path:
    """Grava amostras float (-1..1, mono) como int16; valores fora da faixa são limitados."""
    return write_wav_channels(path, np.asarray(samples, dtype=np.float32).reshape(-1, 1), sample_rate)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Lê um WAV PCM 16 bits e devolve (amostras float32 mono, taxa); estéreo vira média dos canais."""
    frames, sample_rate = read_wav_channels(path)
    return frames.mean(axis=1) if frames.shape[1] > 1 else frames[:, 0], sample_rate


def wav_duration(path: Path) -> float:
    """Duração em segundos lida só do cabeçalho, sem carregar as amostras."""
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


# ---------- WAV de qualquer profundidade, para medir ----------

_FORMAT_PCM = 1
_FORMAT_FLOAT = 3
_FORMAT_EXTENSIBLE = 0xFFFE
_RIFF_IDS = (b"RIFF", b"RF64")


def _wav_layout(handle) -> tuple[int, int, int, int, int, int]:
    """Lê o cabeçalho de um WAV aberto e devolve (formato, canais, taxa, bits, posição dos dados, bytes de dados).

    Percorre os blocos em vez de supor que `data` vem logo depois de `fmt `: o ffmpeg põe um bloco `LIST` antes dele.
    O tamanho dos dados que passa do arquivo (cabeçalho de gravação em andamento) vale o que há de fato."""
    head = handle.read(12)
    if len(head) < 12 or head[:4] not in _RIFF_IDS or head[8:12] != b"WAVE":
        raise ValueError("o arquivo não é um WAV")
    handle.seek(0, 2)
    file_size = handle.tell()
    handle.seek(12)
    fmt: tuple[int, int, int, int] | None = None
    while True:
        chunk = handle.read(8)
        if len(chunk) < 8:
            raise ValueError("o WAV não tem o bloco de dados")
        chunk_id, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
        if chunk_id == b"fmt ":
            body = handle.read(size + (size & 1))
            tag, channels, rate = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
            if tag == _FORMAT_EXTENSIBLE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[
                    0
                ]  # o início do GUID do subformato é o código do formato
            fmt = (tag, channels, rate, bits)
        elif chunk_id == b"data":
            if fmt is None:
                raise ValueError("o WAV tem os dados antes do formato")
            position = handle.tell()
            return (*fmt, position, min(size, file_size - position))
        else:
            handle.seek(size + (size & 1), 1)


def _decode_pcm(raw: bytes, tag: int, bits: int, path: Path) -> np.ndarray:
    """Os bytes de um bloco de dados como ponto flutuante de -1 a 1 (uma amostra por elemento, canais intercalados)."""
    if tag == _FORMAT_FLOAT and bits in (32, 64):
        return np.frombuffer(raw, dtype="<f4" if bits == 32 else "<f8").astype(np.float32)
    if tag == _FORMAT_PCM and bits == 8:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if tag == _FORMAT_PCM and bits == 16:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if tag == _FORMAT_PCM and bits == 24:
        triples = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        value = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        return np.where(value & 0x800000, value - 0x1000000, value).astype(np.float32) / 8388608.0
    if tag == _FORMAT_PCM and bits == 32:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    raise ValueError(f"{path.name}: WAV de {bits} bits (formato {tag}) não é suportado")


def read_wav_float(path: Path, start: float = 0.0, duration: float | None = None) -> tuple[np.ndarray, int]:
    """Lê um WAV PCM (8, 16, 24 ou 32 bits) ou de ponto flutuante (32 ou 64) e devolve (amostras float32 de forma
    (quadros, canais), taxa). `start` e `duration` (segundos) leem só um trecho, sem carregar o arquivo inteiro: é o que
    deixa medir um intervalo de um arquivo processado grande. O que passa do fim do arquivo fica de fora."""
    with open(path, "rb") as handle:
        tag, channels, rate, bits, position, size = _wav_layout(handle)
        block = channels * (bits // 8)
        total = size // block
        first = min(max(int(round(start * rate)), 0), total)
        last = total if duration is None else min(first + max(int(round(duration * rate)), 0), total)
        handle.seek(position + first * block)
        raw = handle.read((last - first) * block)
    samples = _decode_pcm(raw, tag, bits, path)
    return samples.reshape(-1, channels), rate
