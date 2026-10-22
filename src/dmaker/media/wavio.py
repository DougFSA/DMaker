"""Leitura e escrita de WAV PCM 16 bits com a biblioteca padrão.

Existe para que o núcleo de voz não dependa do `soundfile` (que só o extra `voice` instala).
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

INT16_MAX = 32767


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> Path:
    """Grava amostras float (-1..1, mono) como int16; valores fora da faixa são limitados."""
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = np.round(clipped * INT16_MAX).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Lê um WAV PCM 16 bits e devolve (amostras float32 mono, taxa); estéreo vira média dos canais."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(
                f"{path.name}: só WAV de 16 bits é suportado (recebi {handle.getsampwidth() * 8})"
            )
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / INT16_MAX
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, sample_rate


def wav_duration(path: Path) -> float:
    """Duração em segundos lida só do cabeçalho, sem carregar as amostras."""
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()
