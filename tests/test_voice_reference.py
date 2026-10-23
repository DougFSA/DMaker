"""Escolha da janela de referência: pontuação de fala, janelas e desempate."""

from __future__ import annotations

import numpy as np

from dmaker.text.captions import Word
from dmaker.voice.reference import (
    MAX_WINDOWS,
    choose_reference_near,
    choose_window,
    speech_score,
    split_windows,
)


def test_speech_score_counts_letters_and_digits_only():
    assert speech_score("Olá, mundo! 2026...") == 12
    assert speech_score(" ... ") == 0 and speech_score("") == 0


def test_windows_are_fifteen_seconds_with_a_shorter_last_one():
    samples = np.zeros(24000 * 40, dtype=np.float32)
    assert [len(w) / 24000 for w in split_windows(samples, 24000)] == [15.0, 15.0, 10.0]


def test_window_count_is_capped():
    samples = np.zeros(24000 * 15 * (MAX_WINDOWS + 3), dtype=np.float32)
    assert len(split_windows(samples, 24000)) == MAX_WINDOWS


def test_most_speech_wins_and_energy_breaks_ties():
    assert choose_window([5, 30, 12], [1.0, 1.0, 9.0]) == 1
    assert choose_window([10, 10], [1.0, 2.0]) == 1
    assert choose_window([0, 0], [1.0, 2.0]) is None


# ---------- referência perto de uma fala (dublagem) ----------


def _run(start: float, count: int, per_word: float = 0.5) -> list[Word]:
    return [
        Word(start + i * (per_word + 0.02), start + i * (per_word + 0.02) + per_word, f"w{start:g}-{i}", 0.9)
        for i in range(count)
    ]


def test_near_reference_prefers_the_speech_around_the_anchor_over_a_better_length_far_away():
    near = _run(10.0, 8)  # 4 s de fala em volta de 10 a 14 s
    far = _run(60.0, 16)  # 8 s, a duração ideal, mas a um minuto dali
    span = choose_reference_near([*near, *far], around=(11.0, 13.0))
    assert span is not None and 10.0 <= span.start and span.end <= 14.5


def test_near_reference_without_an_anchor_takes_the_ideal_length_anywhere():
    short = _run(1.0, 8)  # ~4 s
    ideal = _run(30.0, 16)  # ~8 s
    span = choose_reference_near([*short, *ideal], around=None)
    assert span is not None and span.start >= 30.0 and 7.0 <= span.duration <= 9.0


def test_near_reference_is_none_when_no_run_reaches_the_minimum():
    assert choose_reference_near(_run(0.0, 3), around=(0.5, 1.0)) is None


def test_near_reference_does_not_cross_a_long_pause():
    words = [*_run(0.0, 8), *_run(10.0, 8)]  # pausa grande no meio
    span = choose_reference_near(words, around=(1.0, 3.0))
    assert span is not None and span.end <= 5.0
