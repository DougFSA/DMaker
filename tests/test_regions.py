"""Regiões nomeadas: validação na spec e resolução (pura) das sobreposições que apontam para elas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmaker.domain.regions import RegionError, fit_in_region, region_pixels, resolve_region
from dmaker.domain.spec import ImageOverlay, Project, Region, TextOverlay, TextStyle, VideoOverlay
from dmaker.filtergraph.common import even

W, H = 1080, 1920
TOPO = Region(x=0.5, y=0.25, width=0.8, height=0.2)  # 864 x 384 px, centro em (540, 480)
REGIONS = {"topo": TOPO}


def _project(overlays: list[dict], regions: dict | None = None) -> dict:
    spec = {"name": "t", "timeline": [{"type": "card", "title": "t"}], "overlays": overlays}
    if regions is not None:
        spec["regions"] = regions
    return spec


# ---------- a região na spec ----------


def test_region_has_to_fit_inside_the_frame():
    with pytest.raises(ValidationError, match="fora do quadro"):
        Region(x=0.9, y=0.5, width=0.4, height=0.2)  # passa da borda direita
    with pytest.raises(ValidationError, match="vertical"):
        Region(x=0.5, y=0.05, width=0.5, height=0.2)  # passa do topo
    assert Region(x=0.5, y=0.5, width=1, height=1).width == 1  # o quadro inteiro cabe


def test_project_without_regions_validates_and_keeps_its_dump_unchanged():
    project = Project.model_validate(_project([{"type": "text", "text": "oi", "position": "top"}]))
    assert project.regions == {}
    dumped = project.model_dump(exclude_none=True)
    assert "region" not in dumped["overlays"][0]  # a chave nova só aparece quando alguém a usa


def test_unknown_region_name_is_a_clear_error_listing_the_known_ones():
    spec = _project([{"type": "image", "src": "a.png", "region": "rodape"}], {"topo": TOPO.model_dump()})
    with pytest.raises(ValidationError, match=r"região desconhecida: rodape.*regiões do projeto: topo"):
        Project.model_validate(spec)
    with pytest.raises(ValidationError, match="nenhuma declarada"):
        Project.model_validate(_project([{"type": "text", "text": "oi", "region": "topo"}]))


@pytest.mark.parametrize(
    "overlay",
    [
        {"type": "text", "text": "oi", "region": "topo", "y": 0.3},
        {"type": "text", "text": "oi", "region": "topo", "position": "top"},
        {"type": "image", "src": "a.png", "region": "topo", "x": 0.5, "y": 0.5},
        {"type": "video", "src": "a.mp4", "region": "topo", "x": 0.5, "y": 0.5},
    ],
)
def test_region_and_explicit_position_together_are_refused(overlay):
    """x/y/position explícitos com `region` seriam ambíguos: a spec recusa em vez de escolher um."""
    with pytest.raises(ValidationError, match="não leva"):
        Project.model_validate(_project([overlay], {"topo": TOPO.model_dump()}))


def test_image_overlay_needs_x_and_y_together():
    with pytest.raises(ValidationError, match="juntos"):
        ImageOverlay(src="a.png", x=0.5)
    assert ImageOverlay(src="a.png", x=0.5, y=0.2).y == 0.2


# ---------- contas de região ----------


def test_region_pixels_gives_left_top_width_height():
    assert region_pixels(TOPO, W, H) == (108, 288, 864, 384)


def test_fit_in_region_contains_without_distortion():
    wide = fit_in_region(TOPO, 16 / 9, W, H)  # 16:9 é mais estreita que a região (2.25): a altura manda
    assert wide.width * W == pytest.approx(384 * 16 / 9, abs=0.1)
    ultrawide = fit_in_region(TOPO, 4.0, W, H)  # mais larga que a região: encosta nos lados
    assert ultrawide.width * W == pytest.approx(864, abs=0.1)
    square = fit_in_region(TOPO, 1.0, W, H)
    assert square.width * W == pytest.approx(384, abs=0.1)  # limitada pela altura
    assert (square.x, square.y) == (0.5, 0.25)  # sempre no centro da região


def test_resolving_an_overlay_without_region_returns_the_same_object():
    overlay = TextOverlay(text="oi", position="top")
    assert resolve_region(overlay, REGIONS, W, H) is overlay


def test_resolve_unknown_region_raises_region_error():
    overlay = TextOverlay.model_construct(text="oi", region="sumiu")  # ignora a validação da spec
    with pytest.raises(RegionError, match="sumiu.*topo"):
        resolve_region(overlay, REGIONS, W, H)


def test_text_is_centered_in_the_region_and_wraps_to_its_width():
    resolved = resolve_region(TextOverlay(text="oi", region="topo"), REGIONS, W, H)
    assert (resolved.x, resolved.y, resolved.region) == (0.5, 0.25, None)
    assert resolved.style.align == "center" and resolved.style.max_width == 0.8
    narrow = TextOverlay(text="oi", region="topo", style=TextStyle(max_width=0.5))
    assert resolve_region(narrow, REGIONS, W, H).style.max_width == 0.5  # o menor dos dois vale
    wide = TextOverlay(text="oi", region="topo", style=TextStyle(max_width=0.95))
    assert resolve_region(wide, REGIONS, W, H).style.max_width == 0.8


def test_left_and_right_aligned_text_touch_the_region_edges():
    left = TextOverlay(text="oi", region="topo", style=TextStyle(align="left"))
    right = TextOverlay(text="oi", region="topo", style=TextStyle(align="right"))
    assert resolve_region(left, REGIONS, W, H).x == pytest.approx(0.1)
    assert resolve_region(right, REGIONS, W, H).x == pytest.approx(0.9)


def test_image_fits_inside_the_region_centered_with_its_own_proportion():
    portrait = resolve_region(ImageOverlay(src="a.png", region="topo"), REGIONS, W, H, content_aspect=0.75)
    assert portrait.region is None and (portrait.x, portrait.y) == (0.5, 0.25)
    assert portrait.width * W == pytest.approx(384 * 0.75, abs=0.1)  # a altura da região manda
    landscape = resolve_region(ImageOverlay(src="a.png", region="topo"), REGIONS, W, H, content_aspect=3.0)
    assert landscape.width * W == pytest.approx(864, abs=0.1)  # a largura da região manda
    unknown = resolve_region(ImageOverlay(src="a.png", region="topo"), REGIONS, W, H)
    assert unknown.width * W == pytest.approx(864, abs=0.1)  # sem a proporção, ocupa a da região


def test_video_fills_the_whole_region_unless_an_aspect_is_asked():
    video = VideoOverlay(src="a.mp4", region="topo")
    filled = resolve_region(video, REGIONS, W, H)
    assert filled.aspect == "864:384" and filled.region is None
    assert (filled.x, filled.y) == (0.5, 0.25)
    # o PiP monta o quadro com even(largura do vídeo * fração) x even(largura / proporção): tem de dar a região
    frame_w = even(W * filled.width)
    assert frame_w == 864 and even(frame_w / (864 / 384)) == 384

    boxed = resolve_region(VideoOverlay(src="a.mp4", region="topo", aspect="1:1"), REGIONS, W, H)
    assert boxed.aspect == "1:1" and boxed.width * W == pytest.approx(384, abs=0.1)
    circle = resolve_region(VideoOverlay(src="a.mp4", region="topo", shape="circle"), REGIONS, W, H)
    assert circle.width * W == pytest.approx(384, abs=0.1)  # o círculo é 1:1, limitado pela altura


@pytest.mark.parametrize("pixels", [78, 312, 374, 748, 770, 894, 950, 972])
def test_video_frame_never_loses_a_pixel_to_float_truncation(pixels):
    """`even` trunca: sem a folga da conta, uma fração que multiplicada desse 971.9999 virava 970 e deixava
    uma fresta entre o quadro e a borda da região (78, 312, 374, 748, 770 e 894 perdem 2 px sem a folga)."""
    region = Region(x=0.5, y=0.5, width=pixels / W, height=0.3)
    resolved = resolve_region(VideoOverlay(src="a.mp4", region="r"), {"r": region}, W, H)
    assert even(W * resolved.width) == pixels
