import pytest

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import CaptionStyle, ProgressBar, TextOverlay
from dmaker.media import fonts
from dmaker.text.ass import AssDoc
from dmaker.text.captions import Cue, Word
from dmaker.text.overlays import (
    Canvas,
    add_captions,
    add_guides,
    add_progress_bar,
    add_text_overlay,
    wrap_lines,
)

pytestmark = pytest.mark.skipif(
    not fonts.family_available("Poppins") and not fonts.family_available("Arial"),
    reason="nenhuma fonte disponível",
)


@pytest.fixture
def canvas() -> Canvas:
    p = get_preset("instagram/reels")
    return Canvas(p.width, p.height, p.safe, load_theme("medlycare"), total=12.0)


def test_font_resolution_and_measure():
    ref = fonts.resolve("Poppins", "bold")
    assert ref.file.exists()
    w, h = fonts.measure("MedlyCare", ref, 66)
    assert 200 < w < 600 and h == 66


def test_wrap_lines():
    ref = fonts.resolve("Poppins", "bold")
    lines = wrap_lines("uma frase bem comprida para quebrar em linhas", ref, 66, 500)
    assert len(lines) >= 2
    assert all(fonts.measure(ln, ref, 66)[0] <= 500 for ln in lines)


@pytest.mark.parametrize("role", ["hook", "title", "subtitle", "cta", "lower-third", "custom"])
def test_text_overlay_roles(canvas, role):
    doc = AssDoc(canvas.width, canvas.height)
    ov = TextOverlay(
        text="Sua agenda em um clique",
        role=role,
        secondary="Cargo" if role == "lower-third" else None,
        start=1,
        end=4,
    )
    add_text_overlay(doc, canvas, ov, 0)
    out = doc.render()
    assert "Dialogue:" in out and "Sua agenda" in out
    assert "Poppins" in out
    if role == "cta":
        assert "\\p1" in out  # caixa arredondada desenhada
        assert "\\move(" in out  # slide-up
    if role == "lower-third":
        assert out.count("Dialogue:") == 3  # caixa + barra + texto


def test_text_overlay_animations_and_boxes(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    add_text_overlay(doc, canvas, TextOverlay(text="Pop", role="hook", animation="pop"), 0)
    add_text_overlay(doc, canvas, TextOverlay(text="Digitando", role="title", animation="typewriter"), 1)
    add_text_overlay(
        doc, canvas, TextOverlay(text="Caixa", role="title", style={"box": True, "uppercase": True}), 2
    )
    out = doc.render()
    assert "\\fscx82\\fscy82" in out and "\\k" in out and "CAIXA" in out


def test_overlay_outside_duration_is_dropped(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    add_text_overlay(doc, canvas, TextOverlay(text="tarde", start=20, end=25), 0)
    assert doc.events == []


def test_captions_karaoke_generates_per_word_events(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    cues = [
        Cue(0.5, 2.0, "oi tudo bem", [Word(0.5, 0.9, "oi"), Word(0.9, 1.4, "tudo"), Word(1.4, 2.0, "bem")])
    ]
    add_captions(doc, canvas, cues, CaptionStyle(mode="karaoke", uppercase=True))
    events = [e for e in doc.events if e.style == "Cap"]
    assert len(events) == 3
    assert events[0].text.count("TUDO") == 1 and "&H00A2B975" in events[1].text  # destaque verde da marca
    assert "Style: Cap,Poppins," in doc.render()


def test_captions_classic_and_boxed(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    add_captions(doc, canvas, [Cue(0, 1, "linha simples")], CaptionStyle(mode="boxed", uppercase=False))
    st = doc.styles["Cap"]
    assert st.border_style == 3 and len(doc.events) == 1 and "linha simples" in doc.events[0].text


def test_progress_bar_and_guides(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    add_progress_bar(doc, canvas, ProgressBar(height=8))
    assert len(doc.events) == 2 and "\\t(0,12000,\\fscx100)" in doc.events[1].text
    add_guides(doc, canvas)
    assert len(doc.events) == 2 + 4 + 1


def test_tone_changes_defaults(canvas):
    from dmaker.text.overlays import effective_style

    ov = TextOverlay(text="x", role="hook")
    assert effective_style(ov, canvas.theme, None)["outline"] > 0
    light = effective_style(ov, canvas.theme, "light")
    assert light["color"] == canvas.theme.colors["primary"] and light["outline"] == 0
    dark = effective_style(ov, canvas.theme, "dark")
    assert dark["color"] == "#FFFFFF"
    # estilo explícito da spec continua mandando
    forced = effective_style(TextOverlay(text="x", role="hook", style={"outline": 3}), canvas.theme, "light")
    assert forced["outline"] == 3


def testtone_for():
    from dmaker.domain.timeline import tone_for

    spans = [(0.0, 3.0), (2.5, 7.0), (7.0, 10.0)]
    tones = ["light", None, "dark"]
    assert tone_for(0, 2, spans, tones) == "light"
    assert tone_for(0, 4, spans, tones) is None  # metade sobre vídeo real
    assert tone_for(7.5, 9, spans, tones) == "dark"
    # encostar 0.1 s no trecho vizinho (transição) não muda o tom dominante
    spans2 = [(0.0, 5.0), (4.9, 9.0)]
    assert tone_for(1.0, 5.0, spans2, ["light", "dark"]) == "light"
    assert tone_for(3.0, 7.0, spans2, ["light", "dark"]) is None


def test_cta_inverts_on_dark_tone(canvas):
    from dmaker.text.overlays import effective_style

    st = effective_style(TextOverlay(text="x", role="cta"), canvas.theme, "dark")
    assert st["box_color"] == canvas.theme.colors["accent"] and st["color"] == canvas.theme.colors["primary"]
    st_light = effective_style(TextOverlay(text="x", role="cta"), canvas.theme, "light")
    assert st_light["box_color"] == canvas.theme.colors["primary"]
