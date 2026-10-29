"""Referência dos campos da spec, gerada do esquema JSON do modelo Pydantic (`Project`).

Cada modelo vira uma tabela com todos os campos, o tipo, o padrão e uma nota curta. A nota é opcional e vem
de `field_notes.py`; o campo em si nunca depende dela, então um campo novo aparece no manual mesmo sem nota.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

ROOT_MODEL = "Project"


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _range_label(prop: dict[str, Any]) -> str:
    low = prop.get("minimum")
    high = prop.get("maximum")
    low_open = prop.get("exclusiveMinimum")
    high_open = prop.get("exclusiveMaximum")
    if low is not None and high is not None:
        return f"de {low:g} a {high:g}"
    if low_open is not None and high is not None:
        return f"maior que {low_open:g}, até {high:g}"
    if low_open is not None and high_open is not None:
        return f"entre {low_open:g} e {high_open:g}, sem os extremos"
    if low is not None:
        return f"mínimo {low:g}"
    if low_open is not None:
        return f"maior que {low_open:g}"
    if high is not None:
        return f"máximo {high:g}"
    return ""


def type_label(prop: dict[str, Any]) -> str:
    """O tipo de um campo em português, com valores fixos e limites quando existem."""
    if "$ref" in prop:
        return f"`{_ref_name(prop['$ref'])}`"
    if "const" in prop:
        return f'`"{prop["const"]}"`'
    if "enum" in prop:
        return " ou ".join(f'`"{value}"`' for value in prop["enum"])
    for key in ("anyOf", "oneOf"):
        if key in prop:
            labels = [type_label(option) for option in prop[key] if option.get("type") != "null"]
            return " ou ".join(dict.fromkeys(labels)) or "qualquer valor"
    kind = prop.get("type")
    if kind == "array":
        items = prop.get("items") or {}
        inner = type_label(items) if items else "qualquer valor"
        if "oneOf" in items:
            inner = type_label(items)
        minimum = f" (pelo menos {prop['minItems']})" if prop.get("minItems") else ""
        return f"lista de {inner}{minimum}"
    if kind == "object":
        extra = prop.get("additionalProperties")
        return f"mapa de {type_label(extra)}" if isinstance(extra, dict) and extra else "objeto"
    names = {"string": "texto", "integer": "inteiro", "number": "número", "boolean": "sim ou não"}
    label = names.get(kind or "", "qualquer valor")
    span = _range_label(prop)
    return f"{label}, {span}" if span else label


def default_label(prop: dict[str, Any], required: bool) -> str:
    """O padrão do campo: `obrigatório`, `nenhum`, o valor, ou `vazio` para lista e mapa sem nada."""
    if required:
        return "obrigatório"
    if "default" not in prop:
        return ""
    value = prop["default"]
    if value is None:
        return "nenhum"
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, dict | list):
        return "vazio" if not value else "os valores padrão do bloco"
    if isinstance(value, str):
        return f"`{value}`" if value else "texto vazio"
    return json.dumps(value)


def note_for(notes: Mapping[str, str], model: str, name: str) -> str:
    return notes.get(f"{model}.{name}") or notes.get(f"*.{name}") or ""


def _used_by(schema: dict[str, Any]) -> dict[str, list[str]]:
    """Quais campos apontam para cada modelo, para a tabela dizer onde ele aparece na spec."""
    users: dict[str, list[str]] = {}
    owners = {ROOT_MODEL: schema.get("properties", {})}
    owners.update({name: d.get("properties", {}) for name, d in schema.get("$defs", {}).items()})
    for owner, properties in owners.items():
        for field_name, prop in properties.items():
            for target in _refs_in(prop):
                users.setdefault(target, []).append(f"{owner}.{field_name}")
    return users


def _refs_in(prop: Any) -> list[str]:
    found: list[str] = []
    if isinstance(prop, dict):
        if "$ref" in prop:
            found.append(_ref_name(prop["$ref"]))
        for value in prop.values():
            found.extend(_refs_in(value))
    elif isinstance(prop, list):
        for item in prop:
            found.extend(_refs_in(item))
    return found


def _table(model: str, definition: dict[str, Any], notes: Mapping[str, str]) -> list[str]:
    required = set(definition.get("required") or [])
    lines = ["| Campo | Tipo | Padrão | O que é |", "| --- | --- | --- | --- |"]
    for name, prop in (definition.get("properties") or {}).items():
        note = note_for(notes, model, name).replace("|", "/")
        lines.append(f"| `{name}` | {type_label(prop)} | {default_label(prop, name in required)} | {note} |")
    return lines


def spec_reference(schema: dict[str, Any], notes: Mapping[str, str]) -> str:
    """Uma tabela por modelo da spec: a raiz (`Project`) primeiro, depois cada bloco que ela usa."""
    users = _used_by(schema)
    definitions: dict[str, dict[str, Any]] = {ROOT_MODEL: schema, **schema.get("$defs", {})}
    total = sum(len(d.get("properties") or {}) for d in definitions.values())
    out = [
        f"São {len(definitions)} blocos e {total} campos. Cada bloco aparece com os campos que ele aceita; "
        "um campo fora desta lista é recusado na validação.",
    ]
    for model, definition in definitions.items():
        out.extend(["", f"#### {model}", ""])
        if model == ROOT_MODEL:
            out.append("A raiz do `spec.json`.")
        else:
            refs = list(dict.fromkeys(users.get(model, [])))
            where = ", ".join(f"`{ref}`" for ref in refs[:6]) + (" e outros" if len(refs) > 6 else "")
            out.append(f"Usado em {where}." if where else "Bloco da spec.")
        out.extend(["", *_table(model, definition, notes)])
    return "\n".join(out)
