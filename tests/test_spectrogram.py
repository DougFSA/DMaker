"""O espectrograma do painel Áudio: as escalas de frequência (funções puras), o reparte dos quadros por coluna, a imagem de
um tom de 3 kHz numa fala sintética no lugar certo, a leitura em pedaços de uma hora, o cache e a rota."""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dmaker import config
from dmaker.analysis.scales import (
    SCALE_NAMES,
    check_band,
    frequency_row,
    row_edges,
    row_frequency,
    scale_frequency,
    scale_position,
)
from dmaker.analysis.spectrogram import (
    MAX_FRAMES_PER_COLUMN,
    SpectrogramParams,
    frame_starts,
    frames_per_column,
    spectrogram_gray,
)
from dmaker.media.sample_reader import StereoReader, WavReader, random_access
from dmaker.media.wavio import write_wav_channels
from dmaker.pipeline.audio_panel import AudioPanelService
from dmaker.pipeline.spectrogram import (
    ReaderFrameSource,
    SpectrogramRequest,
    render_spectrogram,
    snap_grid,
)
from dmaker.ui import server

from .conftest import requires_ffmpeg

RATE = 48000


class ArrayReader:
    """Um leitor na memória que conta o que foi pedido."""

    def __init__(self, samples: np.ndarray, rate: int = RATE) -> None:
        self.samples = samples.reshape(len(samples), -1)
        self.rate = rate
        self.channels = self.samples.shape[1]
        self.reads: list[int] = []

    def read(self, start: float, duration: float) -> np.ndarray:
        first, frames = int(round(start * self.rate)), int(round(duration * self.rate))
        self.reads.append(frames)
        chunk = self.samples[first : first + frames]
        if chunk.shape[0] < frames:
            chunk = np.concatenate([chunk, np.zeros((frames - chunk.shape[0], self.channels), np.float32)])
        return chunk


def speech_with_tone(seconds: float = 4.0, tone_from: float = 1.5, tone_to: float = 2.0) -> np.ndarray:
    """Uma "fala" de tons e chiado, com um tom de 3 kHz de meio segundo no meio."""
    rng = np.random.default_rng(3)
    t = np.arange(int(seconds * RATE)) / RATE
    voice = sum(
        0.05 * np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in (180, 420, 900, 1500, 2300, 3700)
    )
    voice = voice * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)) + 0.005 * rng.standard_normal(len(t))
    hit = (t >= tone_from) & (t < tone_to)
    voice[hit] += 0.3 * np.sin(2 * np.pi * 3000 * t[hit])
    return voice.astype(np.float32)[:, None].repeat(2, axis=1)


# ---------- escalas ----------


@pytest.mark.parametrize("scale", SCALE_NAMES)
def test_every_scale_is_increasing_and_the_inverse_returns_the_frequency(scale):
    frequencies = np.array([20.0, 100.0, 440.0, 1000.0, 3000.0, 8000.0, 20000.0])
    positions = scale_position(scale, frequencies)
    assert np.all(np.diff(positions) > 0)
    assert scale_frequency(scale, positions) == pytest.approx(frequencies, rel=1e-9)


def test_the_known_points_of_each_scale():
    assert scale_position("mel", 1000.0) == pytest.approx(
        1000.0, abs=0.2
    )  # a Mel foi calibrada para valer 1000 em 1 kHz
    assert scale_position("bark", 1000.0) == pytest.approx(8.5, abs=0.1)
    assert scale_position("erb", 1000.0) == pytest.approx(15.6, abs=0.1)
    assert scale_position("log", 1000.0) == pytest.approx(3.0)


def test_rows_are_evenly_spaced_in_the_scale_and_the_row_of_a_frequency_comes_back():
    edges = row_edges("log", 4, 10.0, 10000.0)
    assert edges[0] == pytest.approx(10.0) and edges[-1] == pytest.approx(10000.0)
    assert edges[1:4] == pytest.approx([56.234, 316.23, 1778.28], rel=1e-3)
    for scale in SCALE_NAMES:
        row = frequency_row(scale, 3000.0, 256, 20.0, 12000.0)
        assert row_frequency(scale, row, 256, 20.0, 12000.0) == pytest.approx(3000.0, rel=1e-9)
    assert frequency_row("linear", 24000.0, 100, 0.0, 24000.0) == 0.0  # o topo da imagem é a maior frequência
    assert frequency_row("linear", 0.0, 100, 0.0, 24000.0) == 100.0


def test_a_band_beyond_the_spectrum_or_a_log_scale_from_zero_is_refused_with_the_reason():
    assert check_band("linear", 0.0, 30000.0, 24000.0) == (0.0, 24000.0)
    with pytest.raises(ValueError, match="não cabe"):
        check_band("linear", 5000.0, 5000.5, 24000.0)
    with pytest.raises(ValueError, match="log"):
        check_band("log", 0.0, 8000.0, 24000.0)
    with pytest.raises(ValueError, match="desconhecida"):
        check_band("oitava", 0.0, 8000.0, 24000.0)


# ---------- quadros por coluna ----------


def test_a_zoomed_in_column_takes_one_frame_and_a_far_one_takes_at_most_eight():
    assert frames_per_column(100, 2048) == 1
    assert frames_per_column(2048 * 3, 2048) == 3
    assert frames_per_column(48000 * 3.5, 2048) == MAX_FRAMES_PER_COLUMN
    starts, column = frame_starts(0.0, 48000 * 3.5, 4, 2048)
    assert len(starts) == 4 * MAX_FRAMES_PER_COLUMN and list(column[:9]) == [0] * 8 + [1]
    assert np.all(np.diff(starts) > 0)


# ---------- a imagem ----------


@pytest.mark.parametrize("scale", SCALE_NAMES)
def test_a_3khz_tone_in_a_speech_shows_as_the_brightest_band_at_the_right_row_and_column(scale):
    samples = speech_with_tone()
    reader = ArrayReader(samples)
    params = SpectrogramParams(rows=256, scale=scale, min_hz=20.0, max_hz=12000.0)
    columns = 400
    image = spectrogram_gray(ReaderFrameSource(reader), RATE, 0.0, 4.0 * RATE / columns, columns, params)
    assert image.shape == (256, columns) and image.dtype == np.uint8
    row, column = np.unravel_index(np.argmax(image), image.shape)
    expected_row = frequency_row(scale, 3000.0, 256, 20.0, 12000.0)
    assert abs(row + 0.5 - expected_row) <= 2.0, f"linha {row} contra {expected_row:.1f}"
    assert 1.5 / 4.0 * columns - 3 <= column <= 2.0 / 4.0 * columns + 3
    inside = image[:, 150:195].max(axis=1)
    outside = image[:, 20:100].max(axis=1)
    assert inside.max() == 255 or inside.max() > outside.max()


def test_gain_and_range_move_the_brightness_in_decibels():
    samples = speech_with_tone()
    base = SpectrogramParams(rows=64, max_hz=8000.0, gain_db=0.0, range_db=80.0)
    louder = SpectrogramParams(rows=64, max_hz=8000.0, gain_db=20.0, range_db=80.0)
    flat = [
        spectrogram_gray(ReaderFrameSource(ArrayReader(samples)), RATE, 0.0, RATE * 4.0 / 100, 100, p)
        for p in (base, louder)
    ]
    # 20 dB de ganho em 80 dB de alcance são 25% da escala, onde o pixel não satura
    mid = (flat[0] > 40) & (flat[0] < 200)
    assert np.median(flat[1][mid].astype(int) - flat[0][mid].astype(int)) == pytest.approx(
        255 * 20 / 80, abs=2
    )


def test_invalid_parameters_are_refused_in_portuguese():
    reader = ArrayReader(speech_with_tone())
    source = ReaderFrameSource(reader)
    with pytest.raises(ValueError, match="window_size"):
        spectrogram_gray(source, RATE, 0.0, 480, 10, SpectrogramParams(window_size=1000))
    with pytest.raises(ValueError, match="janela desconhecida"):
        spectrogram_gray(source, RATE, 0.0, 480, 10, SpectrogramParams(window="trapézio"))


# ---------- uma hora sem ler a hora ----------


class LongReader:
    """Um áudio de uma hora que existe só como pedidos: cada leitura devolve silêncio e é anotada."""

    rate = RATE
    channels = 2

    def __init__(self) -> None:
        self.reads: list[int] = []

    def read(self, start: float, duration: float) -> np.ndarray:
        frames = int(round(duration * self.rate))
        self.reads.append(frames)
        return np.zeros((frames, 2), np.float32)


def test_an_hour_of_audio_reads_only_the_frames_each_column_needs_in_small_pieces():
    reader = LongReader()
    source = ReaderFrameSource(reader)
    source.random_access = False  # o caso de um MP3: os pedaços de 20 s
    columns = 1024
    spectrogram_gray(source, RATE, 0.0, 3600.0 * RATE / columns, columns, SpectrogramParams(rows=128))
    assert max(reader.reads) <= 20 * RATE + 2048  # nunca mais que um pedaço
    assert sum(reader.reads) <= 3600 * RATE  # no pior caso, uma passada


def test_an_hour_of_a_wav_reads_just_the_frames_of_each_column():
    reader = LongReader()
    source = ReaderFrameSource(reader)
    source.random_access = True
    columns = 1024
    spectrogram_gray(source, RATE, 0.0, 3600.0 * RATE / columns, columns, SpectrogramParams(rows=128))
    needed = columns * MAX_FRAMES_PER_COLUMN * 2048
    assert sum(reader.reads) == needed  # 8 quadros por coluna: 10% da hora
    assert needed < 0.1 * 3600 * RATE
    assert max(reader.reads) == 2048


def test_a_wav_reader_gives_the_scattered_frames_with_the_file_opened_once(tmp_path):
    path = tmp_path / "rampa.wav"
    samples = (np.arange(5000, dtype=np.float32) / 10000.0)[:, None]
    write_wav_channels(path, np.concatenate([samples, -samples], axis=1), RATE)
    reader = WavReader(path, RATE, 2)
    starts = np.array([-3, 0, 1200, 4990, 9000])  # antes do começo, dentro, perto do fim e depois do fim
    frames = reader.frames(starts, 16)
    assert frames.shape == (5, 16, 2)
    assert np.allclose(frames[1], reader.read(0.0, 16 / RATE), atol=1e-4)
    assert np.allclose(frames[2], reader.read(1200 / RATE, 16 / RATE), atol=1e-4)
    assert np.all(frames[0][:3] == 0) and np.allclose(frames[0][3:], reader.read(0.0, 13 / RATE), atol=1e-4)
    assert np.all(frames[3][10:] == 0) and frames[3][9, 0] > 0 and np.all(frames[4] == 0)
    # o mono é mostrado nos dois canais a -3 dB, como no leitor da mixagem
    mono = tmp_path / "mono.wav"
    write_wav_channels(mono, samples, RATE)
    wrapped = StereoReader(WavReader(mono, RATE, 1))
    assert np.allclose(wrapped.frames(np.array([100]), 8)[0], wrapped.read(100 / RATE, 8 / RATE), atol=1e-4)


def test_only_a_wav_read_by_position_counts_as_random_access(tmp_path):
    path = tmp_path / "a.wav"
    write_wav_channels(path, np.zeros((100, 1), np.float32), RATE)
    wav = WavReader(path, RATE, 1)
    assert random_access(wav) and random_access(StereoReader(wav))
    assert not random_access(ArrayReader(np.zeros((10, 2), np.float32)))


# ---------- grade e cache ----------


def test_neighbouring_requests_snap_to_the_same_grid_and_the_image_never_passes_the_audio():
    step, first, count = snap_grid(10.0, 20.0, 1000, 300.0)
    assert (step, first, count) == snap_grid(10.02, 20.02, 1000, 300.0) == snap_grid(10.0, 20.0, 1000, 300.0)
    assert first * step <= 10.0 and (first + count) * step >= 20.0
    step, first, count = snap_grid(0.0, 3.0, 1000, 3.0)
    assert (first + count) * step < 3.0 + step


def test_the_second_request_comes_from_the_cache_with_the_same_image(tmp_path):
    folder = config.PROJECTS_DIR / "espectro"
    folder.mkdir(parents=True, exist_ok=True)
    write_wav_channels(folder / "voz.wav", speech_with_tone(), RATE)
    project = server_project(folder)
    service = AudioPanelService()
    plan = service.plan(project, "audio.voiceover.0")
    reader = service.reader(plan)
    request = SpectrogramRequest(0.0, 4.0, 400, SpectrogramParams(rows=64, max_hz=8000.0))
    first = render_spectrogram(plan, reader, request)
    second = render_spectrogram(plan, reader, request)
    assert (first.cached, second.cached) == (False, True) and first.png == second.png
    assert list(config.SPECTROGRAM_DIR.glob("*.png"))
    other = render_spectrogram(
        plan, reader, SpectrogramRequest(0.0, 4.0, 400, SpectrogramParams(rows=64, max_hz=6000.0))
    )
    assert not other.cached and other.max_hz == 6000.0
    gray = np.asarray(Image.open(io.BytesIO(first.png)))
    assert gray.shape == (first.rows, first.columns) and first.start == 0.0


def server_project(folder):
    from dmaker.domain.spec import Project

    project = Project.model_validate(
        {
            "name": "espectro",
            "timeline": [{"type": "card", "title": "x", "duration": 5.0}],
            "audio": {"voiceover": [{"src": "voz.wav", "start": 0.0}], "normalize": "off"},
        }
    )
    project.base_dir = folder
    return project


# ---------- a rota ----------


@requires_ffmpeg
def test_the_route_answers_a_png_with_the_real_span_and_a_cached_second_answer():
    folder = config.PROJECTS_DIR / "espectro"
    folder.mkdir(parents=True, exist_ok=True)
    write_wav_channels(folder / "voz.wav", speech_with_tone(), RATE)
    spec = {
        "timeline": [{"type": "card", "title": "x", "duration": 5.0}],
        "audio": {"voiceover": [{"src": "voz.wav", "start": 0.0}], "normalize": "off"},
    }
    body = {
        "spec": spec,
        "target": "audio.voiceover.0",
        "columns": 300,
        "rows": 128,
        "scale": "mel",
        "max_hz": 8000,
    }
    with TestClient(server.app) as client:
        first = client.post("/api/projects/espectro/audio-panel/spectrogram", json=body)
        assert first.status_code == 200, first.text
        assert first.headers["content-type"] == "image/png" and first.headers["x-spectrogram-cached"] == "0"
        image = np.asarray(Image.open(io.BytesIO(first.content)))
        assert image.shape == (128, int(first.headers["x-spectrogram-columns"]))
        assert float(first.headers["x-spectrogram-start"]) <= 0.0 < float(first.headers["x-spectrogram-end"])
        second = client.post("/api/projects/espectro/audio-panel/spectrogram", json=body)
        assert second.headers["x-spectrogram-cached"] == "1" and second.content == first.content
        refused = client.post(
            "/api/projects/espectro/audio-panel/spectrogram", json={**body, "window_size": 1000}
        )
        assert refused.status_code == 400 and "window_size" in refused.json()["detail"]
        bad_scale = client.post(
            "/api/projects/espectro/audio-panel/spectrogram", json={**body, "scale": "oitava"}
        )
        assert bad_scale.status_code == 422
