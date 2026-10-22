"""Escolha da janela de referência: pontuação de fala, janelas e desempate."""

from __future__ import annotations

import numpy as np

from dmaker.voice.reference import MAX_WINDOWS, choose_window, speech_score, split_windows


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
