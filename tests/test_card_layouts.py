"""Cartões definidos por layout no brand.json (fundo em imagem + elementos de texto/imagem)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from dmaker.domain.brand import Theme, load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import CardSegment, Project
from dmaker.media import fonts
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.context import RenderContext, RenderOptions
from dmaker.pipeline.lint import lint
from dmaker.pipeline.segments import CardPreparer
from dmaker.visuals.card_layouts import render_layout_card

pytestmark = pytest.mark.skipif(
    not fonts.family_available("Poppins"), reason="Poppins não disponível para testar fontes de layout"
)


def _make_theme(tmp_path: Path) -> Theme:
    """Tema mínimo em tmp_path: fundo branco liso e o papel "script" apontando para Poppins
    (dispensa uma fonte cursiva real só para testar a mecânica do layout)."""
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    shutil.copy(fonts.fontsdir() / "Poppins-Regular.ttf", fonts_dir / "script.ttf")
    Image.new("RGB", (1920, 1080), "white").save(tmp_path / "bg.png")
    brand = {
        "name": "Marca de teste",
        "fonts": {"family": "Poppins", "files": {"script": "script.ttf"}},
        "card_layouts": {},
    }
    (tmp_path / "brand.json").write_text(json.dumps(brand), encoding="utf-8")
    return load_theme(str(tmp_path / "brand.json"))


def _ink_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Retângulo que envolve todo pixel que não é o fundo branco (o texto/imagem desenhados)."""
    return ImageChops.invert(img.convert("L")).getbbox()


def test_text_interpolated_and_omitted_when_empty(tmp_path):
    theme = _make_theme(tmp_path)
    theme.card_layouts["texto"] = {
        "background": "bg.png",
        "elements": [
            {
                "kind": "text",
                "text": "{{titulo}}",
                "font": "script",
                "size": 120,
                "y": 100,
                "color": "#000000",
            },
            {
                "kind": "text",
                "text": "{{vazio}}",
                "font": "script",
                "size": 120,
                "y": 500,
                "color": "#000000",
            },
        ],
    }
    img = render_layout_card(theme, "texto", {"titulo": "Ola", "vazio": ""}, 1920, 1080)
    bbox = _ink_bbox(img)
    assert bbox is not None
    # só o primeiro texto (perto de y=100) tem tinta; o segundo (interpolado para vazio) foi omitido
    assert bbox[3] < 400


def test_lines_with_four_items_becomes_two_lines(tmp_path):
    theme = _make_theme(tmp_path)
    theme.card_layouts["nomes"] = {
        "background": "bg.png",
        "elements": [
            {
                "kind": "lines",
                "field": "nomes",
                "font": "script",
                "size": 60,
                "y": 500,
                "line_gap": 100,
                "per_line": 2,
                "join": " e ",
            }
        ],
    }
    fields = {"nomes": ["Ana e Bia", "Caio e Dara", "Eva e Fabio", "Gil e Hilda"]}
    img = render_layout_card(theme, "nomes", fields, 1920, 1080)
    bbox = _ink_bbox(img)
    assert bbox is not None
    # duas linhas (uma por par de nomes): a tinta cobre uma faixa maior que uma linha só, mas bem
    # menor que as quatro linhas que sairiam se cada nome virasse sua própria linha
    assert bbox[1] >= 480
    assert 550 < bbox[3] < 780


def test_lines_single_item_uses_single_size_and_y(tmp_path):
    theme = _make_theme(tmp_path)
    theme.card_layouts["nome_unico"] = {
        "background": "bg.png",
        "elements": [
            {
                "kind": "lines",
                "field": "nomes",
                "font": "script",
                "size": 60,
                "y": 700,
                "line_gap": 100,
                "per_line": 2,
                "single_size": 140,
                "single_y": 300,
            }
        ],
    }
    img = render_layout_card(theme, "nome_unico", {"nomes": ["Casal Único"]}, 1920, 1080)
    bbox = _ink_bbox(img)
    assert bbox is not None
    # usou single_y (perto de 300), não o y padrão (700) de quando há várias linhas
    assert bbox[1] < 450


def test_blocks_omits_empty_block(tmp_path):
    theme = _make_theme(tmp_path)
    theme.card_layouts["creditos"] = {
        "background": "bg.png",
        "elements": [
            {
                "kind": "blocks",
                "title_font": "script",
                "text_font": "script",
                "title_size": 40,
                "text_size": 30,
                "title_gap": 50,
                "line_gap": 40,
                "block_gap": 30,
                "center_y": False,
                "y": 200,
                "items": [
                    {"title": "Vazio", "text": "{{vazio}}"},
                    {"title": "Preenchido", "text": "{{preenchido}}"},
                ],
            }
        ],
    }
    img = render_layout_card(theme, "creditos", {"vazio": "", "preenchido": "Conteúdo"}, 1920, 1080)
    bbox = _ink_bbox(img)
    assert bbox is not None
    # o bloco vazio foi omitido: "Preenchido" é o primeiro e único bloco, colado em y=200; se o
    # vazio tivesse sido desenhado, o começo da tinta ficaria bem mais abaixo
    assert bbox[1] < 260


def test_image_multiply_darkens_only_where_logo_has_ink(tmp_path):
    theme = _make_theme(tmp_path)
    logo = Image.new("RGBA", (40, 40), (255, 255, 255, 255))
    ImageDraw.Draw(logo).rectangle([10, 10, 29, 29], fill=(0, 0, 0, 255))
    logo.save(theme.base_dir / "logo.png")
    theme.card_layouts["logo_teste"] = {
        "background": "bg.png",
        "elements": [
            {"kind": "image", "src": "logo.png", "width": 40, "x": 100, "y": 100, "blend": "multiply"}
        ],
    }
    img = render_layout_card(theme, "logo_teste", {}, 1920, 1080)
    assert img.getpixel((115, 115)) == (0, 0, 0)  # dentro do quadrado preto do logo: escurecido
    assert img.getpixel((101, 101)) == (255, 255, 255)  # canto branco do logo: fundo preservado
    assert img.getpixel((500, 500)) == (255, 255, 255)  # fora do logo: fundo preservado


def test_scale_to_half_size_keeps_proportions(tmp_path):
    theme = _make_theme(tmp_path)
    theme.card_layouts["escala"] = {
        "background": "bg.png",
        "elements": [
            {
                "kind": "text",
                "text": "{{titulo}}",
                "font": "script",
                "size": 200,
                "y": 400,
                "color": "#000000",
            }
        ],
    }
    fields = {"titulo": "Ola"}
    full = render_layout_card(theme, "escala", fields, 1920, 1080)
    half = render_layout_card(theme, "escala", fields, 960, 540)
    assert full.size == (1920, 1080)
    assert half.size == (960, 540)
    bbox_full = _ink_bbox(full)
    bbox_half = _ink_bbox(half)
    assert bbox_full is not None and bbox_half is not None
    for full_coord, half_coord in zip(bbox_full, bbox_half, strict=True):
        assert abs(half_coord - full_coord / 2) <= 4


def test_dash_in_fields_appears_in_lint():
    project = Project(
        name="t",
        timeline=[CardSegment(layout="abertura", fields={"igreja": "Matriz — Centro"}, duration=1.0)],
    )
    assert ("timeline[0].fields.igreja", "Matriz — Centro") in project.texts()

    theme = load_theme("pascom-sjb")  # rules.no_dash = true
    preset = get_preset("youtube/video")
    warnings = lint(project, theme, preset, total=1.0, durations=[1.0], infos=[None])
    assert any("travessão" in w for w in warnings)


def test_list_field_values_are_not_checked_by_lint():
    project = Project(
        name="t",
        timeline=[CardSegment(layout="abertura", fields={"nomes": ["Fulano — Beltrano"]}, duration=1.0)],
    )
    assert not any("nomes" in where for where, _ in project.texts())


def test_card_preparer_with_layout_renders_png_and_cache_key_changes_with_field(tmp_path):
    theme = _make_theme(tmp_path)
    theme.card_layouts["abertura"] = {
        "background": "bg.png",
        "elements": [
            {"kind": "text", "text": "{{data}}", "font": "script", "size": 100, "y": 100, "color": "#000000"}
        ],
    }
    preset = get_preset("youtube/video")

    def _prepare(data: str, cache_dir: Path):
        cache_dir.mkdir(parents=True, exist_ok=True)
        project = Project(
            name="t",
            timeline=[CardSegment(layout="abertura", fields={"data": data}, duration=1.0, motion="none")],
        )
        ctx = RenderContext(
            project=project,
            options=RenderOptions(),
            theme=theme,
            preset=preset,
            fps=30,
            job_dir=cache_dir,
            cache_dir=cache_dir,
            runner=RecordingRunner(),
            prober=lambda p: None,
        )
        return CardPreparer().prepare(0, project.timeline[0], None, ctx)

    prepared1 = _prepare("15.08.2026", tmp_path / "cache1")
    prepared2 = _prepare("16.08.2026", tmp_path / "cache2")

    pngs = list((tmp_path / "cache1").glob("*_card.png"))
    assert len(pngs) == 1
    with Image.open(pngs[0]) as img:
        assert img.size == (preset.width, preset.height)
    assert prepared1.mezzanine.name != prepared2.mezzanine.name  # o campo mudou, a chave também


def test_pascom_sjb_brand_layouts_load_and_render():
    theme = load_theme("pascom-sjb")
    assert set(theme.card_layouts) == {"abertura", "creditos", "encerramento"}

    abertura = render_layout_card(
        theme,
        "abertura",
        {
            "data": "15.08.2026",
            "titulo": "Casamento Comunitário",
            "nomes": [
                "Daniel & Bruna",
                "Matheus & Gabriele",
                "Antônio Carlos & Giovana",
                "Luis Carlos & Débora",
            ],
            "igreja": "Matriz da Paróquia São João Batista",
            "cidade": "Amparo-SP",
        },
        1920,
        1080,
    )
    assert abertura.size == (1920, 1080)

    creditos = render_layout_card(
        theme,
        "creditos",
        {
            "celebrante": "Pe. Reginaldo Aparecido Grilo",
            "diacono": "Jorge Márcio Alves",
            "cerimonial": "Pastoral da Família",
            "musicos": "Rodrigo Arantes, Cláudio Diogo Rodrigues,\nIvan Lorandi e Eliana Lorandi",
        },
        1920,
        1080,
    )
    assert creditos.size == (1920, 1080)

    encerramento = render_layout_card(theme, "encerramento", {}, 1920, 1080)
    assert encerramento.size == (1920, 1080)
