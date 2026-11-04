"""Truncar Silêncio: achar as pausas de um som e planejar quanto de cada uma sai. Funções puras sobre amostras.

É o que o "Truncate Silence" do Audacity faz: um silêncio é um trecho em que nenhuma amostra passa do limiar, por mais
de uma duração mínima; ele é truncado para uma duração fixa ("truncar para N s") ou só o excesso é comprimido
("comprimir em N%"). Diferente do corte automático (`voice/cut_plan.py`), não olha palavras: não corta fala, só
encurta pausas. O que sai é o meio da pausa, e o respiro de cada ponta fica, então a fala não encosta na seguinte.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

TruncateMode = Literal["truncate", "compress"]
MODES: tuple[str, ...] = ("truncate", "compress")

FRAME_SECONDS = 0.01  # o silêncio é medido em quadros de 10 ms, como o resto das medidas de nível da voz
MIN_REMOVED = 0.02  # tirar menos que isto (20 ms) não encurta nada que se perceba e só cria uma emenda à toa
# o corte procura o ponto mais quieto perto da borda ideal: 5 ms bastam para cair numa passagem por zero sem entrar na fala
SNAP_SECONDS = 0.005


def find_silences(
    samples: np.ndarray, sample_rate: int, threshold_db: float, min_duration: float
) -> list[tuple[float, float]]:
    """Os silêncios de um sinal mono: `(início, fim)` em segundos dos trechos, de `min_duration` ou mais, em que o pico de
    cada quadro de 10 ms fica abaixo de `threshold_db` (dBFS). Um silêncio que vai até o fim do sinal conta."""
    size = max(1, round(sample_rate * FRAME_SECONDS))
    count = len(samples) // size
    if count == 0:
        return []
    peaks = np.abs(np.asarray(samples[: count * size], dtype=np.float32)).reshape(count, size).max(axis=1)
    quiet = peaks < 10.0 ** (threshold_db / 20.0)
    silences: list[tuple[float, float]] = []
    run_start: int | None = None
    for index, is_quiet in enumerate([*quiet, False]):  # o False final fecha uma pausa que vai até o fim
        if is_quiet and run_start is None:
            run_start = index
        elif not is_quiet and run_start is not None:
            start, end = run_start * FRAME_SECONDS, index * FRAME_SECONDS
            if end - start >= min_duration - 1e-9:
                silences.append((round(start, 6), round(min(end, len(samples) / sample_rate), 6)))
            run_start = None
    return silences


def kept_length(
    length: float, mode: TruncateMode, min_duration: float, truncate_to: float, percent: float
) -> float:
    """Quanto da pausa de `length` segundos fica. `truncate`: a duração fixa (`truncate_to`, nunca mais que a própria
    pausa). `compress`: a duração mínima inteira e `percent` % do que passa dela (0% é o mesmo que truncar para a
    duração mínima; 100% não muda nada)."""
    if mode == "truncate":
        return min(truncate_to, length)
    return min(length, min_duration + (length - min_duration) * percent / 100.0)


def plan_truncation(
    samples: np.ndarray,
    sample_rate: int,
    silences: list[tuple[float, float]],
    mode: TruncateMode,
    min_duration: float,
    truncate_to: float,
    percent: float,
    frame_grid: float | None = None,
    grid_origin: float = 0.0,
) -> list[tuple[float, float]]:
    """Os trechos que SAEM, `(início, fim)` em segundos do sinal e em ordem: o meio de cada silêncio, deixando metade do
    que fica em cada ponta. As duas bordas caem no ponto mais quieto (±5 ms), para a emenda não estalar. Com
    `frame_grid` (a grade de quadros do vídeo), o que fica antes de cada corte dura um múltiplo dela, como no corte
    automático, para a imagem e o som continuarem com a mesma duração depois de cortados em pedaços. `grid_origin` é
    quanto o sinal começa depois do começo do trecho que fica (quando só uma seleção do clipe foi medida)."""
    removed: list[tuple[float, float]] = []
    cursor = (
        -grid_origin
    )  # começo do pedaço que fica: o que fica entre ele e o corte dura um múltiplo da grade
    for start, end in silences:
        length = end - start
        keep = kept_length(length, mode, min_duration, truncate_to, percent)
        if length - keep < MIN_REMOVED:
            continue
        cut_start = _quietest_near(samples, sample_rate, start + keep / 2.0, start, end)
        cut_end = _quietest_near(samples, sample_rate, end - keep / 2.0, start, end)
        if frame_grid:
            # arredonda para cima: o corte anda para dentro da pausa, nunca para dentro da fala que a antecede
            steps = max(math.ceil((cut_start - cursor) / frame_grid - 1e-9), 0)
            cut_start = cursor + steps * frame_grid
        if cut_start < start - 1e-9 or cut_end - cut_start < MIN_REMOVED:
            continue
        removed.append((round(cut_start, 6), round(cut_end, 6)))
        cursor = cut_end
    return removed


def _quietest_near(samples: np.ndarray, sample_rate: int, center: float, low: float, high: float) -> float:
    """O instante de menor amplitude num raio de 5 ms em torno de `center`, sem sair de `low`..`high`."""
    radius = round(sample_rate * SNAP_SECONDS)
    middle = round(center * sample_rate)
    first = max(middle - radius, round(low * sample_rate), 0)
    last = min(middle + radius + 1, round(high * sample_rate), len(samples))
    if last - first < 2:
        return center
    window = np.abs(np.asarray(samples[first:last], dtype=np.float64))
    # num trecho de silêncio digital todas as amostras empatam em zero: o desempate fica com a mais perto de `center`
    window += 1e-12 * np.abs(np.arange(first, last) - middle)
    return (first + int(np.argmin(window))) / sample_rate


def removed_seconds(removed: list[tuple[float, float]]) -> float:
    return math.fsum(end - start for start, end in removed)
