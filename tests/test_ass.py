from dmaker.text.ass import (
    AssDoc,
    Event,
    Style,
    ass_alpha,
    ass_color,
    ass_time,
    escape_text,
    rect_path,
    rounded_rect_path,
)


def test_time_format():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(61.257) == "0:01:01.26"
    assert ass_time(3600 + 5.5) == "1:00:05.50"
    assert ass_time(-3) == "0:00:00.00"


def test_color_conversion_is_bgr():
    assert ass_color("#0C535A") == "&H005A530C"
    assert ass_color("#75B9A2", 128) == "&H80A2B975"
    assert ass_alpha(255) == "&HFF&"


def test_escape_text():
    assert escape_text("a{b}\nc\\d") == "a(b)\\Nc/d"


def test_drawings():
    assert rect_path(10, 4) == "m 0 0 l 10.0 0 l 10.0 4.0 l 0 4.0"
    rr = rounded_rect_path(100, 40, 10)
    assert rr.startswith("m 10.0 0") and " b " in rr
    assert rounded_rect_path(100, 40, 0) == rect_path(100, 40)


def test_doc_render_and_drop_empty_events():
    doc = AssDoc(1080, 1920)
    doc.add_style(Style(name="Cap", fontname="Poppins", fontsize=66, bold=True))
    doc.add(Event(1, 2, "Cap", "oi"))
    doc.add(Event(3, 3, "Cap", "vazio"))
    out = doc.render()
    assert "PlayResX: 1080" in out and "PlayResY: 1920" in out
    assert "Style: Cap,Poppins,66," in out and ",-1,0,0,0," in out
    assert out.count("Dialogue:") == 1
    assert "0:00:01.00,0:00:02.00,Cap" in out
