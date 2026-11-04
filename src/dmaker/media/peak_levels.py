"""Picos por bloco (mínimo e máximo) em várias resoluções, para desenhar a onda de um áudio longo sem carregá-lo.

Tudo aqui é puro: recebe amostras, devolve números. Quem lê o áudio em pedaços e guarda o resultado em disco é
`media/waveform.py`. A pirâmide tem um nível de base (um mínimo e um máximo por `BASE_BLOCK` amostras) e níveis
cada vez mais grossos (cada bloco resume `LEVEL_FACTOR` do nível de baixo): o desenho de uma tela pega o nível cujo
bloco cabe numa coluna de pixels, então custa o mesmo sem importar se a janela tem um segundo ou uma hora.

Os valores ficam em inteiros de 8 bits (-127 a 127): para pintar uma onda em poucas centenas de pixels de altura a
precisão sobra, e uma hora de estéreo cabe em uns 13 MB em vez de uns 100 MB em ponto flutuante.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Amostras por bloco no nível de base. Abaixo disto a janela é lida em amostras de verdade (é barato: são poucos
# segundos), e acima o nível de base já resume o suficiente para uma hora caber em milhões de blocos, não bilhões.
BASE_BLOCK = 64
# Cada nível resume quatro do anterior: a razão entre dois zooms vizinhos nunca passa de 4x, e o desenho pega o
# bloco mais perto da coluna sem refazer a conta.
LEVEL_FACTOR = 4
# O valor 1,0 vira 127. Amostras de ponto flutuante acima disto (um ganho que passa de 0 dBFS) são cortadas no desenho.
QUANT = 127


@dataclass(frozen=True)
class PeakLevel:
    """Um nível da pirâmide: `block` amostras por bloco, com o mínimo e o máximo de cada canal em inteiros de 8 bits."""

    block: int
    mins: np.ndarray  # int8, forma (blocos, canais)
    maxs: np.ndarray  # int8, forma (blocos, canais)

    @property
    def blocks(self) -> int:
        return int(self.mins.shape[0])

    @property
    def channels(self) -> int:
        return int(self.mins.shape[1])


def quantize(values: np.ndarray) -> np.ndarray:
    """Amostras de -1 a 1 como inteiros de 8 bits; o que passa da faixa é cortado."""
    return np.round(np.clip(values, -1.0, 1.0) * QUANT).astype(np.int8)


def dequantize(values: np.ndarray) -> np.ndarray:
    """O caminho de volta de `quantize`: inteiros de 8 bits como ponto flutuante de -1 a 1."""
    return values.astype(np.float32) / QUANT


def block_extremes(samples: np.ndarray, block: int) -> tuple[np.ndarray, np.ndarray]:
    """O mínimo e o máximo de cada bloco de `block` quadros, por canal (em ponto flutuante). O último bloco conta
    mesmo incompleto, senão a ponta do áudio sumiria da onda. Devolve duas matrizes (blocos, canais)."""
    frames, channels = samples.shape
    if frames == 0:
        empty = np.empty((0, channels), dtype=np.float32)
        return empty, empty
    full = frames // block
    mins: list[np.ndarray] = []
    maxs: list[np.ndarray] = []
    if full:
        # canais primeiro e quadros contíguos: o numpy reduz o eixo de dentro (o bloco) em laço rápido, umas oito vezes
        # mais depressa que reduzir o eixo do meio de um (blocos, bloco, canais)
        by_channel = np.ascontiguousarray(samples[: full * block].T).reshape(channels, full, block)
        mins.append(by_channel.min(axis=2).T)
        maxs.append(by_channel.max(axis=2).T)
    if frames % block:
        tail = samples[full * block :]
        mins.append(tail.min(axis=0, keepdims=True))
        maxs.append(tail.max(axis=0, keepdims=True))
    return np.concatenate(mins), np.concatenate(maxs)


class BlockAccumulator:
    """Recebe o áudio em pedaços (de qualquer tamanho) e acumula o nível de base. O que sobra de um pedaço, menos que
    um bloco, espera o seguinte, para a fronteira entre pedaços nunca cortar um bloco ao meio."""

    def __init__(self, channels: int, block: int = BASE_BLOCK) -> None:
        self.channels = channels
        self.block = block
        self._mins: list[np.ndarray] = []
        self._maxs: list[np.ndarray] = []
        self._rest = np.empty((0, channels), dtype=np.float32)
        self.frames = 0

    def push(self, samples: np.ndarray) -> None:
        """Acrescenta um pedaço de forma (quadros, canais)."""
        if samples.shape[0] == 0:
            return
        self.frames += samples.shape[0]
        data = np.concatenate([self._rest, samples]) if self._rest.shape[0] else samples
        whole = (data.shape[0] // self.block) * self.block
        if whole:
            low, high = block_extremes(data[:whole], self.block)
            self._mins.append(quantize(low))
            self._maxs.append(quantize(high))
        self._rest = np.array(data[whole:], dtype=np.float32)

    def append_blocks(self, mins: np.ndarray, maxs: np.ndarray, frames: int) -> None:
        """Acrescenta blocos que alguém já reduziu (vários pedaços podem ser reduzidos ao mesmo tempo): `frames` é
        quantos quadros eles resumem, e o pedaço anterior precisa ter terminado numa fronteira de bloco."""
        if mins.shape[0] == 0:
            return
        self._mins.append(mins)
        self._maxs.append(maxs)
        self.frames += frames

    def base(self, final: bool = False) -> PeakLevel:
        """O nível de base de tudo que chegou. Com `final`, o resto menos que um bloco também entra (no fim do áudio);
        sem ele, só os blocos completos (durante a construção, a pirâmide parcial)."""
        mins, maxs = list(self._mins), list(self._maxs)
        if final and self._rest.shape[0]:
            low, high = block_extremes(self._rest, self.block)
            mins.append(quantize(low))
            maxs.append(quantize(high))
        if not mins:
            empty = np.empty((0, self.channels), dtype=np.int8)
            return PeakLevel(self.block, empty, empty)
        return PeakLevel(self.block, np.concatenate(mins), np.concatenate(maxs))


def coarser(level: PeakLevel, factor: int = LEVEL_FACTOR) -> PeakLevel:
    """O nível que resume `factor` blocos do dado em um. O último grupo pode ser menor."""
    count = level.blocks
    if count == 0:
        return PeakLevel(level.block * factor, level.mins, level.maxs)
    full = count // factor
    mins: list[np.ndarray] = []
    maxs: list[np.ndarray] = []
    if full:
        mins.append(level.mins[: full * factor].reshape(full, factor, -1).min(axis=1))
        maxs.append(level.maxs[: full * factor].reshape(full, factor, -1).max(axis=1))
    if count % factor:
        mins.append(level.mins[full * factor :].min(axis=0, keepdims=True))
        maxs.append(level.maxs[full * factor :].max(axis=0, keepdims=True))
    return PeakLevel(level.block * factor, np.concatenate(mins), np.concatenate(maxs))


def build_levels(base: PeakLevel, factor: int = LEVEL_FACTOR, stop_blocks: int = 256) -> list[PeakLevel]:
    """A pirâmide inteira a partir do nível de base: do mais fino ao mais grosso, parando quando o nível tem poucos
    blocos (`stop_blocks`): um nível mais grosso que isso só serviria a uma tela de poucos pixels."""
    levels = [base]
    while levels[-1].blocks > stop_blocks:
        levels.append(coarser(levels[-1], factor))
    return levels


def pick_level(levels: list[PeakLevel], samples_per_column: float) -> PeakLevel | None:
    """O nível mais grosso cujo bloco ainda cabe numa coluna de pixels (`samples_per_column` amostras), ou None quando
    nem o de base cabe: então a janela é pequena, e o certo é ler as amostras de verdade."""
    chosen: PeakLevel | None = None
    for level in levels:
        if level.block <= samples_per_column:
            chosen = level
    return chosen


def _edges(first: int, last: int, columns: int) -> np.ndarray:
    """As bordas de `columns` colunas entre os índices `first` e `last`, crescentes (cada coluna tem ao menos um)."""
    edges = np.floor(np.linspace(first, last, columns + 1)).astype(np.int64)
    edges[0], edges[-1] = first, last
    # sem isto duas bordas iguais deixariam uma coluna vazia, e o `reduceat` leria o elemento da borda em vez de um grupo
    for index in range(1, columns + 1):
        if edges[index] <= edges[index - 1]:
            edges[index] = edges[index - 1] + 1
    return edges


def level_columns(
    level: PeakLevel, first_frame: int, last_frame: int, columns: int
) -> tuple[np.ndarray, np.ndarray]:
    """O mínimo e o máximo de cada uma de `columns` colunas entre os quadros `first_frame` e `last_frame` (de -1 a 1,
    matrizes (colunas, canais)). As colunas que caem fora do que o nível tem (antes do começo, depois do fim, ou além
    do que a construção parcial já leu) ficam em zero, e as outras não se deslocam por isso."""
    channels = level.channels
    mins = np.zeros((columns, channels), dtype=np.float32)
    maxs = np.zeros((columns, channels), dtype=np.float32)
    if columns <= 0 or level.blocks == 0 or last_frame <= first_frame:
        return mins, maxs
    first_block = max(first_frame // level.block, 0)
    last_block = -(-last_frame // level.block)
    available = level.blocks
    span = last_block - first_block
    if span <= 0 or first_block >= available:
        return mins, maxs
    if span >= columns:
        edges = _edges(first_block, last_block, columns)
        valid = int(np.searchsorted(edges[:-1], available, side="left"))
        starts = edges[:valid] - first_block
        stop = min(last_block, available)
        mins[:valid] = dequantize(np.minimum.reduceat(level.mins[first_block:stop], starts, axis=0))
        maxs[:valid] = dequantize(np.maximum.reduceat(level.maxs[first_block:stop], starts, axis=0))
        return mins, maxs
    # menos blocos que colunas (o nível já é o mais grosso, ou o áudio é curto): cada coluna pega o bloco sob ela
    index = np.clip(((np.arange(columns) + 0.5) / columns * span).astype(np.int64), 0, span - 1) + first_block
    inside = index < available
    mins[inside] = dequantize(level.mins[index[inside]])
    maxs[inside] = dequantize(level.maxs[index[inside]])
    return mins, maxs


def sample_columns(samples: np.ndarray, columns: int) -> tuple[np.ndarray, np.ndarray]:
    """O mínimo e o máximo de cada coluna, lidos das amostras de verdade (matrizes (colunas, canais)). Com menos
    amostras que colunas, cada coluna repete a amostra mais perto: o desenho liga os pontos, não deixa buracos."""
    frames, channels = samples.shape
    if columns <= 0 or frames == 0:
        zero = np.zeros((max(columns, 0), channels), dtype=np.float32)
        return zero, zero.copy()
    if frames < columns:
        index = np.clip(((np.arange(columns) + 0.5) / columns * frames).astype(np.int64), 0, frames - 1)
        picked = np.clip(samples[index], -1.0, 1.0)
        return picked, picked.copy()
    edges = _edges(0, frames, columns)
    low = np.minimum.reduceat(samples, edges[:-1], axis=0)
    high = np.maximum.reduceat(samples, edges[:-1], axis=0)
    return np.clip(low, -1.0, 1.0), np.clip(high, -1.0, 1.0)
