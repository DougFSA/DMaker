"""Contrato entre o catálogo do painel Filtros (interface nova) e o schema da spec.

O catálogo (`frontend/src/lib/filterCatalog.json`) diz quais campos cada tipo de item mostra; as opções, os limites e
os padrões saem do schema. Um campo renomeado ou removido em `domain/spec.py` sumiria da tela sem aviso: este teste lê
os dois lados e reprova na hora.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.spec import Project

CATALOG_PATH = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "filterCatalog.json"

CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
SCHEMA = Project.model_json_schema()
DEFS = SCHEMA["$defs"]


def _alternatives(node: dict) -> list[dict]:
    """As alternativas de um campo (o `anyOf` quebrado em partes), com o `$ref` já seguido."""
    parts = node.get("anyOf", [node])
    resolved = []
    for part in parts:
        if "$ref" in part:
            part = DEFS[part["$ref"].rsplit("/", 1)[-1]]
        resolved.append(part)
    return resolved


def _ref_name(node: dict) -> str | None:
    """O nome da definição para a qual o campo aponta (direto ou dentro de um `anyOf`), se apontar."""
    for part in node.get("anyOf", [node]):
        if "$ref" in part:
            return part["$ref"].rsplit("/", 1)[-1]
    return None


def _types(node: dict) -> set[str]:
    return {part.get("type", "object") for part in _alternatives(node) if part.get("type") != "null"}


def _has_enum(node: dict) -> bool:
    return any("enum" in part for part in _alternatives(node))


def _fields() -> list:
    return [
        pytest.param(group, field, id=f"{group['id']}/{field['key']}")
        for group in CATALOG["groups"]
        for field in group["fields"]
    ]


def _prop(field: dict) -> str:
    return field.get("prop") or field["key"].split(".")[-1]


def test_every_target_points_to_a_real_definition() -> None:
    for name, target in CATALOG["targets"].items():
        if target["def"] is not None:
            assert target["def"] in DEFS, f"o tipo {name} aponta para {target['def']}, que o schema não tem"


def test_catalog_has_the_38_groups_of_the_classic_interface() -> None:
    assert len(CATALOG["groups"]) == 38
    ids = [group["id"] for group in CATALOG["groups"]]
    assert len(set(ids)) == len(ids), "há dois grupos com o mesmo id"


@pytest.mark.parametrize(("group", "field"), _fields())
def test_field_exists_in_its_schema_definition(group: dict, field: dict) -> None:
    def_name = field.get("def") or group["def"]
    assert def_name in DEFS, f"{def_name} não existe no schema"
    properties = DEFS[def_name]["properties"]
    assert _prop(field) in properties, f"{def_name} não tem a propriedade {_prop(field)}"


@pytest.mark.parametrize(("group", "field"), _fields())
def test_field_kind_matches_the_schema_type(group: dict, field: dict) -> None:
    def_name = field.get("def") or group["def"]
    node = DEFS[def_name]["properties"].get(_prop(field))
    assert node is not None, f"{def_name} não tem a propriedade {_prop(field)}"
    kind, types = field["kind"], _types(node)
    if field["key"].split(".")[-1].isdigit():
        assert "array" in types, "o índice do caminho pede uma lista no schema"
    elif kind == "number":
        assert types & {"number", "integer"}, f"{field['key']} é número no catálogo e {types} no schema"
    elif kind == "check":
        assert "boolean" in types, f"{field['key']} é caixa de marcar no catálogo e {types} no schema"
    elif kind == "select":
        assert _has_enum(node) or field.get("values") or field.get("choicesFrom"), (
            f"{field['key']} é uma lista sem opções: o schema não tem enum e o catálogo não traz valores"
        )
    else:
        assert "string" in types, f"{field['key']} é texto no catálogo e {types} no schema"


@pytest.mark.parametrize(("group", "field"), _fields())
def test_field_path_exists_in_every_item_type_that_uses_the_group(group: dict, field: dict) -> None:
    first = field["key"].split(".")[0]
    def_name = field.get("def") or group["def"]
    if "base" in group:
        # grupo do projeto: o caminho fixo tem que ser uma seção da spec que aponta para a definição certa
        section = SCHEMA["properties"][group["base"]]
        assert _ref_name(section) == group["defaultsDef"] == def_name
        return
    for target in group["applies"]:
        item_def = CATALOG["targets"][target]["def"]
        item_properties = DEFS[item_def]["properties"]
        assert first in item_properties, (
            f"{item_def} não tem {first}, e o grupo {group['id']} vale para {target}"
        )
        if "." in field["key"]:
            # campo aninhado: o contêiner do item tem que ser a definição que o campo usa para opções e limites
            assert _ref_name(item_properties[first]) == def_name, f"{item_def}.{first} não é um {def_name}"
        else:
            same = _types(item_properties[first]) == _types(DEFS[def_name]["properties"][_prop(field)])
            assert same, f"{item_def}.{first} tem outro tipo que {def_name}.{_prop(field)}"


def test_catalog_text_has_no_dash() -> None:
    """Regra da marca: nada de travessão em texto de tela, e o catálogo é texto de tela."""
    text = CATALOG_PATH.read_text(encoding="utf-8")
    assert "—" not in text
    assert "–" not in text
