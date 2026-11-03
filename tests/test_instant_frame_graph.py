"""O quadro de um instante, partes puras: a janela da linha do tempo, o grafo dela e a conversão para RGB."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.spec import Transition
from dmaker.domain.timeline import instant_window, timeline_spans
from dmaker.filtergraph.common import Inputs
from dmaker.filtergraph.html_layer import ResolvedHtmlLayer, attach_html_layer
from dmaker.filtergraph.instant import (
    FRAME_ENCODE,
    add_window_inputs,
    display_line,
    instant_timeline_lines,
)

FPS = 30.0
FADE = Transition(type="fade", duration=1.0)
# A [0, 6], B [5, 11] (transição de 1 s: A e B juntos entre 5 e 6), C [11, 15] (corte)
DURATIONS = [6.0, 6.0, 4.0]
TRANSITIONS = [None, FADE, None]


def window_at(t: float):
    return instant_window(DURATIONS, TRANSITIONS, round(t * FPS), FPS)


def test_outside_a_transition_the_window_is_the_frame_itself_and_opens_the_first_clip_right_there():
    window = window_at(3.0)
    assert (window.first, window.last) == (0, 0)
    assert window.first_frame == 90 and window.frame_count == 1
    assert window.seek == pytest.approx(3.0) and window.origin == pytest.approx(3.0)
    assert window.durations == (pytest.approx(3.0),) and window.transitions == (None,)


def test_the_window_of_the_very_first_frame_has_nothing_to_skip():
    window = window_at(0.0)
    assert (window.first, window.last, window.first_frame, window.seek) == (0, 0, 0, 0.0)


def test_inside_a_transition_the_window_starts_where_the_transition_started():
    """O `xfade` conta o progresso do começo da janela: partir no meio dela deixaria o segundo trecho no primeiro
    quadro dele, em vez de no que a transição já alcançou (medido: o quadro saía com a cena errada)."""
    window = window_at(5.5)
    assert (window.first, window.last) == (0, 1)
    assert window.first_frame == 150  # B começa em 5 s: quadro 150
    assert window.frame_count == 166 - 150  # do começo da transição até o quadro pedido (165), inclusive
    assert window.transitions == (None, FADE)
    assert window.durations == (pytest.approx(1.0), pytest.approx(6.0))  # o que sobra de A, e B inteiro
    assert window.origin == pytest.approx(5.0)


def test_the_last_frame_of_a_transition_and_the_first_after_it():
    last_of_transition = window_at(5.0 + 29 / FPS)
    assert (last_of_transition.first, last_of_transition.last) == (0, 1)
    after = window_at(6.0)
    assert (after.first, after.last) == (1, 1) and after.first_frame == 180
    assert after.seek == pytest.approx(1.0)  # B já tocou 1 s


def test_the_frame_just_before_a_transition_is_still_the_first_clip_alone():
    window = window_at(5.0 - 1 / FPS)
    assert (window.first, window.last, window.frame_count) == (0, 0, 1)


def test_a_cut_is_not_a_transition():
    window = window_at(11.0)
    assert (window.first, window.last) == (2, 2) and window.seek == 0.0


def test_a_frame_past_the_end_has_no_window():
    assert instant_window(DURATIONS, TRANSITIONS, round(16 * FPS), FPS) is None


def test_the_window_frames_end_at_the_asked_one_for_every_instant():
    spans = timeline_spans(DURATIONS, TRANSITIONS)
    for index in range(0, 15 * 30, 7):
        window = instant_window(DURATIONS, TRANSITIONS, index, FPS)
        assert window.first_frame <= index < window.first_frame + window.frame_count
        # os trechos da janela são os que aparecem no quadro (mais os da transição que já andava)
        shown = [i for i, (a, b) in enumerate(spans) if a <= index / FPS + 1e-6 < b - 1e-6]
        assert window.first <= shown[0] and window.last >= shown[-1]


# ---------- o grafo ----------


def test_the_graph_keeps_only_the_asked_frame_and_puts_it_on_the_clock_of_the_final_video():
    window = window_at(5.5)
    lines, label = instant_timeline_lines(window, FPS, (540, 960), 165)
    graph = ";".join(lines)
    assert label == "[vclock]"
    assert "xfade=transition=fade" in graph  # a transição do render, com o mesmo teto de duração
    assert "trim=start_frame=15:end_frame=16,setpts=PTS-STARTPTS+5.500000/TB[vclock]" in graph
    assert "[0:a]" not in graph and "acrossfade" not in graph  # um quadro não tem áudio


def test_a_single_clip_window_is_one_input_with_the_frame_at_the_start():
    window = window_at(3.0)
    lines, _ = instant_timeline_lines(window, FPS, (540, 960), 90)
    assert lines[0].startswith("[0:v]fps=30,settb=AVTB,format=yuv420p,setsar=1[tv0]")
    assert lines[-1].endswith("trim=start_frame=0:end_frame=1,setpts=PTS-STARTPTS+3.000000/TB[vclock]")


def test_a_frame_outside_its_window_is_refused():
    with pytest.raises(ValueError, match="não está na janela"):
        instant_timeline_lines(window_at(3.0), FPS, (540, 960), 200)


def test_only_the_first_mezzanine_is_opened_at_the_start_of_the_window():
    inputs = Inputs()
    add_window_inputs(inputs, [Path("a.mov"), Path("b.mov")], window_at(5.5))
    # A é aberto onde a transição começa (5 s dele); B entra inteiro, como no render
    assert inputs.args == ["-ss", "5.000000", "-i", "a.mov", "-i", "b.mov"]
    seeked = Inputs()
    add_window_inputs(seeked, [Path("a.mov")], window_at(3.0))
    assert seeked.args == ["-ss", "3.000000", "-i", "a.mov"]  # um quadro solto abre o trecho nele
    whole = Inputs()
    add_window_inputs(whole, [Path("a.mov")], window_at(0.0))
    assert whole.args == ["-i", "a.mov"]  # nada a pular no começo


def test_the_frame_is_a_single_rgb_png_without_audio():
    assert FRAME_ENCODE == ["-an", "-frames:v", "1"]
    line = display_line("[v_ass]")
    # a conversão que o render faz na saída (para a BT.709 etiquetada) e a que o player faz na leitura
    assert line.startswith("[v_ass]format=yuv420p,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,")
    assert line.endswith("scale=in_color_matrix=bt709:in_range=tv,format=rgb24[vout]")


# ---------- a composição em HTML parada ----------


def test_a_still_html_layer_is_a_looped_image_that_lasts_until_the_end_of_its_window():
    lines: list[str] = []
    inputs = Inputs()
    layer = ResolvedHtmlLayer(Path("comp.png"), 4.0, 4.0 + 1 / FPS, "108", "538", still=True)
    label = attach_html_layer(lines, inputs, "[base]", layer, FPS, "v_html0")
    assert label == "[v_html0]"
    assert inputs.args == ["-loop", "1", "-framerate", "30", "-t", f"{4.0 + 1 / FPS:.3f}", "-i", "comp.png"]
    assert "tpad" not in lines[0] and "setpts" not in lines[0]  # nada de relógio de vídeo numa imagem
    assert "enable='gte(t,3.983333)*lt(t,4.016667)'" in lines[1]


def test_a_video_html_layer_still_aligns_with_the_clock_of_the_video():
    lines: list[str] = []
    layer = ResolvedHtmlLayer(Path("comp.mov"), 1.0, 2.0, "0", "0")
    attach_html_layer(lines, Inputs(), "[base]", layer, FPS, "v_html0")
    assert "tpad=stop_mode=clone:stop=1,setpts=PTS-STARTPTS+0.991667/TB" in lines[0]
