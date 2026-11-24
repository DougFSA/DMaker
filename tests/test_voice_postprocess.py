"""Acabamento das falas: valores inválidos e silêncio nas pontas."""

from __future__ import annotations

import numpy as np

from dmaker.voice.postprocess import finish_speech, sanitize_samples, trim_edge_silence

RATE = 24000


def _padded(lead_s: float, speech_s: float, tail_s: float) -> np.ndarray:
    return np.concatenate(
        [
            np.zeros(int(lead_s * RATE)),
            np.full(int(speech_s * RATE), 0.3),
            np.zeros(int(tail_s * RATE)),
        ]
    ).astype(np.float32)


def test_trim_keeps_a_short_lead_and_a_longer_tail():
    trimmed = trim_edge_silence(_padded(0.5, 1.0, 0.7), RATE)
    assert abs(len(trimmed) / RATE - (0.04 + 1.0 + 0.12)) < 0.002
    assert trimmed[0] == 0 and trimmed[int(0.04 * RATE)] == np.float32(0.3)
    assert trimmed[-1] == 0


def _decaying(speech_s: float, decay_s: float, tail_s: float) -> np.ndarray:
    """Fala seguida do decaimento da última sílaba, de -40 a -70 dBFS em linha reta no dB, e silêncio."""
    decay_db = np.linspace(-40.0, -70.0, int(decay_s * RATE))
    return np.concatenate(
        [
            np.full(int(speech_s * RATE), 0.3),
            10.0 ** (decay_db / 20.0),
            np.zeros(int(tail_s * RATE)),
        ]
    ).astype(np.float32)


def test_trim_keeps_the_whole_decay_of_the_last_syllable():
    """DMK-79: aparar a -40 dB cortava o fim da frase ainda audível."""
    samples = _decaying(1.0, 0.15, 0.6)
    trimmed = trim_edge_silence(samples, RATE)
    decay_end = int(1.15 * RATE)
    assert len(trimmed) >= decay_end
    assert np.array_equal(trimmed[:decay_end], samples[:decay_end])
    assert len(trimmed) < len(samples)


def test_trim_leaves_short_margins_alone():
    samples = _padded(0.01, 1.0, 0.01)
    assert len(trim_edge_silence(samples, RATE)) == len(samples)


def test_fully_silent_speech_comes_back_unchanged():
    silence = np.zeros(RATE, dtype=np.float32)
    assert trim_edge_silence(silence, RATE) is silence


def test_sanitize_replaces_non_finite_samples_with_silence():
    cleaned = sanitize_samples(np.array([0.1, np.nan, np.inf, -np.inf], dtype=np.float32))
    assert cleaned.tolist() == [np.float32(0.1), 0.0, 0.0, 0.0] and cleaned.dtype == np.float32


def test_finish_speech_sanitizes_then_trims():
    samples = _padded(0.4, 0.5, 0.4)
    samples[RATE // 10] = np.nan
    finished = finish_speech(samples, RATE)
    assert np.isfinite(finished).all() and len(finished) < len(samples)
