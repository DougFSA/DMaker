"""Montagem em blocos: entradas demais para uma linha de comando viram intermediários, antes do comando final.

O Windows recusa linha de comando com mais de 32.767 caracteres (WinError 206) e cada `-i` custa um caminho
inteiro. Um capítulo narrado ou uma dublagem longa passa de centenas de arquivos, então a montagem vira uma árvore:
cada bloco de até `MAX_INPUTS` entradas é montado num WAV intermediário, e os WAVs dos blocos fazem o papel das
entradas no nível seguinte, até sobrar um número que cabe no comando final.

Tudo aqui é puro: o plano é dado (comandos e grafos); quem grava os grafos em arquivo e executa é o
`pipeline/block_runner.py`. Quando as entradas já cabem num comando só, o plano não tem bloco nenhum e o comando
final é o mesmo de sempre.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from ..media.ffmpeg import FFmpegCommand

# Entradas por comando. Cada `-i` custa o caminho (até os 260 caracteres do MAX_PATH do Windows, mais aspas e
# espaço): 64 entradas ficam em cerca de 17 mil caracteres, e o grafo inline do comando final (uns 110 caracteres por
# ramo) leva a uns 25 mil no pior caso, folgado contra o limite de 32.767.
MAX_INPUTS = 64

# WAV de 32 bits em ponto flutuante: o intermediário não pode perder nada entre um nível e o seguinte, e o float
# guarda também o que passa de 0 dBFS (a soma de falas sobrepostas), que só o limitador do comando final trata.
INTERMEDIATE_CODEC_ARGS = ["-c:a", "pcm_f32le"]

Item = TypeVar("Item")


@dataclass(frozen=True)
class GraphStep:
    """Um comando ffmpeg do plano. Com `graph_file`, o grafo vai nesse arquivo (`graph` é o texto a gravar)."""

    command: FFmpegCommand
    graph: str | None = None
    graph_file: Path | None = None


@dataclass(frozen=True)
class BlockSlot:
    """Onde um bloco grava a saída e o grafo, e o nome dele para o andamento."""

    out: Path
    graph_file: Path
    label: str


@dataclass(frozen=True)
class BlockReduction(Generic[Item]):
    """Os passos que reduzem as entradas e as entradas que sobram para o comando final."""

    steps: list[GraphStep]
    items: list[Item]


BlockBuilder = Callable[[Sequence[Item], BlockSlot], tuple[GraphStep, Item]]


def graph_file_args(graph_file: Path) -> list[str]:
    """`-/filter_complex <arquivo>`: o grafo sai da linha de comando (o ffmpeg 9 do `dmaker setup` lê dele)."""
    return ["-/filter_complex", str(graph_file)]


def split_evenly(count: int, limit: int = MAX_INPUTS) -> list[range]:
    """Posições de `count` itens em blocos de no máximo `limit`, de tamanhos quase iguais.

    Tamanhos parecidos evitam um último bloco de uma entrada só, que montaria sem juntar nada.
    """
    if limit < 2:
        raise ValueError("Um bloco precisa aceitar pelo menos duas entradas.")
    if count <= 0:
        return []
    blocks = -(-count // limit)
    size, extra = divmod(count, blocks)
    spans: list[range] = []
    start = 0
    for index in range(blocks):
        end = start + size + (1 if index < extra else 0)
        spans.append(range(start, end))
        start = end
    return spans


def reduce_in_blocks(
    items: Sequence[Item],
    work_dir: Path,
    build_block: BlockBuilder[Item],
    limit: int = MAX_INPUTS,
) -> BlockReduction[Item]:
    """Monta as `items` em blocos até sobrarem no máximo `limit` para o comando final.

    `build_block` recebe um bloco e o `BlockSlot` e devolve o passo que o monta e a entrada que o representa
    no nível seguinte. Com `limit` ou menos itens não há nada a fazer: os passos vêm vazios e os itens, intactos.
    """
    steps: list[GraphStep] = []
    current = list(items)
    level = 0
    while len(current) > limit:
        level += 1
        spans = split_evenly(len(current), limit)
        reduced: list[Item] = []
        for number, span in enumerate(spans, 1):
            name = f"bloco-{level}-{number:04d}"
            slot = BlockSlot(
                out=work_dir / f"{name}.wav",
                graph_file=work_dir / f"{name}.graph.txt",
                label=f"bloco {number} de {len(spans)}"
                if level == 1
                else f"junção {level}: {number} de {len(spans)}",
            )
            step, produced = build_block(current[span.start : span.stop], slot)
            steps.append(step)
            reduced.append(produced)
        current = reduced
    return BlockReduction(steps, current)
