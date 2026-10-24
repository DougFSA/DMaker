"""Conversão de voz: o contrato (`VoiceConverter`) e as contas puras de blocos e emenda.

Trocar a voz de uma gravação longa de uma vez só estoura a memória do modelo; por isso o serviço parte o
áudio em blocos que se sobrepõem um pouco e emenda os resultados com um fade de amplitude complementar. As
contas desse plano ficam aqui, sem tocar disco nem modelo, para serem testadas direto.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..media.separation import ProgressCallback
from .levels import quietest_time

BLOCK_SECONDS = 25.0  # tamanho de cada bloco: ~30 s cabem em poucos GB de RAM no modelo, com folga
OVERLAP_SECONDS = (
    1.0  # sobreposição entre blocos: o modelo precisa de contexto nas pontas (~0,7 s de campo receptivo)
)
CUT_SEARCH_SECONDS = 4.0  # quanto o corte pode andar atrás do vale mais quieto (entre duas palavras)


class VoiceConverter(Protocol):
    engine_id: str  # entra na chave do cache: trocar de motor ou de modelo não reaproveita conversões

    def convert(
        self,
        source_vocals: Path,
        target_reference: Path,
        out: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Grava em `out` a fala de `source_vocals` com o timbre de `target_reference`, na mesma duração.

        O ritmo, as pausas e a entonação são os da fonte; só a voz muda. A taxa do WAV de saída é a do motor.
        """
        ...


@dataclass(frozen=True)
class Block:
    """Um bloco do áudio: o que o modelo recebe e a parte dele que vale na emenda."""

    start: float  # início do que o modelo recebe, em segundos
    end: float
    keep_start: float  # o resultado vale a partir daqui; antes, o bloco anterior já cobre
    keep_end: float  # e até aqui; depois, o bloco seguinte assume


def plan_cuts(
    samples: np.ndarray,
    sample_rate: int,
    block_seconds: float = BLOCK_SECONDS,
    search_seconds: float = CUT_SEARCH_SECONDS,
) -> list[float]:
    """Instantes de corte (s) para blocos de ~`block_seconds`, cada um colado no vale mais quieto por perto.

    Cortar entre duas palavras faz o fade da emenda cair onde quase não há som, e a junta fica inaudível.
    """
    total = len(samples) / sample_rate
    cuts: list[float] = []
    target = block_seconds
    while target < total - block_seconds / 2:  # sobra menor que meio bloco fica no último bloco
        cut = quietest_time(samples, sample_rate, target, search_seconds)
        cuts.append(cut)
        target = cut + block_seconds
    return cuts


def plan_blocks(
    total_seconds: float, cuts: list[float], overlap_seconds: float = OVERLAP_SECONDS
) -> list[Block]:
    """Blocos que cobrem `0..total_seconds`: cada um entra `overlap_seconds` em cada vizinho para ter contexto."""
    if total_seconds <= 0:
        raise ValueError("A duração a converter precisa ser maior que zero.")
    edges = [0.0, *sorted(cuts), total_seconds]
    blocks = []
    for index in range(len(edges) - 1):
        keep_start, keep_end = edges[index], edges[index + 1]
        blocks.append(
            Block(
                start=max(0.0, keep_start - overlap_seconds),
                end=min(total_seconds, keep_end + overlap_seconds),
                keep_start=keep_start,
                keep_end=keep_end,
            )
        )
    return blocks


def complementary_fade(length: int) -> tuple[np.ndarray, np.ndarray]:
    """Curvas (sobe, desce) em cosseno elevado que somam exatamente 1.

    As duas pontas da emenda são a mesma fala convertida duas vezes, quase idênticas; com fades de amplitude
    complementar a soma mantém o volume, e um fade de potência constante (que soma 1,41 no meio) faria um
    pico de 3 dB em cada emenda.
    """
    position = (np.arange(length, dtype=np.float32) + 0.5) / max(length, 1)
    rise = np.sin(position * (np.pi / 2)) ** 2
    return rise, 1.0 - rise


def stitch_blocks(
    blocks: list[Block], converted: list[np.ndarray], sample_rate: int, total_samples: int
) -> np.ndarray:
    """Junta o resultado de cada bloco (amostras na taxa do motor) numa faixa de `total_samples`.

    Em cada emenda, o fade cobre o trecho de sobreposição centrado no corte: o bloco que sai desce e o que
    entra sobe. O resultado tem exatamente a duração da fonte, que é o que mantém o vídeo em sincronia.
    """
    if len(blocks) != len(converted):
        raise ValueError("Precisa de um resultado para cada bloco.")
    out = np.zeros(total_samples, dtype=np.float32)
    for index, (block, audio) in enumerate(zip(blocks, converted, strict=True)):
        first = round(block.start * sample_rate)
        piece = np.zeros(round((block.end - block.start) * sample_rate), dtype=np.float32)
        piece[: min(len(piece), len(audio))] = audio[: len(piece)]  # o modelo devolve até 1 quadro a menos
        weights = np.ones(len(piece), dtype=np.float32)
        if index > 0:  # sobe na emenda de entrada
            length = round((block.keep_start - block.start) * 2 * sample_rate)
            length = min(length, len(piece))
            rise, _ = complementary_fade(length)
            weights[:length] = rise
        if index < len(blocks) - 1:  # desce na emenda de saída
            length = round((block.end - block.keep_end) * 2 * sample_rate)
            length = min(length, len(piece))
            _, fall = complementary_fade(length)
            weights[len(piece) - length :] = np.minimum(weights[len(piece) - length :], fall)
        last = min(total_samples, first + len(piece))
        out[first:last] += (piece * weights)[: last - first]
    return out
