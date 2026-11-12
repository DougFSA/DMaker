"""O motor de persona: o contrato, o registro por tipo e a chave de cache do clipe.

Cada tipo de persona (2d, 3d, realista) tem um motor que sabe desenhar o quadro dela. O pipeline nunca escolhe o
motor com `if/elif` por tipo: pede ao registro o do tipo da persona. Um motor novo entra definindo uma classe com
este contrato e chamando `register_engine` no fim do módulo dele; o `persona/__init__.py` importa o módulo.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..domain.persona import Persona, PersonaMark
from ..media.ffmpeg import FFmpegRunner
from .visemes import VisemeSpan


class PersonaEngineError(ValueError):
    """Não há motor para o tipo da persona, ou a aparência não serve ao motor (a mensagem diz o que corrigir)."""


@dataclass(frozen=True)
class PersonaRender:
    """O pedido de um clipe: a persona, a boca, as marcas e o formato. `size` é o tamanho de saída em pixels e
    `duration` o tempo do clipe (a fala mais o respiro)."""

    persona: Persona
    visemes: tuple[VisemeSpan, ...]
    expression: str  # a expressão inicial
    marks: tuple[PersonaMark, ...]
    duration: float
    fps: float
    size: tuple[int, int]
    framing: str = (
        "full"  # "full": tela cheia (meio corpo); "corner": sobreposição no canto (cabeça e ombros)
    )

    @property
    def frame_count(self) -> int:
        return max(round(self.duration * self.fps), 1)


class PersonaEngine(Protocol):
    kind: str  # o tipo de persona que desenha ("2d")
    version: str  # muda quando o desenho muda: invalida os clipes em cache
    produces_alpha: (
        bool  # False: o clipe sai opaco (com o fundo dele), e o pipeline não compõe fundo por cima
    )
    expressions: tuple[str, ...]  # o que `PersonaMark.expression` aceita neste tipo
    gestures: tuple[str, ...]  # o que `PersonaMark.gesture` aceita neste tipo

    def normalize_appearance(self, appearance: Mapping[str, Any]) -> dict[str, Any]:
        """A aparência com os padrões preenchidos; levanta `PersonaEngineError` para o que não vale."""
        ...

    def cache_parts(self, request: PersonaRender) -> tuple[Any, ...]:
        """O que mais, além do pedido, decide o desenho (o conteúdo da página, o modelo 3D...)."""
        ...

    def unavailable_reason(self) -> str | None:
        """Por que o motor não consegue desenhar agora (como instalar o que falta), ou None."""
        ...

    def render(
        self, request: PersonaRender, out: Path, runner: FFmpegRunner, on_warning: Callable[[str], None]
    ) -> None:
        """Escreve o clipe em `out` (vídeo com alfa, ou opaco se `produces_alpha` for falso)."""
        ...

    def still(self, request: PersonaRender, at: float, on_warning: Callable[[str], None]) -> bytes:
        """O quadro do instante `at` (segundos do clipe) em PNG, indo direto a ele: serve ao quadro de um instante
        do editor, que não pode desenhar o clipe inteiro para mostrar um quadro."""
        ...


_ENGINES: dict[str, PersonaEngine] = {}


def register_engine(engine: PersonaEngine) -> PersonaEngine:
    """Registra o motor do tipo `engine.kind` (um por tipo; registrar de novo troca, para os testes)."""
    _ENGINES[engine.kind] = engine
    return engine


def engine_for(kind: str) -> PersonaEngine:
    try:
        return _ENGINES[kind]
    except KeyError:
        known = ", ".join(sorted(_ENGINES)) or "nenhum"
        raise PersonaEngineError(
            f"O tipo de persona {kind!r} ainda não tem motor neste computador (tipos disponíveis: {known})."
        ) from None


def engine_kinds() -> list[str]:
    return sorted(_ENGINES)


def clip_cache_key(engine: PersonaEngine, request: PersonaRender) -> str:
    """A chave do clipe em cache: o mesmo conteúdo dá sempre o mesmo arquivo, como no mezanino."""
    parts = [
        engine.kind,
        engine.version,
        request.persona.fingerprint(),
        [list(span) for span in request.visemes],
        request.expression,
        [mark.model_dump(mode="json", exclude_none=True) for mark in request.marks],
        round(request.duration, 6),
        request.fps,
        list(request.size),
        request.framing,
        list(engine.cache_parts(request)),
    ]
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def capabilities(persona: Persona) -> tuple[list[str], list[str]]:
    """As expressões e os gestos que a persona aceita: os do tipo, limitados pelas listas dela quando ela as traz."""
    engine = engine_for(persona.kind)
    expressions = [e for e in engine.expressions if not persona.expressions or e in persona.expressions]
    gestures = [g for g in engine.gestures if not persona.gestures or g in persona.gestures]
    return expressions, gestures
