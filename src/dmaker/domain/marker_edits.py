"""Edição dos marcadores da spec: acrescentar, mudar e remover. Cada função devolve um Project NOVO (a spec original
nunca é alterada), como as de `edits.py`, e levanta `EditError` em português quando o pedido não faz sentido."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .edits import EditError, _check_index, _clone
from .markers import MarkerError, find_marker, is_marker_ref
from .spec import Project

# os campos de um marcador que a edição pode mudar; `at` (instante) e `start`/`end` (região) se excluem
MARKER_FIELDS = ("at", "start", "end", "text", "color", "group", "low_hz", "high_hz")


def marker_index(project: Project, op: Mapping[str, Any]) -> int:
    """O marcador de uma operação: `index` (posição em `markers`) ou `ref` (`marker:<texto>`)."""
    if op.get("ref") is not None:
        reference = str(op["ref"])
        if not is_marker_ref(reference):
            reference = f"marker:{reference}"
        try:
            return find_marker(project.markers, reference)
        except MarkerError as exc:
            raise EditError(str(exc)) from exc
    if op.get("index") is None:
        raise EditError("informe `index` (posição em markers) ou `ref` (marker:<texto>) do marcador")
    _check_index(len(project.markers), op["index"], "marcador")
    return op["index"]


def add_marker(project: Project, fields: Mapping[str, Any]) -> Project:
    """Acrescenta um marcador ao fim da lista; a spec inteira é revalidada, então campos incoerentes falham aqui."""
    marker = _only_marker_fields(fields)

    def mutate(data: dict) -> None:
        data["markers"].append(marker)

    return _clone(project, mutate)


def set_marker(project: Project, index: int, changes: Mapping[str, Any]) -> Project:
    """Muda campos do marcador `index`. Dar `at` o torna um instante; dar `start` e `end` o torna uma região; um
    valor nulo (`color`, `low_hz`, `high_hz`) tira o campo."""
    _check_index(len(project.markers), index, "marcador")
    changed = _only_marker_fields(changes, keep_none=True)
    if not changed:
        raise EditError(
            "nada a mudar: dê pelo menos um campo do marcador (text, at, start, end, color, group)"
        )

    def mutate(data: dict) -> None:
        current = {key: value for key, value in data["markers"][index].items() if value is not None}
        if changed.get("at") is not None:
            current.pop("start", None)
            current.pop("end", None)
        elif changed.get("start") is not None or changed.get("end") is not None:
            current.pop("at", None)
        for key, value in changed.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        data["markers"][index] = current

    return _clone(project, mutate)


def remove_marker(project: Project, index: int) -> Project:
    """Remove o marcador `index`."""
    _check_index(len(project.markers), index, "marcador")

    def mutate(data: dict) -> None:
        del data["markers"][index]

    return _clone(project, mutate)


def set_group_markers(project: Project, group: str, markers: Sequence[Mapping[str, Any]]) -> Project:
    """Troca TODOS os marcadores do grupo `group` pelos `markers` dados (cada um com `at`, ou `start` e `end`, mais
    `text` e `color`), de uma vez: é um passo só do desfazer. Os marcadores dos outros grupos não são tocados, e o
    grupo vazio (a trilha padrão, da pessoa) é recusado: quem marca automaticamente escreve num grupo com nome."""
    group = group.strip()
    if not group:
        raise EditError(
            "informe o nome do grupo: o grupo vazio é a trilha padrão de marcadores da pessoa e não é substituído"
        )
    created = [{**_only_marker_fields(item), "group": group} for item in markers]

    def mutate(data: dict) -> None:
        data["markers"] = [item for item in data["markers"] if item.get("group", "") != group] + created

    return _clone(project, mutate)


def _only_marker_fields(fields: Mapping[str, Any], keep_none: bool = False) -> dict[str, Any]:
    """Só os campos de marcador que vieram na operação; `type`, `index` e `ref` são da própria operação."""
    unknown = sorted(set(fields) - set(MARKER_FIELDS) - {"type", "index", "ref"})
    if unknown:
        raise EditError(
            f"campo(s) de marcador desconhecido(s): {', '.join(unknown)} (use {', '.join(MARKER_FIELDS)})"
        )
    return {
        key: fields[key] for key in MARKER_FIELDS if key in fields and (keep_none or fields[key] is not None)
    }
