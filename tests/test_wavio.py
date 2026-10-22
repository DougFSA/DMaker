"""Leitura e escrita de WAV com a biblioteca padrão."""

from __future__ import annotations

import numpy as np

from dmaker.media.wavio import read_wav, wav_duration, write_wav


def test_roundtrip_keeps_samples_within_quantization(tmp_path):
    samples = np.sin(np.linspace(0, 20, 2400)).astype(np.float32) * 0.5
    path = write_wav(tmp_path / "sub" / "tom.wav", samples, 24000)
    loaded, rate = read_wav(path)
    assert rate == 24000 and len(loaded) == len(samples)
    assert np.max(np.abs(loaded - samples)) < 1e-4
    assert wav_duration(path) == 0.1


def test_values_outside_range_are_clipped(tmp_path):
    path = write_wav(tmp_path / "alto.wav", np.array([2.0, -2.0], dtype=np.float32), 8000)
    loaded, _ = read_wav(path)
    assert loaded.tolist() == [1.0, -1.0]
