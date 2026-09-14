"""Despacha operações de edição pontual sobre a spec: calcula o layout atual e chama a função pura
correspondente em `domain.edits`. Aberto para extensão: um tipo de operação novo é uma entrada nova
em `EDIT_OPERATIONS`, sem tocar no dispatcher."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.edits import (
    EditError,
    duplicate_overlay,
    duplicate_segment,
    insert_segment,
    move_segment,
    remove_overlay,
    remove_segment,
    set_field,
    set_overlay_span,
    split_segment,
    trim_segment,
)
from ..domain.spec import ClipSegment, Project
from ..media.probe import probe
from .context import Prober
from .layout import ProjectLayout, project_layout
from .sync import OffsetFinder

Operation = Callable[[Project, dict, ProjectLayout], Project]


def _clip_media_duration(project: Project, layout: ProjectLayout, index: int) -> float | None:
    """Limite de `end` do trecho (tempo do arquivo; tempo da sessão quando a fonte é sincronizada,
    já que `offset` é 0 para arquivos avulsos)."""
    segment = project.timeline[index]
    if not isinstance(segment, ClipSegment):
        return None
    source = layout.sources[index]
    if source.info is None or not source.info.duration:
        return None
    return source.offset + source.info.duration


def _op_split(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return split_segment(project, op["index"], op["at"], layout.durations)


def _op_remove(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return remove_segment(project, op["index"])


def _op_move(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return move_segment(project, op["index"], op["to"])


def _op_trim(project: Project, op: dict, layout: ProjectLayout) -> Project:
    index = op["index"]
    media_duration = _clip_media_duration(project, layout, index)
    return trim_segment(project, index, op["side"], op["delta"], layout.durations, media_duration)


def _op_duplicate(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return duplicate_segment(project, op["index"])


def _op_insert(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return insert_segment(project, op["index"], op["segment"])


def _op_overlay_span(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return set_overlay_span(project, op["index"], op["start"], op.get("end"))


def _op_overlay_remove(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return remove_overlay(project, op["index"])


def _op_overlay_duplicate(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return duplicate_overlay(project, op["index"])


def _op_set_field(project: Project, op: dict, layout: ProjectLayout) -> Project:
    return set_field(project, op["path"], op.get("value"))


EDIT_OPERATIONS: dict[str, Operation] = {
    "split": _op_split,
    "remove": _op_remove,
    "move": _op_move,
    "trim": _op_trim,
    "duplicate": _op_duplicate,
    "insert": _op_insert,
    "overlay_span": _op_overlay_span,
    "overlay_remove": _op_overlay_remove,
    "overlay_duplicate": _op_overlay_duplicate,
    "set_field": _op_set_field,
}


def apply_edit(
    project: Project, op: dict, prober: Prober = probe, offset_finder: OffsetFinder | None = None
) -> Project:
    """Calcula o layout atual do projeto e aplica a operação `op["type"]` sobre a spec, devolvendo
    um Project novo. Parâmetro ausente ou do tipo errado em `op` vira EditError."""
    op_type = op.get("type")
    handler = EDIT_OPERATIONS.get(op_type)
    if handler is None:
        raise EditError(
            f"operação de edição desconhecida: {op_type!r}. Use uma de: {', '.join(sorted(EDIT_OPERATIONS))}"
        )
    layout = project_layout(project, prober, offset_finder)
    try:
        return handler(project, op, layout)
    except EditError:
        raise
    except (KeyError, TypeError) as exc:
        raise EditError(f"parâmetros inválidos para a operação {op_type!r}: {exc}") from exc
