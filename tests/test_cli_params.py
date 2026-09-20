"""Conversão dos `--param chave=valor` da CLI para o tipo declarado no template."""

from __future__ import annotations

from pathlib import Path

from dmaker.cli import _coerce_param
from dmaker.domain.templates import Template, TemplateParam


def _template() -> Template:
    return Template(
        "t",
        "",
        Path("t.json"),
        {
            "nomes": TemplateParam("nomes", type="list"),
            "n": TemplateParam("n", type="number"),
            "ok": TemplateParam("ok", type="bool"),
        },
    )


def test_list_param_splits_on_commas():
    assert _coerce_param(_template(), "nomes", "Ana & Bia, Caio & Dora") == ["Ana & Bia", "Caio & Dora"]


def test_list_param_accepts_json_when_items_contain_commas():
    value = '["Daniel & Bruna", "Souza, Ana & Léo"]'
    assert _coerce_param(_template(), "nomes", value) == ["Daniel & Bruna", "Souza, Ana & Léo"]


def test_number_and_bool_params():
    assert _coerce_param(_template(), "n", "2.5") == 2.5
    assert _coerce_param(_template(), "ok", "sim") is True
