"""O espectrograma como imagem em tons de cinza: funções puras sobre quadros de amostras (numpy), sem ffmpeg e sem disco.

Cada coluna da imagem é um trecho de tempo; ela mostra a média da potência de alguns quadros de FFT tirados de dentro do
trecho (no máximo `MAX_FRAMES_PER_COLUMN`), em vez de todos. É o que faz uma hora inteira caber numa tela sem ler a hora:
com o trecho de cada coluna de uns 3,5 s, só uns 8 quadros de 2048 amostras por coluna são lidos, e os quadros entre eles
não contam. Cada linha é uma faixa de frequência da escala escolhida (`scales`), e o valor do pixel é o nível em dB (a
mesma escala de amplitude do espectro de `fft`) com o ganho e o alcance aplicados: 0 é o preto (alcance abaixo do nível) e
255 é o branco. A cor fica por conta de quem mostra a imagem.

O reparte dos quadros e a leitura deles são de quem chama (`FrameSource`): aqui só entram quadros prontos.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .fft import coherent_gain, is_fft_size, window_coefficients
from .scales import check_band, row_edges

# Quantos quadros de FFT entram na média de uma coluna, no máximo. Com mais que isto a vista afastada leria o áudio todo
# para pintar o que o olho já vê com 8 amostras do trecho.
MAX_FRAMES_PER_COLUMN = 8
MAX_ROWS = 2048
MIN_ROWS = 16
DEFAULT_GAIN_DB = 20.0  # o padrão do Audacity: sobe 20 dB, para a fala comum ficar no meio da escala
DEFAULT_RANGE_DB = 80.0  # e mostra 80 dB de dinâmica
_POWER_FLOOR = 1e-24


@dataclass(frozen=True)
class SpectrogramParams:
    """O que muda a imagem além do som e do trecho."""

    rows: int = 256
    scale: str = "linear"
    window: str = "hann"
    window_size: int = 2048
    gain_db: float = DEFAULT_GAIN_DB
    range_db: float = DEFAULT_RANGE_DB
    min_hz: float = 0.0
    max_hz: float = 24000.0

    def checked(self, sample_rate: int) -> SpectrogramParams:
        """Os mesmos parâmetros com a faixa dentro do Nyquist, ou erro em português dizendo o que não vale."""
        if not MIN_ROWS <= self.rows <= MAX_ROWS:
            raise ValueError(f"rows precisa estar entre {MIN_ROWS} e {MAX_ROWS}, não {self.rows}")
        if not is_fft_size(self.window_size):
            raise ValueError(f"window_size inválido: {self.window_size} (potência de dois de 128 a 65536)")
        if not 1.0 <= self.range_db <= 200.0:
            raise ValueError(f"range_db precisa estar entre 1 e 200, não {self.range_db:g}")
        window_coefficients(self.window, 2)  # nome de janela inválido falha aqui, com a lista das válidas
        low, high = check_band(self.scale, self.min_hz, self.max_hz, sample_rate / 2)
        return SpectrogramParams(
            self.rows, self.scale, self.window, self.window_size, self.gain_db, self.range_db, low, high
        )


class FrameSource(Protocol):
    """De onde vêm os quadros: `batches` devolve, em ordem, `(posição do primeiro, quadros)` com os quadros de `size`
    amostras que começam em cada `starts` (inteiros, em amostras; podem sair do áudio, e aí completam com silêncio). A
    forma é `(quadros, size, canais)`. Quem implementa decide como ler sem trazer o áudio todo para a memória."""

    def batches(self, starts: np.ndarray, size: int) -> Iterator[tuple[int, np.ndarray]]: ...


def frames_per_column(column_samples: float, size: int) -> int:
    """Quantos quadros uma coluna de `column_samples` amostras usa: um se ela cabe num quadro, senão os que a cobrem, até
    o teto de `MAX_FRAMES_PER_COLUMN`."""
    return int(min(MAX_FRAMES_PER_COLUMN, max(1, math.ceil(column_samples / size))))


def frame_starts(
    first_sample: float, column_samples: float, columns: int, size: int
) -> tuple[np.ndarray, np.ndarray]:
    """O começo (em amostras) de cada quadro e a coluna a que ele pertence, em ordem. Os quadros de uma coluna ficam
    espalhados por igual dentro do trecho dela, cada um centrado no seu pedaço."""
    per_column = frames_per_column(column_samples, size)
    column = np.repeat(np.arange(columns), per_column)
    part = np.tile(np.arange(per_column), columns)
    centers = first_sample + (column + (part + 0.5) / per_column) * column_samples
    return np.rint(centers - size / 2.0).astype(np.int64), column


class RowMap:
    """Leva a potência por divisão da FFT (`bins`) para a potência por linha da imagem. Linha mais larga que uma divisão
    leva o máximo das divisões dentro dela (um tom estreito não some ao afastar); linha mais estreita interpola entre
    as duas divisões vizinhas do centro dela."""

    def __init__(self, size: int, sample_rate: int, params: SpectrogramParams) -> None:
        edges = row_edges(params.scale, params.rows, params.min_hz, params.max_hz)
        bin_hz = sample_rate / size
        bins = size // 2 + 1
        self.rows = params.rows
        self.coarse: list[tuple[int, int, int]] = []  # (linha, primeira divisão, última divisão)
        fine_rows, fine_at = [], []
        for row in range(params.rows):
            low, high = edges[row], edges[row + 1]
            first, last = math.ceil(low / bin_hz), math.floor(high / bin_hz)
            if high - low >= bin_hz and last >= first:
                self.coarse.append((row, min(first, bins - 1), min(last, bins - 1)))
            else:
                fine_rows.append(row)
                fine_at.append(min(max((low + high) / 2.0 / bin_hz, 0.0), bins - 1.0))
        self.fine_rows = np.asarray(fine_rows, dtype=np.int64)
        position = np.asarray(fine_at, dtype=np.float64)
        self.fine_low = np.floor(position).astype(np.int64)
        self.fine_high = np.minimum(self.fine_low + 1, bins - 1)
        self.fine_weight = position - self.fine_low

    def apply(self, power: np.ndarray) -> np.ndarray:
        """`power` (quadros, divisões) -> (quadros, linhas), a linha 0 sendo a de MENOS frequência."""
        result = np.empty((power.shape[0], self.rows), dtype=np.float64)
        for row, first, last in self.coarse:
            result[:, row] = power[:, first : last + 1].max(axis=1)
        if len(self.fine_rows):
            blended = (
                power[:, self.fine_low] * (1.0 - self.fine_weight)
                + power[:, self.fine_high] * self.fine_weight
            )
            result[:, self.fine_rows] = blended
        return result


def column_power(
    source: FrameSource,
    sample_rate: int,
    first_sample: float,
    column_samples: float,
    columns: int,
    params: SpectrogramParams,
) -> np.ndarray:
    """A potência média de cada coluna por linha, `(colunas, linhas)` com a linha 0 na menor frequência. Lê só os quadros
    que `frame_starts` manda e os processa em lotes: a memória não cresce com a duração do trecho."""
    size = params.window_size
    window = window_coefficients(params.window, size)
    rows = RowMap(size, sample_rate, params)
    starts, column = frame_starts(first_sample, column_samples, columns, size)
    total = np.zeros((columns, params.rows), dtype=np.float64)
    counts = np.zeros(columns, dtype=np.int64)
    for offset, frames in source.batches(starts, size):
        count = frames.shape[0]
        spectra = np.fft.rfft(frames.astype(np.float64) * window[None, :, None], axis=1)
        power = (np.abs(spectra) ** 2).mean(
            axis=2
        )  # a média dos canais, em potência: sem cancelamento de fase
        np.add.at(total, column[offset : offset + count], rows.apply(power))
        np.add.at(counts, column[offset : offset + count], 1)
    return total / np.maximum(counts, 1)[:, None]


def gray_image(power: np.ndarray, params: SpectrogramParams) -> np.ndarray:
    """A imagem 8 bits `(linhas, colunas)` com a menor frequência EMBAIXO (como se lê um espectrograma), a partir da
    potência por coluna e linha. O nível é a amplitude em dBFS (o tom de amplitude A que cai no centro de uma divisão vale
    20·log10(A)); `gain_db` o sobe e `range_db` é quanto abaixo do topo ainda aparece."""
    window = window_coefficients(params.window, params.window_size)
    amplitude = np.sqrt(np.maximum(power, _POWER_FLOOR)) * 2.0 / coherent_gain(window)
    level = 20.0 * np.log10(np.maximum(amplitude, 1e-12)) + params.gain_db
    gray = np.clip((level + params.range_db) / params.range_db, 0.0, 1.0) * 255.0
    return np.rint(gray).astype(np.uint8).T[::-1]


def spectrogram_gray(
    source: FrameSource,
    sample_rate: int,
    first_sample: float,
    column_samples: float,
    columns: int,
    params: SpectrogramParams,
) -> np.ndarray:
    """Tudo junto: a imagem em tons de cinza do trecho que começa em `first_sample`, com `columns` colunas de
    `column_samples` amostras cada."""
    checked = params.checked(sample_rate)
    return gray_image(
        column_power(source, sample_rate, first_sample, column_samples, columns, checked), checked
    )
