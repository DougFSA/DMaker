import json
from pathlib import Path

import pytest

from dmaker.config import TEMPLATES_DIR
from dmaker.domain.spec import Project
from dmaker.domain.templates import (
    Template,
    TemplateError,
    TemplateParam,
    find_template,
    list_templates,
    render_template,
    template_summary,
)

TEMPLATES = list_templates()


def _fake_value(param: TemplateParam):
    """Um valor plausível do tipo certo, para preencher parâmetros obrigatórios em teste."""
    return {
        "text": "valor de teste",
        "path": "D:/teste/arquivo.mp4",
        "paths": ["D:/teste/1.png", "D:/teste/2.png"],
        "number": 3,
        "bool": True,
        "list": ["a", "b"],
    }[param.type]


def _params_with_fakes(template: Template) -> dict:
    return {name: _fake_value(p) for name, p in template.params.items() if p.required}


@pytest.mark.parametrize("template", TEMPLATES, ids=[t.name for t in TEMPLATES])
def test_template_renders_with_defaults_and_validates(template: Template):
    rendered = render_template(template, _params_with_fakes(template))
    assert "params" not in rendered and "description" not in rendered
    project = Project.model_validate(rendered)
    assert project.timeline
    if project.brand == "medlycare":
        for where, text in project.texts():
            assert "—" not in text and "–" not in text, where


def test_templates_exist():
    assert len(TEMPLATES) >= 4


def test_find_template_by_filename_and_by_body_name():
    by_stem = find_template("reel-medlycare-produto")
    assert by_stem.name == "reel-medlycare-produto"
    by_body_name = find_template("medlycare-produto-reel")
    assert by_body_name is by_stem or by_body_name.body["name"] == "medlycare-produto-reel"


def test_find_template_unknown_raises():
    with pytest.raises(TemplateError, match="não encontrado"):
        find_template("nao-existe-esse-template")


# ---------- mecânica de placeholders (domain/templates.py) ----------


def _template(params: dict, body: dict) -> Template:
    parsed = {}
    for name, raw in params.items():
        has_default = "default" in raw
        parsed[name] = TemplateParam(
            name=name,
            description=raw.get("description", ""),
            default=raw.get("default"),
            type=raw.get("type") or ("bool" if isinstance(raw.get("default"), bool) else "text"),
            required=raw.get("required", not has_default),
        )
    return Template(
        name="teste", description="template de teste", path=Path("teste.json"), params=parsed, body=body
    )


def test_placeholder_whole_string_keeps_original_type():
    template = _template(
        {"n": {"type": "number", "required": True}, "ok": {"type": "bool", "default": False}},
        {"a": "{{n}}", "b": "{{ok}}"},
    )
    out = render_template(template, {"n": 5})
    assert out == {"a": 5, "b": False}


def test_placeholder_interpolated_inside_text():
    template = _template({"nome": {"type": "text", "default": "Ana"}}, {"saudacao": "Oi, {{nome}}!"})
    out = render_template(template, {})
    assert out["saudacao"] == "Oi, Ana!"


def test_for_expands_list_with_index():
    template = _template(
        {"itens": {"type": "list", "required": True}},
        {"lista": [{"$for": "itens", "as": "x", "item": {"valor": "{{x}}", "indice": "{{x_index}}"}}]},
    )
    out = render_template(template, {"itens": ["a", "b", "c"]})
    assert out["lista"] == [
        {"valor": "a", "indice": 0},
        {"valor": "b", "indice": 1},
        {"valor": "c", "indice": 2},
    ]


def test_if_drops_item_when_falsy_and_keeps_when_truthy():
    template = _template(
        {"logo": {"type": "bool", "default": False}},
        {"overlays": [{"$if": "{{logo}}", "type": "image", "src": "logo"}, {"type": "progress-bar"}]},
    )
    assert render_template(template, {"logo": False})["overlays"] == [{"type": "progress-bar"}]
    assert render_template(template, {"logo": True})["overlays"] == [
        {"type": "image", "src": "logo"},
        {"type": "progress-bar"},
    ]


def test_if_on_nested_object_drops_the_key():
    template = _template(
        {"musica": {"type": "path", "required": False}},
        {"audio": {"music": {"$if": "{{musica}}", "src": "{{musica}}"}, "normalize": "off"}},
    )
    assert render_template(template, {})["audio"] == {"normalize": "off"}
    assert render_template(template, {"musica": "trilha.mp3"})["audio"] == {
        "music": {"src": "trilha.mp3"},
        "normalize": "off",
    }


def test_missing_required_params_raise_template_error_listing_names():
    template = _template(
        {"a": {"type": "text", "required": True}, "b": {"type": "text", "required": True}}, {"x": "{{a}}"}
    )
    with pytest.raises(TemplateError) as exc_info:
        render_template(template, {})
    assert "a, b" in str(exc_info.value)


def test_unknown_param_raises_template_error():
    template = _template({"a": {"type": "text", "default": "x"}}, {"x": "{{a}}"})
    with pytest.raises(TemplateError, match="não tem os parâmetros"):
        render_template(template, {"z": 1})


def test_wrong_type_raises_template_error():
    template = _template({"n": {"type": "number", "required": True}}, {"x": "{{n}}"})
    with pytest.raises(TemplateError, match='"number"'):
        render_template(template, {"n": "não é número"})


def test_template_summary_lists_params():
    template = _template(
        {
            "titulo": {"type": "text", "default": "Oi", "description": "título do cartão"},
            "video": {"type": "path", "required": True, "description": "vídeo fonte"},
        },
        {},
    )
    summary = template_summary(template)
    assert "teste" in summary
    assert "titulo" in summary and "padrão='Oi'" in summary
    assert "video" in summary and "obrigatório" in summary


def test_all_template_files_are_valid_json_with_params_and_description():
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "params" in data, path
        assert "description" in data, path
