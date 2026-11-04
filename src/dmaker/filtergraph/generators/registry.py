"""Registro dos construtores de gerador de som: cada tipo entra aqui por extensão, sem `if/elif` na produção do som.

Um construtor devolve uma de duas coisas: uma fonte do ffmpeg (`FilterSource`, para o que o ffmpeg já gera: seno, ruído) ou as
amostras em numpy (para o que ele não gera). Quem executa e grava o WAV é o pipeline (`pipeline/generated_sounds.py`): aqui
nada executa nem toca disco.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ...domain.generators import GENERATOR_SAMPLE_RATE, GeneratorBase


@dataclass(frozen=True)
class FilterSource:
    """Uma fonte do ffmpeg: o filtro (já com a duração e a taxa) que gera o sinal mono, sem entrada."""

    graph: str


@dataclass(frozen=True)
class GeneratorRequest:
    """O que um construtor precisa: o gerador com os parâmetros, a duração do item e a taxa. `resolve` leva um caminho da
    spec ao arquivo (o gerador de amostras lê um texto do projeto)."""

    generator: GeneratorBase
    duration: float
    sample_rate: int = GENERATOR_SAMPLE_RATE
    resolve: Callable[[str], Path] | None = None

    @property
    def frames(self) -> int:
        return round(self.duration * self.sample_rate)


class GeneratorBuilder(Protocol):
    """Produz o som de um gerador: uma `FilterSource` ou as amostras (mono `(quadros,)` ou `(quadros, canais)`)."""

    def __call__(self, request: GeneratorRequest) -> FilterSource | np.ndarray: ...


_BUILDERS: dict[str, GeneratorBuilder] = {}


def register_generator_builder(*names: str) -> Callable[[GeneratorBuilder], GeneratorBuilder]:
    """Registra o construtor sob o `type` de um ou mais geradores."""

    def decorator(builder: GeneratorBuilder) -> GeneratorBuilder:
        for name in names:
            if name in _BUILDERS:
                raise ValueError(f"Construtor de gerador já registrado: {name}")
            _BUILDERS[name] = builder
        return builder

    return decorator


def builder_types() -> set[str]:
    return set(_BUILDERS)


def build_generator(request: GeneratorRequest) -> FilterSource | np.ndarray:
    """O som do gerador do pedido (uma fonte do ffmpeg ou as amostras)."""
    name = request.generator.type
    builder = _BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"Gerador de som sem construtor: {name!r}. Há: {', '.join(sorted(_BUILDERS))}")
    return builder(request)
