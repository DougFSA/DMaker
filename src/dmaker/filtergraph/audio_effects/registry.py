"""Registro dos construtores de efeito de áudio: cada tipo de efeito entra aqui por extensão, sem `if/elif` na
montagem. Mesmo molde do registro de transições (`filtergraph.transitions.registry`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ...domain.audio_effects import EffectBase
from ...domain.audio_effects.base import EFFECT_SAMPLE_RATE
from .measure import Measure

# O áudio de um item é levado a esta taxa e a estéreo antes dos efeitos, que é o formato do resto da mixagem;
# as contas em amostras (emenda do intervalo, repetição) usam esta taxa.
SAMPLE_RATE = EFFECT_SAMPLE_RATE


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
            if name in _BUILDERS or name in _SAMPLE_BUILDERS:
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


# ---------- o estágio de amostras ----------
#
# Nem todo efeito cabe num filtro do ffmpeg (a subtração espectral do ruído, a interpolação do Reparar). Esses são uma
# função pura sobre as amostras em numpy, registrada aqui do mesmo jeito que um construtor de filtro: a classe do efeito
# marca `sample_stage = True` e o construtor entra com `@register_sample_builder("<type>")`. O processador parte a
# cadeia em trechos de ffmpeg e estágios de amostras (decodifica, aplica, grava e segue), e o resultado fica no mesmo
# cache por hash.


@dataclass(frozen=True)
class SampleRequest:
    """O que um construtor de amostras recebe: o efeito, o sinal que entra nele e a medida desse sinal.

    `samples` tem a forma `(amostras, canais)`, em ponto flutuante, a `sample_rate`; quando o efeito tem intervalo
    (e não é dono dele), já vem recortado e com o tempo zerado, como no construtor de filtro. `measure` traz o que a
    passada de medida leu (o espectro do perfil de ruído, em `measure.noise`)."""

    effect: EffectBase
    samples: np.ndarray
    sample_rate: int = SAMPLE_RATE
    measure: Measure | None = None


class SampleBuilder(Protocol):
    """Devolve o sinal depois do efeito, com a mesma forma do que entrou (ou outro comprimento, se o efeito muda a
    duração). Função pura: não toca disco nem executa nada."""

    def __call__(self, request: SampleRequest) -> np.ndarray: ...


_SAMPLE_BUILDERS: dict[str, SampleBuilder] = {}


def register_sample_builder(*names: str) -> Callable[[SampleBuilder], SampleBuilder]:
    """Registra o construtor de amostras sob o `type` de um ou mais efeitos."""

    def decorator(builder: SampleBuilder) -> SampleBuilder:
        for name in names:
            if name in _BUILDERS or name in _SAMPLE_BUILDERS:
                raise ValueError(f"Construtor de efeito já registrado: {name}")
            _SAMPLE_BUILDERS[name] = builder
        return builder

    return decorator


def sample_builder_types() -> set[str]:
    return set(_SAMPLE_BUILDERS)


def is_sample_effect(effect: EffectBase) -> bool:
    """Se o efeito roda sobre as amostras (e não como filtro do ffmpeg)."""
    return effect.type in _SAMPLE_BUILDERS


def build_samples(request: SampleRequest) -> np.ndarray:
    name = request.effect.type
    try:
        builder = _SAMPLE_BUILDERS[name]
    except KeyError:
        raise ValueError(f"Efeito de áudio sem construtor de amostras registrado: {name}") from None
    return builder(request)


# ---------- a resposta de frequência ----------
#
# Um efeito de equalização tem, além do construtor do filtro, uma conta pura da resposta dele: o ganho em dB em cada
# frequência. A interface desenha o gráfico com ela, sem rodar o ffmpeg. A conta parte dos MESMOS dados que o construtor
# usa (as seções do filtro, a curva amostrada), então o gráfico e o som do render só podem diferir pela precisão do filtro.


class ResponseFunction(Protocol):
    """O ganho em dB do efeito nas frequências `hz`, na taxa `rate`. Função pura: não executa nem toca disco."""

    def __call__(self, effect: EffectBase, hz: np.ndarray, rate: int) -> np.ndarray: ...


_RESPONSES: dict[str, ResponseFunction] = {}


def register_response(*names: str) -> Callable[[ResponseFunction], ResponseFunction]:
    """Registra a conta da resposta de frequência sob o `type` de um ou mais efeitos."""

    def decorator(function: ResponseFunction) -> ResponseFunction:
        for name in names:
            if name in _RESPONSES:
                raise ValueError(f"Resposta de frequência já registrada: {name}")
            _RESPONSES[name] = function
        return function

    return decorator


def response_types() -> set[str]:
    return set(_RESPONSES)


def frequency_response(effect: EffectBase, hz: np.ndarray, rate: int = SAMPLE_RATE) -> np.ndarray:
    """O ganho em dB do efeito em cada frequência de `hz`. Um efeito sem conta registrada é erro com o motivo."""
    try:
        function = _RESPONSES[effect.type]
    except KeyError:
        known = ", ".join(sorted(_RESPONSES))
        raise ValueError(f"o efeito {effect.type!r} não tem resposta de frequência. Têm: {known}") from None
    return function(effect, np.asarray(hz, dtype=float), rate)
