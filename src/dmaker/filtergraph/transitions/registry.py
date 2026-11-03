"""Registro dos construtores de transição: cada tipo entra aqui por extensão, sem `if/elif` na montagem."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TransitionRequest:
    """Tudo o que um construtor precisa para ligar dois fluxos de vídeo.

    `a` (o que já existe) e `b` (o próximo trecho) são rótulos de filtro com colchetes; `out` é o rótulo em que o
    resultado deve sair. `tag` é único por transição e serve de prefixo para rótulos intermediários e nomes de
    instância de filtro, para duas transições no mesmo grafo não se cruzarem. A transição acontece nos últimos
    `duration` segundos de `a` (a partir de `offset`) e nos primeiros de `b`.
    """

    a: str
    b: str
    out: str
    tag: str
    duration: float
    offset: float
    fps: float
    curve: str = "linear"
    size: tuple[int, int] | None = None

    @property
    def frames(self) -> int:
        return frame_count(self.duration, self.fps)

    def require_size(self) -> tuple[int, int]:
        if self.size is None:
            raise ValueError("Esta transição precisa do tamanho do quadro (largura, altura)")
        return self.size

    def first_window_frame(self) -> int:
        return first_frame_at(self.offset, self.fps)


def frame_count(duration: float, fps: float) -> int:
    """Quadros da janela de transição (pelo menos 2, para haver um começo e um meio)."""
    return max(2, round(duration * fps))


def first_frame_at(offset: float, fps: float) -> int:
    """Índice do primeiro quadro cujo timestamp alcança `offset`, arredondado como o `xfade` o recebe (em
    milissegundos) e contando em microssegundos como o FFmpeg: é onde a janela de transição começa."""
    offset_us = round(round(offset, 3) * 1_000_000)
    k = max(0, math.ceil(offset_us * fps / 1_000_000 - 1e-6))
    while round(k * 1_000_000 / fps) < offset_us:
        k += 1
    while k > 0 and round((k - 1) * 1_000_000 / fps) >= offset_us:
        k -= 1
    return k


class TransitionBuilder(Protocol):
    """Gera as linhas do grafo que ligam `a` e `b` em `out`. Função pura: não executa nem toca disco."""

    def __call__(self, request: TransitionRequest) -> list[str]: ...


_BUILDERS: dict[str, TransitionBuilder] = {}


def register(*names: str) -> Callable[[TransitionBuilder], TransitionBuilder]:
    """Registra o construtor sob um ou mais nomes de transição."""

    def decorator(builder: TransitionBuilder) -> TransitionBuilder:
        for name in names:
            if name in _BUILDERS:
                raise ValueError(f"Transição já registrada: {name}")
            _BUILDERS[name] = builder
        return builder

    return decorator


def registered_names() -> set[str]:
    return set(_BUILDERS)


def build_transition(name: str, request: TransitionRequest) -> list[str]:
    try:
        builder = _BUILDERS[name]
    except KeyError:
        raise ValueError(f"Transição sem construtor registrado: {name}") from None
    return builder(request)
