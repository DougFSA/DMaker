"""Sincronização por áudio: sinais sintéticos deslocados devem devolver o deslocamento certo."""

import numpy as np
import pytest

from dmaker.media.audiosync import RATE, SyncResult, estimate_offset


def _event_audio(seconds: float, seed: int = 1) -> np.ndarray:
    """Som de evento: ruído com rajadas (palmas, música) para a correlação ter o que agarrar."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    signal = rng.normal(0, 0.02, n).astype(np.float32)
    for start in rng.uniform(0, seconds - 0.5, size=int(seconds * 2)):
        i = int(start * RATE)
        burst = rng.normal(0, 0.4, int(0.15 * RATE)) * np.hanning(int(0.15 * RATE))
        signal[i : i + len(burst)] += burst.astype(np.float32)
    return signal


@pytest.mark.parametrize("offset", [1.234, 17.5, -3.75])
def test_estimate_offset_recovers_shift(offset):
    master = _event_audio(120)
    shift = int(round(offset * RATE))
    # other = trecho do mesmo som, começando `offset` s depois do master (ou antes, se negativo)
    if shift >= 0:
        other = master[shift:].copy()
    else:
        other = np.concatenate([np.zeros(-shift, dtype=np.float32), master])
    other += np.random.default_rng(7).normal(0, 0.01, len(other)).astype(np.float32)  # microfone diferente
    result = estimate_offset(master, other)
    assert result.offset == pytest.approx(offset, abs=0.002)
    assert result.reliable


def test_long_recordings_use_coarse_stage(monkeypatch):
    master = _event_audio(900, seed=3)  # 15 min
    other = master[int(400.5 * RATE) : int(700 * RATE)].copy()  # gravador ligou em 400.5 s
    result = estimate_offset(master, other)
    assert result.offset == pytest.approx(400.5, abs=0.002)


def test_unrelated_audio_has_low_confidence():
    a = _event_audio(30, seed=1)
    b = _event_audio(30, seed=99)
    assert isinstance(estimate_offset(a, b), SyncResult)
    assert estimate_offset(a, b).confidence < estimate_offset(a, a).confidence
