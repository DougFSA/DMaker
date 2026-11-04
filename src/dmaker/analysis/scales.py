"""As escalas de frequência do espectrograma: como a altura da imagem se reparte entre os Hz.

Cada escala é um par de funções puras, da frequência para uma posição e de volta, e as linhas da imagem ficam igualmente
espaçadas na posição. A linear mostra o espectro como ele é; as outras quatro dão mais linhas às frequências baixas, onde o
ouvido separa melhor um som do outro: a log (oitavas), a Mel, a Bark e a ERB (as três da psicoacústica). Os nomes e as
fórmulas são as conhecidas da literatura (Mel de O'Shaughnessy, Bark de Traunmüller, ERB de Glasberg e Moore).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np

ScaleName = Literal["linear", "log", "mel", "bark", "erb"]
SCALE_NAMES: tuple[str, ...] = ("linear", "log", "mel", "bark", "erb")

# A escala log não tem o zero (o logaritmo dele não existe): abaixo disto toda frequência vale esta
LOG_FLOOR_HZ = 1.0
MIN_SPAN_HZ = 1.0  # uma faixa mais estreita que isto não tem imagem para mostrar


_FORWARD: dict[str, Callable[[np.ndarray | float], np.ndarray | float]] = {
    "linear": lambda hz: hz,
    "log": lambda hz: np.log10(np.maximum(hz, LOG_FLOOR_HZ)),
    "mel": lambda hz: 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0),
    "bark": lambda hz: 26.81 * np.asarray(hz) / (1960.0 + np.asarray(hz)) - 0.53,
    "erb": lambda hz: 21.4 * np.log10(1.0 + 0.00437 * np.asarray(hz)),
}
_INVERSE: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "linear": lambda position: position,
    "log": lambda position: 10.0**position,
    "mel": lambda position: 700.0 * (10.0 ** (position / 2595.0) - 1.0),
    "bark": lambda position: 1960.0 * (position + 0.53) / (26.81 - (position + 0.53)),
    "erb": lambda position: (10.0 ** (position / 21.4) - 1.0) / 0.00437,
}


def check_scale(scale: str) -> None:
    if scale not in _FORWARD:
        raise ValueError(f"escala desconhecida: {scale!r}. Use uma de: {', '.join(SCALE_NAMES)}")


def scale_position(scale: str, hz: np.ndarray | float) -> np.ndarray | float:
    """A posição de uma frequência na escala (cresce com a frequência)."""
    check_scale(scale)
    return _FORWARD[scale](hz)


def scale_frequency(scale: str, position: np.ndarray) -> np.ndarray:
    """A frequência de uma posição da escala (o inverso de `scale_position`)."""
    check_scale(scale)
    return _INVERSE[scale](np.asarray(position, dtype=np.float64))


def check_band(scale: str, min_hz: float, max_hz: float, nyquist: float) -> tuple[float, float]:
    """A faixa mostrada, validada e com o teto no Nyquist; a log pede um piso acima de zero."""
    check_scale(scale)
    top = min(max_hz, nyquist)
    if min_hz < 0 or top - min_hz < MIN_SPAN_HZ:
        raise ValueError(
            f"a faixa de {min_hz:g} a {max_hz:g} Hz não cabe no espectro (de 0 a {nyquist:g} Hz, com ao menos {MIN_SPAN_HZ:g} Hz)"
        )
    if scale == "log" and min_hz < LOG_FLOOR_HZ:
        raise ValueError(
            f"a escala log precisa de min_hz de {LOG_FLOOR_HZ:g} Hz ou mais (o zero não tem logaritmo)"
        )
    return min_hz, top


def row_edges(scale: str, rows: int, min_hz: float, max_hz: float) -> np.ndarray:
    """As `rows + 1` fronteiras das linhas, em Hz e em ordem crescente: a linha `i` (de baixo para cima) cobre de
    `edges[i]` a `edges[i + 1]`, e todas têm a mesma altura na escala."""
    low, high = float(scale_position(scale, min_hz)), float(scale_position(scale, max_hz))
    return scale_frequency(scale, np.linspace(low, high, rows + 1))


def frequency_row(scale: str, hz: float, rows: int, min_hz: float, max_hz: float) -> float:
    """A linha da imagem (contada de CIMA, como o PNG; fracionária, o centro da linha é .5) onde cai a frequência `hz`.
    O que a interface usa para pôr a régua de frequência e o retângulo da seleção no lugar certo."""
    low, high = float(scale_position(scale, min_hz)), float(scale_position(scale, max_hz))
    fraction = (float(scale_position(scale, hz)) - low) / (high - low)
    return (1.0 - fraction) * rows


def row_frequency(scale: str, row: float, rows: int, min_hz: float, max_hz: float) -> float:
    """O inverso de `frequency_row`: a frequência (Hz) de uma posição da imagem contada de cima."""
    low, high = float(scale_position(scale, min_hz)), float(scale_position(scale, max_hz))
    position = low + (1.0 - row / rows) * (high - low)
    return float(scale_frequency(scale, np.asarray([position]))[0])


__all__ = [
    "SCALE_NAMES",
    "ScaleName",
    "check_band",
    "check_scale",
    "frequency_row",
    "row_edges",
    "row_frequency",
    "scale_frequency",
    "scale_position",
]
