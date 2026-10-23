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


def test_multichannel_roundtrip_keeps_channels_apart(tmp_path):
    from dmaker.media.wavio import read_wav_channels, write_wav_channels

    stereo = np.stack([np.full(100, 0.25, np.float32), np.full(100, -0.5, np.float32)], axis=1)
    path = write_wav_channels(tmp_path / "estereo.wav", stereo, 44100)
    loaded, rate = read_wav_channels(path)
    assert rate == 44100 and loaded.shape == (100, 2)
    assert np.allclose(loaded, stereo, atol=1e-4)
    mono, _ = read_wav(path)  # a leitura mono continua tirando a média dos canais
    assert np.allclose(mono, -0.125, atol=1e-4)


def test_multichannel_write_requires_frames_by_channels(tmp_path):
    import pytest

    from dmaker.media.wavio import write_wav_channels

    with pytest.raises(ValueError, match="quadros, canais"):
        write_wav_channels(tmp_path / "x.wav", np.zeros(10, np.float32), 8000)
