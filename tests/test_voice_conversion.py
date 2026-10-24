"""Plano de blocos e emenda da conversão de voz, e a medida de fala usada no embedding: funções puras."""

from __future__ import annotations

import numpy as np
import pytest

from dmaker.voice.conversion import (
    Block,
    complementary_fade,
    plan_blocks,
    plan_cuts,
    stitch_blocks,
)
from dmaker.voice.levels import frame_rms, speech_only

RATE = 8000


def speech_with_pauses(total_seconds: float, pause_every: float = 10.0) -> np.ndarray:
    """Seno contínuo com uma pausa de meio segundo a cada `pause_every` segundos."""
    t = np.arange(int(total_seconds * RATE)) / RATE
    samples = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    for pause_start in np.arange(pause_every, total_seconds, pause_every):
        samples[int(pause_start * RATE) : int((pause_start + 0.5) * RATE)] = 0.0
    return samples


# ---------- cortes ----------


def test_short_audio_needs_no_cut():
    assert plan_cuts(speech_with_pauses(20.0), RATE, block_seconds=25.0) == []


def test_cuts_land_on_the_silences_near_each_block_size():
    samples = speech_with_pauses(75.0, pause_every=5.0)
    cuts = plan_cuts(samples, RATE, block_seconds=25.0, search_seconds=4.0)
    assert len(cuts) == 2
    for cut in cuts:
        frame = frame_rms(samples, RATE)[int(cut / 0.01)]
        assert frame < 1e-6, f"o corte em {cut:.2f} s não caiu numa pausa"
    assert cuts[1] - cuts[0] == pytest.approx(25.0, abs=4.5)


def test_a_leftover_smaller_than_half_a_block_joins_the_last_block():
    samples = speech_with_pauses(30.0)
    assert plan_cuts(samples, RATE, block_seconds=25.0) == []


# ---------- blocos ----------


def test_blocks_overlap_their_neighbours_and_cover_everything():
    blocks = plan_blocks(60.0, [24.0, 49.0], overlap_seconds=1.0)
    assert blocks == [
        Block(start=0.0, end=25.0, keep_start=0.0, keep_end=24.0),
        Block(start=23.0, end=50.0, keep_start=24.0, keep_end=49.0),
        Block(start=48.0, end=60.0, keep_start=49.0, keep_end=60.0),
    ]


def test_single_block_has_no_overlap_to_cut():
    assert plan_blocks(12.0, []) == [Block(start=0.0, end=12.0, keep_start=0.0, keep_end=12.0)]


def test_plan_rejects_an_empty_duration():
    with pytest.raises(ValueError, match="maior que zero"):
        plan_blocks(0.0, [])


# ---------- emenda ----------


def test_complementary_fades_sum_to_one_everywhere():
    for length in (1, 7, 480):
        rise, fall = complementary_fade(length)
        assert rise.shape == fall.shape == (length,)
        np.testing.assert_allclose(rise + fall, 1.0, atol=1e-6)
    rise, _ = complementary_fade(100)
    assert rise[0] < 0.01 and rise[-1] > 0.99 and np.all(np.diff(rise) > 0)


def test_stitching_identical_blocks_rebuilds_the_source_exactly():
    """Cada bloco devolve a própria fatia da fonte: depois da emenda, nada muda (sem pico nem buraco)."""
    samples = speech_with_pauses(75.0, pause_every=5.0)
    blocks = plan_blocks(75.0, plan_cuts(samples, RATE, block_seconds=25.0))
    assert len(blocks) == 3
    pieces = [samples[round(b.start * RATE) : round(b.end * RATE)] for b in blocks]
    rebuilt = stitch_blocks(blocks, pieces, RATE, len(samples))
    assert len(rebuilt) == len(samples)
    np.testing.assert_allclose(rebuilt, samples, atol=1e-5)


def test_stitching_tolerates_a_block_a_few_samples_short():
    """O modelo devolve até um quadro a menos: o fim do bloco completa com silêncio sem deslocar nada."""
    samples = speech_with_pauses(30.0)
    blocks = plan_blocks(30.0, [15.0])
    pieces = [samples[round(b.start * RATE) : round(b.end * RATE) - 100] for b in blocks]
    rebuilt = stitch_blocks(blocks, pieces, RATE, len(samples))
    assert len(rebuilt) == len(samples)
    np.testing.assert_allclose(rebuilt[: 14 * RATE], samples[: 14 * RATE], atol=1e-5)


def test_stitching_needs_one_result_per_block():
    with pytest.raises(ValueError, match="um resultado para cada bloco"):
        stitch_blocks(plan_blocks(10.0, [5.0]), [np.zeros(10, dtype=np.float32)], RATE, 10 * RATE)


# ---------- só a fala ----------


def test_speech_only_drops_the_pauses():
    samples = speech_with_pauses(10.5, pause_every=5.0)
    spoken = speech_only(samples, RATE)
    assert 9.4 * RATE < len(spoken) < 10.1 * RATE  # perdeu o meio segundo de pausa
    assert np.all(np.abs(spoken) > 0) or np.count_nonzero(spoken) > 0.99 * len(spoken)


def test_speech_only_limits_the_length_taking_the_middle():
    samples = speech_with_pauses(30.0, pause_every=1000.0)
    spoken = speech_only(samples, RATE, limit_seconds=5.0)
    assert len(spoken) == pytest.approx(5.0 * RATE, abs=0.02 * RATE)


def test_speech_only_returns_silence_untouched():
    silence = np.zeros(RATE, dtype=np.float32)
    assert speech_only(silence, RATE) is silence
