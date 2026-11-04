"""As curvas de ganho dos fades e dos crossfades, funções puras: cada uma tem teste numérico direto.

Os valores das cinco curvas do Fade In são os que o `afade` do ffmpeg devolve (medidos num sinal constante, ver
`test_audio_fades_integration.py`); aqui a conta pura é comparada com eles e as propriedades (monotonia, soma dos
ganhos do crossfade) são conferidas em muitos pontos.
"""

from __future__ import annotations

import itertools
import math

import pytest

from dmaker.domain.fade_curves import (
    ADJUSTABLE_SHAPES,
    AFADE_CURVE,
    CROSSFADE_TYPES,
    FADE_CURVES,
    FLOOR_DB,
    adjustable_gain,
    crossfade_gains,
    crossfade_laws,
    curve_db_points,
    fade_in_gain,
    fade_out_gain,
    gain_from_unit,
    monotonic,
    shape_position,
)

GRID = [step / 200 for step in range(201)]


@pytest.mark.parametrize("curve", FADE_CURVES)
def test_each_fade_curve_rises_monotonically_from_silence_to_full_level(curve):
    values = [fade_in_gain(curve, u) for u in GRID]
    assert monotonic(values)
    assert values[0] < 0.01 and values[-1] == pytest.approx(1.0)


def test_the_five_curves_are_different_envelopes():
    envelopes = {curve: [fade_in_gain(curve, u) for u in GRID] for curve in FADE_CURVES}
    for one, other in itertools.combinations(FADE_CURVES, 2):
        biggest = max(abs(a - b) for a, b in zip(envelopes[one], envelopes[other], strict=True))
        assert biggest > 0.1, f"{one} e {other} dão a mesma envoltória"


@pytest.mark.parametrize(
    ("curve", "u", "expected"),
    [  # os números que o `afade` do ffmpeg (tri, log, exp, hsin, qua) devolve num sinal constante
        ("linear", 0.25, 0.25),
        ("logarithmic", 0.5, 0.9398),
        ("logarithmic", 0.1, 0.8),
        ("exponential", 0.5, 0.00316),
        ("exponential", 0.9, 0.3162),
        ("sine", 0.25, 0.1464),
        ("sine", 0.5, 0.5),
        ("quadratic", 0.5, 0.25),
        ("quadratic", 0.9, 0.81),
    ],
)
def test_the_pure_curves_match_what_afade_does(curve, u, expected):
    assert fade_in_gain(curve, u) == pytest.approx(expected, abs=1e-3)


def test_each_curve_names_an_afade_curve_and_the_fade_out_is_the_fade_in_backwards():
    assert set(AFADE_CURVE) == set(FADE_CURVES)
    assert len(set(AFADE_CURVE.values())) == 5
    for curve in FADE_CURVES:
        for u in (0.0, 0.2, 0.7, 1.0):
            assert fade_out_gain(curve, u) == pytest.approx(fade_in_gain(curve, 1 - u))
        assert monotonic([fade_out_gain(curve, u) for u in GRID], rising=False)


def test_an_unknown_curve_or_shape_is_refused_with_the_valid_ones():
    with pytest.raises(ValueError, match="linear"):
        fade_in_gain("zigzag", 0.5)
    with pytest.raises(ValueError, match="up"):
        shape_position("zigzag", 0.0, 0.5)


# ---------- Fade Ajustável ----------


def test_a_partial_fade_goes_from_the_start_gain_to_the_end_gain_without_reaching_silence():
    values = [adjustable_gain("up", 0.0, 1.0, 0.4, u) for u in GRID]
    assert values[0] == pytest.approx(1.0) and values[-1] == pytest.approx(0.4)
    assert monotonic(values, rising=False)
    assert min(values) == pytest.approx(0.4)


def test_the_mid_adjust_bends_the_shape_and_zero_leaves_it_straight():
    assert shape_position("up", 0.0, 0.5) == pytest.approx(0.5)
    assert shape_position("down", 0.0, 0.5) == pytest.approx(0.5)
    assert shape_position("up", 50.0, 0.5) == pytest.approx(0.25)  # positivo demora a abrir
    assert shape_position("up", -50.0, 0.5) == pytest.approx(math.sqrt(0.5))  # negativo abre logo
    assert shape_position("up", 100.0, 0.5) < shape_position("up", 50.0, 0.5)


@pytest.mark.parametrize("shape", ADJUSTABLE_SHAPES)
@pytest.mark.parametrize("mid", [-100.0, -30.0, 0.0, 60.0, 100.0])
def test_every_shape_is_monotonic_and_reaches_both_ends(shape, mid):
    values = [shape_position(shape, mid, u) for u in GRID]
    assert monotonic(values)
    assert values[0] == pytest.approx(0.0, abs=1e-9) and values[-1] == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize(("up", "down"), [("up", "down"), ("s_up", "s_down"), ("sine_up", "sine_down")])
def test_the_down_shape_is_the_up_shape_mirrored(up, down):
    for u in (0.1, 0.35, 0.8):
        assert shape_position(down, 25.0, u) == pytest.approx(1.0 - shape_position(up, 25.0, 1.0 - u))


def test_the_s_shapes_are_smooth_at_the_ends_and_cross_the_middle_at_half():
    assert shape_position("s_up", 0.0, 0.5) == pytest.approx(0.5)
    assert shape_position("s_up", 0.0, 0.05) < 0.01  # devagar nas pontas
    assert shape_position("s_up", 0.0, 0.5) > shape_position("up", 0.0, 0.5) - 1e-9


def test_gain_units_percent_and_decibels():
    assert gain_from_unit(40.0, "percent") == pytest.approx(0.4)
    assert gain_from_unit(-6.0, "db") == pytest.approx(0.5012, abs=1e-3)
    assert gain_from_unit(0.0, "db") == 1.0


# ---------- crossfade ----------


@pytest.mark.parametrize("kind", ["constant_gain", "constant_power_1", "constant_power_2", "custom"])
def test_the_leaving_gain_falls_and_the_entering_gain_rises(kind):
    leaving = [crossfade_gains(kind, u)[0] for u in GRID]
    entering = [crossfade_gains(kind, u)[1] for u in GRID]
    assert monotonic(leaving, rising=False) and monotonic(entering)
    assert (leaving[0], leaving[-1]) == (pytest.approx(1.0), pytest.approx(0.0, abs=1e-9))
    assert (entering[0], entering[-1]) == (pytest.approx(0.0, abs=1e-9), pytest.approx(1.0))


def test_constant_gain_sums_the_amplitudes_to_one():
    for u in GRID:
        out, entering = crossfade_gains("constant_gain", u)
        assert out + entering == pytest.approx(1.0)


@pytest.mark.parametrize("kind", ["constant_power_1", "constant_power_2"])
def test_constant_power_sums_the_powers_to_one(kind):
    for u in GRID:
        out, entering = crossfade_gains(kind, u)
        assert out**2 + entering**2 == pytest.approx(1.0, abs=1e-9)


def test_constant_power_is_minus_three_db_at_the_middle_and_constant_gain_minus_six():
    out, entering = crossfade_gains("constant_power_1", 0.5)
    assert 20 * math.log10(out) == pytest.approx(-3.01, abs=0.01) and out == pytest.approx(entering)
    out, _ = crossfade_gains("constant_gain", 0.5)
    assert 20 * math.log10(out) == pytest.approx(-6.02, abs=0.01)


def test_the_custom_crossfade_uses_the_chosen_shape_and_the_leaving_side_is_its_complement():
    for u in (0.2, 0.5, 0.9):
        out, entering = crossfade_gains("custom", u, "s_up", 30.0)
        assert out + entering == pytest.approx(1.0)
        assert entering == pytest.approx(shape_position("s_up", 30.0, u))


def test_the_two_laws_of_a_crossfade_are_adjustable_fades_that_the_spec_can_write():
    leaving, entering = crossfade_laws("constant_power_1")
    assert (leaving.start_gain, leaving.end_gain) == (1.0, 0.0)
    assert (entering.start_gain, entering.end_gain) == (0.0, 1.0)
    assert {leaving.shape, entering.shape} <= set(ADJUSTABLE_SHAPES)
    with pytest.raises(ValueError, match="constant_gain"):
        crossfade_laws("zigzag")
    assert set(CROSSFADE_TYPES) == {"constant_gain", "constant_power_1", "constant_power_2", "custom"}


# ---------- da curva ao filtro ----------


def test_the_sampled_curve_is_denser_at_the_ends_and_starts_at_the_floor_when_the_gain_is_zero():
    points = curve_db_points(lambda u: u, 2.0, count=48)
    assert len(points) == 49
    instants = [at for at, _ in points]
    assert instants[0] == 0.0 and instants[-1] == pytest.approx(2.0)
    assert monotonic(instants)
    assert (instants[1] - instants[0]) < (instants[25] - instants[24]) / 10  # as pontas são mais densas
    assert points[0][1] == FLOOR_DB  # ganho zero é o piso do Envelope
    assert points[-1][1] == pytest.approx(0.0, abs=1e-3)


def test_the_sampled_points_follow_the_curve_within_two_tenths_of_a_db_where_the_sound_is_audible():
    gain = lambda u: adjustable_gain("s_up", 0.0, 0.0, 1.0, u)  # noqa: E731
    points = curve_db_points(gain, 1.0)
    for (a_at, a_db), (b_at, b_db) in zip(points, points[1:], strict=False):
        for fraction in (0.25, 0.5, 0.75):
            at = a_at + (b_at - a_at) * fraction
            interpolated = a_db + (b_db - a_db) * fraction
            true = 20 * math.log10(max(gain(at), 1e-9))
            if true > -40:  # abaixo disso o ouvido não distingue
                assert interpolated == pytest.approx(true, abs=0.2)
