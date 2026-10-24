"""Linha do tempo esticada da dublagem: trechos, soma de durações, monotonicidade e posição das falas. Tudo puro."""

from __future__ import annotations

import random

import pytest

from dmaker.voice.dub_retime import (
    IDENTITY,
    RetimePlan,
    StretchWindow,
    VideoPiece,
    plan_retime,
    retimed_span,
)

TOTAL = 40.0


def pieces_of(plan: RetimePlan) -> list[tuple[float, float, float]]:
    return [(p.start, p.end, p.factor) for p in plan.pieces]


# ---------- trechos ----------


def test_no_windows_is_the_identity_and_nothing_moves():
    plan = plan_retime([], TOTAL)
    assert plan is IDENTITY and plan.is_identity and plan.stretched_pieces == ()
    assert plan.retime(12.34) == 12.34
    assert retimed_span(plan, 3.0, 2.0) == (3.0, 5.0)


def test_a_window_splits_the_file_into_before_stretched_and_after():
    plan = plan_retime([StretchWindow(10.0, 14.0, 1.25)], TOTAL)
    assert pieces_of(plan) == [(0.0, 10.0, 1.0), (10.0, 14.0, 1.25), (14.0, TOTAL, 1.0)]
    assert [p.stretched for p in plan.pieces] == [False, True, False]
    assert plan.stretched_pieces == (VideoPiece(10.0, 14.0, 1.25),)


def test_the_total_is_the_original_plus_what_each_window_grew():
    windows = [StretchWindow(2.0, 5.0, 1.2), StretchWindow(10.0, 14.0, 1.25), StretchWindow(30.0, 31.0, 1.3)]
    plan = plan_retime(windows, TOTAL)
    grown = 3.0 * 0.2 + 4.0 * 0.25 + 1.0 * 0.3
    assert plan.total_seconds == pytest.approx(TOTAL + grown)
    assert plan.source_seconds == pytest.approx(TOTAL)


def test_a_window_at_the_start_or_the_end_leaves_no_empty_piece():
    plan = plan_retime([StretchWindow(0.0, 3.0, 1.2), StretchWindow(37.0, TOTAL, 1.2)], TOTAL)
    assert pieces_of(plan) == [(0.0, 3.0, 1.2), (3.0, 37.0, 1.0), (37.0, TOTAL, 1.2)]
    whole = plan_retime([StretchWindow(0.0, TOTAL, 1.1)], TOTAL)
    assert pieces_of(whole) == [(0.0, TOTAL, 1.1)]


def test_adjacent_windows_have_no_piece_between_them():
    plan = plan_retime([StretchWindow(5.0, 8.0, 1.2), StretchWindow(8.0, 10.0, 1.3)], TOTAL)
    assert pieces_of(plan) == [(0.0, 5.0, 1.0), (5.0, 8.0, 1.2), (8.0, 10.0, 1.3), (10.0, TOTAL, 1.0)]


def test_windows_that_did_not_need_stretching_are_ignored():
    plan = plan_retime([StretchWindow(5.0, 8.0, 1.0), StretchWindow(9.0, 9.0, 1.3)], TOTAL)
    assert plan is IDENTITY


def test_unsorted_overlapping_and_out_of_range_windows_are_made_consistent():
    windows = [StretchWindow(20.0, 26.0, 1.2), StretchWindow(10.0, 22.0, 1.3), StretchWindow(38.0, 99.0, 1.1)]
    plan = plan_retime(windows, TOTAL)
    # a de 10 a 22 vem antes; a de 20 a 26 só pega o que sobra (22 a 26); a última é recortada em TOTAL
    assert pieces_of(plan) == [
        (0.0, 10.0, 1.0),
        (10.0, 22.0, 1.3),
        (22.0, 26.0, 1.2),
        (26.0, 38.0, 1.0),
        (38.0, TOTAL, 1.1),
    ]
    assert sum(p.source_seconds for p in plan.pieces) == pytest.approx(TOTAL)


def test_the_pieces_always_cover_the_file_without_gap_or_overlap():
    rng = random.Random(19)
    for _ in range(200):
        windows = []
        for _ in range(rng.randint(0, 8)):
            start = rng.uniform(-2.0, TOTAL + 2.0)
            windows.append(StretchWindow(start, start + rng.uniform(0.0, 9.0), rng.uniform(0.9, 1.35)))
        plan = plan_retime(windows, TOTAL, fps=rng.choice([None, 25.0, 30000 / 1001]))
        if plan.is_identity:
            continue
        assert plan.pieces[0].start == 0.0 and plan.pieces[-1].end == TOTAL
        for before, after in zip(plan.pieces, plan.pieces[1:], strict=False):
            assert before.end == after.start
        assert all(p.end > p.start for p in plan.pieces)
        assert plan.source_seconds == pytest.approx(TOTAL)
        assert plan.total_seconds >= TOTAL


def test_cuts_fall_on_the_frame_grid_when_the_rate_is_known():
    plan = plan_retime([StretchWindow(10.013, 14.027, 1.25)], TOTAL, fps=25.0)
    first, second, _ = plan.pieces
    # 10,013 s cai no quadro 250 (10,00 s) e 14,027 s no quadro 351 (14,04 s), a 25 quadros por segundo
    assert first.end == pytest.approx(10.0) and second.end == pytest.approx(14.04)
    for edge in (first.end, second.end):
        assert edge * 25 == pytest.approx(round(edge * 25))


def test_without_a_rate_the_cuts_are_kept_as_given():
    plan = plan_retime([StretchWindow(10.013, 14.027, 1.25)], TOTAL)
    assert plan.pieces[1].start == 10.013 and plan.pieces[1].end == 14.027


def test_an_empty_file_has_nothing_to_stretch():
    assert plan_retime([StretchWindow(0.0, 1.0, 1.2)], 0.0) is IDENTITY


# ---------- tempo no arquivo esticado ----------


def test_times_before_the_first_stretch_do_not_move():
    plan = plan_retime([StretchWindow(10.0, 14.0, 1.25)], TOTAL)
    assert plan.retime(0.0) == 0.0 and plan.retime(9.999) == pytest.approx(9.999)


def test_a_speech_inside_the_stretch_starts_where_the_stretch_starts_and_later_ones_shift_by_the_growth():
    plan = plan_retime([StretchWindow(10.0, 14.0, 1.25)], TOTAL)
    assert plan.retime(10.0) == pytest.approx(10.0)
    assert plan.retime(12.0) == pytest.approx(10.0 + 2.0 * 1.25)  # dentro: escala com o fator
    assert plan.retime(14.0) == pytest.approx(15.0)  # o fim da janela: 4 s viraram 5
    assert plan.retime(20.0) == pytest.approx(21.0)  # depois: +1 s do que cresceu
    assert plan.retime(TOTAL) == pytest.approx(plan.total_seconds)


def test_growth_accumulates_across_several_stretches():
    plan = plan_retime([StretchWindow(5.0, 9.0, 1.25), StretchWindow(20.0, 24.0, 1.5)], TOTAL)
    assert plan.retime(9.0) == pytest.approx(10.0)  # +1 s
    assert plan.retime(20.0) == pytest.approx(21.0)
    assert plan.retime(24.0) == pytest.approx(27.0)  # +1 s +2 s
    assert plan.retime(30.0) == pytest.approx(33.0)


def test_retiming_is_continuous_at_every_boundary():
    plan = plan_retime([StretchWindow(5.0, 9.0, 1.25), StretchWindow(20.0, 24.0, 1.5)], TOTAL)
    for boundary in (5.0, 9.0, 20.0, 24.0):
        assert plan.retime(boundary - 1e-9) == pytest.approx(plan.retime(boundary + 1e-9), abs=1e-6)


def test_retiming_never_goes_backwards_and_never_shrinks_a_gap():
    rng = random.Random(7)
    for _ in range(100):
        windows = [
            StretchWindow(s, s + rng.uniform(0.5, 5.0), rng.uniform(1.0, 1.3))
            for s in sorted(rng.uniform(0.0, TOTAL - 6.0) for _ in range(rng.randint(1, 6)))
        ]
        plan = plan_retime(windows, TOTAL, fps=30.0)
        instants = sorted(rng.uniform(0.0, TOTAL) for _ in range(60))
        mapped = [plan.retime(t) for t in instants]
        assert mapped == sorted(mapped)
        for (a, b), (ma, mb) in zip(
            zip(instants, instants[1:], strict=False), zip(mapped, mapped[1:], strict=False), strict=True
        ):
            assert mb - ma >= (b - a) - 1e-9  # esticar só alonga: dois instantes nunca ficam mais perto


def test_times_outside_the_file_are_clamped():
    plan = plan_retime([StretchWindow(10.0, 14.0, 1.25)], TOTAL)
    assert plan.retime(-3.0) == 0.0
    assert plan.retime(TOTAL + 5.0) == pytest.approx(plan.total_seconds)


def test_the_speech_span_starts_at_the_retimed_start_and_lasts_what_the_voice_plays():
    plan = plan_retime([StretchWindow(10.0, 14.0, 1.25)], TOTAL)
    assert retimed_span(plan, 10.0, 5.0) == pytest.approx((10.0, 15.0))
    after = retimed_span(plan, 20.0, 3.5)
    assert after == pytest.approx((21.0, 24.5))  # a voz toca em tempo real, só o começo se desloca


def test_piece_durations_follow_the_factor():
    piece = VideoPiece(2.0, 6.0, 1.25)
    assert piece.source_seconds == 4.0 and piece.output_seconds == 5.0 and piece.stretched
    assert not VideoPiece(0.0, 1.0).stretched
