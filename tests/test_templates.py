import json
from pathlib import Path

import pytest

from dmaker.config import TEMPLATES_DIR
from dmaker.domain.spec import Project
from dmaker.domain.templates import (
    Template,
    TemplateError,
    TemplateParam,
    expand_dir,
    find_template,
    list_templates,
    load_template,
    render_template,
    template_summary,
)

TEMPLATES = list_templates()


def _fake_value(param: TemplateParam, tmp_path: Path):
    """Um valor plausível do tipo certo, para preencher parâmetros obrigatórios em teste. `dir` cria
    uma pastinha de verdade em `tmp_path` com um arquivo de mídia vazio dentro."""
    if param.example is not None:  # o exemplo do próprio template é o valor mais plausível
        return param.example
    if param.type == "dir":
        folder = tmp_path / param.name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "0001.mp4").write_bytes(b"")
        return str(folder)
    return {
        "text": "valor de teste",
        "path": "D:/teste/arquivo.mp4",
        "paths": ["D:/teste/1.png", "D:/teste/2.png"],
        "number": 3,
        "bool": True,
        "list": ["a", "b"],
    }[param.type]


def _params_with_fakes(template: Template, tmp_path: Path) -> dict:
    return {name: _fake_value(p, tmp_path) for name, p in template.params.items() if p.required}


@pytest.mark.parametrize("template", TEMPLATES, ids=[t.name for t in TEMPLATES])
def test_template_renders_with_defaults_and_validates(template: Template, tmp_path):
    rendered = render_template(template, _params_with_fakes(template, tmp_path))
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


# ---------- parâmetro "dir" / expand_dir (domain/templates.py) ----------


def test_expand_dir_lists_media_files_in_natural_order(tmp_path):
    for name in ["cam1_0010.mp4", "cam1_0002.mp4", "cam1_0001.mp4", "notas.txt", "capa.png"]:
        (tmp_path / name).write_bytes(b"")
    files = expand_dir(tmp_path)
    assert [Path(f).name for f in files] == ["cam1_0001.mp4", "cam1_0002.mp4", "cam1_0010.mp4"]
    assert all(Path(f).is_absolute() for f in files)


def test_expand_dir_natural_order_with_camera_style_names(tmp_path):
    for name in ["VID_20250815_102.mp4", "VID_20250815_101.mp4", "VID_20250815_110.mp4"]:
        (tmp_path / name).write_bytes(b"")
    files = expand_dir(tmp_path)
    assert [Path(f).name for f in files] == [
        "VID_20250815_101.mp4",
        "VID_20250815_102.mp4",
        "VID_20250815_110.mp4",
    ]


def test_expand_dir_is_case_insensitive_about_extension(tmp_path):
    (tmp_path / "a.MP4").write_bytes(b"")
    (tmp_path / "b.M4A").write_bytes(b"")
    assert len(expand_dir(tmp_path)) == 2


def test_expand_dir_raises_on_missing_folder(tmp_path):
    with pytest.raises(TemplateError, match="não encontrada"):
        expand_dir(tmp_path / "nao-existe")


def test_expand_dir_raises_on_empty_folder(tmp_path):
    (tmp_path / "leia-me.txt").write_bytes(b"")
    with pytest.raises(TemplateError, match="sem arquivos"):
        expand_dir(tmp_path)


def test_dir_param_becomes_list_of_absolute_paths(tmp_path):
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "a.mp4").write_bytes(b"")
    template = _template({"pasta": {"type": "dir", "required": True}}, {"arquivos": "{{pasta}}"})
    out = render_template(template, {"pasta": str(tmp_path)})
    assert out["arquivos"] == [str((tmp_path / "a.mp4").resolve()), str((tmp_path / "b.mp4").resolve())]


def test_dir_param_wrong_type_raises_template_error():
    template = _template({"pasta": {"type": "dir", "required": True}}, {"x": "{{pasta}}"})
    with pytest.raises(TemplateError, match='"dir"'):
        render_template(template, {"pasta": 123})


def test_all_template_files_are_valid_json_with_params_and_description():
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "params" in data, path
        assert "description" in data, path


# ---------- campos de objeto, preparador de parâmetros e exemplo ----------


def test_placeholder_reaches_a_field_of_an_object_param():
    template = _template(
        {"assuntos": {"type": "list", "required": True}},
        {
            "trechos": [
                {"$for": "assuntos", "as": "a", "item": {"dur": "{{a.fim}}", "rotulo": "ate {{a.fim}} s"}}
            ],
            "primeiro": "{{assuntos}}",
        },
    )
    out = render_template(template, {"assuntos": [{"fim": 4}, {"fim": 9}]})
    assert out["trechos"] == [{"dur": 4, "rotulo": "ate 4 s"}, {"dur": 9, "rotulo": "ate 9 s"}]


def test_nested_placeholder_with_a_missing_field_is_a_template_error():
    template = _template(
        {"a": {"type": "list", "required": True}}, {"x": [{"$for": "a", "as": "i", "item": "{{i.nome}}"}]}
    )
    with pytest.raises(TemplateError, match='i.nome.*sem o campo "nome"'):
        render_template(template, {"a": [{"fim": 1}]})
    with pytest.raises(TemplateError, match="desconhecido"):
        render_template(_template({}, {"x": "{{sumiu.campo}}"}), {})


def test_prepare_hook_runs_before_substitution_and_its_errors_become_template_errors(monkeypatch):
    from dmaker.domain import templates

    def preparer(params):
        if params["n"] < 0:
            raise ValueError("n negativo")
        return {**params, "dobro": params["n"] * 2}

    monkeypatch.setitem(templates.PARAM_PREPARERS, "dobrar", preparer)
    template = _template({"n": {"type": "number", "required": True}}, {"x": "{{dobro}}"})
    template.prepare = "dobrar"
    assert render_template(template, {"n": 4}) == {"x": 8}
    with pytest.raises(TemplateError, match="teste.*n negativo"):
        render_template(template, {"n": -1})


def test_unknown_prepare_hook_is_refused_when_the_template_is_loaded(tmp_path):
    path = tmp_path / "ruim.json"
    path.write_text(json.dumps({"description": "x", "prepare": "nao-existe", "params": {}}), encoding="utf-8")
    with pytest.raises(TemplateError, match="preparador desconhecido.*nao-existe"):
        load_template(path)


def test_param_example_shows_up_in_the_summary_and_in_the_loaded_template():
    explicativo = find_template("explicativo")
    assert explicativo.prepare == "explicativo"
    assert explicativo.params["assuntos"].example[0]["fim"] == 20
    assert "exemplo:" in template_summary(explicativo) and '"fundo": "escuro"' in template_summary(
        explicativo
    )
