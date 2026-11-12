"""A persona sobreposta fica acima da legenda queimada: a faixa da legenda, o retângulo e o aviso do QA.

Régua de texto fixa e sonda falsa, sem ffmpeg: as contas de pixel são as do preset `instagram/reels`."""

from __future__ import annotations

from pathlib import Path

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import CaptionStyle, PersonaOverlay, Project
from dmaker.filtergraph.persona_rect import persona_overlay_rect
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.layout import project_layout
from dmaker.pipeline.overlay_boxes import overlay_boxes
from dmaker.pipeline.report import check_persona_over_caption
from dmaker.text.caption_band import caption_band, project_caption_band
from dmaker.text.overlays import Canvas, default_caption_y

REELS = get_preset("instagram/reels")  # 1080x1920, zona segura 220 / 420 / 60 / 150
W, H, SAFE = REELS.width, REELS.height, REELS.safe
THEME = load_theme(None, None)
CANVAS = Canvas(W, H, SAFE, THEME, total=0.0)
SCALE = 1.0


def ruler(text: str, ref, size: float, spacing: float = 0) -> tuple[float, float]:
    """Cada caractere mede 0,5 do corpo: a quebra fica previsível sem depender da fonte."""
    return len(text) * size * 0.5, size


def persona(**fields) -> PersonaOverlay:
    base = {"type": "persona", "persona": "bia", "speech": {"text": "oi"}, "width": 0.5, "aspect": "3:4"}
    return PersonaOverlay.model_validate({**base, **fields})


# ---------- a faixa da legenda ----------


def test_the_band_is_centred_on_the_default_caption_line_and_covers_the_most_lines():
    style = CaptionStyle(max_words=4, max_chars=22)
    top, bottom = caption_band(style, CANVAS, ruler)
    size = style.size * SCALE
    center = default_caption_y(CANVAS, size)
    assert (top + bottom) / 2 == center  # centrada na linha do desenho
    # largura útil 1080-2*(60+40)=880; "MMMMMM" mede 6*36=216 e quatro palavras 4*216+3*36=972: duas linhas
    assert bottom - top == 2 * size + 2 * style.outline * SCALE


def test_the_band_follows_an_explicit_y_and_one_line_styles():
    style = CaptionStyle(y=0.5, max_words=1, max_chars=8)
    top, bottom = caption_band(style, CANVAS, ruler)
    assert (top + bottom) / 2 == H * 0.5
    assert bottom - top == style.size + 2 * style.outline  # uma palavra só: uma linha


def test_the_rounded_mode_has_no_outline_and_the_boxed_mode_has_a_thick_one():
    rounded = caption_band(CaptionStyle(mode="rounded", max_words=1, max_chars=8), CANVAS, ruler)
    boxed = caption_band(CaptionStyle(mode="boxed", max_words=1, max_chars=8), CANVAS, ruler)
    assert rounded[1] - rounded[0] == 72
    assert boxed[1] - boxed[0] == 72 + 2 * 14


def test_no_band_when_the_project_burns_no_captions():
    project = Project.model_validate(
        {
            "name": "p",
            "timeline": [{"type": "card", "title": "Oi", "duration": 2}],
            "captions": {"enabled": False},
        }
    )
    assert project_caption_band(project, CANVAS, measure=ruler) is None
    assert project_caption_band(project.model_copy(update={"captions": None}), CANVAS, measure=ruler) is None
    on = project.model_copy(update={"captions": project.captions.model_copy(update={"enabled": True})})
    assert project_caption_band(on, CANVAS, measure=ruler) is not None
    assert project_caption_band(on, CANVAS, no_captions=True, measure=ruler) is None


# ---------- o retângulo ----------

BAND = (1250.0, 1440.0)


def test_without_captions_the_rect_is_the_old_one():
    assert persona_overlay_rect(persona(), W, H, SCALE, SAFE) == (
        W - SAFE.right - 40 - 540,
        H - SAFE.bottom - 40 - 720,
        540,
        720,
    )


def test_a_bottom_corner_rises_above_the_caption_with_the_margin():
    for position in ("bottom-right", "bottom-left", "bottom"):
        left, top, width, height = persona_overlay_rect(persona(position=position), W, H, SCALE, SAFE, BAND)
        assert top + height == BAND[0] - 40, position
        assert (width, height) == (540, 720)
    margin = persona_overlay_rect(persona(margin=100), W, H, SCALE, SAFE, BAND)
    assert margin[1] + margin[3] == BAND[0] - 100


def test_the_horizontal_place_does_not_change_when_it_rises():
    plain = persona_overlay_rect(persona(position="bottom-left"), W, H, SCALE, SAFE)
    risen = persona_overlay_rect(persona(position="bottom-left"), W, H, SCALE, SAFE, BAND)
    assert plain[0] == risen[0] and plain[2:] == risen[2:] and risen[1] < plain[1]


def test_top_center_and_explicit_xy_do_not_move():
    for fields in (
        {"position": "top-right"},
        {"position": "top"},
        {"position": "center"},
        {"x": 0.5, "y": 0.8},
    ):
        placed = persona_overlay_rect(persona(**fields), W, H, SCALE, SAFE, BAND)
        assert placed == persona_overlay_rect(persona(**fields), W, H, SCALE, SAFE), fields


def test_a_card_that_does_not_fit_stays_at_the_top_of_the_safe_zone():
    tall_band = (700.0, 1440.0)  # 700 - 40 - 720 fica acima da zona segura de cima (220)
    left, top, width, height = persona_overlay_rect(persona(), W, H, SCALE, SAFE, tall_band)
    assert top == SAFE.top and (width, height) == (540, 720)


def test_a_card_already_above_the_band_does_not_go_down():
    low_band = (1800.0, 1900.0)
    plain = persona_overlay_rect(persona(), W, H, SCALE, SAFE)
    assert persona_overlay_rect(persona(), W, H, SCALE, SAFE, low_band) == plain


# ---------- a caixa da interface é a do render ----------


def make_project(tmp_path: Path, overlay: dict, **extra) -> Project:
    (tmp_path / "take.mp4").write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "p",
            "output": {"preset": "instagram/reels"},
            "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
            "overlays": [overlay],
            "audio": {"normalize": "off"},
            **extra,
        }
    )
    project.base_dir = tmp_path
    return project


def prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 8.0, 1920, 1080, 30.0, True, True, False)


OVERLAY = {"type": "persona", "persona": "bia", "speech": {"text": "oi"}, "width": 0.5}


def test_the_interface_box_is_the_rect_the_render_uses(tmp_path):
    project = make_project(tmp_path, OVERLAY, captions={"source": "narration"})
    (box,) = overlay_boxes(project, REELS, THEME, prober, measure=ruler, kinds={"persona"}).boxes
    band = project_caption_band(project, CANVAS, measure=ruler)
    assert band is not None
    expected = persona_overlay_rect(project.overlays[0], W, H, SCALE, SAFE, band)
    assert box.rect == tuple(float(v) for v in expected)
    assert box.rect[1] + box.rect[3] == band[0] - 40  # e ela de fato subiu


def test_the_box_stays_in_the_corner_without_captions(tmp_path):
    project = make_project(tmp_path, OVERLAY)
    (box,) = overlay_boxes(project, REELS, THEME, prober, measure=ruler, kinds={"persona"}).boxes
    assert box.rect[1] + box.rect[3] == H - SAFE.bottom - 40


# ---------- o aviso do QA ----------


def qa_findings(tmp_path: Path, overlay: dict, **extra):
    project = make_project(tmp_path, overlay, **extra)
    return check_persona_over_caption(project, project_layout(project, prober))


def test_the_default_corner_does_not_warn(tmp_path):
    assert qa_findings(tmp_path, OVERLAY, captions={"source": "narration"}) == []


def test_xy_over_the_caption_warns_with_the_visible_span(tmp_path):
    overlay = {**OVERLAY, "x": 0.5, "y": 0.7, "start": 1.0, "end": 3.5}
    [finding] = qa_findings(tmp_path, overlay, captions={"source": "narration"})
    assert finding.level == "aviso" and finding.where == "overlays[0]"
    assert finding.message == "A persona sobreposta 1 cobre a legenda de 1,0 s a 3,5 s: mude position ou x/y."
    assert "—" not in finding.message and "–" not in finding.message


def test_a_card_that_did_not_fit_warns(tmp_path):
    overlay = {**OVERLAY, "width": 0.9, "aspect": "9:16"}  # alto demais para caber acima da legenda
    [finding] = qa_findings(tmp_path, overlay, captions={"source": "narration"})
    assert "cobre a legenda" in finding.message


def test_no_warning_without_captions_or_for_a_persona_far_from_them(tmp_path):
    assert qa_findings(tmp_path, {**OVERLAY, "x": 0.5, "y": 0.7}) == []
    assert qa_findings(tmp_path, {**OVERLAY, "x": 0.5, "y": 0.1}, captions={"source": "narration"}) == []
    assert qa_findings(tmp_path, {**OVERLAY, "x": 0.5, "y": 0.7}, captions={"enabled": False}) == []
