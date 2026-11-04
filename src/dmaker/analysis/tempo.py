"""O andamento de uma música (batidas por minuto) e onde cai o primeiro tempo, por autocorrelação dos ataques.

O Achar Batidas procura picos de energia e, num ritmo de metrônomo com o primeiro tempo mais forte, só acha os tempos fortes:
a mediana dos intervalos dava um quarto do andamento (22,5 em vez de 90). Aqui o andamento sai do conjunto: os ataques do sinal
(os aumentos de energia) se repetem a cada tempo, então a autocorrelação deles tem picos nos múltiplos do período, e o
período que mais se repete é o andamento. Funções puras sobre amostras: não tocam disco, nem o ffmpeg.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# O passo da envoltória de ataques. 1 ms põe o período de 128 BPM (469 ms) em 469 passos: o refinamento com vários
# múltiplos do período chega a décimos de BPM, sem precisar de passo menor.
HOP_SECONDS = 0.001
# O ouvido ouve andamento de 60 a 200 BPM como "um tempo"; fora disso a música tem outro tempo que bate o pé, e a
# estimativa devolve o múltiplo ou a metade que cai na faixa (as outras opções vão em `alternatives`).
DEFAULT_MIN_BPM = 60.0
DEFAULT_MAX_BPM = 200.0
# O centro e a largura (em oitavas) da preferência por andamentos médios, que desempata entre um andamento e o dobro dele
PREFERRED_BPM = 110.0
PREFERENCE_OCTAVES = 1.0
# Quantos múltiplos do período a pontuação soma (o 1º, 2º, 3º e 4º): um período certo se repete em todos
SCORE_MULTIPLES = 4
REFINE_MULTIPLES = 16
# A análise lê no máximo isto do começo do sinal: o andamento de uma música não muda com os minutos, e a autocorrelação de
# cinco minutos já tem centenas de tempos
MAX_ANALYSIS_SECONDS = 300.0
# O mínimo de ataques para falar em andamento: abaixo disso o sinal é uma pancada só
MIN_SECONDS = 1.5


@dataclass(frozen=True)
class TempoEstimate:
    """O andamento estimado: `bpm`, o instante do primeiro tempo no sinal (`beat_offset`, de 0 até um período), a
    confiança (0 a 1, quanto da energia dos ataques se repete nesse período) e as outras leituras possíveis (a metade e
    o dobro que cabem na faixa), para a pessoa trocar quando o ouvido ouvir outro tempo."""

    bpm: float
    beat_offset: float
    confidence: float
    alternatives: tuple[float, ...] = ()


def attack_strength(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, float]:
    """A força dos ataques de `samples` (mono) a cada `HOP_SECONDS`: o aumento da raiz da energia de um bloco para o
    seguinte (a queda vale zero). Devolve a série e o passo real em segundos."""
    hop = max(int(round(sample_rate * HOP_SECONDS)), 1)
    count = len(samples) // hop
    if count < 3:
        return np.zeros(0), hop / sample_rate
    blocks = np.abs(np.asarray(samples[: count * hop], dtype=np.float64)).reshape(count, hop).mean(axis=1)
    # a raiz comprime a faixa: uma batida fraca e uma forte ainda contam parecido, e o ruído de fundo não domina
    smooth = np.sqrt(blocks)
    return np.maximum(np.diff(smooth, prepend=smooth[0]), 0.0), hop / sample_rate


def _autocorrelation(series: np.ndarray) -> np.ndarray:
    """A autocorrelação da série sem a média, sem viés (cada atraso dividido pelo número de pares que o compõem) e
    normalizada pelo atraso 0. Pelo FFT: uma série de cinco minutos custa milissegundos."""
    x = series - series.mean()
    size = 1 << (2 * len(x) - 1).bit_length()
    spectrum = np.fft.rfft(x, size)
    raw = np.fft.irfft(spectrum * np.conj(spectrum), size)[: len(x)]
    raw = raw / np.arange(len(x), 0, -1)
    return raw / raw[0] if raw[0] > 0 else raw


def _preference(bpm: np.ndarray | float) -> np.ndarray | float:
    return np.exp(-0.5 * (np.log2(np.asarray(bpm) / PREFERRED_BPM) / PREFERENCE_OCTAVES) ** 2)


def _score(acf: np.ndarray, bpm: np.ndarray, step: float, multiples: int) -> np.ndarray:
    """Para cada andamento de `bpm`, a média da autocorrelação nos seus primeiros `multiples` múltiplos do período (os
    que cabem na metade da série, onde a autocorrelação ainda tem pares de sobra), com interpolação entre os passos."""
    lags = 60.0 / bpm / step
    limit = len(acf) / 2.0
    total = np.zeros_like(bpm)
    used = np.zeros_like(bpm)
    for k in range(1, multiples + 1):
        at = lags * k
        inside = at < limit
        values = np.interp(np.where(inside, at, 0.0), np.arange(len(acf)), acf)
        total += np.where(inside, values, 0.0)
        used += inside
    return np.where(used > 0, total / np.maximum(used, 1), 0.0)


def estimate_tempo(
    samples: np.ndarray,
    sample_rate: int,
    min_bpm: float = DEFAULT_MIN_BPM,
    max_bpm: float = DEFAULT_MAX_BPM,
) -> TempoEstimate | None:
    """O andamento e o primeiro tempo de `samples` (mono), ou None se o sinal é curto demais ou não tem ataque nenhum."""
    limit = int(MAX_ANALYSIS_SECONDS * sample_rate)
    series, step = attack_strength(np.asarray(samples)[:limit], sample_rate)
    if len(series) * step < MIN_SECONDS or not np.any(series > 0):
        return None
    acf = _autocorrelation(series)
    grid = np.arange(min_bpm, max_bpm + 0.05, 0.1)
    coarse = _score(acf, grid, step, SCORE_MULTIPLES) * _preference(grid)
    best = float(grid[int(np.argmax(coarse))])
    # o refinamento soma mais múltiplos: o erro de um período de 1 passo se divide pelo número do múltiplo
    fine = np.arange(best - 1.0, best + 1.0 + 1e-9, 0.01)
    refined = float(fine[int(np.argmax(_score(acf, fine, step, REFINE_MULTIPLES)))])
    confidence = float(np.clip(_score(acf, np.array([refined]), step, SCORE_MULTIPLES)[0], 0.0, 1.0))
    offset = _first_beat(series, step, 60.0 / refined)
    alternatives = tuple(
        round(candidate, 2) for candidate in (refined / 2.0, refined * 2.0) if min_bpm <= candidate <= max_bpm
    )
    return TempoEstimate(round(refined, 2), round(float(offset), 4), round(confidence, 3), alternatives)


def _first_beat(series: np.ndarray, step: float, period: float) -> float:
    """O instante, de 0 até um período, em que os ataques caem quando dobrados sobre o período: a fase da grade. Os
    ataques entram num histograma circular de um período, suavizado por 5 ms, e o pico é o primeiro tempo."""
    bins = max(int(round(period / step)), 1)
    phase = ((np.arange(len(series)) * step) % period) / period
    histogram = np.bincount(
        np.minimum((phase * bins).astype(int), bins - 1), weights=series, minlength=bins
    ).astype(np.float64)
    width = max(int(round(0.005 / step)) | 1, 3)
    kernel = np.hanning(width + 2)[1:-1]
    kernel /= kernel.sum()
    padded = np.concatenate([histogram[-width:], histogram, histogram[:width]])
    smooth = np.convolve(padded, kernel, mode="same")[width:-width]
    peak = int(np.argmax(smooth))
    # interpolação parabólica entre os três blocos do pico: tira a quantização de 1 passo
    left, middle, right = smooth[(peak - 1) % bins], smooth[peak], smooth[(peak + 1) % bins]
    curvature = left - 2.0 * middle + right
    shift = 0.5 * (left - right) / curvature if curvature < 0 else 0.0
    found = ((peak + shift + 0.5) / bins * period) % period
    # um ataque colado no começo do sinal cai ora logo depois do zero, ora logo antes do fim do período: é o mesmo tempo
    return 0.0 if period - found <= 3 * step else found


def beats_from_grid(offset: float, bpm: float, duration: float) -> list[float]:
    """Os instantes dos tempos de uma grade (`offset`, `bpm`) dentro de `duration`: serve para marcar o que a estimativa
    entendeu e para conferir a estimativa contra um sinal de teste."""
    if bpm <= 0 or duration <= offset:
        return []
    period = 60.0 / bpm
    count = int(math.floor((duration - offset) / period + 1e-9)) + 1
    return [round(offset + n * period, 6) for n in range(count)]
