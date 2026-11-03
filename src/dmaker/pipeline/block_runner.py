"""Executa o plano de uma montagem em blocos: grava o grafo de cada passo, roda o comando e limpa os intermediários.

O plano (`filtergraph/blocks.py`) é dado puro; aqui fica só o que toca o disco e o runner.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ..filtergraph.blocks import GraphStep
from ..media.ffmpeg import FFmpegRunner


@contextmanager
def block_workspace(parent: Path) -> Iterator[Path]:
    """Pasta temporária dos intermediários de uma montagem, dentro de `parent` (o disco do cache, que já guarda
    os WAVs pesados) em vez da pasta temporária do sistema, que costuma ser o disco menor.

    Some ao fim, com erro ou sem ele; uma pasta por montagem, para duas montagens ao mesmo tempo não se pisarem.
    """
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="montagem-", dir=parent, ignore_cleanup_errors=True) as folder:
        yield Path(folder)


def run_steps(runner: FFmpegRunner, steps: Iterable[GraphStep]) -> None:
    """Roda os passos na ordem; os que têm grafo em arquivo gravam o arquivo antes do comando."""
    for step in steps:
        if step.graph_file is not None and step.graph is not None:
            step.graph_file.parent.mkdir(parents=True, exist_ok=True)
            step.graph_file.write_text(step.graph, encoding="utf-8")
        runner.run(step.command)
