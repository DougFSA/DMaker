"""Medidas de nível sobre amostras de fala: volume da voz, ganho para igualar e ponto mais quieto. Funções puras."""

from __future__ import annotations

import math

import numpy as np

FRAME_SECONDS = (
    0.01  # 10 ms: curto o bastante para achar o vale entre duas palavras, longo para um RMS estável
)
ACTIVE_BELOW_PEAK_DB = 25.0  # quadros mais de 25 dB abaixo dos mais fortes são pausa ou respiração, não fala
MAX_GAIN_DB = 9.0  # além disso a diferença é de timbre ou de gravação, e amplificar só pioraria
SILENCE_FLOOR = 1e-9


def frame_rms(samples: np.ndarray, sample_rate: int, frame_seconds: float = FRAME_SECONDS) -> np.ndarray:
    """RMS de cada quadro consecutivo (o resto menor que um quadro é descartado)."""
    size = max(1, int(sample_rate * frame_seconds))
    count = len(samples) // size
    if count == 0:
        return np.zeros(0, dtype=np.float64)
    frames = np.asarray(samples[: count * size], dtype=np.float64).reshape(count, size)
    return np.sqrt(np.mean(np.square(frames), axis=1))


def active_rms(samples: np.ndarray, sample_rate: int) -> float:
    """Volume (RMS) só dos quadros com fala: pausas não puxam a média para baixo. 0.0 se tudo é silêncio."""
    levels = frame_rms(samples, sample_rate)
    if levels.size == 0:
        return 0.0
    loud = float(np.percentile(levels, 95))
    if loud < SILENCE_FLOOR:
        return 0.0
    active = levels[levels >= loud * 10.0 ** (-ACTIVE_BELOW_PEAK_DB / 20.0)]
    return float(np.sqrt(np.mean(np.square(active))))


def gain_to_match_db(speech_rms: float, reference_rms: float, limit_db: float = MAX_GAIN_DB) -> float:
    """Ganho em dB que leva `speech_rms` até `reference_rms`, limitado a ±`limit_db`; 0 se faltar medida."""
    if speech_rms <= SILENCE_FLOOR or reference_rms <= SILENCE_FLOOR:
        return 0.0
    gain = 20.0 * math.log10(reference_rms / speech_rms)
    return max(-limit_db, min(limit_db, gain))


def quietest_time(
    samples: np.ndarray, sample_rate: int, center: float, radius: float, frame_seconds: float = FRAME_SECONDS
) -> float:
    """Instante (s) do quadro mais quieto em `center` ± `radius`; no empate, o mais perto de `center`.

    Emendar no vale entre duas palavras evita um corte no meio de um som. Fora do áudio, devolve `center`.
    """
    size = max(1, int(sample_rate * frame_seconds))
    first = max(0, int((center - radius) * sample_rate))
    last = min(len(samples), int((center + radius) * sample_rate))
    levels = frame_rms(samples[first:last], sample_rate, frame_seconds)
    if levels.size == 0:
        return center
    centers = (first + np.arange(levels.size) * size + size / 2) / sample_rate
    # a distância ao centro desempata sem pesar: 1e-6 por segundo é menor que qualquer diferença de nível real
    best = int(np.argmin(levels + 1e-6 * np.abs(centers - center)))
    return float(centers[best])
