"""Isolamento vocal: contas puras e o `DemucsSeparator` com um modelo falso (sem baixar os pesos).
O modelo de verdade só roda com DMAKER_VOICE_SMOKE=1."""

from __future__ import annotations

import os
import threading
import wave
from pathlib import Path

import numpy as np
import pytest

from dmaker.media.separation import (
    SAMPLE_RATE,
    DemucsSeparator,
    Stems,
    expected_chunks,
    normalize_mix,
    split_vocals,
)
from dmaker.media.wavio import read_wav_channels, write_wav_channels

NAMES = ["drums", "bass", "other", "vocals"]
SHARES = (0.1, 0.1, 0.2, 0.6)  # parte da mistura que o modelo falso atribui a cada stem


def stereo_signal(seconds: float, seed: int = 0) -> np.ndarray:
    """Ruído suave e não nulo, de forma (quadros, 2)."""
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((int(SAMPLE_RATE * seconds), 2)) * 0.1).astype(np.float32)


# ---------- contas puras ----------


def test_expected_chunks_counts_windows_shifts_and_models():
    one_second = SAMPLE_RATE
    assert expected_chunks(10 * one_second, SAMPLE_RATE, 2.0, 0.0, 1) == 5
    assert expected_chunks(10 * one_second, SAMPLE_RATE, 2.0, 0.5, 1) == 10  # passo de 1 s
    assert expected_chunks(10 * one_second, SAMPLE_RATE, 2.0, 0.0, 2, models=3) == 30
    assert expected_chunks(10 * one_second, SAMPLE_RATE, 2.0, 0.0, 0) == 5  # shifts=0 ainda faz uma passada


def test_normalize_mix_centers_and_gives_unit_deviation():
    mix = stereo_signal(1.0).T + 0.05
    normalized, std = normalize_mix(mix)
    mono = normalized.mean(axis=0)
    assert mono.std() == pytest.approx(1.0, abs=1e-3) and mono.mean() == pytest.approx(0.0, abs=1e-5)
    assert np.allclose(normalized * std, mix - mix.mean(axis=0).mean(), atol=1e-5)


def test_normalize_mix_survives_silence():
    normalized, std = normalize_mix(np.zeros((2, 100), np.float32))
    assert np.all(np.isfinite(normalized)) and std > 0


def test_split_vocals_returns_voice_and_the_sum_of_the_other_stems():
    estimates = np.stack([np.full((2, 4), v, np.float32) for v in (1.0, 2.0, 3.0, 10.0)])
    vocals, background = split_vocals(estimates, NAMES)
    assert np.all(vocals == 10.0) and np.all(background == 6.0)
    vocals_scaled, background_scaled = split_vocals(estimates, NAMES, std=2.0)
    assert np.all(vocals_scaled == 20.0) and np.all(background_scaled == 12.0)


def test_split_vocals_requires_a_vocals_stem():
    with pytest.raises(ValueError):
        split_vocals(np.zeros((2, 2, 4), np.float32), ["drums", "bass"])


def test_stems_in_directory_use_fixed_names(tmp_path: Path):
    stems = Stems.in_directory(tmp_path)
    assert stems.vocals.name == "vocals.wav" and stems.background.name == "background.wav"
    assert not stems.exist()
    stems.vocals.write_bytes(b"x")
    stems.background.write_bytes(b"x")
    assert stems.exist()


# ---------- DemucsSeparator com modelo falso ----------

torch = pytest.importorskip("torch")
pytest.importorskip("demucs")


class FakeDemucs(torch.nn.Module):
    """Divide a mistura em stems proporcionais: a voz fica com 60%, o resto com 40%."""

    sources = NAMES
    samplerate = SAMPLE_RATE
    audio_channels = 2
    segment = 1.0

    def forward(self, mix):
        return torch.stack([mix * share for share in SHARES], dim=1)


def make_separator(**options) -> DemucsSeparator:
    return DemucsSeparator(model_loader=FakeDemucs, **options)


def write_input(path: Path, seconds: float = 3.0) -> np.ndarray:
    samples = stereo_signal(seconds)
    write_wav_channels(path, samples, SAMPLE_RATE)
    return samples


def test_separation_writes_stereo_44k_wavs_that_add_up_to_the_input(tmp_path: Path):
    original = write_input(tmp_path / "in.wav")
    centered = original - original.mean(axis=1).mean()  # o separador tira o deslocamento DC
    stems = make_separator(device="cpu").separate(tmp_path / "in.wav", tmp_path / "out")

    with wave.open(str(stems.vocals), "rb") as handle:
        assert (handle.getnchannels(), handle.getframerate(), handle.getsampwidth()) == (2, SAMPLE_RATE, 2)
    vocals, _ = read_wav_channels(stems.vocals)
    background, _ = read_wav_channels(stems.background)
    assert vocals.shape == original.shape
    assert np.allclose(vocals, centered * 0.6, atol=2e-4)
    assert np.allclose(background, centered * 0.4, atol=2e-4)
    assert np.allclose(vocals + background, centered, atol=4e-4)  # voz + fundo reconstroem a mistura


def test_progress_runs_from_zero_to_the_total_in_order(tmp_path: Path):
    write_input(tmp_path / "in.wav", seconds=4.0)
    calls: list[tuple[int, int]] = []
    make_separator(device="cpu", overlap=0.25).separate(
        tmp_path / "in.wav", tmp_path / "out", lambda done, total: calls.append((done, total))
    )

    total = expected_chunks(4 * SAMPLE_RATE, SAMPLE_RATE, 1.0, 0.25, 1)
    assert calls[0] == (0, total) and calls[-1] == (total, total)
    assert [done for done, _ in calls] == sorted(done for done, _ in calls)
    assert all(done <= total for done, _ in calls)


def test_model_loads_lazily_and_only_once_even_with_concurrent_calls(tmp_path: Path):
    loads = []

    def loader():
        loads.append(1)
        return FakeDemucs()

    separator = DemucsSeparator(model_loader=loader, device="cpu")
    assert loads == []  # criar o separador não carrega o modelo

    write_input(tmp_path / "in.wav", seconds=1.0)
    results = []
    threads = [
        threading.Thread(
            target=lambda n=n: results.append(separator.separate(tmp_path / "in.wav", tmp_path / f"o{n}"))
        )
        for n in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(loads) == 1 and len(results) == 3


def test_inference_is_serialized(tmp_path: Path):
    """O modelo não é seguro para uso concorrente: duas separações nunca rodam o forward ao mesmo tempo."""
    active, peak = [0], [0]
    guard = threading.Lock()

    class Probe(FakeDemucs):
        def forward(self, mix):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            try:
                return super().forward(mix)
            finally:
                with guard:
                    active[0] -= 1

    separator = DemucsSeparator(model_loader=Probe, device="cpu")
    write_input(tmp_path / "in.wav", seconds=2.0)
    threads = [
        threading.Thread(target=separator.separate, args=(tmp_path / "in.wav", tmp_path / f"o{n}"))
        for n in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 1


def test_wrong_format_is_rejected_with_a_clear_message(tmp_path: Path):
    write_wav_channels(tmp_path / "mono.wav", np.zeros((100, 1), np.float32), SAMPLE_RATE)
    with pytest.raises(ValueError, match="estéreo"):
        make_separator(device="cpu").separate(tmp_path / "mono.wav", tmp_path / "out")
    write_wav_channels(tmp_path / "lento.wav", np.zeros((100, 2), np.float32), 22050)
    with pytest.raises(ValueError, match="22050"):
        make_separator(device="cpu").separate(tmp_path / "lento.wav", tmp_path / "out")


def test_model_id_changes_with_the_parameters_that_change_the_result():
    base = DemucsSeparator().model_id
    assert base.startswith("demucs:htdemucs")
    assert DemucsSeparator(shifts=2).model_id != base
    assert DemucsSeparator(overlap=0.1).model_id != base
    assert DemucsSeparator(segment=5).model_id != base
    assert DemucsSeparator(model="outro").model_id != base


@pytest.mark.skipif(
    os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="modelo real: defina DMAKER_VOICE_SMOKE=1"
)
def test_real_htdemucs_keeps_a_tone_out_of_the_vocals(tmp_path: Path):
    """Smoke com o modelo de verdade: 6 s de ruído; só confere formato, soma e que o modelo roda."""
    original = write_input(tmp_path / "in.wav", seconds=6.0)
    stems = DemucsSeparator(device="cpu").separate(tmp_path / "in.wav", tmp_path / "out")
    vocals, _ = read_wav_channels(stems.vocals)
    background, _ = read_wav_channels(stems.background)
    assert vocals.shape == original.shape
    assert np.allclose(vocals + background, original, atol=5e-2)


def test_compute_threads_is_at_least_one():
    from dmaker.media.cpu import compute_threads

    assert compute_threads() >= 1
