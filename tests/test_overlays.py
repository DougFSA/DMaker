import re

import pytest

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import CaptionStyle, ProgressBar, TextOverlay
from dmaker.media import fonts
from dmaker.text.ass import AssDoc, ass_color
from dmaker.text.captions import Cue, Word
from dmaker.text.overlays import (
    Canvas,
    add_captions,
    add_guides,
    add_progress_bar,
    add_text_overlay,
    effective_style,
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


def test_caption_box_color_accepts_theme_key(canvas):
    """A caixa da legenda segue o tema como os outros campos de cor, sem hex na spec."""
    doc = AssDoc(canvas.width, canvas.height)
    style = CaptionStyle(mode="boxed", box_color="primary", box_alpha=1.0)
    add_captions(doc, canvas, [Cue(0, 1, "linha")], style)
    assert doc.styles["Cap"].outline == ass_color(canvas.theme.colors["primary"])


def test_boxed_text_drops_the_outline(canvas):
    """Contorno sobre caixa engrossa a letra e borra o texto; quem pedir `outline` manda nele."""
    from dmaker.text.overlays import effective_style

    boxed = TextOverlay(text="x", role="subtitle", style={"box": True})
    assert effective_style(boxed, canvas.theme, None)["outline"] == 0

    asked = TextOverlay(text="x", role="subtitle", style={"box": True, "outline": 2})
    assert effective_style(asked, canvas.theme, None)["outline"] == 2
    assert effective_style(TextOverlay(text="x", role="subtitle"), canvas.theme, None)["outline"] > 0


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


# ---------- caixa arredondada (DMK-33) ----------


def test_measure_rendered_matches_the_libass_render():
    """Larguras conferidas contra o render real do libass (Poppins Bold, Fontsize 72): tinta de 174, 84
    e 480 px nas três frases; a largura medida inclui o respiro lateral das letras, uns 3 a 6 px."""
    ref = fonts.resolve("Poppins", "bold")
    assert ref.family == "Poppins"
    for text, ink in (("HHHHHH", 174), ("HHH", 84), ("AVATAR TOYOTA WAVE", 480)):
        width, height = fonts.measure_rendered(text, ref, 72)
        assert ink < width < ink + 8
        assert height == 72
    assert fonts.measure_rendered("HHH", ref, 144)[0] == pytest.approx(
        2 * fonts.measure_rendered("HHH", ref, 72)[0]
    )
    assert fonts.measure_rendered("HHH", ref, 72, spacing=2)[0] == pytest.approx(
        fonts.measure_rendered("HHH", ref, 72)[0] + 6
    )


def test_libass_cell_comes_from_the_os2_table_and_falls_back_to_the_hhea(monkeypatch):
    """O libass dimensiona o Fontsize por winAscent+winDescent (1,762 na Poppins), não pela hhea (1,4)."""
    ref = fonts.resolve("Poppins", "regular")
    assert fonts._libass_cell_ratio(str(ref.file)) == pytest.approx(1.762)
    assert fonts.measure_rendered("agenda", ref, 72)[0] < 0.85 * fonts.measure("agenda", ref, 72)[0]
    fonts._libass_cell_ratio.cache_clear()
    fonts._libass_metrics.cache_clear()  # as medidas da tabela OS/2 também ficam em cache
    monkeypatch.setattr(fonts, "_sfnt_table", lambda file, tag: None)
    try:
        assert fonts._libass_cell_ratio(str(ref.file)) == pytest.approx(1.4)
    finally:
        fonts._libass_cell_ratio.cache_clear()
        fonts._libass_metrics.cache_clear()


def test_boxed_caption_is_byte_for_byte_what_it_was(canvas):
    """O `boxed` (caixa do próprio ASS) não pode mudar com a chegada do `rounded`."""
    doc = AssDoc(canvas.width, canvas.height)
    cues = [Cue(0.5, 2.0, "oi tudo bem com voce hoje aqui"), Cue(2.0, 3.5, "linha simples sem palavras")]
    add_captions(doc, canvas, cues, CaptionStyle(mode="boxed"))
    assert doc.styles["Cap"].line() == (
        "Style: Cap,Poppins,72,&H00FFFFFF,&H00A2B975,&H00000000,&H66000000,-1,0,0,0,100,100,0,0,3,14,0,5,100,190,10,1"
    )
    assert [e.line() for e in doc.events] == [
        r"Dialogue: 5,0:00:00.50,0:00:02.00,Cap,,0,0,0,,{\an5\pos(540,1344)}OI TUDO BEM COM VOCE HOJE AQUI",
        r"Dialogue: 5,0:00:02.00,0:00:03.50,Cap,,0,0,0,,{\an5\pos(540,1344)}LINHA SIMPLES SEM PALAVRAS",
    ]


def test_block_box_overlay_is_byte_for_byte_what_it_was(canvas):
    """O `box` de texto (um retângulo em volta do bloco) segue medindo e desenhando como antes."""
    doc = AssDoc(canvas.width, canvas.height)
    ov = TextOverlay(text="Sua agenda em um clique com muito texto para quebrar linhas", role="cta", end=4)
    add_text_overlay(doc, canvas, ov, 0)
    box, text = (e.line() for e in doc.events)
    assert box == (
        r"Dialogue: 10,0:00:00.00,0:00:04.00,T0,,0,0,0,,{\an5\move(540,1420,540,1360,0,320)\fad(200,200)"
        r"\1c&H005A530C\1a&H00&\bord0\shad0\p1}m 30.0 0 l 877.0 0 b 893.6 0 907.0 13.4 907.0 30.0 "
        r"l 907.0 130.0 b 907.0 146.6 893.6 160.0 877.0 160.0 l 30.0 160.0 b 13.4 160.0 0 146.6 0 130.0 "
        r"l 0 30.0 b 0 13.4 13.4 0 30.0 0{\p0}"
    )
    assert text.endswith(r"}Sua agenda em um clique com muito texto\Npara quebrar linhas")


def _two_line_cue() -> Cue:
    words = "agenda inteligente para clinica pequena e rapida".split()
    return Cue(0.0, 4.2, " ".join(words), [Word(i * 0.6, (i + 1) * 0.6, w) for i, w in enumerate(words)])


def test_rounded_caption_draws_one_box_under_the_karaoke_text(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    add_captions(doc, canvas, [_two_line_cue()], CaptionStyle(mode="rounded", max_words=8, max_chars=60))
    boxes = [e for e in doc.events if e.layer == 4]
    texts = [e for e in doc.events if e.layer == 5]
    assert len(boxes) == 1 and (boxes[0].start, boxes[0].end) == (0.0, 4.2)  # uma caixa para a cue inteira
    assert "\\p1" in boxes[0].text and "\\bord0" in boxes[0].text
    assert len(texts) == 7  # uma por palavra: o destaque anda por cima da caixa
    assert all("\\N" in e.text and "\\q2" in e.text for e in texts)  # linhas quebradas por nós
    assert texts[3].text.count("&H00A2B975") == 1 and "CLINICA" in texts[3].text  # destaque da marca
    st = doc.styles["Cap"]
    assert st.border_style == 1 and st.outline_w == 0 and st.shadow == 0  # texto liso sobre a caixa


def _drawing(event_text: str) -> str:
    """Os comandos m/l/b do desenho vetorial (tag p1) de um evento."""
    return event_text.split("\\p1}", 1)[1].split("{\\p0}", 1)[0]


def _drawing_size(drawing: str) -> tuple[float, float]:
    numbers = [float(t) for t in drawing.split() if t not in ("m", "l", "b")]
    return max(numbers[0::2]), max(numbers[1::2])


def _rows(event_text: str) -> list[str]:
    """As linhas do texto de um evento, sem as tags do ASS."""
    body = event_text.split("}", 1)[1]
    return [re.sub(r"\{[^}]*\}", "", row) for row in body.split("\\N")]


def test_rounded_caption_box_matches_the_wrapped_text(canvas):
    """A caixa tem uma linha por linha do texto e a largura da maior, com a margem da marca."""
    doc = AssDoc(canvas.width, canvas.height)
    add_captions(doc, canvas, [_two_line_cue()], CaptionStyle(mode="rounded", max_words=8, max_chars=60))
    text = next(e for e in doc.events if e.layer == 5).text
    box = next(e for e in doc.events if e.layer == 4).text
    rows = _rows(text)
    assert len(rows) == 2
    ref = fonts.resolve("Poppins", "bold")
    widest = max(fonts.measure_rendered(row, ref, 72)[0] for row in rows)
    width, height = _drawing_size(_drawing(box))
    assert width == pytest.approx(widest + 2 * canvas.theme.rounded_box_padding, abs=0.2)
    assert height == pytest.approx(2 * 72)


def test_rounded_caption_without_word_times_is_a_single_static_event(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    cue = Cue(1.0, 3.0, "uma legenda sem tempo por palavra que precisa quebrar em duas linhas")
    add_captions(doc, canvas, [cue], CaptionStyle(mode="rounded"))
    assert [e.layer for e in doc.events] == [4, 5]
    assert "&H00A2B975" not in doc.events[1].text and "\\N" in doc.events[1].text


def test_rounded_caption_position_is_the_center_of_the_block(canvas):
    """Texto e caixa compartilham o centro: o texto em an5 no y da legenda, a caixa em volta dele."""
    doc = AssDoc(canvas.width, canvas.height)
    add_captions(
        doc, canvas, [_two_line_cue()], CaptionStyle(mode="rounded", y=0.7, max_words=8, max_chars=60)
    )
    text = next(e for e in doc.events if e.layer == 5).text
    box = next(e for e in doc.events if e.layer == 4).text
    assert "\\an5\\q2\\pos(540,1344)" in text
    width, height = _drawing_size(_drawing(box))
    left, top = (float(v) for v in re.search(r"\\an7\\pos\(([\d.]+),([\d.]+)\)", box).groups())
    assert (left + width / 2, top + height / 2) == pytest.approx((540, 1344), abs=0.1)


def test_rounded_caption_follows_the_background_tone(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    add_captions(doc, canvas, [_two_line_cue()], CaptionStyle(mode="rounded"), lambda start, end: "light")
    assert "CapLight" in doc.styles and "Cap" not in doc.styles
    box = next(e for e in doc.events if e.layer == 4).text
    assert (
        ass_color(canvas.theme.colors["primary"]) in box and "\\1a&H00&" in box
    )  # caixa opaca na cor da marca


def test_rounded_box_margin_comes_from_the_brand(canvas):
    canvas.theme.style["rounded_box_padding"] = 60
    doc = AssDoc(canvas.width, canvas.height)
    add_captions(doc, canvas, [Cue(0, 1, "linha")], CaptionStyle(mode="rounded"))
    width, _ = _drawing_size(_drawing(next(e for e in doc.events if e.layer == 4).text))
    ref = fonts.resolve("Poppins", "bold")
    assert width == pytest.approx(fonts.measure_rendered("LINHA", ref, 72)[0] + 120, abs=0.2)


def test_brand_defaults_and_validation_for_the_rounded_box():
    from dmaker.domain.brand import DEFAULT_ROUNDED_BOX_PADDING, DEFAULT_ROUNDED_BOX_RADIUS

    theme = load_theme("default")
    assert (theme.rounded_box_radius, theme.rounded_box_padding) == (
        DEFAULT_ROUNDED_BOX_RADIUS,
        DEFAULT_ROUNDED_BOX_PADDING,
    )
    custom = load_theme("default", {"style": {"rounded_box_radius": 12, "rounded_box_padding": 40}})
    assert (custom.rounded_box_radius, custom.rounded_box_padding) == (12.0, 40.0)
    broken = load_theme("default", {"style": {"rounded_box_radius": -3}})
    with pytest.raises(ValueError, match="rounded_box_radius"):
        broken.rounded_box_radius  # noqa: B018


def test_text_overlay_rounded_box_hugs_each_line(canvas):
    doc = AssDoc(canvas.width, canvas.height)
    ov = TextOverlay(
        text="Sua agenda em um clique, sem complicacao",
        role="title",
        animation="none",
        style={"box_shape": "rounded"},
    )
    add_text_overlay(doc, canvas, ov, 0)
    box, text = doc.events
    assert box.layer < text.layer and "\\p1" in box.text
    assert text.text.count("\\N") == 1  # o título quebra em duas linhas, e a caixa tem uma por linha
    assert box.text.count(" b ") >= 8  # cantos de fora e as curvas da emenda


def test_text_overlay_rounded_shape_turns_the_box_on_unless_told_otherwise(canvas):
    asked = effective_style(
        TextOverlay(text="x", role="title", style={"box_shape": "rounded"}), canvas.theme, None
    )
    assert asked["box"] is True and asked["outline"] == 0  # sem contorno grosso sobre a caixa
    assert asked["box_radius"] == canvas.theme.rounded_box_radius
    assert asked["box_padding"] == canvas.theme.rounded_box_padding
    off = effective_style(
        TextOverlay(text="x", role="title", style={"box_shape": "rounded", "box": False}), canvas.theme, None
    )
    assert off["box"] is False
    own = effective_style(
        TextOverlay(
            text="x", role="title", style={"box_shape": "rounded", "box_radius": 9, "box_padding": 11}
        ),
        canvas.theme,
        None,
    )
    assert (own["box_radius"], own["box_padding"]) == (9, 11)  # o que o texto pede na spec manda na marca
    block = effective_style(TextOverlay(text="x", role="cta"), canvas.theme, None)
    assert block["box_shape"] == "block" and block["box_radius"] == 30  # o bloco segue com o padrão do papel


def test_rounded_text_overlay_on_a_tone_keeps_readable_text(canvas):
    """Sobre cartão claro o título sem caixa vira cor da marca; com a caixa arredondada fica branco."""
    plain = effective_style(TextOverlay(text="x", role="title"), canvas.theme, "light")
    boxed = effective_style(
        TextOverlay(text="x", role="title", style={"box_shape": "rounded"}), canvas.theme, "light"
    )
    assert plain["color"] == canvas.theme.colors["primary"]
    assert boxed["color"] == "#FFFFFF"


def test_new_fields_reach_the_schema_published_by_the_mcp_and_the_ui():
    from dmaker.domain.spec import Project

    schema = Project.model_json_schema()
    defs = schema["$defs"]
    assert "rounded" in defs["CaptionStyle"]["properties"]["mode"]["enum"]
    assert defs["TextStyle"]["properties"]["box_shape"]["anyOf"][0]["enum"] == ["block", "rounded"]


def test_old_specs_without_the_new_fields_validate_and_keep_their_defaults():
    assert CaptionStyle().mode == "karaoke"
    assert TextOverlay(text="x").style.box_shape is None
    assert TextOverlay.model_validate({"text": "x", "style": {"box": True}}).style.box_shape is None
