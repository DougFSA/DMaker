"""Caixa de cada sobreposição (`pipeline/overlay_boxes.py`): a conta única da interface e do QA, que chama as
mesmas funções do render. Régua de texto fixa e sonda falsa, sem ffmpeg."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import SafeZone, get_preset
from dmaker.domain.spec import ImageOverlay, Project, TextOverlay, VideoOverlay
from dmaker.filtergraph.common import Inputs
from dmaker.filtergraph.expressions import evaluate
from dmaker.filtergraph.overlays import (
    ResolvedImageOverlay,
    image_overlay_graph,
    image_overlay_origin,
    image_overlay_size,
    overlay_position,
)
from dmaker.filtergraph.pip import ResolvedVideoOverlay, pip_origin, pip_position, pip_size
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.overlay_boxes import OverlayBox, overlay_boxes, sides_outside_safe_zone
from dmaker.text.ass import AssDoc
from dmaker.text.overlays import Canvas, add_text_overlay, layout_text_overlay

REELS = get_preset("instagram/reels")  # 1080x1920, zona segura 220 / 420 / 60 / 150
W, H = REELS.width, REELS.height
THEME = load_theme(None, None)
SAFE = REELS.safe


def fixed_ruler(text: str, ref, size: float, spacing: float = 0) -> tuple[float, float]:
    """Cada caractere mede 0,5 do corpo: o texto tem largura previsível sem depender da fonte."""
    return len(text) * size * 0.5 + spacing * len(text), size


def media_info(path: Path, width: int = 400, height: int = 300) -> MediaInfo:
    return MediaInfo(path, 5.0, width, height, 30.0, True, True, False)


def make_prober(sizes: dict[str, tuple[int, int]] | None = None):
    sizes = sizes or {}

    def prober(path: Path) -> MediaInfo:
        return media_info(path, *sizes.get(path.name, (400, 300)))

    return prober


def make_project(tmp_path: Path, overlays: list[dict], **extra) -> Project:
    for name in ("logo.png", "cam.mp4", "comp.html"):
        (tmp_path / name).write_bytes(b"x")
    spec = {
        "name": "caixas",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "cam.mp4", "start": 0, "end": 4}],
        "overlays": overlays,
        **extra,
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


def boxes_of(project: Project, prober=None, kinds=None) -> list[OverlayBox]:
    return overlay_boxes(
        project, REELS, THEME, prober or make_prober(), measure=fixed_ruler, kinds=kinds
    ).boxes


def one_box(tmp_path: Path, overlay: dict, prober=None, **extra) -> OverlayBox:
    (box,) = boxes_of(make_project(tmp_path, [overlay], **extra), prober)
    return box


# ---------- as contas puras ----------


def test_evaluate_runs_the_expressions_the_overlay_filter_gets():
    names = {"W": 1080, "H": 1920, "w": 270, "h": 200}
    for position in ("top-left", "top-right", "bottom-left", "bottom-right", "top", "bottom", "center"):
        x, y = overlay_position(position, W, H, 40, SAFE)
        assert isinstance(evaluate(x, names), float) and isinstance(evaluate(y, names), float)
    assert evaluate("W-w-190", names) == 1080 - 270 - 190
    assert evaluate("(W-w)/2", names) == 405
    assert evaluate("302.40-w/2", names) == pytest.approx(167.4)
    assert evaluate("-3+2*4", names) == 5


@pytest.mark.parametrize("expression", ["__import__('os')", "W**2", "abs(W)", "foo+1", "W-", "1 if W else 2"])
def test_evaluate_refuses_anything_that_is_not_plain_arithmetic(expression):
    with pytest.raises(ValueError):
        evaluate(expression, {"W": 1080})


def test_sides_outside_safe_zone_has_a_one_pixel_slack():
    inside = (SAFE.left, SAFE.top, W - SAFE.left - SAFE.right, H - SAFE.top - SAFE.bottom)
    assert sides_outside_safe_zone(inside, W, H, SAFE) == ()
    assert sides_outside_safe_zone((60 - 1, 220, 100, 100), W, H, SAFE) == ()  # 1 px de folga
    assert sides_outside_safe_zone((60 - 2, 220, 100, 100), W, H, SAFE) == ("left",)
    assert sides_outside_safe_zone((60, 220 - 2, 100, 100), W, H, SAFE) == ("top",)
    assert sides_outside_safe_zone((900, 400, 100, 100), W, H, SAFE) == ("right",)  # passa de 930
    assert sides_outside_safe_zone((400, 1500, 100, 100), W, H, SAFE) == ("bottom",)  # passa de 1500
    assert sides_outside_safe_zone((0, 0, W, H), W, H, SAFE) == ("top", "bottom", "left", "right")


def test_sides_outside_safe_zone_without_a_zone_never_complains():
    assert sides_outside_safe_zone((0, 0, W, H), W, H, SafeZone()) == ()


# ---------- texto ----------


def box_event_position(doc: AssDoc) -> tuple[int, float, float]:
    """(alinhamento, x, y) do evento da caixa de fundo, o primeiro com desenho vetorial."""
    event = next(e for e in doc.events if "\\p1" in e.text)
    an, x, y = re.search(r"\\an(\d)\\pos\(([\d.-]+),([\d.-]+)\)", event.text).groups()
    return int(an), float(x), float(y)


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_text_area_is_where_the_render_puts_the_background_box(align):
    """A caixa que a interface mostra é a que o ASS desenha: mesma âncora, mesmo alinhamento, mesmo tamanho."""
    overlay = TextOverlay(
        text="Titulo do video aqui",
        role="title",
        x=0.5,
        y=0.3,
        start=0,
        end=3,
        style={"box": True, "align": align},
    )
    canvas = Canvas(W, H, SAFE, THEME, 3.0)
    left, top, width, height = layout_text_overlay(
        canvas, overlay
    ).area()  # com a régua do libass, a do render
    doc = AssDoc(W, H, "t")
    add_text_overlay(doc, canvas, overlay, 0)
    an, x, y = box_event_position(doc)
    drawn_left = {4: x, 5: x - width / 2, 6: x - width}[an]
    assert drawn_left == pytest.approx(left, abs=0.5)  # o `\pos` do ASS vai arredondado
    assert y - height / 2 == pytest.approx(top, abs=0.5)


def test_centered_text_without_box_is_the_widest_line_around_the_anchor(tmp_path):
    box = one_box(tmp_path, {"type": "text", "text": "ola mundo", "role": "title", "x": 0.5, "y": 0.4})
    size = 80  # corpo do papel `title` na base 1080
    left, top, width, height = box.rect
    assert width == pytest.approx(9 * size * 0.5)
    assert height == pytest.approx(size)
    assert (left + width / 2, top + height / 2) == pytest.approx((540, 768))
    assert box.anchor == pytest.approx((540, 768))
    assert box.kind == "text" and box.resize == "text_width" and box.movable and box.locked_reason is None


def test_left_aligned_text_anchors_on_the_text_edge_and_the_box_reaches_the_padding(tmp_path):
    """No `lower-third` padrão (alinhado à esquerda, com caixa) o `x` da spec é a borda do texto, e a caixa
    começa o padding antes dele."""
    box = one_box(tmp_path, {"type": "text", "text": "Dra. Maria", "role": "lower-third"})
    pad = 22  # box_padding do papel
    left, _, width, _ = box.rect
    assert box.anchor[0] == pytest.approx(SAFE.left + pad + 28)  # a borda do texto: margem + padding + 28 px
    assert left == pytest.approx(box.anchor[0] - pad)
    assert width == pytest.approx(10 * 48 * 0.5 + 2 * pad)
    assert box.placement == "position"
    assert box.outside_safe_zone == ()  # a conta antiga centrava a caixa e acusava a esquerda sem razão


def test_right_aligned_text_anchors_on_the_right_edge(tmp_path):
    box = one_box(
        tmp_path,
        {"type": "text", "text": "Dra. Maria", "role": "lower-third", "style": {"align": "right"}},
    )
    left, _, width, _ = box.rect
    assert box.anchor[0] == pytest.approx(W - SAFE.right - 22 - 28)
    assert left + width == pytest.approx(box.anchor[0] + 22)


@pytest.mark.parametrize(
    ("align", "x", "left_of_text"),
    [("left", 0.2, 216), ("center", 0.5, 540 - 10 * 80 * 0.5 / 2), ("right", 0.9, 972 - 10 * 80 * 0.5)],
)
def test_text_x_is_the_edge_for_left_and_right_and_the_center_otherwise(tmp_path, align, x, left_of_text):
    box = one_box(
        tmp_path,
        {"type": "text", "text": "Dra. Maria", "role": "title", "x": x, "y": 0.5, "style": {"align": align}},
    )
    assert box.rect[0] == pytest.approx(left_of_text)
    assert box.anchor == pytest.approx((x * W, 0.5 * H))
    assert box.placement == "xy"


def test_secondary_line_grows_the_block_and_may_widen_it(tmp_path):
    plain = one_box(tmp_path, {"type": "text", "text": "Nome", "role": "title", "x": 0.5, "y": 0.5})
    with_secondary = one_box(
        tmp_path,
        {
            "type": "text",
            "text": "Nome",
            "secondary": "Um cargo bem comprido",
            "role": "title",
            "x": 0.5,
            "y": 0.5,
        },
    )
    assert with_secondary.rect[3] == pytest.approx(plain.rect[3] + 0.7 * 80)
    assert with_secondary.rect[2] == pytest.approx(len("Um cargo bem comprido") * 0.7 * 80 * 0.5)
    assert with_secondary.anchor == pytest.approx(plain.anchor)  # o bloco cresce em volta da mesma âncora


def test_background_box_adds_padding_on_every_side(tmp_path):
    base = {"type": "text", "text": "ola mundo", "role": "title", "x": 0.5, "y": 0.5}
    plain = one_box(tmp_path, base)
    boxed = one_box(tmp_path, {**base, "style": {"box": True, "box_padding": 30}})
    assert boxed.rect[2] == pytest.approx(plain.rect[2] + 60)
    assert boxed.rect[3] == pytest.approx(plain.rect[3] + 60)
    assert boxed.anchor == pytest.approx(plain.anchor)


def test_rounded_box_has_one_pad_per_side_horizontally_and_none_vertically(tmp_path):
    """A caixa arredondada por linha é a soma das linhas com o padding dos lados; verticalmente é só o texto."""
    box = one_box(
        tmp_path,
        {
            "type": "text",
            "text": "uma frase que precisa quebrar em duas linhas porque e comprida demais para caber",
            "role": "title",
            "x": 0.5,
            "y": 0.5,
            "style": {"box_shape": "rounded", "box_padding": 20, "max_width": 0.5},
        },
    )
    assert box.rect[2] <= 0.5 * W + 1  # nunca passa da largura permitida
    assert box.rect[3] == pytest.approx(80 * round(box.rect[3] / 80))  # múltiplo da altura de uma linha


def test_text_region_puts_the_anchor_on_the_region_and_remembers_its_name(tmp_path):
    regions = {"faixa": {"x": 0.5, "y": 0.3, "width": 0.6, "height": 0.1}}
    box = one_box(
        tmp_path, {"type": "text", "text": "Assunto", "region": "faixa", "role": "title"}, regions=regions
    )
    assert box.placement == "region" and box.region == "faixa"
    assert box.anchor == pytest.approx((540, 576))
    left_aligned = one_box(
        tmp_path,
        {"type": "text", "text": "Assunto", "region": "faixa", "role": "title", "style": {"align": "left"}},
        regions=regions,
    )
    assert left_aligned.anchor[0] == pytest.approx(540 - 0.3 * W)  # a borda esquerda da região


def test_wrap_area_follows_the_alignment(tmp_path):
    base = {"type": "text", "text": "ola", "role": "title", "x": 0.5, "y": 0.5}
    centered = one_box(tmp_path, {**base, "style": {"max_width": 0.6}})
    assert centered.wrap == pytest.approx((540 - 0.3 * W, 0.6 * W))
    left = one_box(
        tmp_path, {**base, "x": 0.2, "style": {"max_width": 0.6, "align": "left", "box_padding": 20}}
    )
    assert left.wrap == pytest.approx((0.2 * W - 20, 0.6 * W))
    right = one_box(
        tmp_path, {**base, "x": 0.9, "style": {"max_width": 0.6, "align": "right", "box_padding": 20}}
    )
    assert right.wrap[0] + right.wrap[1] == pytest.approx(0.9 * W + 20)


def test_the_text_keeps_its_measure_for_the_qa(tmp_path):
    box = one_box(tmp_path, {"type": "text", "text": "ola mundo", "role": "title"})
    assert box.text is not None and box.text.lines == ["ola mundo"]
    assert box.text.wrap_width == pytest.approx(W * 0.86 - 2 * 24 * (1080 / 1080))


# ---------- imagem ----------


def test_image_box_is_the_scaled_picture_around_its_center(tmp_path):
    box = one_box(
        tmp_path, {"type": "image", "src": "logo.png", "x": 0.28, "y": 0.45, "width": 0.25}, make_prober()
    )
    assert box.rect == pytest.approx((0.28 * W - 135, 0.45 * H - 101, 270, 202))
    assert box.anchor == pytest.approx((0.28 * W, 0.45 * H))
    assert box.placement == "xy" and box.resize == "keep_aspect" and box.movable


def test_image_height_follows_the_file_aspect_rounded_to_an_even_number(tmp_path):
    box = one_box(
        tmp_path,
        {"type": "image", "src": "logo.png", "x": 0.5, "y": 0.5, "width": 0.22},
        make_prober({"logo.png": (301, 203)}),
    )
    assert box.rect[2] == 236  # 1080 * 0.22 = 237.6 -> par abaixo
    assert box.rect[3] == 2 * round(236 / (301 / 203) / 2)


def test_named_image_position_respects_the_safe_zone(tmp_path):
    box = one_box(tmp_path, {"type": "image", "src": "logo.png", "position": "top-right", "width": 0.2})
    left, top, width, _ = box.rect
    assert left + width == pytest.approx(W - SAFE.right - 40)
    assert top == pytest.approx(SAFE.top + 40)
    assert box.placement == "position" and box.outside_safe_zone == ()
    glued = one_box(
        tmp_path,
        {"type": "image", "src": "logo.png", "position": "top-right", "width": 0.2, "safe_zone": False},
    )
    assert glued.rect[1] == pytest.approx(40) and set(glued.outside_safe_zone) == {"top", "right"}


def test_circle_image_is_a_square(tmp_path):
    box = one_box(
        tmp_path, {"type": "image", "src": "logo.png", "x": 0.5, "y": 0.5, "width": 0.3, "shape": "circle"}
    )
    assert box.rect[2] == box.rect[3] == 324


def test_image_in_a_region_fits_it_without_distortion(tmp_path):
    regions = {"quadro": {"x": 0.5, "y": 0.5, "width": 0.8, "height": 0.2}}
    box = one_box(tmp_path, {"type": "image", "src": "logo.png", "region": "quadro"}, regions=regions)
    assert box.placement == "region" and box.region == "quadro"
    assert box.anchor == pytest.approx((540, 960))
    assert box.rect[3] == pytest.approx(0.2 * H, abs=2)  # 400x300 numa faixa larga: manda a altura


def test_image_outside_the_safe_zone_reports_the_side(tmp_path):
    box = one_box(tmp_path, {"type": "image", "src": "logo.png", "x": 0.98, "y": 0.5, "width": 0.2})
    assert "right" in box.outside_safe_zone and "left" not in box.outside_safe_zone


def test_a_missing_image_has_no_area_and_says_why(tmp_path):
    box = one_box(tmp_path, {"type": "image", "src": "sumiu.png", "x": 0.5, "y": 0.5})
    assert box.rect is None and box.anchor is None and not box.movable
    assert "sumiu.png" in box.locked_reason and box.resize == "none"


def test_logo_without_the_brand_logo_says_why(tmp_path):
    box = one_box(tmp_path, {"type": "image", "src": "logo"})
    assert not box.movable and "logo" in box.locked_reason.lower()


# ---------- PiP ----------


def test_pip_box_is_the_video_rectangle_around_its_center(tmp_path):
    box = one_box(
        tmp_path,
        {"type": "video", "src": "cam.mp4", "x": 0.68, "y": 0.45, "width": 0.3},
        make_prober({"cam.mp4": (1920, 1080)}),
    )
    assert box.rect == pytest.approx(
        (0.68 * W - 162, 0.45 * H - 91, 324, 182), abs=0.5
    )  # o render arredonda o canto
    assert box.anchor == pytest.approx((0.68 * W, 0.45 * H))
    assert box.kind == "video" and box.placement == "xy" and box.resize == "keep_aspect"


def test_pip_aspect_comes_from_the_spec_or_the_circle(tmp_path):
    wide = {"type": "video", "src": "cam.mp4", "x": 0.5, "y": 0.5, "width": 0.3}
    square = one_box(tmp_path, {**wide, "aspect": "1:1"})
    circle = one_box(tmp_path, {**wide, "shape": "circle"})
    assert square.rect[2] == square.rect[3] == 324 and circle.rect[2] == circle.rect[3] == 324
    vertical = one_box(tmp_path, wide, make_prober({"cam.mp4": (1080, 1920)}))
    assert vertical.rect[3] > vertical.rect[2]


def test_named_pip_position_uses_the_safe_zone_and_margin(tmp_path):
    box = one_box(tmp_path, {"type": "video", "src": "cam.mp4", "position": "bottom-right", "width": 0.3})
    left, top, width, height = box.rect
    assert left + width == pytest.approx(W - SAFE.right - 40)
    assert top + height == pytest.approx(H - SAFE.bottom - 40)
    assert box.placement == "position" and box.outside_safe_zone == ()


def test_pip_from_a_named_source_takes_its_aspect_from_the_first_file(tmp_path):
    box = one_box(
        tmp_path,
        {"type": "video", "source": "cam2", "x": 0.5, "y": 0.5, "width": 0.3},
        make_prober({"cam.mp4": (1000, 1000)}),
        sources={"cam2": {"src": "cam.mp4"}},
    )
    assert box.rect[2] == box.rect[3]


def test_pip_in_a_region_takes_the_region_aspect(tmp_path):
    regions = {"cam": {"x": 0.5, "y": 0.7, "width": 0.4, "height": 0.2}}
    box = one_box(tmp_path, {"type": "video", "src": "cam.mp4", "region": "cam"}, regions=regions)
    assert box.placement == "region" and box.anchor == pytest.approx((540, 1344))
    assert box.rect[2] == pytest.approx(0.4 * W, abs=2) and box.rect[3] == pytest.approx(0.2 * H, abs=2)


def test_a_missing_pip_file_has_no_area_and_says_why(tmp_path):
    box = one_box(tmp_path, {"type": "video", "src": "sumiu.mp4", "x": 0.5, "y": 0.5})
    assert box.rect is None and not box.movable and "sumiu.mp4" in box.locked_reason


# ---------- composição HTML ----------


def test_html_box_is_the_html_box_of_the_render(tmp_path):
    box = one_box(
        tmp_path,
        {"type": "html", "src": "comp.html", "x": 0.5, "y": 0.62, "width": 0.6, "height": 0.12},
    )
    assert box.rect == (216, 1075, 648, 230)
    assert box.anchor == pytest.approx((540, 0.62 * H)) and box.resize == "free" and box.placement == "xy"
    assert box.outside_safe_zone == ()


def test_html_outside_the_safe_zone_reports_the_sides(tmp_path):
    box = one_box(
        tmp_path, {"type": "html", "src": "comp.html", "x": 0.5, "y": 0.95, "width": 0.9, "height": 0.2}
    )
    assert set(box.outside_safe_zone) == {"bottom", "left", "right"}


def test_a_full_page_html_is_not_checked_against_the_safe_zone(tmp_path):
    box = one_box(tmp_path, {"type": "html", "src": "comp.html"})
    assert box.placement == "full" and box.rect == (0, 0, W, H) and box.outside_safe_zone == ()


def test_html_in_a_region_fills_it(tmp_path):
    regions = {"mapa": {"x": 0.5, "y": 0.5, "width": 0.5, "height": 0.25}}
    box = one_box(tmp_path, {"type": "html", "src": "comp.html", "region": "mapa"}, regions=regions)
    assert box.placement == "region" and box.rect == (270, 720, 540, 480)


def test_html_pinned_to_a_caption_word_has_no_area_and_no_handles(tmp_path):
    box = one_box(
        tmp_path, {"type": "html", "src": "comp.html", "anchor": {"word": "frio"}, "start": 1, "end": 3}
    )
    assert box.placement == "anchor" and box.rect is None and box.anchor is None
    assert not box.movable and box.resize == "none" and '"frio"' in box.locked_reason
    assert (box.start, box.end) == (1, 3)


def test_html_with_a_broken_template_says_why_instead_of_failing(tmp_path):
    box = one_box(tmp_path, {"type": "html", "infographic": "modelo-que-nao-existe"})
    assert box.rect is None and not box.movable and box.locked_reason


# ---------- o que não se move ----------


def test_progress_bar_shows_its_strip_but_is_locked(tmp_path):
    box = one_box(tmp_path, {"type": "progress-bar", "height": 12, "position": "bottom"})
    assert box.kind == "progress-bar" and box.rect == (0, H - 12, W, 12)
    assert not box.movable and box.resize == "none" and box.locked_reason
    top = one_box(tmp_path, {"type": "progress-bar", "position": "top"})
    assert top.rect[1] == 0 and top.outside_safe_zone == ()


def test_audiogram_shows_its_area_but_is_locked(tmp_path):
    box = one_box(tmp_path, {"type": "audiogram", "style": "circle", "x": 0.5, "y": 0.5, "width": 0.5})
    assert box.kind == "audiogram" and not box.movable and box.locked_reason
    assert box.rect[2] == box.rect[3] == 540
    assert box.anchor == pytest.approx((540, 960))


# ---------- a lista e a API ----------


def test_boxes_follow_the_order_of_the_overlays_and_carry_their_index(tmp_path):
    project = make_project(
        tmp_path,
        [
            {"type": "text", "text": "um", "start": 1, "end": 2},
            {"type": "progress-bar"},
            {"type": "image", "src": "logo.png", "x": 0.5, "y": 0.5},
            {"type": "html", "src": "comp.html", "start": 0.5},
        ],
    )
    boxes = boxes_of(project)
    assert [b.index for b in boxes] == [0, 1, 2, 3]
    assert [b.kind for b in boxes] == ["text", "progress-bar", "image", "html"]
    assert (boxes[0].start, boxes[0].end) == (1, 2) and boxes[3].end is None


def test_kinds_filter_skips_the_others_but_keeps_the_index(tmp_path):
    project = make_project(
        tmp_path,
        [
            {"type": "text", "text": "um"},
            {"type": "image", "src": "logo.png", "x": 0.5, "y": 0.5},
            {"type": "text", "text": "dois"},
        ],
    )
    assert [b.index for b in boxes_of(project, kinds={"text"})] == [0, 2]
    assert [b.index for b in boxes_of(project, kinds={"image"})] == [1]


def test_to_dict_is_the_api_contract_in_fractions_of_the_native_frame(tmp_path):
    project = make_project(
        tmp_path,
        [
            {"type": "text", "text": "ola mundo", "role": "title", "x": 0.5, "y": 0.5, "start": 0, "end": 4},
            {"type": "html", "src": "comp.html", "anchor": {"word": "frio"}},
        ],
    )
    result = overlay_boxes(project, REELS, THEME, make_prober(), measure=fixed_ruler).to_dict()
    json.dumps(result)  # tem que ser serializável
    assert (result["width"], result["height"]) == (1080, 1920)
    assert result["safe_zone"] == {
        "top": round(220 / 1920, 6),
        "bottom": round(420 / 1920, 6),
        "left": round(60 / 1080, 6),
        "right": round(150 / 1080, 6),
    }
    text, locked = result["boxes"]
    assert set(text) == {
        "index", "kind", "start", "end", "left", "top", "width", "height", "anchor", "placement",
        "region", "resize", "wrap", "movable", "locked_reason", "outside_safe_zone",
    }  # fmt: skip
    assert text["anchor"] == {"x": 0.5, "y": 0.5} and text["end"] == 4.0
    assert text["left"] + text["width"] / 2 == pytest.approx(0.5, abs=1e-5)
    assert text["top"] + text["height"] / 2 == pytest.approx(0.5, abs=1e-5)
    assert text["wrap"]["width"] == pytest.approx(0.86) and text["region"] is None
    assert locked["left"] is None and locked["anchor"] is None and locked["wrap"] is None
    assert locked["movable"] is False and locked["end"] is None


# ---------- o render e a caixa dão a mesma conta ----------


def test_image_box_origin_is_the_origin_the_render_graph_gives_the_overlay_filter(tmp_path):
    for fields in (
        {"x": 0.28, "y": 0.45, "width": 0.25},
        {"position": "bottom-left", "width": 0.2},
        {"position": "center", "width": 0.3, "safe_zone": False},
    ):
        overlay = ImageOverlay(src="logo.png", **fields)
        size = image_overlay_size(overlay, W, 4 / 3)
        origin = image_overlay_origin(overlay, size, W, H, 1.0, SAFE)
        lines: list[str] = []
        image_overlay_graph(
            lines,
            Inputs(),
            "[base]",
            [ResolvedImageOverlay(overlay, Path("logo.png"), 0, 3)],
            W,
            H,
            30,
            3,
            1.0,
            SAFE,
        )
        overlay_line = next(line for line in lines if "overlay=x=" in line)
        x_expr, y_expr = re.search(r"overlay=x=(\S+?):y=(\S+?):enable", overlay_line).groups()
        names = {"W": W, "H": H, "w": size[0], "h": size[1]}
        assert (evaluate(x_expr, names), evaluate(y_expr, names)) == pytest.approx(origin)


def test_pip_box_origin_is_the_origin_of_the_render_position(tmp_path):
    for fields in (
        {"x": 0.68, "y": 0.45, "width": 0.3},
        {"position": "bottom-right", "width": 0.28},
        {"position": "top", "width": 0.4, "margin": 10},
    ):
        overlay = VideoOverlay(src="cam.mp4", **fields)
        size = pip_size(overlay, W, 16 / 9)
        resolved = ResolvedVideoOverlay(overlay, Path("cam.mp4"), 0, 0, 3, *size, Path("m.png"), None, 0)
        assert pip_position(resolved, W, H, 1.0, SAFE) == pip_origin(overlay, *size, W, H, 1.0, SAFE)


def test_pip_size_is_even_and_keeps_the_aspect_without_the_float_trap():
    overlay = VideoOverlay(src="cam.mp4", width=0.21, aspect="226:480")
    width, height = pip_size(overlay, W, None)
    assert width % 2 == 0 and height % 2 == 0
    assert height >= width / (226 / 480) - 2  # 480 / (480/226) não vira 224 por truncamento


def test_a_persona_overlay_has_the_box_the_render_gives_it_but_is_locked(tmp_path):
    box = one_box(
        tmp_path,
        {
            "type": "persona",
            "persona": "bia",
            "speech": {"text": "oi"},
            "position": "bottom-right",
            "width": 0.5,
            "aspect": "3:4",
        },
    )
    assert box.kind == "persona" and not box.movable and box.locked_reason
    left, top, width, height = box.rect
    assert (width, height) == (540, 720)  # metade da largura do quadro, em 3:4: as contas do render
    assert left + width == W - SAFE.right - 40 and top + height == H - SAFE.bottom - 40
