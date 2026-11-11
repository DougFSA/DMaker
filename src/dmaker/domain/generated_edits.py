"""Edição dos sons gerados (`audio.generated`): acrescentar, mudar e tirar. Tudo puro: cada função devolve um Project NOVO e
levanta `EditError` em português quando o pedido não faz sentido (gerador que não existe, parâmetro fora da faixa)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .edits import EditError, _check_index, _clone
from .generators import GENERATOR_CLASSES, parse_generator
from .spec import GeneratedSound, Project

ITEM_FIELDS = tuple(GeneratedSound.model_fields)


def _item(data: dict[str, Any]) -> dict[str, Any]:
    """O item validado (com a mensagem só da regra de negócio) e de volta como dicionário."""
    unknown = sorted(set(data) - set(ITEM_FIELDS))
    if unknown:
        raise EditError(
            f"campo(s) de som gerado desconhecido(s): {', '.join(unknown)}. Use: {', '.join(ITEM_FIELDS)}"
        )
    try:
        return GeneratedSound.model_validate(data).model_dump()
    except ValidationError as exc:
        reasons = [str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()]
        raise EditError("; ".join(dict.fromkeys(reasons))) from exc


def add_generated(
    project: Project, fields: dict[str, Any], resolve: Callable[[str], Path] | None = None
) -> Project:
    """Acrescenta o som: `generator` é obrigatório. Sem `duration`, vale a que o gerador pede (as batidas do ritmo, as
    teclas do DTMF, as linhas do texto de amostras) ou, sem duração natural, um segundo."""
    name = fields.get("generator")
    if name not in GENERATOR_CLASSES:
        known = ", ".join(GENERATOR_CLASSES)
        raise EditError(f"informe `generator`, um de: {known}")
    item = dict(fields)
    if item.get("duration") is None:
        try:
            item["duration"] = parse_generator(name, item.get("params")).natural_duration(
                resolve or project.resolve
            )
        except (ValueError, FileNotFoundError) as exc:
            raise EditError(str(exc)) from exc
    sound = _item(item)

    def mutate(data: dict) -> None:
        data["audio"].setdefault("generated", []).append(sound)

    return _clone(project, mutate)


def set_generated(project: Project, index: int, fields: dict[str, Any]) -> Project:
    """Muda os campos dados do som `index`, mantendo os outros. `params` se soma aos parâmetros que o som já tem; trocar o
    `generator` zera os parâmetros (os do gerador novo começam nos padrões dele) a menos que o pedido traga os novos."""
    _check_index(len(project.audio.generated), index, "som gerado")
    if not fields:
        raise EditError('informe o que mudar no som (por exemplo duration=2 ou params={"frequency_hz": 880})')
    current = project.audio.generated[index].model_dump()
    merged = {**current, **{key: value for key, value in fields.items() if key != "params"}}
    if "params" in fields:
        same_generator = merged["generator"] == current["generator"]
        merged["params"] = {**(current["params"] if same_generator else {}), **(fields["params"] or {})}
    elif merged["generator"] != current["generator"]:
        merged["params"] = {}
    sound = _item(merged)

    def mutate(data: dict) -> None:
        data["audio"]["generated"][index] = sound

    return _clone(project, mutate)


def remove_generated(project: Project, index: int) -> Project:
    _check_index(len(project.audio.generated), index, "som gerado")

    def mutate(data: dict) -> None:
        del data["audio"]["generated"][index]

    return _clone(project, mutate)
