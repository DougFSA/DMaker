"""A curva de um equalizador por pontos (EQ Gráfico e EQ por Curva), em contas puras sobre numpy.

Os dois efeitos descrevem o ganho por frequência com pontos `(Hz, dB)`. `interpolate_db` liga os pontos pela escala e pelo
método que a pessoa escolheu, e `gain_entry` escreve a MESMA curva, amostrada, na sintaxe do `firequalizer` do ffmpeg.
A resposta que a interface desenha é o que `interpolate_db` devolve, então o gráfico e o filtro partem da mesma conta.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np

Scale = Literal["log", "linear"]
Method = Literal["linear", "cosine", "cubic"]

# O `firequalizer` aceita no máximo 100 entradas em `gain_entry` (com 101 ele recusa montar o filtro), então a curva é
# amostrada dentro deste teto: os pontos da pessoa mais o que sobrar, repartido entre os intervalos
MAX_ENTRIES = 100
# As pontas da curva: o ganho se mantém de 10 Hz (abaixo do menor ponto permitido) ao fim do espectro de 48 kHz
SAMPLE_LOW_HZ = 10.0
SAMPLE_HIGH_HZ = 24000.0
# Peso mínimo, em dB, de um intervalo plano na partilha das amostras extras (para ele não ficar sem nenhuma)
SPARE_FLOOR_DB = 0.5


def _axis(hz: np.ndarray, scale: Scale) -> np.ndarray:
    return np.log2(hz) if scale == "log" else hz


def _pchip_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Inclinações de uma cúbica de Hermite que preserva a forma (Fritsch-Butland): nunca passa do maior nem do menor
    ponto vizinho, então um ganho de +6 dB em uma banda não faz a vizinha cair abaixo de zero."""
    h = np.diff(x)
    delta = np.diff(y) / h
    slopes = np.zeros_like(y)
    if len(x) == 2:
        slopes[:] = delta[0]
        return slopes
    for k in range(1, len(x) - 1):
        if delta[k - 1] * delta[k] > 0:
            w1 = 2.0 * h[k] + h[k - 1]
            w2 = h[k] + 2.0 * h[k - 1]
            slopes[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])

    def edge(h0: float, h1: float, d0: float, d1: float) -> float:
        value = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if value * d0 <= 0:
            return 0.0
        if d0 * d1 <= 0 and abs(value) > 3.0 * abs(d0):
            return 3.0 * d0
        return value

    slopes[0] = edge(h[0], h[1], delta[0], delta[1])
    slopes[-1] = edge(h[-1], h[-2], delta[-1], delta[-2])
    return slopes


def interpolate_db(
    points_hz: Sequence[float],
    points_db: Sequence[float],
    hz: np.ndarray,
    scale: Scale = "log",
    method: Method = "cubic",
) -> np.ndarray:
    """O ganho em dB, em cada frequência de `hz`, da curva que passa pelos pontos. `scale` é o eixo em que se interpola
    (`log`: por oitava; `linear`: por Hz) e `method`, o desenho entre dois pontos: `linear` (retas), `cosine` (suave nos
    pontos) ou `cubic` (cúbica que preserva a forma). Fora do primeiro e do último ponto, o ganho se mantém."""
    if len(points_hz) != len(points_db) or not points_hz:
        raise ValueError("a curva precisa de pelo menos um ponto, com frequência e ganho")
    order = np.argsort(points_hz)
    px = _axis(np.asarray(points_hz, dtype=float)[order], scale)
    py = np.asarray(points_db, dtype=float)[order]
    x = _axis(np.maximum(np.asarray(hz, dtype=float), 1e-3), scale)
    if len(px) == 1:
        return np.full_like(x, py[0])
    clamped = np.clip(x, px[0], px[-1])
    if method == "linear":
        return np.interp(clamped, px, py)
    index = np.clip(np.searchsorted(px, clamped, side="right") - 1, 0, len(px) - 2)
    width = px[index + 1] - px[index]
    t = (clamped - px[index]) / width
    if method == "cosine":
        eased = (1.0 - np.cos(np.pi * t)) / 2.0
        return py[index] + (py[index + 1] - py[index]) * eased
    slopes = _pchip_slopes(px, py)
    t2, t3 = t * t, t**3
    return (
        (2 * t3 - 3 * t2 + 1) * py[index]
        + (t3 - 2 * t2 + t) * width * slopes[index]
        + (-2 * t3 + 3 * t2) * py[index + 1]
        + (t3 - t2) * width * slopes[index + 1]
    )


def sample_frequencies(points_hz: Sequence[float], points_db: Sequence[float]) -> np.ndarray:
    """As frequências em que a curva é escrita para o ffmpeg: as dos pontos (um canto da curva cai exatamente onde a
    pessoa o pôs), as duas pontas e, entre pontos vizinhos, amostras extras até o teto de `MAX_ENTRIES`, repartidas pelo
    quanto o ganho muda em cada intervalo (um trecho plano quase não precisa, uma subida íngreme precisa de várias,
    porque o ffmpeg interpola entre as amostras por conta própria). Abaixo do primeiro ponto e acima do último o ganho
    é fixo e nada extra é preciso."""
    order = np.argsort(points_hz)
    hz = np.asarray(points_hz, dtype=float)[order]
    db = np.asarray(points_db, dtype=float)[order]
    nodes = np.unique(np.round(np.concatenate([[SAMPLE_LOW_HZ, SAMPLE_HIGH_HZ], hz]), 6))
    spare = MAX_ENTRIES - len(nodes)
    extra: list[np.ndarray] = []
    if spare > 0 and len(hz) > 1:
        weights = np.abs(np.diff(db)) + SPARE_FLOOR_DB
        counts = np.floor(spare * weights / weights.sum()).astype(int)
        for low, high, count in zip(hz[:-1], hz[1:], counts, strict=True):
            if count > 0 and high > low:
                extra.append(low * (high / low) ** (np.arange(1, count + 1) / (count + 1)))
    return np.unique(np.round(np.concatenate([nodes, *extra]), 6))


def gain_entry(hz: np.ndarray, db: np.ndarray) -> str:
    """A curva na sintaxe do `gain_entry` do `firequalizer`: `entry(f,g);entry(f,g);...`, com g em dB."""
    return ";".join(f"entry({f:.6g},{g:.6g})" for f, g in zip(hz, db, strict=True))


def curve_for_filter(
    points_hz: Sequence[float], points_db: Sequence[float], scale: Scale, method: Method
) -> tuple[np.ndarray, np.ndarray]:
    """As frequências e os ganhos (dB) que o `firequalizer` recebe: a curva do efeito amostrada em `sample_frequencies`."""
    hz = sample_frequencies(points_hz, points_db)
    return hz, interpolate_db(points_hz, points_db, hz, scale, method)


def display_frequencies(count: int = 256, low: float = 20.0, high: float = 20000.0) -> np.ndarray:
    """As frequências do gráfico de resposta: `count` valores igualmente espaçados em oitavas, de `low` a `high`."""
    return low * (high / low) ** (np.arange(count) / (count - 1))
