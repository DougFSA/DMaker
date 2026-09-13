import pytest

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.media import fonts
from dmaker.visuals.cards import render_backdrop, render_card, render_framed_image
from dmaker.visuals.geometry import fit_rect

pytestmark = pytest.mark.skipif(
    not fonts.family_available("Poppins") and not fonts.family_available("Arial"),
    reason="nenhuma fonte disponível",
)


def test_fit_rect_is_even_and_centered():
    x, y, w, h = fit_rect(1000, 620, 1080, 1920, 0.05)
    assert w % 2 == 0 and h % 2 == 0 and w <= 1080 * 0.9
    assert abs((x + w / 2) - 540) <= 1 and abs((y + h / 2) - 960) <= 1


def test_render_card_and_backdrop_sizes():
    theme = load_theme("medlycare")
    p = get_preset("instagram/reels")
    img = render_card(theme, 540, 960, "Sua agenda organizada", "MedlyCare", None, True, None, p.safe, seed=1)
    assert img.size == (540, 960)
    dark = render_card(theme, 540, 960, "Teste grátis", None, "dark", True, None, p.safe, seed=2)
    assert dark.size == (540, 960)
    bg = render_backdrop(theme, 540, 960, None, 3, (27, 300, 486, 300))
    assert bg.size == (540, 960)


def test_render_framed_image(tmp_path):
    from PIL import Image

    src = tmp_path / "print.png"
    Image.new("RGB", (1000, 620), "#3366CC").save(src)
    theme = load_theme("medlycare")
    out = render_framed_image(theme, 540, 960, src, None, 0, 0.05, 0.02)
    assert out.size == (540, 960)
    # o centro do quadro mostra a imagem (azul), não o fundo branco
    r, g, b = out.getpixel((270, 480))
    assert b > r and b > g


def test_default_theme_card_without_logo():
    theme = load_theme("default")
    img = render_card(theme, 480, 480, "Título do vídeo", "subtítulo", None, True, None, None, seed=5)
    assert img.size == (480, 480)
