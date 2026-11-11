"""Confere as personas que um projeto usa: existência, tipo com motor, expressões, gestos e marcas (função pura
sobre um cadastro injetado)."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.persona import Persona
from ..domain.spec import PersonaOverlay, PersonaSegment, Project
from .engine import PersonaEngineError, capabilities
from .marks import mark_problems

PersonaLookup = Callable[[str], Persona]


def persona_problems(project: Project, lookup: PersonaLookup) -> list[str]:
    """Mensagens (PT-BR) de tudo o que impede a persona de entrar no projeto. A duração da fala só é conhecida ao
    sintetizar, então aqui a marca só é conferida contra uma duração que a spec já fixa."""
    problems: list[str] = []
    for index, segment in enumerate(project.timeline):
        if isinstance(segment, PersonaSegment):
            problems += _check(
                lookup,
                f"timeline[{index}]",
                segment.persona,
                segment.expression,
                segment.marks,
                segment.duration,
            )
    for index, overlay in enumerate(project.overlays):
        if isinstance(overlay, PersonaOverlay):
            fixed = overlay.end - overlay.start if overlay.end is not None else None
            problems += _check(
                lookup, f"overlays[{index}]", overlay.persona, overlay.expression, overlay.marks, fixed
            )
    return problems


def _check(lookup: PersonaLookup, where: str, persona_id: str, expression, marks, duration) -> list[str]:
    try:
        persona = lookup(persona_id)
    except ValueError as exc:  # PersonaNotFoundError
        return [f"{where}.persona: {exc}"]
    try:
        expressions, gestures = capabilities(persona)
    except PersonaEngineError as exc:
        return [f"{where}.persona: {exc}"]
    return mark_problems(marks, expression, expressions, gestures, duration, where, persona.kind)
