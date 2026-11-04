"""O painel Áudio no servidor: os picos por bloco e a pirâmide (funções puras e leitura em pedaços), o plano de um alvo, a
janela para tocar, a prévia de um efeito e as três rotas. Os sinais são tons gerados aqui, com medida numérica."""

from __future__ import annotations

import io
import time
import wave
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.domain.audio_effects import parse_effect
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.peak_levels import (
    BASE_BLOCK,
    BlockAccumulator,
    PeakLevel,
    block_extremes,
    build_levels,
    coarser,
    dequantize,
    level_columns,
    pick_level,
    quantize,
    sample_columns,
)
from dmaker.media.probe import probe
from dmaker.media.sample_reader import DecodingReader, WavReader, open_reader, wav_format
from dmaker.media.waveform import PeakPyramid, build_pyramid, load_pyramid, save_pyramid
from dmaker.media.wavio import read_wav_float, wav_bytes, write_wav_channels
from dmaker.pipeline import audio_panel
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.audio_panel import (
    AudioPanelError,
    AudioPanelService,
    PeakTasks,
    PlanCache,
    wave_payload,
)
from dmaker.ui import server

from .conftest import requires_ffmpeg

RATE = 48000


def tone(hz: float, seconds: float, amp: float = 0.5, rate: int = RATE) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


class ArrayReader:
    """Um leitor de amostras na memória: o `SampleReader` que os testes puros usam no lugar do disco."""

    def __init__(self, samples: np.ndarray, rate: int = RATE) -> None:
        self.samples = samples.reshape(len(samples), -1)
        self.rate = rate
        self.channels = self.samples.shape[1]

    def read(self, start: float, duration: float) -> np.ndarray:
        first = int(round(start * self.rate))
        frames = int(round(duration * self.rate))
        chunk = self.samples[first : first + frames]
        if chunk.shape[0] < frames:
            chunk = np.concatenate([chunk, np.zeros((frames - chunk.shape[0], self.channels), np.float32)])
        return chunk


# ---------- picos por bloco ----------


def test_block_extremes_take_the_min_and_max_of_each_block_and_keep_the_partial_tail():
    samples = np.arange(10, dtype=np.float32).reshape(10, 1) / 10
    low, high = block_extremes(samples, 4)
    assert low.shape == (3, 1)
    assert low[:, 0].tolist() == pytest.approx([0.0, 0.4, 0.8])
    assert high[:, 0].tolist() == pytest.approx([0.3, 0.7, 0.9])


def test_quantize_roundtrips_within_one_step_and_clips_beyond_full_scale():
    values = np.linspace(-1, 1, 201, dtype=np.float32)
    assert np.max(np.abs(dequantize(quantize(values)) - values)) <= 0.5 / 127 + 1e-6
    assert quantize(np.array([3.0, -3.0], dtype=np.float32)).tolist() == [127, -127]


def test_accumulator_gives_the_same_blocks_however_the_audio_is_cut_into_chunks():
    signal = tone(300, 1.0, 0.8)[:, None]
    whole = BlockAccumulator(1)
    whole.push(signal)
    pieces = BlockAccumulator(1)
    for first in range(
        0, len(signal), 1000
    ):  # 1000 não é múltiplo de 64: o resto passa de um pedaço ao outro
        pieces.push(signal[first : first + 1000])
    a, b = whole.base(final=True), pieces.base(final=True)
    assert a.mins.tolist() == b.mins.tolist()
    assert a.maxs.tolist() == b.maxs.tolist()
    assert whole.frames == pieces.frames == len(signal)


def test_the_pyramid_levels_keep_the_global_extremes():
    signal = tone(100, 2.0, 0.6)[:, None]
    signal[70000] = 0.95
    accumulator = BlockAccumulator(1)
    accumulator.push(signal)
    levels = build_levels(accumulator.base(final=True))
    assert [level.block for level in levels[:3]] == [64, 256, 1024]
    for level in levels:
        assert dequantize(level.maxs).max() == pytest.approx(0.95, abs=1 / 127)
        assert dequantize(level.mins).min() == pytest.approx(-0.6, abs=1 / 127)
    assert levels[-1].blocks <= 256


def test_pick_level_takes_the_coarsest_block_that_fits_a_column_and_none_below_the_base():
    base = PeakLevel(64, np.zeros((1000, 1), np.int8), np.zeros((1000, 1), np.int8))
    levels = build_levels(base, stop_blocks=1)
    assert pick_level(levels, 63) is None
    assert pick_level(levels, 64).block == 64
    assert pick_level(levels, 1000).block == 256
    assert pick_level(levels, 5000).block == 4096


def test_level_columns_follow_the_window_and_leave_unbuilt_columns_empty():
    signal = np.zeros((6400, 1), np.float32)
    signal[3200:] = 0.5  # a segunda metade
    accumulator = BlockAccumulator(1)
    accumulator.push(signal)
    level = accumulator.base(final=True)
    low, high = level_columns(level, 0, 6400, 4)
    assert high[:, 0].tolist() == pytest.approx([0.0, 0.0, 0.5, 0.5], abs=1 / 127)
    # a pirâmide parcial (só a primeira metade lida) não estica o que tem sobre a janela: o resto vem zerado
    half = BlockAccumulator(1)
    half.push(signal[:3200])
    _, partial = level_columns(half.base(), 0, 6400, 4)
    assert partial[:, 0].tolist() == pytest.approx([0.0, 0.0, 0.0, 0.0])
    half_late = BlockAccumulator(1)
    half_late.push(signal[:4800])
    _, later = level_columns(half_late.base(), 0, 6400, 4)
    assert later[:, 0].tolist() == pytest.approx([0.0, 0.0, 0.5, 0.0], abs=1 / 127)


def test_sample_columns_repeat_the_nearest_sample_when_there_are_fewer_samples_than_columns():
    samples = np.array([[0.1], [0.5], [-0.5]], dtype=np.float32)
    low, high = sample_columns(samples, 6)
    assert high[:, 0].tolist() == pytest.approx([0.1, 0.1, 0.5, 0.5, -0.5, -0.5])
    assert low.tolist() == high.tolist()


def test_coarser_groups_four_blocks_and_keeps_the_last_partial_group():
    level = PeakLevel(
        64,
        np.arange(10, dtype=np.int8).reshape(10, 1),
        np.arange(10, dtype=np.int8).reshape(10, 1) + 1,
    )
    grouped = coarser(level)
    assert grouped.block == 256
    assert grouped.mins[:, 0].tolist() == [0, 4, 8]
    assert grouped.maxs[:, 0].tolist() == [4, 8, 10]


# ---------- a pirâmide ----------


def test_the_parallel_build_equals_the_serial_one_and_reports_progress_in_order():
    signal = np.stack([tone(200, 5.0, 0.7), tone(450, 5.0, 0.3)], axis=1)
    reader = ArrayReader(signal)
    seen: list[float] = []
    built = build_pyramid(reader, 5.0, chunk_seconds=1.0, workers=3, on_progress=seen.append)
    direct = BlockAccumulator(2)
    direct.push(signal)
    base = direct.base(final=True)
    assert built.frames == len(signal)
    assert built.levels[0].mins.tolist() == base.mins.tolist()
    assert built.levels[0].maxs.tolist() == base.maxs.tolist()
    assert seen == sorted(seen) and seen[-1] == pytest.approx(5.0)


def test_the_build_can_be_stopped_and_still_returns_what_was_read():
    reader = ArrayReader(tone(200, 5.0, 0.7)[:, None])
    calls = {"count": 0}

    def stop() -> bool:
        calls["count"] += 1
        return calls["count"] > 2

    built = build_pyramid(reader, 5.0, chunk_seconds=1.0, workers=1, should_stop=stop)
    assert 0 < built.frames < 5 * RATE


def test_the_pyramid_survives_a_trip_to_disk_and_answers_windows_by_level(tmp_path):
    signal = tone(440, 4.0, 0.5)[:, None]
    built = build_pyramid(ArrayReader(signal), 4.0, chunk_seconds=1.0)
    path = tmp_path / "pir.npz"
    save_pyramid(path, built)
    loaded = load_pyramid(path)
    assert loaded is not None
    assert (loaded.rate, loaded.channels, loaded.frames) == (RATE, 1, len(signal))
    low, high = loaded.window(0.0, 4.0, 200)
    assert high.max() == pytest.approx(0.5, abs=2 / 127)
    assert low.min() == pytest.approx(-0.5, abs=2 / 127)
    assert loaded.window(1.0, 1.0 + 100 / RATE, 200) is None  # menos de um bloco por coluna: ler as amostras
    assert load_pyramid(tmp_path / "nao-existe.npz") is None
    (tmp_path / "ruim.npz").write_bytes(b"nao e um npz")
    assert load_pyramid(tmp_path / "ruim.npz") is None


# ---------- ler amostras ----------


def test_the_wav_reader_returns_exactly_the_frames_asked_and_pads_past_the_end(tmp_path):
    path = tmp_path / "t.wav"
    write_wav_channels(path, tone(1000, 1.0, 0.5)[:, None], RATE)
    assert wav_format(path) == (RATE, 1)
    assert wav_format(tmp_path / "nada.wav") is None
    reader = WavReader(path, RATE, 1)
    assert reader.read(0.25, 0.5).shape == (24000, 1)
    tail = reader.read(0.9, 0.3)
    assert tail.shape == (14400, 1)
    assert np.abs(tail[-1000:]).max() == 0  # depois do fim vem silêncio
    assert reader.read(0.0, 0.0).shape == (0, 1)


@requires_ffmpeg
def test_a_mono_file_is_shown_in_both_channels_at_the_level_the_ffmpeg_mixes_it(tmp_path):
    """O ganho do mono para o estéreo é o do ffmpeg (o que a cadeia de efeitos e a mixagem usam), medido aqui."""
    from dmaker.media.ffmpeg import FFmpegCommand
    from dmaker.media.sample_reader import MONO_TO_STEREO_GAIN

    mono = tmp_path / "m.wav"
    write_wav_channels(mono, tone(300, 1.0, 0.5)[:, None], RATE)
    stereo = tmp_path / "s.wav"
    SubprocessRunner(quiet=True).run(
        FFmpegCommand(
            ["-i", str(mono), "-af", "aformat=channel_layouts=stereo", "-c:a", "pcm_f32le", str(stereo)]
        )
    )
    mixed, _ = read_wav_float(stereo)
    shown = open_reader(SubprocessRunner(quiet=True), mono, prober=probe).read(0.0, 1.0)
    assert shown.shape == mixed.shape == (RATE, 2)
    assert np.abs(shown - mixed).max() < 1e-4
    assert MONO_TO_STEREO_GAIN == pytest.approx(0.70710678, abs=1e-8)


def test_the_wav_reader_starts_at_the_base_offset_of_the_file(tmp_path):
    path = tmp_path / "t.wav"
    samples = np.concatenate([np.zeros(RATE // 2), np.full(RATE // 2, 0.4)]).astype(np.float32)
    write_wav_channels(path, samples[:, None], RATE)
    assert WavReader(path, RATE, 1, base=0.5).read(0.0, 0.1).mean() == pytest.approx(0.4, abs=1e-3)


@requires_ffmpeg
def test_the_decoding_reader_matches_the_wav_reader_on_a_compressed_file(tmp_path):
    wav = tmp_path / "t.wav"
    write_wav_channels(wav, np.stack([tone(500, 2.0, 0.5), tone(900, 2.0, 0.25)], axis=1), RATE)
    flac = tmp_path / "t.flac"
    from dmaker.media.ffmpeg import FFmpegCommand

    runner = SubprocessRunner(quiet=True)
    runner.run(FFmpegCommand(["-i", str(wav), "-c:a", "flac", str(flac)], label="teste"))
    assert wav_format(flac) is None
    reader = open_reader(runner, flac, prober=probe)
    assert isinstance(reader, DecodingReader) and (reader.rate, reader.channels) == (RATE, 2)
    direct = WavReader(wav, RATE, 2)
    for start, length in (
        (0.0, 0.5),
        (0.7123, 0.3),
        (1.8, 0.5),
    ):  # o último passa do fim e completa com zeros
        a, b = reader.read(start, length), direct.read(start, length)
        assert a.shape == b.shape == (int(round(length * RATE)), 2)
        assert np.abs(a - b).max() < 2e-3
    shifted = open_reader(runner, flac, prober=probe, base=-0.25)  # antes do começo do arquivo vem silêncio
    head = shifted.read(0.0, 0.5)
    assert np.abs(head[: RATE // 4]).max() == 0
    assert np.abs(head[RATE // 4 :]).max() > 0.1


# ---------- o alvo ----------


def make_project(folder: Path, effects: list[dict] | None = None, volume: float = 1.0) -> Project:
    write_wav_channels(folder / "voz.wav", tone(220, 3.0, 0.25)[:, None], RATE)
    voice: dict = {"src": "voz.wav", "start": 0.5, "volume": volume}
    if effects:
        voice["effects"] = effects
    project = Project.model_validate(
        {
            "name": "painel",
            "timeline": [{"type": "card", "title": "Painel", "duration": 5.0}],
            "audio": {"voiceover": [voice], "normalize": "off"},
        }
    )
    project.base_dir = folder
    return project


def pcm_of(content: bytes) -> np.ndarray:
    """O WAV de 16 bits de uma resposta como matriz (quadros, canais) de -1 a 1."""
    with wave.open(io.BytesIO(content)) as handle:
        channels = handle.getnchannels()
        raw = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2") / 32768.0
    return raw.reshape(-1, channels)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))


@requires_ffmpeg
def test_the_plan_of_a_voice_file_has_the_clock_the_duration_and_a_key_that_ignores_the_volume(tmp_path):
    service = AudioPanelService()
    project = make_project(tmp_path)
    plan = service.plan(project, "audio.voiceover.0")
    assert plan.duration == pytest.approx(3.0, abs=0.01)
    assert plan.processed is False
    assert plan.to_project(1.0) == pytest.approx(1.5)
    project.audio.voiceover[0].volume = 0.5
    assert service.plan(project, "audio.voiceover.0").key == plan.key  # o ganho do item não muda a onda
    project.audio.voiceover[0].effects = [parse_effect({"type": "amplify", "gain_db": 6})]
    with_effect = service.plan(project, "audio.voiceover.0")
    assert with_effect.processed is True and with_effect.key != plan.key


@requires_ffmpeg
def test_a_target_without_sound_is_refused_with_the_reason(tmp_path):
    with pytest.raises(audio_panel.TargetError, match="não existe"):
        AudioPanelService().plan(make_project(tmp_path), "audio.voiceover.4")


@requires_ffmpeg
def test_the_processed_plan_reads_the_effect_output_inside_the_interval_only(tmp_path):
    effect = {"type": "amplify", "gain_db": 6.0, "start": 1.0, "end": 2.0, "prevent_clipping": False}
    service = AudioPanelService()
    plan = service.plan(make_project(tmp_path, [effect]), "audio.voiceover.0")
    reader = service.reader(plan)
    assert reader is not None
    inside, outside = reader.read(1.2, 0.5), reader.read(2.4, 0.5)
    assert rms(inside) / rms(outside) == pytest.approx(2.0, rel=0.03)  # +6 dB é o dobro da amplitude


@requires_ffmpeg
def test_the_window_is_a_16_bit_wav_with_the_item_volume_and_refuses_oversized_windows(tmp_path, monkeypatch):
    service = AudioPanelService()
    plan = service.plan(make_project(tmp_path, volume=0.5), "audio.voiceover.0")
    data, seconds = service.window_wav(plan, 0.5, 1.5)
    with wave.open(io.BytesIO(data)) as handle:
        # o mono vai para os dois canais, 3 dB abaixo, como na mixagem
        assert (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (2, 2, RATE)
        assert handle.getnframes() == RATE
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2") / 32768.0
    assert seconds == pytest.approx(1.0)
    assert rms(pcm) == pytest.approx(0.25 * 0.5 * 0.7071 / np.sqrt(2), rel=0.03)
    with pytest.raises(AudioPanelError, match="não cabe"):
        service.window_wav(plan, 5.0, 6.0)
    monkeypatch.setattr(audio_panel, "MAX_WINDOW_SECONDS", 1.0)
    with pytest.raises(AudioPanelError, match="passa de"):
        service.window_wav(plan, 0.0, 2.0)


@requires_ffmpeg
def test_wave_payload_shapes_peaks_for_a_far_window_and_samples_for_a_close_one(tmp_path):
    service = AudioPanelService()
    plan = service.plan(make_project(tmp_path), "audio.voiceover.0")
    tasks = PeakTasks(lambda: tmp_path / "picos")
    build = tasks.request(lambda runner: AudioPanelService(runner), plan)
    assert build.done.wait(20) and build.state == "ready"
    reader = service.reader(plan)
    far = wave_payload(plan, build, reader, 0.0, plan.duration, 300)
    assert far["mode"] == "peaks" and far["state"] == "ready" and far["channels"] == 2
    assert len(far["mins"]) == 2 and len(far["mins"][0]) == 300
    assert max(far["maxs"][0]) == pytest.approx(0.25 * 0.7071 * 127, abs=2)
    assert far["clock"] == {"start": 0.5, "speed": 1.0}
    close = wave_payload(plan, build, reader, 1.0, 1.0 + 200 / RATE, 400)
    assert close["mode"] == "samples" and len(close["samples"][0]) == 200
    medium = wave_payload(
        plan, build, reader, 1.0, 1.0 + 20000 / RATE, 100
    )  # 200 amostras por coluna: abaixo do bloco
    assert medium["mode"] == "peaks" or medium["mode"] == "raw"
    assert (tmp_path / "picos").glob("pyr-*.npz")
    assert (
        tasks.request(lambda runner: AudioPanelService(runner), plan).state == "ready"
    )  # a mesma chave não refaz


@requires_ffmpeg
def test_a_build_with_effects_reports_the_stage_and_ends_with_the_processed_wave(tmp_path):
    effect = {"type": "amplify", "gain_db": 6.0, "prevent_clipping": False}
    service = AudioPanelService()
    plan = service.plan(make_project(tmp_path, [effect]), "audio.voiceover.0")
    tasks = PeakTasks(lambda: tmp_path / "picos")
    build = tasks.request(lambda runner: AudioPanelService(runner), plan)
    assert build.done.wait(30) and build.state == "ready", build.error
    payload = wave_payload(plan, build, service.reader(plan), 0.0, plan.duration, 200)
    assert max(payload["maxs"][0]) == pytest.approx(0.25 * 0.7071 * 2 * 127, abs=3)


def test_a_failed_build_keeps_the_reason_and_is_retried_on_the_next_request(tmp_path):
    class Broken(AudioPanelService):
        def reader(self, plan, *, create=True):
            raise RuntimeError("sem disco")

    plan = audio_panel.HeardPlan("audio.music", _item(tmp_path), 1.0, 0.0, False, "chave-falha", RATE, 1)
    tasks = PeakTasks(lambda: tmp_path / "picos")
    build = tasks.request(lambda runner: Broken(runner), plan)
    assert build.done.wait(5) and build.state == "failed" and "sem disco" in (build.error or "")
    again = tasks.request(lambda runner: Broken(runner), plan)
    assert again is not build


def test_the_build_progress_only_moves_forward_and_ends_at_100(tmp_path, monkeypatch):
    """O andamento é o dos segundos já lidos (e não o de cada comando do ffmpeg, que zeraria a conta)."""
    monkeypatch.setattr("dmaker.media.waveform.PYRAMID_CHUNK_SECONDS", 0.5)
    samples = ArrayReader(tone(220, 6.0, 0.4)[:, None])

    class Fake(AudioPanelService):
        def reader(self, plan, *, create=True):
            return samples

    plan = audio_panel.HeardPlan("audio.music", _item(tmp_path), 6.0, 0.0, False, "chave-andamento", RATE, 1)
    tasks = PeakTasks(lambda: tmp_path / "picos")
    build = tasks.request(lambda runner: Fake(runner), plan)
    seen = []
    while not build.done.is_set():
        seen.append(build.percent)
        time.sleep(0.001)
    seen.append(build.percent)
    assert build.state == "ready" and build.percent == 100
    assert seen == sorted(seen)  # nunca anda para trás
    pyramid = build.snapshot()
    assert pyramid is not None and pyramid.complete and pyramid.frames == 6 * RATE


def _item(folder: Path):
    from dmaker.pipeline.analysis_items import ItemAudio, ItemClock

    return ItemAudio("teste", folder / "x.wav", 0.0, 1.0, clock=ItemClock(0.0))


def test_the_plan_cache_reuses_a_plan_until_the_spec_changes(tmp_path):
    cache = PlanCache()
    project = Project.model_validate(
        {"name": "x", "timeline": [{"type": "card", "title": "a", "duration": 1.0}]}
    )
    (tmp_path / "x.wav").write_bytes(b"x")
    plan = audio_panel.HeardPlan("t", _item(tmp_path), 1.0, 0.0, False, "k", RATE, 1)
    made = []
    for _ in range(3):
        cache.get(project, "t", lambda: made.append(1) or plan)
    assert len(made) == 1
    edited = Project.model_validate(
        {"name": "x", "timeline": [{"type": "card", "title": "b", "duration": 1.0}]}
    )
    cache.get(edited, "t", lambda: made.append(1) or plan)
    assert len(made) == 2


# ---------- a prévia do efeito ----------


@requires_ffmpeg
def test_the_preview_is_the_render_output_of_the_same_chain(tmp_path):
    """A prévia e o render passam pelo mesmo `EffectProcessor`: o trecho da prévia é igual, amostra a amostra, ao do
    arquivo que o render usaria."""
    project = make_project(tmp_path)
    effect = {"type": "normalize", "peak_db": -3.0, "start": 1.0, "end": 2.0}
    service = AudioPanelService()
    plan, shift, exact, note = service.preview(project, "audio.voiceover.0", effect, 0.8, 2.2)
    assert (shift, exact, note) == (0.0, True, "")
    data, _ = service.window_wav(plan, 0.8, 2.2)
    heard = pcm_of(data)
    applied = Project.model_validate({**project.model_dump(mode="json"), "name": "painel"})
    applied.audio.voiceover[0].effects = [parse_effect(effect)]  # o que "Aplicar" grava e o render lê
    applied.base_dir = tmp_path
    item = AudioItem(tmp_path / "voz.wav", 3.0, tuple(applied.audio.voiceover[0].effects))
    rendered = EffectProcessor(SubprocessRunner(quiet=True)).process(item)
    expected, _ = read_wav_float(rendered.path, 0.8, 1.4)
    assert heard.shape == expected.shape
    assert np.abs(heard - expected).max() < 2 / 32768
    inside = expected[int(0.3 * RATE) : int(1.0 * RATE), 0]  # 1,1 s a 1,8 s: dentro do intervalo
    assert 20 * np.log10(np.abs(inside).max()) == pytest.approx(
        -3.0, abs=0.1
    )  # normalizou a seleção para -3 dBFS


@requires_ffmpeg
def test_a_long_item_previews_an_excerpt_and_says_when_it_is_not_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_panel, "PREVIEW_FULL_LIMIT", 1.0)
    monkeypatch.setattr(audio_panel, "PREVIEW_PAD", 0.5)
    project = make_project(tmp_path)
    service = AudioPanelService()
    inside = {"type": "amplify", "gain_db": 6.0, "start": 1.2, "end": 1.8, "prevent_clipping": False}
    plan, shift, exact, note = service.preview(project, "audio.voiceover.0", inside, 1.0, 2.0)
    assert shift == pytest.approx(0.5) and exact is True and note == ""
    excerpt, _ = service.window_wav(plan, 1.0 - shift, 2.0 - shift)
    full = AudioPanelService().plan(make_project(tmp_path, [inside]), "audio.voiceover.0")
    full_reader = service.reader(full)
    expected = full_reader.read(1.0, 1.0)
    got = pcm_of(excerpt)
    assert got.shape == expected.shape
    assert np.abs(got - expected).max() < 3 / 32768  # o recorte dá o mesmo som que o item inteiro
    whole_item = {"type": "normalize", "peak_db": -3.0}
    _, _, exact_whole, note_whole = service.preview(project, "audio.voiceover.0", whole_item, 1.0, 2.0)
    assert exact_whole is False and "aproximada" in note_whole


@requires_ffmpeg
def test_a_bad_effect_is_refused_with_the_reason_before_anything_is_processed(tmp_path):
    with pytest.raises(AudioPanelError, match="gain_db|Input|valid"):
        AudioPanelService().preview(
            make_project(tmp_path), "audio.voiceover.0", {"type": "amplify", "gain_db": 900}, 0.0, 1.0
        )


# ---------- as rotas ----------


@pytest.fixture
def client(tmp_path):
    folder = config.PROJECTS_DIR / "painel"
    folder.mkdir(parents=True, exist_ok=True)
    write_wav_channels(folder / "voz.wav", tone(220, 3.0, 0.25)[:, None], RATE)
    with TestClient(server.app) as test_client:
        yield test_client


def spec_with(effects: list[dict] | None = None) -> dict:
    voice: dict = {"src": "voz.wav", "start": 0.5}
    if effects:
        voice["effects"] = effects
    return {
        "timeline": [{"type": "card", "title": "Painel", "duration": 5.0}],
        "audio": {"voiceover": [voice], "normalize": "off"},
    }


def ask_wave(client, spec, **extra):
    body = {"spec": spec, "target": "audio.voiceover.0", "columns": 200, **extra}
    return client.post("/api/projects/painel/audio-panel/wave", json=body)


@requires_ffmpeg
def test_the_wave_route_answers_the_whole_item_and_a_close_window(client):
    started = time.perf_counter()
    reply = ask_wave(client, spec_with())
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert (
        body["state"] == "ready"
        and body["mode"] == "peaks"
        and body["duration"] == pytest.approx(3.0, abs=0.01)
    )
    assert body["clock"] == {"start": 0.5, "speed": 1.0} and body["rate"] == RATE
    assert time.perf_counter() - started < 10
    close = ask_wave(client, spec_with(), start=1.0, end=1.004, columns=400).json()
    assert close["mode"] == "samples" and len(close["samples"][0]) == int(round(0.004 * RATE))


@requires_ffmpeg
def test_the_wave_route_uses_the_spec_in_the_body_not_the_one_on_disk(client):
    plain = ask_wave(client, spec_with()).json()
    boosted = ask_wave(
        client, spec_with([{"type": "amplify", "gain_db": 6.0, "prevent_clipping": False}])
    ).json()
    assert max(boosted["maxs"][0]) == pytest.approx(2 * max(plain["maxs"][0]), abs=3)


@requires_ffmpeg
def test_the_wave_route_refuses_a_bad_target_and_a_bad_spec_with_the_reason(client):
    missing = client.post(
        "/api/projects/painel/audio-panel/wave", json={"spec": spec_with(), "target": "audio.voiceover.9"}
    )
    assert missing.status_code == 400 and "não existe" in missing.json()["detail"]
    invalid = client.post(
        "/api/projects/painel/audio-panel/wave", json={"spec": {"timeline": 3}, "target": "audio.music"}
    )
    assert invalid.status_code == 400


@requires_ffmpeg
def test_the_window_route_returns_a_wav_for_playing_without_downloading_the_whole_file(client):
    reply = client.post(
        "/api/projects/painel/audio-panel/window",
        json={"spec": spec_with(), "target": "audio.voiceover.0", "start": 0.5, "end": 1.0},
    )
    assert reply.status_code == 200 and reply.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(reply.content)) as handle:
        assert handle.getnframes() == RATE // 2
    assert float(reply.headers["x-window-seconds"]) == pytest.approx(0.5)
    too_long = client.post(
        "/api/projects/painel/audio-panel/window",
        json={"spec": spec_with(), "target": "audio.voiceover.0", "start": 4.0, "end": 9.0},
    )
    assert too_long.status_code == 400 and "não cabe" in too_long.json()["detail"]


@requires_ffmpeg
def test_the_preview_route_returns_the_window_with_the_effect_and_the_exactness_headers(client):
    effect = {"type": "amplify", "gain_db": 6.0, "prevent_clipping": False}
    before = client.post(
        "/api/projects/painel/audio-panel/window",
        json={"spec": spec_with(), "target": "audio.voiceover.0", "start": 0.5, "end": 1.5},
    )
    after = client.post(
        "/api/projects/painel/audio-panel/preview",
        json={"spec": spec_with(), "target": "audio.voiceover.0", "start": 0.5, "end": 1.5, "effect": effect},
    )
    assert after.status_code == 200, after.text
    assert after.headers["x-preview-exact"] == "1" and unquote(after.headers["x-preview-note"]) == ""

    assert rms(pcm_of(after.content)) / rms(pcm_of(before.content)) == pytest.approx(2.0, rel=0.03)
    bad = client.post(
        "/api/projects/painel/audio-panel/preview",
        json={
            "spec": spec_with(),
            "target": "audio.voiceover.0",
            "start": 0.0,
            "end": 1.0,
            "effect": {"type": "nao-existe"},
        },
    )
    assert bad.status_code == 400


def test_wav_bytes_roundtrip_matches_the_input_within_one_step():
    samples = tone(200, 0.1, 0.5)[:, None]
    with wave.open(io.BytesIO(wav_bytes(samples, RATE))) as handle:
        back = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2") / 32768.0
    assert np.abs(back - samples[:, 0]).max() < 1 / 16384
    with pytest.raises(ValueError):
        wav_bytes(np.zeros(4, np.float32), RATE)


def test_an_empty_pyramid_has_no_duration_and_the_base_block_is_the_documented_one():
    assert BASE_BLOCK == 64 and PeakPyramid(RATE, 1, 0).duration == 0.0
