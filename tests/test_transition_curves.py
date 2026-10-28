"""Curvas de tempo das transições: extremos, ritmo do ease e o passa-e-assenta da mola."""

from __future__ import annotations

import pytest

from dmaker.domain.curves import CURVES, progress, samples

FRAMES = 15


def _speeds(values: list[float]) -> list[float]:
    return [b - a for a, b in zip(values, values[1:], strict=False)]


@pytest.mark.parametrize("curve", CURVES)
def test_every_curve_starts_at_zero_and_ends_at_one(curve):
    assert progress(curve, 0.0) == 0.0
    assert progress(curve, 1.0) == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("curve", CURVES)
def test_time_outside_the_window_is_clamped(curve):
    assert progress(curve, -3.0) == progress(curve, 0.0)
    assert progress(curve, 7.0) == progress(curve, 1.0)


def test_linear_is_the_identity():
    for u in (0.0, 0.1, 0.5, 0.93, 1.0):
        assert progress("linear", u) == u


def test_ease_is_monotonic_symmetric_and_gentle_at_both_ends():
    values = [progress("ease", k / 100) for k in range(101)]
    assert all(b >= a for a, b in zip(values, values[1:], strict=False))
    assert progress("ease", 0.5) == pytest.approx(0.5)
    assert progress("ease", 0.2) + progress("ease", 0.8) == pytest.approx(1.0)
    # parte e chega devagar: no primeiro e no último décimo anda bem menos que na linear
    assert progress("ease", 0.1) < 0.01 and progress("ease", 0.9) > 0.99


def test_spring_passes_the_target_a_little_and_settles():
    values = [progress("spring", k / 200) for k in range(201)]
    peak = max(values)
    assert 1.05 < peak < 1.15  # passa uns 10%: lê como mola sem balançar a imagem
    assert values.index(peak) < 0.4 * len(values)  # a passada vem logo, não no fim
    assert all(abs(v - 1.0) < 0.01 for v in values[int(0.7 * 200) :])  # assenta bem antes do fim
    assert values[-1] == pytest.approx(1.0, abs=1e-3)


def test_spring_accelerates_then_settles_frame_by_frame():
    """O deslocamento quadro a quadro: a mola corre no começo e quase não anda no fim, o ease é simétrico e a
    linear é constante."""
    linear, ease, spring = (samples(curve, FRAMES) for curve in ("linear", "ease", "spring"))
    linear_steps, ease_steps, spring_steps = _speeds(linear), _speeds(ease), _speeds(spring)
    assert max(linear_steps) - min(linear_steps) < 1e-9
    assert abs(ease_steps.index(max(ease_steps)) - len(ease_steps) / 2) <= 1
    fastest = spring_steps.index(max(spring_steps))
    assert fastest < len(spring_steps) / 3
    assert max(spring_steps) > max(linear_steps) * 2.5  # acelera bem mais que a linear
    assert all(abs(step) < 0.05 * max(spring_steps) for step in spring_steps[-4:])  # assenta
    # chega perto do ponto final antes que o ease e a linear
    first_at = {
        name: next(k for k, v in enumerate(values) if v >= 0.9)
        for name, values in (("linear", linear), ("ease", ease), ("spring", spring))
    }
    assert first_at["spring"] < first_at["ease"] < first_at["linear"]


def test_samples_are_one_per_frame_and_the_last_is_before_one():
    values = samples("linear", FRAMES)
    assert len(values) == FRAMES and values[0] == 0.0
    # o quadro que vale 1 é o primeiro do trecho seguinte
    assert values[-1] == pytest.approx((FRAMES - 1) / FRAMES)


def test_unknown_curve_is_refused_in_portuguese():
    with pytest.raises(ValueError, match="Curva desconhecida"):
        progress("elastico", 0.5)
