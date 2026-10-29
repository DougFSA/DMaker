"""A documentação, as licenças e os arquivos de apoio dos infográficos prontos (DMK-24): o guia, o manual gerado, a
skill, a atribuição dos emojis e o que a origem falsa serve à página (a biblioteca do grifo, os emojis, os arquivos do
projeto e as fontes da marca)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker import config
from dmaker.domain.brand import load_theme
from dmaker.domain.infographics import find_infographic, load_infographics
from dmaker.manual import files
from dmaker.manual.markers import read_generated
from dmaker.manual.reference_infographics import infographic_section, infographics_reference
from dmaker.media import fonts, html_site
from dmaker.media.html_render import HtmlComposition, runtime_script
from dmaker.pipeline.html_layer import brand_font_faces, brand_page_fields
from dmaker.pipeline.infographics import describe_infographics

DASHES = ("—", "–")
GUIDE = config.PACKAGE_DIR / "resources" / "guide.md"
SKILL = config.ROOT / ".claude" / "skills" / "dmaker" / "SKILL.md"


def guide_section() -> str:
    guide = GUIDE.read_text(encoding="utf-8")
    start = guide.index("### Infográficos prontos")
    return guide[start : guide.index("\n## ", start)]


# ---------- o guia e a skill ----------


def test_the_guide_lists_every_model_the_shortcut_the_schema_the_tools_and_how_to_write_a_new_one():
    section = guide_section()
    for name in load_infographics():
        assert f"`{name}`" in section, f"o guia não descreve o modelo {name}"
    for term in (
        '"infographic": "contador"',
        "`infographic` **ou** `src`",
        "`esquema.json`",
        "`min`",
        "`max_length`",
        "`options`",
        "list_infographics",
        "add_infographic",
        "render_infographic_frame",
        "dmaker infographics",
        "`anchor`",
        "`files`",
        "`infografico`",
        "overlays[2].data.ate",
        "Animated Noto Emoji, Google, CC BY 4.0",
        '"use o contador para 95 mg"'.replace('"use', "Use").replace('mg"', "mg"),
    ):
        assert term in section, f"o guia de infográficos não traz: {term}"
    assert not any(dash in section for dash in DASHES)


def test_the_guide_contract_names_the_new_brand_variables_and_libraries():
    guide = GUIDE.read_text(encoding="utf-8")
    for term in (
        "var(--dm-radius)",
        "--dm-font-script",
        "rough-notation.js",
        "/_dmaker/emoji/",
        "/_dmaker/files/",
    ):
        assert term in guide


def test_the_skill_gives_the_infographic_example_and_stays_under_its_size_limit():
    text = SKILL.read_text(encoding="utf-8")
    assert "use o contador para 95 mg" in text and "list_infographics" in text and "add_infographic" in text
    assert len(text.encode("utf-8")) < 6_000 and not any(dash in text for dash in DASHES)
    # as regras que a skill já tinha continuam todas lá
    for rule in (
        "Nunca travessão",
        "medlycare.com.br",
        "nunca o Python global",
        "nunca chute duração",
        "autocut",
    ):
        assert rule in text


# ---------- o manual gerado dos esquemas ----------


def test_the_manual_table_has_a_row_for_every_parameter_of_every_model_and_is_generated_from_the_schemas():
    block = read_generated(files.read_manual(), "infograficos")
    assert block is not None
    for model in describe_infographics():
        assert f"#### `{model['name']}`" in block
        for param in model["params"]:
            assert f"| `{param['name']}` |" in block, f"{model['name']}.{param['name']} falta no manual"
    assert "overlays[2].data.ate" in block and not any(dash in block for dash in DASHES)


def test_the_reference_generator_writes_types_defaults_limits_and_options():
    model = {
        "name": "pizza",
        "title": "Pizza",
        "description": "Uma fatia por vez.",
        "size": [900, 300],
        "duration": 4.0,
        "anchors_to_caption": True,
        "params": [
            {"name": "fatias", "type": "integer", "label": "Fatias", "required": True, "min": 1, "max": 12},
            {
                "name": "massa",
                "type": "choice",
                "label": "Massa",
                "required": False,
                "default": "fina",
                "options": ["fina", "grossa"],
            },
            {
                "name": "legenda",
                "type": "text",
                "label": "Legenda",
                "description": "Com | barra",
                "required": False,
                "default": "",
                "max_length": 20,
            },
            {"name": "ativo", "type": "bool", "label": "Ativo", "required": False, "default": True},
            {"name": "cor", "type": "color", "label": "Cor", "required": False, "default": "accent"},
            {
                "name": "peso",
                "type": "number",
                "label": "Peso",
                "required": False,
                "min": 0.5,
                "max": 2000000000.0,
            },
        ],
    }
    text = infographic_section(model)
    assert "#### `pizza`: Pizza" in text and "900x300 px" in text and "duração sugerida: 4 s" in text
    assert "Prende-se a uma palavra da legenda" in text
    assert "| `fatias` | inteiro | obrigatório | de 1 a 12 | Fatias |" in text
    assert "| `massa` | uma opção | `fina` | `fina`, `grossa` | Massa |" in text
    assert "| `legenda` | texto | vazio | até 20 caracteres | Legenda. Com \\| barra |" in text
    assert "| `ativo` | sim ou não | `sim` |  | Ativo |" in text
    assert "| `cor` | cor | `accent` | `#RRGGBB` ou uma cor da marca | Cor |" in text
    assert "| `peso` | número | vazio | de 0.5 a 2000000000 | Peso |" in text
    assert infographics_reference([]) == "Nenhum infográfico pronto nesta instalação."
    assert infographics_reference([model]).startswith("São 1 modelos: `pizza`.")


# ---------- licenças e arquivos de apoio ----------


def test_third_party_registers_the_two_new_libraries_with_the_license_and_the_attribution():
    text = (config.ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "## rough-notation" in text and "0.5.1" in text and "npm pack rough-notation@0.5.1" in text
    assert "LICENSE-rough-notation.txt" in text and "Preet Shihn" in text
    assert "## Animated Noto Emoji (Google)" in text and "CC BY 4.0" in text
    assert "https://creativecommons.org/licenses/by/4.0/" in text and "atribuição" in text
    assert "Animated Noto Emoji, Google, CC BY 4.0" in text and not any(dash in text for dash in DASHES)
    assert (
        (config.HTML_ASSETS_DIR / "LICENSE-rough-notation.txt")
        .read_text(encoding="utf-8")
        .startswith("MIT License")
    )
    assert (config.HTML_ASSETS_DIR / "rough-notation.js").stat().st_size > 5_000


def test_every_emoji_the_schema_offers_has_a_lottie_file_and_the_credit_file_lists_them():
    options = find_infographic("emoji").schema.params["emoji"].options
    assert len(options) == 10
    credit = (config.HTML_ASSETS_DIR / "emoji" / "ATRIBUICAO.md").read_text(encoding="utf-8")
    assert "CC BY 4.0" in credit and "Google" in credit and "nenhuma no conteúdo" in credit.lower()
    for name in options:
        animation = json.loads(
            (config.HTML_ASSETS_DIR / "emoji" / f"{name}.json").read_text(encoding="utf-8")
        )
        assert animation["w"] > 0 and animation["op"] > animation["ip"] and animation["layers"], name
        assert f"`{name}.json`" in credit, f"{name} não está na lista de atribuição"
    assert not any(dash in credit for dash in DASHES)


# ---------- o que a origem falsa serve ----------


@pytest.fixture
def site(tmp_path: Path):
    folder = tmp_path / "comp"
    folder.mkdir()
    (folder / "index.html").write_text("<p>oi</p>", encoding="utf-8")
    image = tmp_path / "fora" / "foto.png"
    image.parent.mkdir()
    image.write_bytes(b"png")
    secret = tmp_path / "segredo.txt"
    secret.write_text("nao", encoding="utf-8")
    return html_site.CompositionSite(folder, files={"foto.png": image}), secret


def test_the_page_can_load_the_grifo_library_and_the_emojis_but_not_an_undeclared_file(site):
    served, secret = site
    rough = served.lookup("/_dmaker/rough-notation.js")
    assert (
        rough is not None
        and rough.content_type.startswith("text/javascript")
        and b"RoughNotation" in rough.body
    )
    emoji = served.lookup("/_dmaker/emoji/joinha.json")
    assert emoji is not None and emoji.content_type.startswith("application/json")
    assert json.loads(emoji.body)["layers"]
    assert served.lookup("/_dmaker/emoji/nao-existe.json") is None
    assert served.lookup("/_dmaker/files/segredo.txt") is None
    assert served.lookup(f"/_dmaker/files/{secret}") is None  # nunca um caminho do disco


def test_a_project_file_declared_by_the_composition_is_served_by_name_only(site):
    served, _ = site
    photo = served.lookup("/_dmaker/files/foto.png")
    assert photo is not None and photo.body == b"png" and photo.content_type == "image/png"
    assert (
        served.lookup("/_dmaker/files/../foto.png") is None
        and served.lookup("/_dmaker/files/outra.png") is None
    )


# ---------- a marca que chega à página ----------


def test_the_brand_css_carries_the_radius_and_the_role_fonts():
    css = html_site.brand_css({"accent": "#75B9A2"}, "Poppins", 28.0, {"script": "dm-script"})
    assert "--dm-accent:#75B9A2" in css and "--dm-radius:28px" in css
    assert '--dm-font-script:"dm-script","Poppins",sans-serif' in css
    assert "--dm-radius" not in html_site.brand_css({}, "Poppins")  # os chamadores antigos saem iguais


def test_poppins_brands_serve_the_poppins_and_only_add_the_role_fonts_of_the_brand():
    assert brand_font_faces(load_theme("medlycare")) == ()  # a Poppins de assets/fonts já cobre tudo
    faces = brand_font_faces(load_theme("casamento-azul"))
    roles = {face.family for face in faces}
    assert {"dm-script", "dm-date"} <= roles and all(face.path.is_file() for face in faces)
    page = HtmlComposition(
        source=config.INFOGRAPHICS_DIR / "contador",
        size=(900, 300),
        **brand_page_fields(load_theme("casamento-azul")),
    )
    script = runtime_script(page)
    assert 'font-family:\\"Poppins\\"' in script or "Poppins" in script  # a Poppins continua servida
    assert "dm-script" in script and "--dm-font-script" in script and "--dm-radius:28px" in script
    assert "/_dmaker/files/font-0.ttf" in script


def test_a_brand_with_another_family_gets_that_family_instead_of_the_poppins():
    windows = config.WINDOWS_FONTS_DIR / "arial.ttf"
    if not windows.exists():
        pytest.skip("a Arial do Windows não está nesta máquina")
    theme = load_theme("medlycare", {"fonts": {"family": "Arial"}})
    faces = brand_font_faces(theme)
    assert {face.family for face in faces} == {"Arial"} and {face.weight for face in faces} >= {400, 700}
    assert all(face.path.name in ("arial.ttf", "ariali.ttf", "arialbd.ttf") for face in faces)
    script = runtime_script(
        HtmlComposition(
            source=config.INFOGRAPHICS_DIR / "contador", size=(900, 300), **brand_page_fields(theme)
        )
    )
    assert '--dm-font:\\"Arial\\",sans-serif' in script or '--dm-font:"Arial"' in script
    assert "Poppins-" not in script  # a Poppins não é mandada no lugar da família da marca


def test_the_brand_corner_radius_follows_the_brand_setting():
    assert brand_page_fields(load_theme("medlycare"))["radius"] == 28.0
    assert brand_page_fields(load_theme(None, {"style": {"rounded_box_radius": 60}}))["radius"] == 60.0


def test_font_metrics_used_by_the_caption_layout_follow_the_libass_cell():
    ref = fonts.resolve("Poppins", "bold")
    left, top, right, bottom = fonts.ink_box("Hg", ref, 100)
    assert left == pytest.approx(0, abs=1) and top < -30 and bottom > 5  # acima e abaixo da linha de base
    assert right == pytest.approx(fonts.measure_rendered("Hg", ref, 100)[0], rel=0.01)
    ascent = fonts.baseline_offset(ref, 100)
    assert 50 < ascent < 70  # a linha de base fica a pouco mais da metade da célula (winAscent 1,05 de 1,76)
