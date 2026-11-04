"""O sinal que os analisadores recebem (amostras em ponto flutuante) e as contas de nível em dB.

Tudo é função pura sobre numpy: ler o arquivo, decodificar e achar o item na spec são do pipeline
(`pipeline/audio_analysis.py`). Os níveis seguem a convenção do Audacity: dB relativo à escala cheia (dBFS), em que
um seno de amplitude 1 tem RMS de -3,01 dB e pico de 0 dB.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# O silêncio total daria -infinito, que o JSON não guarda: ele vira este piso (cerca de 24 bits de faixa dinâmica).
DB_FLOOR = -144.0
_TINY = 10.0 ** (DB_FLOOR / 20.0)


def linear_to_db(value: float | np.ndarray) -> float | np.ndarray:
    """Amplitude linear em dB (20·log10), com o piso `DB_FLOOR` no silêncio."""
    return 20.0 * np.log10(np.maximum(np.abs(value), _TINY))


def db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


@dataclass(frozen=True)
class Signal:
    """Amostras de forma (quadros, canais) e a taxa em Hz. É o que todo analisador recebe."""

    samples: np.ndarray
    sample_rate: int

    def __post_init__(self) -> None:
        if self.samples.ndim != 2:
            raise ValueError("as amostras precisam ter a forma (quadros, canais)")
        if self.sample_rate <= 0:
            raise ValueError("a taxa de amostragem precisa ser positiva")

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration(self) -> float:
        return self.frames / self.sample_rate

    def mono(self) -> np.ndarray:
        """A média dos canais, como o Audacity mistura o estéreo para analisar (um canal só passa direto)."""
        if self.channels == 1:
            return self.samples[:, 0]
        return self.samples.mean(axis=1)

    def slice(self, start: float, end: float | None = None) -> Signal:
        """O trecho de `start` a `end` segundos (até o fim, sem `end`). Fora do sinal, o trecho fica vazio."""
        first = max(int(round(start * self.sample_rate)), 0)
        last = self.frames if end is None else min(int(round(end * self.sample_rate)), self.frames)
        return Signal(self.samples[first : max(last, first)], self.sample_rate)

    def time_of(self, index: int | float | np.ndarray) -> float | np.ndarray:
        """O instante, em segundos desde o começo do sinal, de uma amostra."""
        return index / self.sample_rate


def rms(samples: np.ndarray) -> float:
    """RMS linear de todas as amostras (todos os canais juntos). 0.0 para um trecho vazio."""
    if samples.size == 0:
        return 0.0
    return math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))


def rms_db(samples: np.ndarray) -> float:
    return float(linear_to_db(rms(samples)))


def peak_db(samples: np.ndarray) -> float:
    """O pico (maior amostra em módulo) em dBFS."""
    if samples.size == 0:
        return DB_FLOOR
    return float(linear_to_db(float(np.max(np.abs(samples)))))


def frame_levels_db(samples: np.ndarray, sample_rate: int, frame_seconds: float) -> np.ndarray:
    """RMS em dB de cada quadro consecutivo de `frame_seconds` (o resto menor que um quadro é descartado), com os
    canais somados em potência. Devolve um vetor vazio quando o sinal é mais curto que um quadro."""
    size = max(int(round(sample_rate * frame_seconds)), 1)
    count = samples.shape[0] // size
    if count == 0:
        return np.zeros(0, dtype=np.float64)
    block = np.asarray(samples[: count * size], dtype=np.float64)
    power = np.square(block).reshape(count, size, -1).mean(axis=(1, 2))
    return linear_to_db(np.sqrt(power))
