"""As marcas de uma persona (expressão e gesto no tempo) em dados que o motor lê, e a conferência delas (funções puras)."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.persona import DEFAULT_EXPRESSION, PersonaMark


def expression_track(initial: str, marks: Sequence[PersonaMark]) -> list[tuple[float, str]]:
    """As trocas de expressão `(instante, nome)` em ordem, começando na expressão inicial em 0."""
    track = [(0.0, initial or DEFAULT_EXPRESSION)]
    track += sorted((mark.at, mark.expression) for mark in marks if mark.expression is not None)
    return track


def gesture_track(marks: Sequence[PersonaMark]) -> list[tuple[float, str]]:
    """Os gestos `(instante, nome)` em ordem."""
    return sorted((mark.at, mark.gesture) for mark in marks if mark.gesture is not None)


def mark_problems(
    marks: Sequence[PersonaMark],
    initial: str,
    expressions: Sequence[str],
    gestures: Sequence[str],
    duration: float | None,
    where: str,
    kind: str,
) -> list[str]:
    """Mensagens (PT-BR) do que não cabe na persona: expressão ou gesto que o tipo não faz e marca fora da duração.
    `duration` None pula a conferência de tempo (a duração ainda não é conhecida)."""
    problems: list[str] = []
    if initial not in expressions:
        problems.append(_unknown(f"{where}.expression", "a expressão", initial, kind, expressions))
    for index, mark in enumerate(marks):
        here = f"{where}.marks[{index}]"
        if mark.expression is not None and mark.expression not in expressions:
            problems.append(_unknown(here, "a expressão", mark.expression, kind, expressions))
        if mark.gesture is not None and mark.gesture not in gestures:
            problems.append(_unknown(here, "o gesto", mark.gesture, kind, gestures))
        if duration is not None and mark.at >= duration:
            problems.append(
                f"{here}: a marca em {mark.at:g}s cai fora da fala, que dura {duration:.1f}s; "
                "use um instante menor que a duração."
            )
    return problems


def _unknown(where: str, what: str, name: str, kind: str, allowed: Sequence[str]) -> str:
    known = ", ".join(allowed) or "nenhuma"
    return f"{where}: {what} {name!r} não existe nesta persona (tipo {kind}); use: {known}."
