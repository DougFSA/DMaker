"""Edição das regras do Auto Duck (`audio.ducks`): acrescentar, mudar e tirar. Tudo puro: cada função devolve um Project
NOVO e levanta `EditError` em português quando o pedido não faz sentido (inclusive as combinações de trilha que a regra
não aceita, com o motivo escrito para quem não conhece a mixagem)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .auto_duck import AutoDuck
from .edits import EditError, _check_index, _clone
from .spec import Project

RULE_FIELDS = tuple(AutoDuck.model_fields)


def _rule(data: dict[str, Any]) -> dict[str, Any]:
    """A regra validada (com a mensagem só da regra de negócio) e de volta como dicionário."""
    unknown = sorted(set(data) - set(RULE_FIELDS))
    if unknown:
        raise EditError(
            f"campo(s) de Auto Duck desconhecido(s): {', '.join(unknown)}. Use: {', '.join(RULE_FIELDS)}"
        )
    try:
        return AutoDuck.model_validate(data).model_dump()
    except ValidationError as exc:
        reasons = [str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()]
        raise EditError("; ".join(dict.fromkeys(reasons))) from exc


def add_duck(project: Project, fields: dict[str, Any]) -> Project:
    """Acrescenta a regra: `background` (a trilha que abaixa) e `key` (a que comanda) são obrigatórios."""
    if "background" not in fields or "key" not in fields:
        raise EditError(
            "informe `background` (a trilha que abaixa) e `key` (a trilha que comanda), por exemplo A2 e A3"
        )
    rule = _rule(fields)

    def mutate(data: dict) -> None:
        data["audio"].setdefault("ducks", []).append(rule)

    return _clone(project, mutate)


def set_duck(project: Project, index: int, fields: dict[str, Any]) -> Project:
    """Muda os campos dados da regra `index`, mantendo os outros."""
    _check_index(len(project.audio.ducks), index, "regra de Auto Duck")
    if not fields:
        raise EditError("informe o que mudar na regra (por exemplo amount_db=-15)")
    rule = _rule({**project.audio.ducks[index].model_dump(), **fields})

    def mutate(data: dict) -> None:
        data["audio"]["ducks"][index] = rule

    return _clone(project, mutate)


def remove_duck(project: Project, index: int) -> Project:
    _check_index(len(project.audio.ducks), index, "regra de Auto Duck")

    def mutate(data: dict) -> None:
        del data["audio"]["ducks"][index]

    return _clone(project, mutate)
