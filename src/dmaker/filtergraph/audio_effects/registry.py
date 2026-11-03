"""Registro dos construtores de efeito de áudio: cada tipo de efeito entra aqui por extensão, sem `if/elif` na
montagem. Mesmo molde do registro de transições (`filtergraph.transitions.registry`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ...domain.audio_effects import EffectBase
from .measure import Measure

# O áudio de um item é levado a esta taxa e a estéreo antes dos efeitos, que é o formato do resto da mixagem;
# as contas em amostras (emenda do intervalo, repetição) usam esta taxa.
SAMPLE_RATE = 48000


@dataclass(frozen=True)
class EffectRequest:
    """Tudo o que um construtor precisa para ligar a entrada de um efeito à saída dele.

    `source` e `out` são rótulos de filtro com colchetes; `tag` é único por efeito no grafo e serve de prefixo
    dos rótulos intermediários, para dois efeitos no mesmo grafo não se cruzarem. `duration` é a duração do
    sinal que entra (já no intervalo, quando o efeito tem um). `measure` traz o que a passada de análise leu
    desse sinal e só vem preenchida para os efeitos que declaram `needs_measure()`. `side` é o rótulo de uma
    segunda entrada de áudio, para os efeitos que usam outra trilha (nenhum efeito atual usa).
    """

    effect: EffectBase
    source: str
    out: str
    tag: str
    duration: float
    measure: Measure | None = None
    side: str | None = None
    sample_rate: int = SAMPLE_RATE

    @property
    def samples(self) -> int:
        return round(self.duration * self.sample_rate)

    def label(self, name: str) -> str:
        """Rótulo intermediário próprio deste efeito: `[<tag>_<name>]`."""
        return f"[{self.tag}_{name}]"

    def chain(self, *filters: str) -> list[str]:
        """O caso comum: uma linha só, com os filtros em sequência da entrada à saída."""
        return [f"{self.source}{','.join(filters)}{self.out}"]


class EffectBuilder(Protocol):
    """Gera as linhas do grafo que ligam `source` a `out`. Função pura: não executa nem toca disco."""

    def __call__(self, request: EffectRequest) -> list[str]: ...


_BUILDERS: dict[str, EffectBuilder] = {}


def register_builder(*names: str) -> Callable[[EffectBuilder], EffectBuilder]:
    """Registra o construtor sob o `type` de um ou mais efeitos."""

    def decorator(builder: EffectBuilder) -> EffectBuilder:
        for name in names:
            if name in _BUILDERS:
                raise ValueError(f"Construtor de efeito já registrado: {name}")
            _BUILDERS[name] = builder
        return builder

    return decorator


def builder_types() -> set[str]:
    return set(_BUILDERS)


def build_effect(request: EffectRequest) -> list[str]:
    name = request.effect.type
    try:
        builder = _BUILDERS[name]
    except KeyError:
        raise ValueError(f"Efeito de áudio sem construtor registrado: {name}") from None
    return builder(request)
