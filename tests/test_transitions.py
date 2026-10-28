"""Transições: registro por extensão, grafos como função pura e os planos de movimento (sem rodar o ffmpeg)."""

from __future__ import annotations

import math
import re

import pytest
from pydantic import ValidationError

from dmaker.domain import curves
from dmaker.domain.spec import Transition
from dmaker.domain.timeline import effective_transition
from dmaker.domain.transitions import MOTION_TRANSITIONS, XFADE_TYPES, all_transition_names, catalog
from dmaker.filtergraph.common import AUDIO_FMT_MIX
from dmaker.filtergraph.expressions import lookup, number, sendcmd_table
from dmaker.filtergraph.lightleak import LeakLook, leak_expressions, light_leak_source
from dmaker.filtergraph.timeline import timeline_graph
from dmaker.filtergraph.transitions import TransitionRequest, build_transition, registered_names
from dmaker.filtergraph.transitions.burn import plan_filmburn, plan_lightleak
from dmaker.filtergraph.transitions.crosszoom import BLUR_FRACTION, MIN_ZOOM, ZOOM_GAIN, plan_crosszoom
from dmaker.filtergraph.transitions.push import plan_blurslide, plan_whippan
from dmaker.filtergraph.transitions.registry import first_frame_at, frame_count
from dmaker.filtergraph.transitions.window import monotone, no_undershoot, open_window

SIZE = (1080, 1920)
MOTION = sorted(MOTION_TRANSITIONS)


def legacy_timeline_graph(n, durations, transitions, fps, want_video=True) -> list[str]:
    """O `timeline_graph` de antes das transições registradas, copiado como estava: o que o render sempre gerou
    para os tipos do xfade, e que precisa continuar saindo igual."""
    lines: list[str] = []
    for i in range(n):
        if want_video:
            lines.append(f"[{i}:v]fps={fps:g},settb=AVTB,format=yuv420p,setsar=1[tv{i}]")
        lines.append(f"[{i}:a]{AUDIO_FMT_MIX}[ta{i}]")
    runs: list[list[int]] = [[0]]
    for i in range(1, n):
        tr = transitions[i]
        if tr is None or tr.type == "cut":
            runs[-1].append(i)
        else:
            runs.append([i])
    labels: list[tuple[str | None, str, float]] = []
    for r, run in enumerate(runs):
        dur = sum(durations[i] for i in run)
        if len(run) == 1:
            i = run[0]
            labels.append((f"[tv{i}]" if want_video else None, f"[ta{i}]", dur))
            continue
        if want_video:
            ins = "".join(f"[tv{i}][ta{i}]" for i in run)
            lines.append(f"{ins}concat=n={len(run)}:v=1:a=1[rv{r}_][ra{r}]")
            lines.append(f"[rv{r}_]fps={fps:g},settb=AVTB[rv{r}]")
            labels.append((f"[rv{r}]", f"[ra{r}]", dur))
        else:
            ins = "".join(f"[ta{i}]" for i in run)
            lines.append(f"{ins}concat=n={len(run)}:v=0:a=1[ra{r}]")
            labels.append((None, f"[ra{r}]", dur))
    cur_v, cur_a, cur_len = labels[0]
    for k in range(1, len(runs)):
        vl, al, dlen = labels[k]
        tr = transitions[runs[k][0]]
        d = effective_transition(tr, cur_len, dlen)
        offset = cur_len - d
        if want_video:
            lines.append(f"{cur_v}{vl}xfade=transition={tr.type}:duration={d:.3f}:offset={offset:.3f}[xv{k}]")
            cur_v = f"[xv{k}]"
        lines.append(f"{cur_a}{al}acrossfade=d={d:.3f}:c1=tri:c2=tri[xa{k}]")
        cur_a = f"[xa{k}]"
        cur_len = cur_len + dlen - d
    return lines


def evaluate(expression: str, **variables: float) -> float:
    """Avalia no Python as expressões de tabela do FFmpeg (só números, `if` e `lt`)."""
    source = expression.replace("if(", "_if(").replace("lt(", "_lt(")
    scope = {"_if": lambda c, a, b: a if c else b, "_lt": lambda x, y: x < y, **variables}
    return eval(source, {"__builtins__": {}}, scope)  # noqa: S307 (entrada gerada pelo próprio teste)


# ---------- registro e catálogo ----------


def test_registry_and_catalog_list_the_same_transitions():
    assert registered_names() == all_transition_names()
    assert {info.name for info in catalog()} == all_transition_names()
    assert XFADE_TYPES | set(MOTION_TRANSITIONS) == all_transition_names()
    assert not XFADE_TYPES & set(MOTION_TRANSITIONS)


def test_every_transition_says_what_it_does_without_dashes():
    for info in catalog():
        assert info.summary.strip(), f"{info.name} está sem descrição"
        assert "—" not in info.summary and "–" not in info.summary


def test_the_five_motion_transitions_come_first_in_the_catalog():
    first = [info for info in catalog()[:5]]
    assert {info.name for info in first} == {"crosszoom", "whippan", "blurslide", "filmburn", "lightleak"}
    assert all(info.kind == "motion" for info in first)
    assert all(info.kind == "xfade" for info in catalog()[5:])


def test_unknown_builder_and_duplicate_registration_are_refused():
    request = TransitionRequest("[a]", "[b]", "[o]", "t", 0.5, 1.0, 30.0)
    with pytest.raises(ValueError, match="sem construtor"):
        build_transition("giro3d", request)
    from dmaker.filtergraph.transitions import register

    with pytest.raises(ValueError, match="já registrada"):
        register("fade")(lambda r: [])


# ---------- spec ----------


def test_spec_accepts_motion_types_and_a_curve_and_rejects_unknowns():
    transition = Transition(type="WhipPan", duration=0.4, curve="spring")
    assert (transition.type, transition.curve) == ("whippan", "spring")
    assert Transition(type="fade").curve == "linear"  # padrão: nada muda para quem não pede curva
    for bad in ("giro3d", "folha"):
        with pytest.raises(ValidationError, match="Transição desconhecida"):
            Transition(type=bad)
    with pytest.raises(ValidationError):
        Transition(type="fade", curve="elastico")


# ---------- transições antigas continuam idênticas ----------


@pytest.mark.parametrize("kind", sorted(XFADE_TYPES))
def test_xfade_types_with_a_linear_curve_generate_the_graph_they_always_did(kind):
    transitions = [
        None,
        Transition(type=kind, duration=0.5),
        Transition(type="cut"),
        Transition(type=kind, duration=0.8),
    ]
    durations = [4.0, 3.5, 2.0, 5.0]
    for want_video in (True, False):
        new = timeline_graph(4, durations, transitions, 30, want_video).lines
        assert new == legacy_timeline_graph(4, durations, transitions, 30, want_video)


def test_explicit_linear_curve_equals_no_curve():
    plain = timeline_graph(2, [3, 3], [None, Transition(type="wipeleft")], 30).lines
    explicit = timeline_graph(2, [3, 3], [None, Transition(type="wipeleft", curve="linear")], 30).lines
    assert plain == explicit


# ---------- curva nas transições do xfade ----------


def test_xfade_with_a_curve_remaps_the_time_of_the_first_stream_only_inside_the_window():
    graph = timeline_graph(2, [3, 3], [None, Transition(type="wipeleft", duration=0.5, curve="ease")], 30)
    text = ";".join(graph.lines)
    # a janela começa no quadro 75 (2,5 s a 30 fps); antes dele o timestamp passa como veio
    assert "[tv0]setpts='if(lt(N,75),PTS," in text
    assert "xfade=transition=wipeleft:duration=0.500:offset=2.500" in text
    assert text.count("setpts=N/30/TB[xv1]") == 1  # ritmo constante de volta na saída
    assert graph.video == "[xv1]" and graph.total == 5.5


def test_xfade_curve_table_follows_the_curve_and_never_runs_backwards():
    request = TransitionRequest("[a]", "[b]", "[o]", "tx1", 0.5, 2.5, 30.0, curve="spring")
    line = build_transition("wipeleft", request)[0]
    table = re.search(r"\((if\(lt\(\(N-75\).*\))\)/TB", line)
    assert table
    values = [evaluate(table.group(1).replace("(N-75)", "i"), i=k) for k in range(request.frames)]
    expected = monotone(curves.samples("spring", request.frames))
    assert values == pytest.approx([2.5 + 0.5 * w for w in expected], abs=1e-5)
    assert all(b >= a for a, b in zip(values, values[1:], strict=False))
    assert max(values) <= 3.0  # a mola passa de 1, a cortina não: limitado ao fim da janela


def test_first_window_frame_matches_where_xfade_starts():
    assert first_frame_at(2.5, 30) == 75
    assert first_frame_at(0.0, 30) == 0
    assert first_frame_at(4.07, 30) == 123  # o primeiro quadro que alcança o offset
    assert first_frame_at(1.5, 24) == 36
    assert frame_count(0.5, 30) == 15 and frame_count(0.01, 30) == 2


# ---------- expressões ----------


def test_number_is_short_and_has_no_scientific_notation():
    assert number(0.5) == "0.5" and number(2.0) == "2" and number(-0.00001) == "0" and number(1e-9) == "0"
    assert number(1234.5678, 2) == "1234.57"


def test_lookup_table_returns_each_frame_value_and_clamps_outside():
    values = [0.0, 0.25, 0.5, 0.75, 1.0, 0.5, 0.125]
    expression = lookup(values, "n")
    for index, value in enumerate(values):
        assert evaluate(expression, n=index) == pytest.approx(value)
    assert evaluate(expression, n=99) == values[-1]  # quadros além da tabela ficam no último valor
    assert evaluate(expression, n=-1) == values[0]
    assert lookup([3.0], "n") == "3"
    assert expression.count("if(") == len(values) - 1


def test_lookup_depth_grows_with_the_log_of_the_size():
    expression = lookup([float(k) for k in range(300)], "n")
    deepest = max(len(part) for part in re.findall(r"(?:if\(lt\()+", expression))
    assert deepest // len("if(lt(") <= 10  # busca binária: ~log2(300), não 300 ifs aninhados
    assert all(evaluate(expression, n=k) == k for k in (0, 1, 150, 299))


def test_sendcmd_table_times_each_command_half_a_frame_before_its_frame():
    text = sendcmd_table("gblur@x", "sigma", [0.0, 4.0, 8.5], 30.0)
    commands = text.split(";")
    assert commands[0] == "0 gblur@x sigma 0"
    assert commands[1] == "0.016667 gblur@x sigma 4"
    assert commands[2] == "0.05 gblur@x sigma 8.5"


# ---------- grafo das de movimento ----------


def _request(curve="linear", frames_seconds=0.5, tag="tx1", size=SIZE, offset=2.5):
    return TransitionRequest("[a]", "[b]", "[out]", tag, frames_seconds, offset, 30.0, curve, size)


@pytest.mark.parametrize("kind", MOTION)
def test_motion_transitions_need_the_frame_size(kind):
    with pytest.raises(ValueError, match="tamanho do quadro"):
        build_transition(kind, _request(size=None))


def test_window_slices_a_by_time_and_b_by_frame_count_and_stitches_them_back():
    request = _request()
    lines, window = open_window(request)
    text = ";".join(lines)
    assert "[a]split=2[tx1_a0][tx1_a1]" in text and "[b]split=2[tx1_b0][tx1_b1]" in text
    assert "trim=end=2.500000" in text and "trim=start=2.500000,setpts=N/30/TB,trim=end_frame=15" in text
    assert "trim=end_frame=15,setpts=N/30/TB[tx1_head]" in text and "trim=start_frame=15" in text
    assert (window.before, window.tail, window.head, window.after) == (
        "[tx1_before]",
        "[tx1_tail]",
        "[tx1_head]",
        "[tx1_after]",
    )


@pytest.mark.parametrize("kind", MOTION)
@pytest.mark.parametrize("curve", curves.CURVES)
def test_motion_graph_has_no_dangling_or_reused_labels(kind, curve):
    lines = build_transition(kind, _request(curve))
    produced: dict[str, int] = {}
    consumed: dict[str, int] = {}
    for line in lines:
        inputs = re.match(r"^((?:\[[^\]]+\])*)", line).group(1)
        outputs = re.search(r"((?:\[[^\]]+\])+)$", line).group(1)
        for label in re.findall(r"\[[^\]]+\]", inputs):
            consumed[label] = consumed.get(label, 0) + 1
        for label in re.findall(r"\[[^\]]+\]", outputs):
            produced[label] = produced.get(label, 0) + 1
    assert consumed.pop("[a]") == 1 and consumed.pop("[b]") == 1  # cada entrada é usada uma vez só
    assert produced.pop("[out]") == 1
    assert set(produced) == set(consumed) and all(
        count == 1 for count in [*produced.values(), *consumed.values()]
    )


@pytest.mark.parametrize("kind", MOTION)
def test_two_transitions_in_one_timeline_do_not_share_labels_or_filter_names(kind):
    transitions = [
        None,
        Transition(type=kind, duration=0.4),
        Transition(type=kind, duration=0.4, curve="ease"),
    ]
    graph = timeline_graph(3, [4.0, 4.0, 4.0], transitions, 30, True, SIZE)
    text = ";".join(graph.lines)
    for tag in ("tx1", "tx2"):
        assert f"[{tag}_" in text
    names = re.findall(r"gblur@(\w+)=", text)
    assert len(names) == len(set(names))  # cada gblur tem o seu nome: o sendcmd de um não mexe no outro
    assert graph.video == "[xv2]" and graph.total == pytest.approx(11.2)


def test_motion_transitions_through_timeline_graph_replace_the_xfade_line():
    graph = timeline_graph(2, [3, 3], [None, Transition(type="crosszoom", duration=0.5)], 30, True, SIZE)
    text = ";".join(graph.lines)
    assert "xfade=transition=crosszoom" not in text
    assert "[tv0]split=2[tx1_a0][tx1_a1]" in text and "concat=n=3:v=1:a=0" in text
    assert (
        text.endswith("[xa1]") or "acrossfade=d=0.500:c1=tri:c2=tri[xa1]" in text
    )  # o áudio segue como sempre
    assert graph.video == "[xv1]" and graph.total == 5.5


# ---------- planos de movimento ----------


@pytest.mark.parametrize("curve", curves.CURVES)
def test_crosszoom_plan_is_continuous_with_the_clips_around_it(curve):
    plan = plan_crosszoom(curve, 15)
    assert plan.zoom_out[0] == 1.0 and plan.mix[0] == 0.0 and plan.blur[0] == 0.0  # começa igual ao que sai
    assert plan.zoom_in[-1] == pytest.approx(1.0, abs=0.05 if curve == "linear" else 0.01)
    assert all(MIN_ZOOM <= z <= 1 + ZOOM_GAIN * 1.2 for z in plan.zoom_in)
    assert all(b >= a for a, b in zip(plan.mix, plan.mix[1:], strict=False)) and plan.mix[-1] == 1.0
    assert max(plan.blur) <= BLUR_FRACTION + 1e-9


def test_crosszoom_blur_peaks_in_the_middle_and_the_zoom_is_the_same_where_the_images_meet():
    plan = plan_crosszoom("linear", 15)
    assert plan.blur.index(max(plan.blur)) in (7, 8)
    middle = next(k for k, m in enumerate(plan.mix) if m >= 0.5)
    assert plan.zoom_out[middle] == pytest.approx(plan.zoom_in[middle], abs=0.05)


def test_crosszoom_with_spring_zooms_out_past_the_frame_once_and_settles():
    plan = plan_crosszoom("spring", 15)
    assert min(plan.zoom_in) < 1.0  # a mola passa do enquadramento
    assert all(
        z <= 1.0 + 1e-9 for z in plan.zoom_in[plan.zoom_in.index(min(plan.zoom_in)) :]
    )  # e não volta a passar
    assert plan.zoom_in[-1] == pytest.approx(1.0, abs=2e-3)


def test_whippan_plan_follows_the_curve_and_blurs_with_the_speed():
    linear = plan_whippan("linear", 15)
    assert linear.shift == pytest.approx([k / 15 for k in range(15)])
    assert linear.blur[7] == pytest.approx(linear.blur[3])  # velocidade constante: desfoque constante
    assert all(
        plan_whippan(curve, 15).blur[0] == 0.0 for curve in curves.CURVES
    )  # o primeiro quadro sai nítido
    ease = plan_whippan("ease", 15)
    assert ease.blur.index(max(ease.blur)) in (6, 7, 8)  # mais rápido no meio: traço mais longo no meio
    assert ease.blur[0] < 0.1 * max(ease.blur) and ease.blur[-1] < 0.1 * max(ease.blur)
    assert all(b >= a for a, b in zip(ease.shift, ease.shift[1:], strict=False))


def test_whippan_with_spring_accelerates_overshoots_once_and_settles():
    plan = plan_whippan("spring", 15)
    peak = plan.shift.index(max(plan.shift))
    assert 1.05 < max(plan.shift) < 1.15
    assert all(
        s >= 1.0 for s in plan.shift[plan.shift.index(next(s for s in plan.shift if s >= 1.0)) :]
    )  # sem recuo aquém
    assert plan.shift[-1] == pytest.approx(1.0, abs=2e-3)
    assert plan.blur.index(max(plan.blur)) < peak  # o traço mais longo é na corrida, antes do pico
    assert plan.blur[-1] < 0.01 * max(plan.blur)  # assenta nítido


def test_blurslide_blur_is_a_bell_over_the_progress():
    plan = plan_blurslide("linear", 15)
    assert plan.blur[0] == 0.0 and plan.blur.index(max(plan.blur)) in (7, 8)
    spring = plan_blurslide("spring", 15)
    assert max(spring.shift) > 1.0
    assert all(
        b < 1e-9 for s, b in zip(spring.shift, spring.blur, strict=False) if s >= 1.0
    )  # passar do ponto não desfoca


@pytest.mark.parametrize("planner", [plan_lightleak, plan_filmburn])
@pytest.mark.parametrize("curve", curves.CURVES)
def test_burn_plans_start_dark_and_swap_the_images_under_the_light(planner, curve):
    plan = planner(curve, 15)
    assert plan.intensity[0] == 0.0 and plan.mix[0] == 0.0
    assert all(0.0 <= i <= 1.0 for i in plan.intensity)
    assert all(b >= a for a, b in zip(plan.mix, plan.mix[1:], strict=False))
    swap = next(
        k for k, m in enumerate(plan.mix) if m >= 0.5
    )  # o quadro em que a imagem que entra passa a valer
    assert plan.intensity[swap] >= 0.5 * max(plan.intensity)


def test_filmburn_is_fixed_between_renders_and_lightleak_crosses_the_frame():
    assert plan_filmburn("ease", 15) == plan_filmburn("ease", 15)  # a oscilação de brilho não é sorteada
    leak = plan_lightleak("linear", 15)
    assert leak.position[0] < 0 < 1 < leak.position[-1] + 0.2
    assert all(b >= a for a, b in zip(leak.position, leak.position[1:], strict=False))


def test_monotone_and_no_undershoot_helpers():
    assert monotone([0.0, 0.4, 0.3, 1.2, 0.9]) == [0.0, 0.4, 0.4, 1.0, 1.0]
    assert no_undershoot([0.0, 0.6, 1.08, 0.97, 1.01, 0.995]) == [0.0, 0.6, 1.08, 1.0, 1.01, 1.0]
    assert no_undershoot([0.0, 0.5, 0.9]) == [0.0, 0.5, 0.9]


# ---------- gerador do vazamento de luz ----------

LOOK = LeakLook(
    edge=(200, 40, 140), mid=(255, 140, 40), core=(255, 235, 180), width=0.25, tilt=0.3, floor=0.1
)


def test_leak_expressions_cover_color_and_alpha_and_use_the_frame_tables():
    expressions = leak_expressions(LOOK, [0.0, 0.5, 1.0], [-0.2, 0.5, 1.2])
    assert set(expressions) == {"r", "g", "b", "a"}
    assert "lt(N," in expressions["a"] and "lt(N," in expressions["r"]
    assert "exp(-pow(" in expressions["r"] and "min(1,2*" in expressions["g"]
    assert expressions["a"].startswith("255*clip(1*(")  # ganho 1 por padrão


def test_leak_source_is_a_small_frame_scaled_up_with_alpha_and_the_window_timestamps():
    (line,) = light_leak_source("[leak]", SIZE, 30.0, LOOK, [0.0, 0.5, 1.0], [0.0, 0.5, 1.0])
    assert line.startswith("color=c=black@0:s=135x240:r=30")  # 1/8 de cada lado: 32 mil pixels, não 2 milhões
    assert "format=gbrap,geq=" in line and "trim=end_frame=3" in line
    assert "scale=1080:1920:flags=bicubic,format=yuva420p" in line
    assert line.endswith("settb=AVTB,setpts=N/30/TB[leak]")


def test_leak_source_requires_one_value_per_frame():
    with pytest.raises(ValueError, match="um valor por quadro"):
        light_leak_source("[leak]", SIZE, 30.0, LOOK, [0.0, 1.0], [0.0])


def test_curve_helpers_agree_with_the_domain_module():
    assert math.isclose(curves.progress("spring", 0.2), curves.samples("spring", 5)[1])
