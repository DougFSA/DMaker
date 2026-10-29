"""Infográficos prontos (DMK-24), sem Chromium nem ffmpeg: o esquema de parâmetros e a validação, o atalho
`infographic` da composição em HTML, a conferência no `validate_project`, o renderizador falso no pipeline, os
adaptadores (CLI, MCP, API da interface), o modelo "explicativo" e o QA. O que só o navegador real mostra (o
contador contando, a barra enchendo, a troca de marca, o grifo na palavra) fica em `test_infographics_render.py`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.domain.brand import load_theme
from dmaker.domain.infographic_schema import (
    BRAND_COLOR_NAMES,
    SchemaError,
    parse_schema,
    validate_params,
    with_defaults,
)
from dmaker.domain.infographics import (
    InfographicError,
    find_infographic,
    infographic_warnings,
    load_infographics,
    resolve_infographic,
)
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import HtmlOverlay, Project
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.infographics import (
    add_infographic,
    coerce_assignments,
    describe_infographics,
    infographic_frame,
)
from dmaker.pipeline.layout import project_layout, to_presentation
from dmaker.pipeline.projects import summarize
from dmaker.pipeline.report import check_html_safe_zone

from .test_html import FakeHtmlRenderer, _render, _spec

DASHES = ("—", "–")
MODELS = ("barra", "contador", "emoji", "etiqueta", "grifo", "imagem", "linha")
TOPO = {"topo": {"x": 0.5, "y": 0.2575, "width": 0.7222, "height": 0.265}}


def _card_project(*overlays: dict, brand: str | None = None, **extra) -> Project:
    spec = {
        "name": "explicativo",
        "output": {"preset": "instagram/reels"},
        "regions": TOPO,
        "timeline": [{"type": "card", "flat": True, "duration": 8, "motion": "none", "logo": False}],
        "overlays": list(overlays),
        "audio": {"normalize": "off"},
        **extra,
    }
    if brand:
        spec["brand"] = brand
    return Project.model_validate(spec)


def _infographic(name: str = "contador", **fields) -> dict:
    return {"type": "html", "infographic": name, "region": "topo", "start": 1, "end": 5, **fields}


def _layout(project: Project):
    def prober(path: Path) -> MediaInfo:
        return MediaInfo(path, 8.0, 1080, 1920, 30.0, True, True, False)

    return to_presentation(project, project_layout(project, prober))


# ---------- o esquema de cada modelo ----------


def test_the_library_has_the_seven_models_each_with_an_index_and_a_valid_schema():
    models = load_infographics()
    assert tuple(models) == MODELS
    for name, model in models.items():
        assert (model.folder / "index.html").is_file() and (model.folder / "esquema.json").is_file()
        schema = model.schema
        assert schema.name == name and schema.title and schema.description and schema.params
        # o formulário e a IA leem português: todo parâmetro tem rótulo, e o exemplo passa no próprio esquema
        assert all(param.label for param in schema.params.values())
        assert validate_params(schema, schema.example) == []
        assert not any(dash in schema.description for dash in DASHES)


def test_the_models_use_only_the_brand_variables_and_do_not_paint_a_background():
    for name, model in load_infographics().items():
        html = (model.folder / "index.html").read_text(encoding="utf-8")
        assert not any(dash in html for dash in DASHES), name
        if name != "emoji":  # o emoji é uma figura pronta do Google: não há cor de marca a aplicar
            assert "var(--dm-" in html, f"{name}: o modelo não usa a marca"
        # a página não pinta o fundo (o vídeo aparece) e não escreve cor de marca na mão
        assert "<body style" not in html and "body {" not in html.replace("html, body {", "")
        for literal in ("#75b9a2", "#0c535a", "#facc15"):
            assert literal not in html.lower(), f"{name}: cor da marca escrita na mão ({literal})"


def test_the_counter_schema_matches_the_acceptance_example():
    schema = find_infographic("contador").schema
    assert schema.params["ate"].required and schema.params["de"].default == 0
    assert schema.params["duracao"].default == 1.2
    assert {"prefixo", "sufixo", "casas", "easing", "cor"} <= set(schema.params)


def test_the_grifo_declares_which_parameters_pin_it_to_a_caption_word():
    anchor = find_infographic("grifo").schema.caption_anchor
    assert anchor is not None and anchor.word == "palavra" and anchor.margin == "recuo"
    assert all(find_infographic(name).schema.caption_anchor is None for name in MODELS if name != "grifo")


def test_describe_gives_the_agent_the_name_the_description_and_the_schema_of_each_model():
    described = {item["name"]: item for item in describe_infographics()}
    counter = described["contador"]
    assert counter["title"] == "Contador" and counter["description"]
    ate = next(param for param in counter["params"] if param["name"] == "ate")
    assert ate == {
        "name": "ate",
        "type": "number",
        "label": "Termina em",
        "description": ate["description"],
        "required": True,
        "min": -1000000000.0,
        "max": 1000000000.0,
        "example": 10000,
    }
    choice = next(param for param in counter["params"] if param["name"] == "easing")
    assert choice["options"] == ["suave", "entrada-saida", "linear"] and choice["default"] == "suave"
    json.dumps(described)  # é JSON de verdade (vai pelo MCP e pela API)


# ---------- a validação (função pura) ----------


@pytest.fixture(scope="module")
def counter():
    return find_infographic("contador").schema


def _issues(schema, **data):
    return {issue.param: issue.detail for issue in validate_params(schema, data)}


def test_valid_parameters_have_no_issue(counter):
    assert validate_params(counter, {"ate": 10000, "prefixo": "+ de R$", "casas": 1, "sombra": False}) == []


def test_text_in_place_of_a_number_is_pointed_at_with_the_value(counter):
    issues = _issues(counter, ate="dez mil")
    assert issues == {"ate": "precisa ser um número (veio o texto 'dez mil')"}
    assert validate_params(counter, {"ate": "dez mil"})[0].message.startswith("`ate` precisa ser um número")


def test_a_boolean_is_not_a_number_and_nan_is_not_a_number_either(counter):
    assert "ate" in _issues(counter, ate=True)
    assert "ate" in _issues(counter, ate=float("nan"))
    assert "ate" in _issues(counter, ate=float("inf"))


def test_limits_enum_required_unknown_key_and_length_are_all_checked(counter):
    assert "não pode passar de 1000000000" in _issues(counter, ate=2e9)["ate"]
    assert "não pode ser menor que -1000000000" in _issues(counter, ate=-2e9)["ate"]
    assert (
        "casas" in _issues(counter, ate=1, casas=9)
        and "inteiro" in _issues(counter, ate=1, casas=1.5)["casas"]
    )
    assert (
        "precisa ser um destes: suave, entrada-saida, linear"
        in _issues(counter, ate=1, easing="rapido")["easing"]
    )
    assert _issues(counter)["ate"].startswith("é obrigatório no modelo contador")
    assert "30" in _issues(counter, ate=1, prefixo="x" * 31)["prefixo"]
    assert "verdadeiro ou falso" in _issues(counter, ate=1, sombra="sim")["sombra"]


def test_an_unknown_key_suggests_the_closest_parameter_and_lists_the_valid_ones(counter):
    detail = _issues(counter, ate=1, prefix="x")["prefix"]
    assert "não é um parâmetro do modelo contador" in detail and "quis dizer `prefixo`?" in detail
    assert "de, ate, prefixo" in detail


def test_colors_accept_a_hex_or_a_brand_color_name(counter):
    assert validate_params(counter, {"ate": 1, "cor": "#12AB9F", "cor_texto": "primary"}) == []
    assert "cor" in _issues(counter, ate=1, cor="azul")
    assert "cor" in _issues(counter, ate=1, cor="#12AB9")
    # com as cores de uma marca, só valem as dela
    assert validate_params(counter, {"ate": 1, "cor": "mint"}, color_names=["primary"])[0].param == "cor"
    assert set(BRAND_COLOR_NAMES) >= {"primary", "accent", "white", "bg_dark"}


def test_defaults_fill_what_is_missing_and_the_request_always_wins(counter):
    merged = with_defaults(counter, {"ate": 95, "de": 5, "prefixo": None})
    assert merged["ate"] == 95 and merged["de"] == 5 and merged["duracao"] == 1.2
    assert merged["prefixo"] == "" and merged["cor"] == "accent" and merged["sombra"] is True


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda s: s["params"]["ate"].update(type="decimal"), "tipo desconhecido"),
        (lambda s: s["params"]["ate"].pop("label"), "rótulo em português"),
        (lambda s: s["params"]["ate"].pop("min"), "precisa de `min` e `max`"),
        (lambda s: s["params"]["prefixo"].pop("max_length"), "`text` precisa de `max_length`"),
        (lambda s: s["params"]["easing"].update(options=[]), "precisa de `options`"),
        (lambda s: s["params"]["de"].update(default=5e9), "o padrão não passa no próprio esquema"),
        (lambda s: s["params"]["ate"].update(default=3), "obrigatório não tem padrão"),
        (lambda s: s.update(size=[10, 10]), "`size` precisa ser"),
        (lambda s: s.update(example={}), "o `example` não passa"),
        (
            lambda s: s.update(
                caption_anchor={"word": "nao_existe", "occurrence": "de", "hold": "de", "margin": "de"}
            ),
            "não é um parâmetro",
        ),
    ],
)
def test_a_badly_written_schema_says_what_is_wrong(mutation, message):
    raw = json.loads((config.INFOGRAPHICS_DIR / "contador" / "esquema.json").read_text(encoding="utf-8"))
    mutation(raw)
    with pytest.raises(SchemaError, match=message):
        parse_schema("contador", raw)


# ---------- o atalho na spec ----------


def test_a_composition_names_exactly_one_of_src_or_infographic():
    assert HtmlOverlay.model_validate({"type": "html", "infographic": "contador"}).src is None
    assert HtmlOverlay.model_validate({"type": "html", "src": "comp"}).infographic is None
    with pytest.raises(ValidationError, match="um dos dois e não os dois"):
        HtmlOverlay.model_validate({"type": "html", "src": "comp", "infographic": "contador"})
    with pytest.raises(ValidationError, match="um dos dois e não os dois"):
        HtmlOverlay.model_validate({"type": "html"})


def test_a_project_saved_before_the_shortcut_loads_and_saves_the_same(tmp_path: Path):
    old = {
        "name": "antigo",
        "timeline": [{"type": "card", "flat": True, "duration": 4}],
        "overlays": [{"type": "html", "src": "comp", "start": 1, "end": 3, "data": {"a": 1}}],
    }
    project = Project.model_validate(old)
    saved = json.loads(project.model_dump_json(exclude_none=True))
    assert saved["overlays"][0] == {
        "type": "html", "src": "comp", "start": 1.0, "end": 3.0, "width": 1.0, "height": 1.0,
        "data": {"a": 1}, "files": {}, "layer": "front",
    }  # fmt: skip
    assert "infographic" not in saved["overlays"][0] and "anchor" not in saved["overlays"][0]


def test_an_anchored_composition_does_not_take_a_region_or_a_center():
    with pytest.raises(ValidationError, match="o lugar vem da palavra"):
        HtmlOverlay.model_validate(
            {"type": "html", "infographic": "grifo", "region": "topo", "anchor": {"word": "frio"}}
        )
    anchor = HtmlOverlay.model_validate(
        {"type": "html", "infographic": "grifo", "anchor": {"word": "frio", "hold": "palavra"}}
    ).anchor
    assert anchor is not None and anchor.hold == "word" and anchor.occurrence == 1 and anchor.margin == 24


def test_the_resolver_swaps_the_name_for_the_library_folder_and_merges_the_schema_defaults():
    project = _card_project(_infographic(data={"ate": 10000, "prefixo": "+ de R$"}))
    overlay = project.overlays[0]
    resolved = resolve_infographic(overlay, project)
    assert resolved.infographic is None and resolved.src == str(config.INFOGRAPHICS_DIR / "contador")
    assert resolved.data["ate"] == 10000 and resolved.data["prefixo"] == "+ de R$"
    assert resolved.data["duracao"] == 1.2 and resolved.data["easing"] == "suave" and resolved.data["de"] == 0
    assert overlay.infographic == "contador" and "duracao" not in overlay.data  # a spec original não muda
    assert resolve_infographic(HtmlOverlay.model_validate({"type": "html", "src": "x"}), project).src == "x"


def test_without_a_place_the_model_takes_its_own_area_and_with_a_region_it_takes_the_region():
    free = HtmlOverlay.model_validate({"type": "html", "infographic": "barra", "data": {"valor": 95}})
    area = find_infographic("barra").schema.area
    resolved = resolve_infographic(free, None)
    assert (resolved.x, resolved.y, resolved.width, resolved.height) == (
        area["x"], area["y"], area["width"], area["height"],
    )  # fmt: skip
    placed = HtmlOverlay.model_validate(
        {"type": "html", "infographic": "barra", "region": "topo", "data": {"valor": 95}}
    )
    assert resolve_infographic(placed, None).x is None  # a região (resolvida depois) é quem manda
    sized = HtmlOverlay.model_validate(
        {"type": "html", "infographic": "barra", "width": 0.5, "height": 0.1, "data": {"valor": 95}}
    )
    assert resolve_infographic(sized, None).width == 0.5


def test_the_resolver_refuses_an_unknown_model_and_invalid_parameters_with_the_message():
    unknown = HtmlOverlay.model_validate({"type": "html", "infographic": "pizza"})
    with pytest.raises(InfographicError, match="desconhecido: 'pizza' \\(modelos: barra, contador"):
        resolve_infographic(unknown, None)
    bad = HtmlOverlay.model_validate({"type": "html", "infographic": "contador", "data": {"ate": "dez mil"}})
    with pytest.raises(InfographicError, match="contador: `ate` precisa ser um número"):
        resolve_infographic(bad, None)


def test_a_file_parameter_is_served_under_the_files_prefix_and_must_exist(tmp_path: Path):
    (tmp_path / "foto.PNG").write_bytes(b"png")
    project = _card_project(_infographic("imagem", data={"arquivo": "foto.PNG"}))
    project.base_dir = tmp_path
    resolved = resolve_infographic(project.overlays[0], project)
    assert resolved.files == {"arquivo.png": str(tmp_path / "foto.PNG")}
    assert resolved.data["arquivo"] == "/_dmaker/files/arquivo.png"
    missing = _card_project(_infographic("imagem", data={"arquivo": "sumiu.png"}))
    missing.base_dir = tmp_path
    with pytest.raises(InfographicError, match="arquivo que não existe"):
        resolve_infographic(missing.overlays[0], missing)


def test_the_grifo_with_a_word_becomes_an_anchored_composition_without_a_place():
    overlay = HtmlOverlay.model_validate(
        {
            "type": "html",
            "infographic": "grifo",
            "data": {"palavra": "frio", "ocorrencia": 2, "permanencia": "palavra"},
        }
    )
    resolved = resolve_infographic(overlay, None)
    assert resolved.anchor is not None
    assert (resolved.anchor.word, resolved.anchor.occurrence, resolved.anchor.hold) == ("frio", 2, "word")
    assert (
        resolved.anchor.margin == 32 and resolved.x is None
    )  # o lugar vem da palavra, não da área do modelo
    free = resolve_infographic(HtmlOverlay.model_validate({"type": "html", "infographic": "grifo"}), None)
    assert free.anchor is None and free.x is not None


# ---------- a validação do projeto (validate_project e lint) ----------


def _warnings(project: Project) -> list[str]:
    return summarize(
        project, prober=lambda path: MediaInfo(path, 8.0, 1080, 1920, 30.0, True, True, False)
    ).warnings


def test_validate_project_points_at_text_in_place_of_a_number_with_the_field_path():
    project = _card_project(_infographic(data={"ate": "dez mil"}))
    warnings = [w for w in _warnings(project) if w.startswith("overlays[0]")]
    assert warnings == ["overlays[0].data.ate: precisa ser um número (veio o texto 'dez mil')"]


def test_validate_project_points_at_every_problem_of_every_infographic_with_its_own_path():
    project = _card_project(
        _infographic(data={"ate": 1}),
        _infographic("barra", data={"valor": 5000000000, "marcas": 99, "xis": 1}),
        _infographic("pizza"),
        _infographic("contador", data={}),
    )
    paths = [w.split(":")[0] for w in _warnings(project) if w.startswith("overlays")]
    assert paths == [
        "overlays[1].data.xis",
        "overlays[1].data.valor",
        "overlays[1].data.marcas",
        "overlays[2].infographic",
        "overlays[3].data.ate",
    ]
    unknown = next(w for w in _warnings(project) if w.startswith("overlays[2]"))
    assert "modelo desconhecido 'pizza'" in unknown and "contador" in unknown


def test_a_valid_infographic_project_validates_without_a_warning():
    assert [w for w in _warnings(_card_project(_infographic(data={"ate": 10000}))) if "overlays" in w] == []


def test_a_brand_that_forbids_dashes_catches_one_in_an_infographic_text():
    project = _card_project(_infographic(data={"ate": 1, "prefixo": "R$ — mais"}), brand="medlycare")
    warnings = [w for w in _warnings(project) if w.startswith("overlays[0]")]
    assert len(warnings) == 1 and "overlays[0].data.prefixo: contém travessão" in warnings[0]
    assert "MedlyCare" in warnings[0]


def test_a_missing_image_and_a_word_pinned_without_captions_are_warned():
    missing = _card_project(_infographic("imagem", data={"arquivo": "nao-existe.png"}))
    assert any(w.startswith("overlays[0].data.arquivo: arquivo não encontrado") for w in _warnings(missing))
    pinned = _card_project({"type": "html", "infographic": "grifo", "data": {"palavra": "frio"}, "start": 1})
    assert any("não tem legendas" in w for w in infographic_warnings(pinned, load_theme(None)))


def test_the_project_summary_warns_before_any_browser_is_opened():
    # o lint roda no `validate_project`, sem Chromium: é onde o valor fora do esquema aparece, e não no render
    project = _card_project(_infographic(data={"ate": "x"}))
    assert any("overlays[0].data.ate" in w for w in infographic_warnings(project, load_theme(None)))


# ---------- o pipeline com o renderizador falso ----------


def _pipeline_spec(*overlays: dict) -> dict:
    spec = _spec()
    spec["overlays"] = list(overlays)
    return spec


def test_the_pipeline_hands_the_renderer_an_ordinary_composition_with_the_defaults_and_the_brand(
    tmp_path: Path,
):
    spec = _pipeline_spec(_infographic(data={"ate": 10000, "prefixo": "+ de R$"}, start=1.0, end=4.0))
    spec["brand"] = "medlycare"
    _, _, renderer = _render(tmp_path, spec)

    [(composition, times)] = renderer.calls
    assert composition.source == config.INFOGRAPHICS_DIR / "contador"
    assert composition.data["ate"] == 10000 and composition.data["duracao"] == 1.2  # os padrões do esquema
    assert composition.colors["accent"] == "#75B9A2" and composition.font_family == "Poppins"
    assert composition.radius == 28.0  # os cantos da marca chegam à página
    assert composition.size == (1080, 960) and len(times) == 90  # a região "topo" do `_spec` e os 3 s


def test_the_cache_key_changes_with_the_brand_and_with_an_image_the_page_reads(tmp_path: Path):
    spec = _pipeline_spec(_infographic("imagem", data={"arquivo": "foto.png"}, start=0.0, end=1.0))

    def keys(brand: str | None, picture: bytes = b"a") -> set[str]:
        root = tmp_path / (brand or "sem-marca") / picture.decode()
        root.mkdir(parents=True, exist_ok=True)
        (root / "foto.png").write_bytes(picture)
        _render(root, {**spec, "brand": brand} if brand else spec)
        return {p.name for p in (root / "mez").glob("*_html.mov")}

    assert keys("medlycare").isdisjoint(keys(None))  # outra marca, outra camada (cores, fonte e cantos)
    assert keys("casamento-azul", b"a") != keys("casamento-azul", b"b")  # a imagem mudou: renderiza de novo
    assert keys("casamento-azul", b"a") == keys("casamento-azul", b"a")  # e a mesma imagem reaproveita


def test_the_page_receives_the_image_by_name_and_the_renderer_gets_the_file(tmp_path: Path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "foto.png").write_bytes(b"png")
    spec = _pipeline_spec(_infographic("imagem", data={"arquivo": "foto.png"}, start=0.0, end=1.0))
    _, _, renderer = _render(tmp_path, spec)
    composition = renderer.calls[0][0]
    assert composition.data["arquivo"] == "/_dmaker/files/arquivo.png"
    assert composition.files == {"arquivo.png": tmp_path / "foto.png"}


def test_the_render_stops_before_the_mezzanines_when_the_parameters_are_outside_the_schema(tmp_path: Path):
    spec = _pipeline_spec(_infographic(data={"ate": "dez mil"}))
    with pytest.raises(InfographicError, match="contador: `ate` precisa ser um número"):
        _render(tmp_path, spec)


def test_the_render_of_an_unknown_model_fails_with_the_list_of_models(tmp_path: Path):
    with pytest.raises(InfographicError, match="modelos: barra, contador"):
        _render(tmp_path, _pipeline_spec(_infographic("pizza")))


def test_a_project_without_infographics_renders_the_same_graph(tmp_path: Path):
    html = _spec({"start": 1.0, "end": 2.0})
    with_shortcut = _pipeline_spec(_infographic("etiqueta", data={"texto": "Oi"}, start=1.0, end=2.0))
    first, _, _ = _render(tmp_path / "a", html)
    second, _, _ = _render(tmp_path / "b", with_shortcut)
    assert first.warnings == second.warnings == []
    assert (first.job_dir / "graph.txt").read_text(encoding="utf-8").count("[html0]") == (
        second.job_dir / "graph.txt"
    ).read_text(encoding="utf-8").count("[html0]")


# ---------- o QA: a área da composição e a zona segura ----------


def _qa(project: Project):
    return check_html_safe_zone(project, _layout(project))


def test_the_qa_accepts_the_top_region_of_the_explainer_and_the_five_default_areas():
    ok = _card_project(
        *[
            _infographic(name, data=find_infographic(name).schema.example)
            for name in MODELS
            if name != "imagem"
        ]
    )
    assert _qa(ok) == []
    areas = [
        {
            "type": "html",
            "infographic": name,
            "data": find_infographic(name).schema.example,
            "start": 0,
            "end": 3,
        }
        for name in MODELS
        if name != "imagem"
    ]
    assert _qa(_card_project(*areas)) == []  # sem região, a área própria de cada modelo também está dentro


def test_the_qa_flags_a_composition_box_that_invades_the_area_covered_by_the_app():
    safe = get_preset("instagram/reels").safe
    low = _card_project(
        {
            "type": "html",
            "infographic": "contador",
            "data": {"ate": 1},
            "x": 0.5,
            "y": 0.9,
            "width": 0.8,
            "height": 0.1,
        }
    )
    [finding] = _qa(low)
    assert (
        finding.level == "aviso" and finding.where == "overlays[0]" and "interface do app" in finding.message
    )
    wide = _card_project(
        {"type": "html", "src": "comp", "x": 0.5, "y": 0.3, "width": 1.0, "height": 0.2, "start": 0}
    )
    assert [f.where for f in _qa(wide)] == ["overlays[0]"]  # 1080 de largura passa dos 60 px de margem
    assert safe.left == 60 and safe.right == 150


def test_the_qa_ignores_the_whole_frame_a_composition_that_is_pinned_and_a_broken_model():
    whole = _card_project({"type": "html", "src": "comp"})
    pinned = _card_project({"type": "html", "infographic": "grifo", "anchor": {"word": "x"}})
    broken = _card_project(_infographic(data={"ate": "x"}))
    assert _qa(whole) == _qa(pinned) == _qa(broken) == []


# ---------- adicionar ao projeto (serviço, CLI e MCP) ----------


def test_add_infographic_puts_the_composition_in_the_overlays_validated():
    project = _card_project()
    added = add_infographic(project, "contador", {"ate": 10000}, start=1, end=4, region="topo")
    overlay = added.overlays[-1]
    assert isinstance(overlay, HtmlOverlay)
    assert (overlay.infographic, overlay.region, overlay.start, overlay.end) == ("contador", "topo", 1, 4)
    assert overlay.data == {"ate": 10000} and project.overlays == []


def test_add_infographic_refuses_bad_values_an_unknown_model_and_an_unknown_region():
    project = _card_project()
    with pytest.raises(InfographicError, match="`ate` precisa ser um número"):
        add_infographic(project, "contador", {"ate": "dez mil"})
    with pytest.raises(InfographicError, match="desconhecido"):
        add_infographic(project, "pizza")
    with pytest.raises(Exception, match="região desconhecida"):
        add_infographic(project, "contador", {"ate": 1}, region="rodape")


def test_assignments_from_the_command_line_become_values_of_the_schema_types(counter):
    values = coerce_assignments(
        counter, ["ate=10000", "de=-2,5", "sombra=nao", "prefixo=+ de R$", "casas=2", "xis=ola"]
    )
    assert values == {
        "ate": 10000,
        "de": -2.5,
        "sombra": False,
        "prefixo": "+ de R$",
        "casas": 2,
        "xis": "ola",
    }
    assert coerce_assignments(counter, ["ate=dez"]) == {"ate": "dez"}  # quem diz que não é número é o esquema
    with pytest.raises(InfographicError, match="nome=valor"):
        coerce_assignments(counter, ["ate"])


def test_the_frame_service_checks_the_values_before_opening_any_browser():
    renderer = FakeHtmlRenderer()
    with pytest.raises(InfographicError, match="`ate` precisa ser um número"):
        infographic_frame("contador", Path("x.png"), params={"ate": "x"}, renderer=renderer)
    assert renderer.stills == []


def test_the_frame_service_renders_the_finished_model_at_its_natural_size(tmp_path: Path):
    renderer = FakeHtmlRenderer()
    frame = infographic_frame(
        "contador", tmp_path / "q.png", params={"ate": 10000}, brand="medlycare", renderer=renderer
    )
    [(composition, at)] = renderer.stills
    schema = find_infographic("contador").schema
    assert composition.size == schema.size and at == pytest.approx(schema.duration * 0.6)
    assert composition.data["ate"] == 10000 and composition.data["duracao"] == 1.2
    assert composition.colors["accent"] == "#75B9A2" and frame.path.exists()


def test_the_command_line_lists_the_models_and_the_parameters_of_one():
    runner = CliRunner()
    listing = runner.invoke(app, ["infographics", "list"])
    assert listing.exit_code == 0
    assert all(name in listing.output for name in MODELS)
    one = runner.invoke(app, ["infographics", "list", "contador"])
    assert one.exit_code == 0 and "ate" in one.output and "obrigat" in one.output and "easing" in one.output
    assert runner.invoke(app, ["infographics", "list", "pizza"]).exit_code == 1


def test_the_command_line_adds_an_infographic_to_a_saved_project(tmp_path: Path):
    from dmaker.pipeline.projects import save_project

    save_project(_card_project(), tmp_path / "explicativo")
    runner = CliRunner()
    spec = str(tmp_path / "explicativo" / "spec.json")
    result = runner.invoke(
        app,
        [
            "infographics",
            "add",
            spec,
            "contador",
            "-p",
            "ate=10000",
            "-p",
            "prefixo=+ de R$",
            "--region",
            "topo",
            "--start",
            "1",
            "--end",
            "4",
        ],
    )
    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / "explicativo" / "spec.json").read_text(encoding="utf-8"))
    assert saved["overlays"][-1]["infographic"] == "contador"
    assert saved["overlays"][-1]["data"] == {"ate": 10000, "prefixo": "+ de R$"}
    bad = runner.invoke(app, ["infographics", "add", spec, "contador", "-p", "ate=dez"])
    assert bad.exit_code == 1 and "precisa ser um número" in " ".join(bad.output.split())


def test_the_mcp_tools_list_the_schemas_and_add_to_the_project(tmp_path: Path):
    from dmaker import mcp_server
    from dmaker.pipeline.projects import save_project

    listed = mcp_server.list_infographics()
    assert [item["name"] for item in listed] == list(MODELS)
    assert all(item["params"] and item["description"] for item in listed)

    save_project(_card_project(), tmp_path / "explicativo")
    result = mcp_server.add_infographic(
        str(tmp_path / "explicativo" / "spec.json"),
        "barra",
        {"valor": 95, "maximo": 400},
        start=1,
        end=4,
        region="topo",
    )
    assert result["overlay_index"] == 0 and not any(w.startswith("overlays[0]") for w in result["warnings"])
    with pytest.raises(InfographicError, match="`valor` é obrigatório"):
        mcp_server.add_infographic(str(tmp_path / "explicativo" / "spec.json"), "barra", {})


# ---------- a API da interface ----------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from dmaker.ui import server

    return TestClient(server.app)


def test_the_api_lists_the_models_with_their_schema(client):
    body = client.get("/api/infographics").json()
    assert [item["name"] for item in body["infographics"]] == list(MODELS)
    counter = body["infographics"][1]
    assert counter["params"][1]["name"] == "ate" and counter["params"][1]["required"] is True


def test_the_api_answers_404_for_an_unknown_model_and_422_for_values_outside_the_schema(client):
    assert client.get("/api/infographics/pizza/preview").status_code == 404
    assert client.post("/api/infographics/pizza/frame", json={"params": {}}).status_code == 404
    bad = client.post("/api/infographics/contador/frame", json={"params": {"ate": "dez mil"}})
    assert bad.status_code == 422 and "`ate` precisa ser um número" in bad.json()["detail"]
    assert client.get("/api/infographics/contador/preview?brand=nao-existe").status_code == 404


def test_the_example_values_of_a_file_parameter_point_into_the_model_folder():
    from dmaker.ui.infographic_routes import example_params

    model = find_infographic("imagem")
    example = example_params(model)
    assert Path(example["arquivo"]) == model.folder / "exemplo.png" and Path(example["arquivo"]).is_file()


def test_the_api_frame_calls_the_same_service_and_caches_by_content(client, monkeypatch, tmp_path: Path):
    from dmaker.ui import infographic_routes as routes

    calls: list[dict] = []

    class OpenRenderer:
        def unavailable_reason(self):
            return None

    def fake_frame(name, out, **kwargs):
        calls.append({"name": name, **kwargs})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(routes, "PlaywrightHtmlRenderer", OpenRenderer)
    monkeypatch.setattr(routes, "infographic_frame", fake_frame)
    first = client.post(
        "/api/infographics/contador/frame", json={"params": {"ate": 95}, "at": 1.5, "brand": "medlycare"}
    )
    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    assert first.content.startswith(b"\x89PNG")
    client.post(
        "/api/infographics/contador/frame", json={"params": {"ate": 95}, "at": 1.5, "brand": "medlycare"}
    )
    client.post(
        "/api/infographics/contador/frame", json={"params": {"ate": 96}, "at": 1.5, "brand": "medlycare"}
    )
    assert len(calls) == 2  # o segundo pedido igual veio do cache; o de outro valor, não
    assert calls[0]["params"] == {"ate": 95} and calls[0]["at"] == 1.5 and calls[0]["brand"] == "medlycare"


def test_the_api_says_how_to_install_the_browser_when_it_is_missing(client, monkeypatch):
    from dmaker.ui import infographic_routes as routes

    class NoBrowser:
        def unavailable_reason(self):
            return "rode dmaker setup --html"

    monkeypatch.setattr(routes, "PlaywrightHtmlRenderer", NoBrowser)
    answer = client.post("/api/infographics/etiqueta/frame", json={"params": {"texto": "Oi"}})
    assert answer.status_code == 503 and "dmaker setup --html" in answer.json()["detail"]


# ---------- o modelo "explicativo" fecha o épico ----------


def test_a_topic_with_an_infographic_becomes_an_html_overlay_during_the_topic(tmp_path: Path):
    from dmaker.domain.templates import find_template, render_template

    template = find_template("explicativo")
    topics = [
        {"fim": 20, "infografico": {"nome": "contador", "parametros": {"ate": 10000, "prefixo": "+ de R$"}}},
        {"fim": 40, "imagem": "C:/imagens/a.png"},
        {"fim": 60, "infografico": {"nome": "barra"}},
    ]
    spec = render_template(
        template, {"gravacao": str(tmp_path / "rosto.mp4"), "assuntos": topics, "legendas": False}
    )
    html = [overlay for overlay in spec["overlays"] if overlay["type"] == "html"]
    assert html == [
        {"type": "html", "infographic": "contador", "data": {"ate": 10000, "prefixo": "+ de R$"}, "region": "topo", "start": 0.0, "end": 20.0},
        {"type": "html", "infographic": "barra", "data": {}, "region": "topo", "start": 40.0, "end": 60.0},
    ]  # fmt: skip
    assert [overlay["type"] for overlay in spec["overlays"]] == ["video", "image", "html", "html"]
    project = Project.model_validate({**spec, "name": "x"})
    assert sum(isinstance(overlay, HtmlOverlay) for overlay in project.overlays) == 2


def test_the_explainer_checks_the_shape_of_the_infographic_of_each_topic():
    from dmaker.domain.explainer import plan_topics

    with pytest.raises(ValueError, match="assunto 1: `infografico` precisa ser um objeto"):
        plan_topics([{"fim": 5, "infografico": "contador"}])
    with pytest.raises(ValueError, match="assunto 1: `infografico` precisa de `nome`"):
        plan_topics([{"fim": 5, "infografico": {"parametros": {}}}])
    with pytest.raises(ValueError, match="campo\\(s\\) desconhecido\\(s\\): cor"):
        plan_topics([{"fim": 5, "infografico": {"nome": "contador", "cor": "x"}}])
    with pytest.raises(ValueError, match="`infografico.parametros` precisa ser um objeto"):
        plan_topics([{"fim": 5, "infografico": {"nome": "contador", "parametros": [1]}}])
    [topic] = plan_topics([{"fim": 5, "infografico": {"nome": " barra "}}])
    assert topic["infografico"] == {"nome": "barra", "parametros": {}}
    assert plan_topics([{"fim": 5}])[0]["infografico"] is None


def test_the_explainer_values_outside_the_schema_show_up_in_validate_project(tmp_path: Path):
    from dmaker.domain.templates import find_template, render_template

    topics = [{"fim": 20, "infografico": {"nome": "contador", "parametros": {"ate": "dez mil"}}}]
    spec = render_template(
        find_template("explicativo"),
        {"gravacao": str(tmp_path / "r.mp4"), "assuntos": topics, "legendas": False},
    )
    project = Project.model_validate({**spec, "name": "x"})
    index = next(i for i, overlay in enumerate(project.overlays) if isinstance(overlay, HtmlOverlay))
    assert any(
        w.startswith(f"overlays[{index}].data.ate:") for w in infographic_warnings(project, load_theme(None))
    )
