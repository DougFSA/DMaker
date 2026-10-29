"""Onde cada palavra da legenda cai e quando ela é dita (DMK-24): a conta pura que prende um grifo à palavra, e o
resolvedor que a aplica à composição. O libass real é comparado com esta conta em `test_infographics_render.py`."""

from __future__ import annotations

import pytest

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import CaptionStyle, HtmlOverlay, Project
from dmaker.media import fonts
from dmaker.pipeline.context import RenderContext, RenderOptions
from dmaker.pipeline.infographic_anchor import anchor_html_overlay
from dmaker.text.caption_layout import find_caption_word, layout_cue
from dmaker.text.captions import Cue, Word
from dmaker.text.overlays import Canvas

WORDS = [Word(0.5, 1.0, "Hoje"), Word(1.0, 1.6, "faz"), Word(1.6, 2.4, "FRIO,"), Word(2.4, 3.5, "demais")]
CUE = Cue(0.5, 3.5, "Hoje faz FRIO, demais", WORDS)
PRESET = get_preset("instagram/reels")


def canvas(preset=PRESET) -> Canvas:
    return Canvas(preset.width, preset.height, preset.safe, load_theme(None), 6.0)


def style(**fields) -> CaptionStyle:
    return CaptionStyle(**{"size": 72, "uppercase": False, "y": 0.7, **fields})


def test_every_word_of_a_one_line_cue_gets_a_box_in_order_inside_the_line():
    placed = layout_cue(CUE, style(), canvas())
    assert [word.text for word in placed] == ["Hoje", "faz", "FRIO,", "demais"]
    lefts = [word.left for word in placed]
    assert lefts == sorted(lefts) and all(
        a.right < b.left + 40 for a, b in zip(placed, placed[1:], strict=False)
    )
    # a linha é centrada no quadro: o meio da primeira ponta ao fim da última é o meio da largura
    assert (placed[0].left + placed[-1].right) / 2 == pytest.approx(540, abs=8)
    assert all(word.height > 0 and word.width > 0 for word in placed)


def test_the_box_is_the_ink_of_the_word_not_the_whole_line_cell():
    [word] = layout_cue(Cue(0, 1, "frio", [Word(0, 1, "frio")]), style(), canvas())
    size = 72 * canvas().scale
    assert word.height < size * 0.6  # as letras ocupam bem menos que a célula da linha (1,76 do corpo)
    ref = fonts.resolve("Poppins", "bold")
    assert word.width == pytest.approx(fonts.measure_rendered("frio", ref, size)[0], rel=0.01)
    assert word.top < 0.7 * 1920 < word.bottom + size  # e ficam em volta do y da legenda (70% da altura)


def test_the_time_is_the_karaoke_window_of_the_word_and_the_line_end():
    first, _, third, last = layout_cue(CUE, style(), canvas())
    assert (first.start, first.end, first.line_end) == (0.5, 1.0, 3.5)
    assert (third.start, third.end) == (1.6, 2.4) and last.end == 3.5


def test_uppercase_widens_the_box_and_a_lower_size_narrows_it():
    lower = Cue(0, 2, "hoje frio", [Word(0, 1, "hoje"), Word(1, 2, "frio")])
    plain = layout_cue(lower, style(), canvas())[1]
    upper = layout_cue(lower, style(uppercase=True), canvas())[1]
    small = layout_cue(lower, style(size=40), canvas())[1]
    assert upper.width > plain.width * 1.05 and small.width < plain.width * 0.7


def test_a_long_cue_wraps_into_rows_and_the_rounded_mode_leaves_room_for_the_box_padding():
    words = [Word(i * 0.4, i * 0.4 + 0.4, f"palavra{i}") for i in range(7)]
    cue = Cue(0, 2.8, " ".join(w.text for w in words), words)
    karaoke = layout_cue(cue, style(), canvas())
    rounded = layout_cue(cue, style(mode="rounded"), canvas())
    assert len({round(word.top) for word in karaoke}) >= 2  # quebrou em mais de uma linha
    assert len({round(word.top) for word in rounded}) >= len({round(word.top) for word in karaoke})
    for placed in (karaoke, rounded):
        assert (
            min(word.left for word in placed) >= PRESET.safe.left
            and max(word.right for word in placed) <= 1080
        )


def test_the_preview_is_the_same_layout_at_half_the_size():
    full = layout_cue(CUE, style(), canvas())[2]
    half_preset = PRESET.preview()
    half = layout_cue(CUE, style(), canvas(half_preset))[2]
    assert half.left == pytest.approx(full.left / 2, abs=2) and half.right == pytest.approx(
        full.right / 2, abs=2
    )
    assert half.top == pytest.approx(full.top / 2, abs=2) and half.bottom == pytest.approx(
        full.bottom / 2, abs=2
    )


def test_a_cue_without_word_times_spreads_the_duration_by_word_length():
    cue = Cue(0, 4, "um dois tres", [])
    placed = layout_cue(cue, style(), canvas())
    assert [word.text for word in placed] == ["um", "dois", "tres"]
    assert placed[0].start == 0 and placed[-1].end == pytest.approx(4, abs=0.2)
    assert placed[0].end - placed[0].start < placed[1].end - placed[1].start


# ---------- achar a palavra ----------


def cues() -> list[Cue]:
    second = [Word(5.0, 5.4, "o"), Word(5.4, 6.0, "frio")]
    return [CUE, Cue(5.0, 6.0, "o frio", second)]


def test_the_word_is_found_ignoring_case_accent_and_punctuation():
    for target in ("frio", "FRIO", " Frio ", "frio,"):
        word = find_caption_word(cues(), target, style(), canvas())
        assert word is not None and word.text == "FRIO," and word.start == 1.6
    accented = [Cue(0, 2, "está aí", [Word(0, 1, "está"), Word(1, 2, "aí")])]
    assert find_caption_word(accented, "ESTA", style(), canvas()).text == "está"


def test_the_occurrence_and_the_search_window_pick_which_time_the_word_is_said():
    second = find_caption_word(cues(), "frio", style(), canvas(), occurrence=2)
    assert second is not None and second.start == 5.4
    assert find_caption_word(cues(), "frio", style(), canvas(), occurrence=3) is None
    assert find_caption_word(cues(), "frio", style(), canvas(), after=3.0).start == 5.4
    assert find_caption_word(cues(), "frio", style(), canvas(), after=3.0, before=5.0) is None
    assert find_caption_word(cues(), "calor", style(), canvas()) is None


# ---------- o resolvedor aplicado à composição ----------


def render_context(project: Project) -> tuple[RenderContext, list[str]]:
    from pathlib import Path

    ctx = RenderContext(
        project=project,
        options=RenderOptions(),
        theme=load_theme(None),
        preset=PRESET,
        fps=30,
        job_dir=Path("."),
        cache_dir=Path("."),
        runner=None,
        prober=None,
        matter=None,
        narrator=None,
        isolator=None,
        log=lambda message: None,
    )
    return ctx, ctx.warnings


def pinned(**anchor) -> tuple[RenderContext, HtmlOverlay]:
    project = Project.model_validate(
        {
            "name": "p",
            "timeline": [{"type": "card", "flat": True, "duration": 8}],
            "captions": {"source": "x.srt", "style": {"size": 72, "uppercase": False, "y": 0.7}},
            "overlays": [{"type": "html", "infographic": "grifo", "anchor": {"word": "frio", **anchor}}],
        }
    )
    ctx, _ = render_context(project)
    return ctx, project.overlays[0]


def test_the_anchored_composition_gets_the_start_the_end_and_the_box_of_the_word():
    ctx, overlay = pinned(margin=24, hold="line")
    resolved = anchor_html_overlay(ctx, overlay, [CUE], 8.0, 0)
    word = find_caption_word([CUE], "frio", ctx.project.captions.style, canvas(), after=0)
    assert (resolved.start, resolved.end) == (1.6, 3.5)  # da palavra ao fim da linha
    left, right = word.left - 24, word.right + 24
    assert resolved.x * 1080 == pytest.approx((left + right) / 2, abs=0.5)
    assert resolved.width * 1080 == pytest.approx(right - left, abs=0.5)
    assert resolved.y * 1920 == pytest.approx((word.top + word.bottom) / 2, abs=0.5)
    assert resolved.height * 1920 == pytest.approx(word.height + 48, abs=0.5) and resolved.region is None
    assert resolved.anchor is not None  # a spec original continua com a âncora


def test_hold_word_ends_with_the_word_and_the_margin_scales_with_the_preview():
    ctx, overlay = pinned(hold="word", margin=40)
    assert anchor_html_overlay(ctx, overlay, [CUE], 8.0, 0).end == 2.4
    half = ctx.__class__(**{**ctx.__dict__, "preset": PRESET.preview()})
    small = anchor_html_overlay(half, overlay, [CUE], 8.0, 0)
    big = anchor_html_overlay(ctx, overlay, [CUE], 8.0, 0)
    assert small.width == pytest.approx(
        big.width, abs=0.003
    )  # as frações do quadro não dependem do tamanho dele


def test_a_word_that_is_not_in_the_caption_or_a_project_without_captions_warns_and_is_ignored():
    ctx, overlay = pinned()
    missing = overlay.model_copy(
        update={"anchor": overlay.anchor.model_copy(update={"word": "calor", "occurrence": 2})}
    )
    assert anchor_html_overlay(ctx, missing, [CUE], 8.0, 3) is None
    assert ctx.warnings == ["overlays[3]: a palavra 'calor' (2ª vez) não aparece na legenda; foi ignorada"]
    assert anchor_html_overlay(ctx, overlay, None, 8.0, 0) is None
    assert "não há legenda neste render" in ctx.warnings[-1]


def test_a_composition_without_an_anchor_passes_through_untouched():
    ctx, _ = pinned()
    plain = HtmlOverlay.model_validate({"type": "html", "src": "x"})
    assert anchor_html_overlay(ctx, plain, [CUE], 8.0, 0) is plain
