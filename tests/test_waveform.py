"""Forma de onda das trilhas de áudio: cálculo de picos (puro), caminho de cache, `WaveformBuilder`
com dependências falsas e a API da interface (GET /api/waveform)."""

from __future__ import annotations

import os
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.media import waveform as waveform_module
from dmaker.media.ffmpeg import FFmpegError, RecordingRunner
from dmaker.media.waveform import (
    ANALYSIS_RATE,
    PEAKS_PER_SECOND,
    Waveform,
    WaveformBuilder,
    peaks_from_samples,
    waveform_path,
)
from dmaker.ui import server

# ---------- peaks_from_samples (puro) ----------


def test_peaks_from_samples_counts_one_window_per_slice_and_normalizes():
    rate = 8000
    pps = 50
    window = rate // pps  # 160 amostras por janela
    samples = np.zeros(window * 4, dtype=np.float32)
    samples[0:window] = 0.5  # janela 0: pico médio
    samples[window : window * 2] = -1.0  # janela 1: o maior pico (módulo), vira a referência 1.0
    # janelas 2 e 3 ficam em silêncio
    peaks = peaks_from_samples(samples, rate, pps)
    assert len(peaks) == 4
    assert peaks[0] == pytest.approx(0.5)
    assert peaks[1] == pytest.approx(1.0)
    assert peaks[2] == 0.0 and peaks[3] == 0.0


def test_peaks_from_samples_counts_partial_last_window():
    rate = 8000
    pps = 50
    window = rate // pps
    samples = np.full(window + 10, 0.25, dtype=np.float32)  # uma janela cheia + um resto
    peaks = peaks_from_samples(samples, rate, pps)
    assert len(peaks) == 2  # a última janela, mesmo incompleta, também vira um pico
    assert peaks[0] == pytest.approx(1.0) and peaks[1] == pytest.approx(1.0)  # mesmo valor: normaliza igual


def test_peaks_from_samples_silence_is_all_zero():
    peaks = peaks_from_samples(np.zeros(8000, dtype=np.float32), 8000, 50)
    assert len(peaks) == 50
    assert all(p == 0.0 for p in peaks)


def test_peaks_from_samples_empty_input_is_empty():
    assert peaks_from_samples(np.array([], dtype=np.float32), 8000, 50) == []


# ---------- Waveform.to_dict / from_dict ----------


def test_waveform_round_trips_through_dict():
    original = Waveform(duration=2.5, peaks_per_second=50, peaks=[0.1, 0.9, 1.0])
    restored = Waveform.from_dict(original.to_dict())
    assert restored == original


# ---------- waveform_path ----------


def test_waveform_path_is_stable_and_lives_in_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WAVEFORM_DIR", tmp_path / "waveform")
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"conteudo")
    first = waveform_path(src)
    assert waveform_path(src) == first
    assert first.parent == config.WAVEFORM_DIR
    assert first.suffix == ".json"


def test_waveform_path_changes_when_source_or_stream_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WAVEFORM_DIR", tmp_path / "waveform")
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"conteudo")
    before = waveform_path(src)

    future = time.time() + 5
    os.utime(src, (future, future))
    assert waveform_path(src) != before  # fonte reeditada: cache novo

    assert waveform_path(src, stream=1) != waveform_path(src, stream=0)  # faixa diferente: cache diferente


# ---------- WaveformBuilder ----------


def _write_tone_and_silence_wav(path: Path, rate: int, tone_seconds: float, silence_seconds: float) -> None:
    """Um wav mono sintético: `tone_seconds` de tom puro seguidos de `silence_seconds` de silêncio."""
    t = np.arange(int(tone_seconds * rate)) / rate
    tone = (np.sin(2 * np.pi * 440.0 * t) * 0.8 * 32767).astype(np.int16)
    silence = np.zeros(int(silence_seconds * rate), dtype=np.int16)
    pcm = np.concatenate([tone, silence])
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


def test_waveform_builder_computes_peaks_high_in_tone_and_low_in_silence(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WAVEFORM_DIR", tmp_path / "waveform")
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"video")

    def on_run(command):
        dst = Path(command.args[-1])
        _write_tone_and_silence_wav(dst, ANALYSIS_RATE, tone_seconds=1.0, silence_seconds=1.0)

    runner = RecordingRunner(on_run=on_run)
    workdir = tmp_path / "tmp"
    builder = WaveformBuilder(runner, workdir=workdir)

    waveform = builder.build(src)

    assert len(runner.commands) == 1
    assert "-ar" in runner.commands[0] and str(ANALYSIS_RATE) in runner.commands[0]
    assert waveform.peaks_per_second == PEAKS_PER_SECOND
    assert waveform.duration == pytest.approx(2.0, abs=0.01)

    half = len(waveform.peaks) // 2
    assert min(waveform.peaks[: half - 2]) > 0.5  # trecho do tom: picos altos
    assert max(waveform.peaks[half + 2 :]) < 0.05  # trecho de silêncio: quase zero
    assert list(workdir.iterdir()) == []  # wav temporário apagado depois do cálculo

    cached = waveform_path(src)
    assert cached.exists()


def test_waveform_builder_load_or_build_uses_cache_without_running_ffmpeg_again(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WAVEFORM_DIR", tmp_path / "waveform")
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"video")

    def on_run(command):
        _write_tone_and_silence_wav(Path(command.args[-1]), ANALYSIS_RATE, 0.5, 0.5)

    runner = RecordingRunner(on_run=on_run)
    builder = WaveformBuilder(runner, workdir=tmp_path / "tmp")

    first = builder.load_or_build(src)
    assert len(runner.commands) == 1

    second = builder.load_or_build(src)
    assert len(runner.commands) == 1  # cache em disco: não roda ffmpeg de novo
    assert second.peaks == first.peaks
    assert second.duration == pytest.approx(first.duration)


# ---------- API (ui/server.py): GET /api/waveform ----------


class _FakeWaveformBuilder:
    """Dublê: devolve picos fixos sem rodar ffmpeg."""

    def __init__(self, runner):
        pass

    def load_or_build(self, src: Path, stream: int = 0) -> Waveform:
        return Waveform(duration=2.0, peaks_per_second=50, peaks=[0.1, 0.9])


class _FailingWaveformBuilder:
    """Dublê: simula um arquivo sem a faixa de áudio pedida (ffmpeg falha ao mapear)."""

    def __init__(self, runner):
        pass

    def load_or_build(self, src: Path, stream: int = 0) -> Waveform:
        raise FFmpegError("ffmpeg falhou", cmd=["ffmpeg"], stderr="Stream map '0:a:0' matches no streams")


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


def test_get_waveform_returns_peaks_and_generates_on_cache_miss(tmp_path, client, monkeypatch):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"video")
    monkeypatch.setattr(waveform_module, "WaveformBuilder", _FakeWaveformBuilder)
    resp = client.get("/api/waveform", params={"path": str(src)})
    assert resp.status_code == 200
    assert resp.json() == {"duration": 2.0, "peaks_per_second": 50, "peaks": [0.1, 0.9]}


def test_get_waveform_404_when_file_not_allowed(tmp_path, client):
    disallowed = tmp_path / "notas.txt"
    disallowed.write_text("nao e midia", encoding="utf-8")
    resp = client.get("/api/waveform", params={"path": str(disallowed)})
    assert resp.status_code == 404


def test_get_waveform_404_when_file_does_not_exist(tmp_path, client):
    resp = client.get("/api/waveform", params={"path": str(tmp_path / "nao-existe.mp4")})
    assert resp.status_code == 404


def test_get_waveform_404_when_source_has_no_audio_stream(tmp_path, client, monkeypatch):
    src = tmp_path / "sem-audio.mp4"
    src.write_bytes(b"video")
    monkeypatch.setattr(waveform_module, "WaveformBuilder", _FailingWaveformBuilder)
    resp = client.get("/api/waveform", params={"path": str(src)})
    assert resp.status_code == 404
