"""A estimativa de andamento (BPM) e do primeiro tempo, sobre sinais de teste de andamento conhecido.

Critério do card: a detecção acerta numa faixa de ritmo a 90, 120 e 128 BPM (±1 BPM). Aqui o sinal é gerado em numpy (cliques
de 5 ms, com o primeiro tempo de cada compasso mais forte, como a Faixa de Ritmo); o teste com a Faixa de Ritmo gerada pelo
ffmpeg de verdade está em `test_music_tempo_integration.py`.
"""

from __future__ import annotations

import numpy as np
import pytest

from dmaker.analysis import parse_analyzer
from dmaker.analysis.signal import Signal
from dmaker.analysis.tempo import attack_strength, beats_from_grid, estimate_tempo

RATE = 48000


def clicks(
    bpm: float, seconds: float = 20.0, offset: float = 0.0, accent: int = 4, noise: float = 0.0
) -> np.ndarray:
    """Cliques de 1 kHz (5 ms, janela de Hann) a cada tempo; o primeiro de cada `accent` tempos é duas vezes mais forte."""
    samples = np.zeros(int(seconds * RATE))
    t = np.arange(int(0.005 * RATE)) / RATE
    click = np.sin(2 * np.pi * 1000 * t) * np.hanning(len(t))
    period = 60.0 / bpm
    for number in range(int((seconds - offset) / period)):
        start = int(round((offset + number * period) * RATE))
        gain = 0.8 if accent and number % accent == 0 else 0.4
        samples[start : start + len(click)] += gain * click
    if noise:
        samples += np.random.default_rng(7).normal(0.0, noise, len(samples))
    return samples


@pytest.mark.parametrize("bpm", [90.0, 120.0, 128.0])
def test_the_estimate_hits_the_card_tempos_within_one_bpm(bpm):
    estimate = estimate_tempo(clicks(bpm), RATE)
    assert estimate is not None
    assert estimate.bpm == pytest.approx(bpm, abs=1.0)
    assert estimate.confidence > 0.3


@pytest.mark.parametrize("bpm", [75.0, 97.5, 140.0])
def test_other_tempos_are_found_too(bpm):
    assert estimate_tempo(clicks(bpm), RATE).bpm == pytest.approx(bpm, abs=1.0)


def test_a_very_fast_tempo_is_read_at_half_and_the_double_comes_as_the_other_reading():
    """Acima de uns 155 BPM os dois tempos (87 e 174) soam igualmente certos; a estimativa fica com o médio."""
    estimate = estimate_tempo(clicks(174.0), RATE)
    assert estimate.bpm == pytest.approx(87.0, abs=1.0)
    assert 174.0 in estimate.alternatives


def test_an_accented_bar_does_not_read_as_a_quarter_of_the_tempo():
    """O Achar Batidas sozinho marcava só os tempos fortes e a mediana dava 22,5 em vez de 90."""
    assert estimate_tempo(clicks(90.0, accent=4), RATE).bpm == pytest.approx(90.0, abs=1.0)
    assert estimate_tempo(clicks(90.0, accent=3), RATE).bpm == pytest.approx(90.0, abs=1.0)
    assert estimate_tempo(clicks(90.0, accent=0), RATE).bpm == pytest.approx(90.0, abs=1.0)


def test_the_first_beat_is_where_the_clicks_start():
    estimate = estimate_tempo(clicks(120.0, offset=0.23), RATE)
    assert estimate.beat_offset == pytest.approx(0.23, abs=0.008)
    assert estimate_tempo(clicks(120.0, offset=0.0), RATE).beat_offset == pytest.approx(0.0, abs=0.008)


def test_the_estimate_survives_background_noise():
    estimate = estimate_tempo(clicks(100.0, noise=0.03), RATE)
    assert estimate.bpm == pytest.approx(100.0, abs=1.0)


def test_the_other_readings_are_the_half_and_the_double_that_fit_the_range():
    estimate = estimate_tempo(clicks(120.0), RATE)
    assert estimate.alternatives == (60.0,)  # o dobro (240) passa dos 200 BPM
    assert 90.0 * 2 in estimate_tempo(clicks(90.0), RATE).alternatives


def test_a_signal_without_attacks_or_too_short_has_no_tempo():
    assert estimate_tempo(np.zeros(RATE * 5), RATE) is None
    assert estimate_tempo(clicks(120.0, seconds=1.0), RATE) is None
    assert estimate_tempo(np.zeros(0), RATE) is None


def test_the_attack_strength_only_counts_rises_in_energy():
    series, step = attack_strength(clicks(120.0, seconds=3.0), RATE)
    assert step == pytest.approx(0.001, rel=0.05)
    assert series.min() >= 0.0 and series.max() > 0.0


def test_the_beat_finder_now_reports_the_tempo_from_the_whole_pattern():
    result = parse_analyzer("beats", {}).analyze(Signal(clicks(90.0).reshape(-1, 1).astype(np.float32), RATE))
    assert result.bpm == pytest.approx(90.0, abs=1.0)
    assert result.beat_offset == pytest.approx(0.0, abs=0.008)
    assert result.bpm_confidence > 0.3 and 180.0 in result.bpm_alternatives


def test_a_grid_of_beats_from_an_offset_and_a_tempo():
    assert beats_from_grid(0.25, 120.0, 2.0) == [0.25, 0.75, 1.25, 1.75]
    assert beats_from_grid(3.0, 120.0, 2.0) == []
