"""Atraso, Eco, Reverb, Distorção, Phaser, Tremolo, Wahwah e Vocoder com ffmpeg de verdade, medidos em sinais conhecidos.

Cada critério do card tem aqui o número que o mede: o primeiro eco de um clique a 300 ms com metade da amplitude, o RT60 de um
clique depois de passar pelo `afir`, a envoltória do Tremolo a 5 Hz, o Vocoder reconhecido pelo Whisper (com os modelos
de voz de verdade, só com `DMAKER_VOICE_SMOKE=1`) e o pico de todo efeito e predefinição abaixo de 0 dBFS.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_effects import EFFECT_PRESETS, parse_effect
from dmaker.domain.audio_effects.creative_presets import REVERB_RT60_RANGES
from dmaker.domain.spec import Project
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.wavio import write_wav_float
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor

from .audio_measure import (
    RATE,
    burst,
    click,
    dominant_frequency,
    envelope_peaks,
    peak_db,
    schroeder_rt60,
    write_speech_like,
)
from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def decode(path: Path, channels: int = 2, rate: int = RATE) -> np.ndarray:
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path), "-vn"]
    command += ["-ac", str(channels), "-ar", str(rate), "-f", "f32le", "-"]
    data = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")
    return data.reshape(-1, channels)


@pytest.fixture
def processor(tmp_path) -> EffectProcessor:
    return EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx")


def process(
    processor: EffectProcessor, source: Path, seconds: float, *chain: dict
) -> tuple[np.ndarray, float]:
    done = processor.process(AudioItem(source, seconds, tuple(parse_effect(item) for item in chain)))
    assert done is not None
    return decode(done.path), done.duration


@pytest.fixture
def clicks(tmp_path) -> Path:
    return write_wav_float(tmp_path / "clique.wav", click(8.0), RATE)


@pytest.fixture
def speech(tmp_path) -> Path:
    return write_speech_like(tmp_path / "fala.wav", 6.0)


def peaks_after(samples: np.ndarray, threshold: float = 1e-4) -> list[tuple[float, float]]:
    """Os instantes (ms depois do primeiro pico) e as amplitudes dos picos acima do limiar, num sinal feito de cliques."""
    found = np.nonzero(np.abs(samples[:, 0]) > threshold)[0]
    origin = found[0]
    return [(round((i - origin) / RATE * 1000, 3), float(samples[i, 0])) for i in found]


# ---------- Eco ----------


def test_the_echo_of_a_click_comes_back_at_300_ms_with_half_the_amplitude(processor, clicks):
    samples, duration = process(processor, clicks, 8.0, {"type": "echo", "delay_seconds": 0.3, "decay": 0.5})
    found = peaks_after(samples)
    assert found[0] == (0.0, pytest.approx(0.8, abs=1e-4))
    assert found[1] == (300.0, pytest.approx(0.4, abs=1e-4))  # o primeiro eco: 300 ms, metade
    assert [round(moment) for moment, _ in found[:6]] == [0, 300, 600, 900, 1200, 1500]
    assert [round(amplitude / 0.8, 4) for _, amplitude in found[:6]] == pytest.approx(
        [0.5**k for k in range(6)], abs=2e-4
    )
    assert duration == pytest.approx(8.0) and len(samples) == 8 * RATE  # o item mantém a duração


def test_the_echo_keeps_going_until_minus_60_db_and_the_tail_can_extend_the_item(processor, clicks):
    samples, _ = process(processor, clicks, 8.0, {"type": "echo", "delay_seconds": 0.3, "decay": 0.5})
    found = peaks_after(samples, 1e-5)
    assert len(found) == 11 and found[-1][0] == pytest.approx(3000.0)  # 10 repetições, a última a -62 dB
    longer, duration = process(
        processor, clicks, 8.0, {"type": "echo", "delay_seconds": 3.0, "decay": 0.5, "extend_tail": True}
    )
    assert duration == pytest.approx(8.0 + 30.0) and len(longer) == round(38.0 * RATE)
    cut, _ = process(processor, clicks, 8.0, {"type": "echo", "delay_seconds": 3.0, "decay": 0.5})
    # o clique em 0,5 s e ecos a cada 3 s: o item de 8 s guarda os de 3,5 s e 6,5 s; esticado, os 10 ecos até 30,5 s
    assert len(peaks_after(cut)) == 3 and len(peaks_after(longer)) == 11


# ---------- Atraso ----------


def test_the_delay_repeats_at_equal_gaps_with_the_volume_falling_per_echo(processor, clicks):
    samples, _ = process(
        processor,
        clicks,
        8.0,
        {"type": "delay", "delay_seconds": 0.4, "echoes": 3, "decay_db": -6, "dry_db": 0},
    )
    found = peaks_after(samples)
    assert [round(moment) for moment, _ in found] == [0, 400, 800, 1200]
    assert [amplitude / 0.8 for _, amplitude in found] == pytest.approx([1.0, 0.501, 0.251, 0.126], abs=1e-3)


def test_the_bouncing_delay_closes_in_and_the_reverse_one_opens_up(processor, clicks):
    bouncing, _ = process(
        processor, clicks, 8.0, {"type": "delay", "delay_type": "bouncing", "delay_seconds": 1.0, "echoes": 4}
    )
    reverse, _ = process(
        processor,
        clicks,
        8.0,
        {"type": "delay", "delay_type": "reverse_bouncing", "delay_seconds": 1.0, "echoes": 4},
    )
    first = np.diff([moment for moment, _ in peaks_after(bouncing)])
    second = np.diff([moment for moment, _ in peaks_after(reverse)])
    assert list(first) == pytest.approx([1000, 700, 490, 343], abs=1) and list(second) == pytest.approx(
        first[::-1], abs=1
    )


def test_the_delay_dry_gain_scales_the_original_and_leaves_the_echoes(processor, clicks):
    samples, _ = process(
        processor,
        clicks,
        8.0,
        {"type": "delay", "delay_seconds": 0.5, "echoes": 1, "decay_db": 0, "dry_db": -12},
    )
    first, second = peaks_after(samples)
    assert first[1] / second[1] == pytest.approx(10 ** (-12 / 20), rel=1e-3)


def test_the_delay_can_raise_the_pitch_of_each_echo_with_the_rubberband(processor, tmp_path):
    t = np.arange(round(1.0 * RATE)) / RATE
    burst = np.zeros((4 * RATE, 2), dtype=np.float32)
    burst[: len(t)] = (0.4 * np.sin(2 * np.pi * 440.0 * t))[:, None]
    source = write_wav_float(tmp_path / "rajada.wav", burst, RATE)
    samples, duration = process(
        processor,
        source,
        4.0,
        {"type": "delay", "delay_seconds": 1.5, "echoes": 1, "pitch_semitones": 12, "decay_db": 0},
    )
    assert duration == pytest.approx(4.0) and len(samples) == 4 * RATE
    echo = samples[round(1.6 * RATE) : round(2.4 * RATE), 0]
    first = samples[round(0.1 * RATE) : round(0.9 * RATE), 0]
    spectrum = lambda x: np.fft.rfftfreq(len(x), 1 / RATE)[
        int(np.argmax(np.abs(np.fft.rfft(x * np.hanning(len(x))))))
    ]  # noqa: E731
    assert spectrum(first) == pytest.approx(440.0, abs=3.0) and spectrum(echo) == pytest.approx(
        880.0, abs=4.0
    )


# ---------- Reverb ----------


def rt60_of(processor: EffectProcessor, source: Path, effect: dict) -> float:
    samples, _ = process(processor, source, 8.0, {**effect, "wet_only": True})
    return schroeder_rt60(samples, round(0.5 * RATE) + 1)


def test_the_small_room_reverb_gives_a_dry_click_the_reverb_time_of_the_preset(processor, clicks):
    effect = dict(EFFECT_PRESETS["reverb_small_room_bright"].effects[0])
    measured = rt60_of(processor, clicks, effect)
    low, high = REVERB_RT60_RANGES["reverb_small_room_bright"]
    assert low <= measured <= high
    assert measured > 0.2  # o clique seco não tem reverberação nenhuma antes do efeito


@pytest.mark.parametrize("preset_id", sorted(REVERB_RT60_RANGES))
def test_every_audacity_reverb_preset_lands_in_its_reverb_time_range_after_the_ffmpeg_convolution(
    processor, clicks, preset_id
):
    measured = rt60_of(processor, clicks, dict(EFFECT_PRESETS[preset_id].effects[0]))
    low, high = REVERB_RT60_RANGES[preset_id]
    assert low <= measured <= high, f"{preset_id}: RT60 {measured:.2f} s fora de {low} a {high}"


def test_the_reverb_mixes_dry_and_wet_with_no_latency_and_wet_only_drops_the_original(processor, clicks):
    effect = {"type": "reverb", "room_size": 30, "wet_db": -12, "dry_db": 0}
    samples, _ = process(processor, clicks, 8.0, effect)
    at = round(0.5 * RATE)
    assert samples[at, 0] == pytest.approx(0.8, abs=0.01)  # o clique seco no mesmo quadro: sem atraso
    assert float(np.abs(samples[at + 1 : at + 480]).max()) < 0.2
    wet_only, _ = process(processor, clicks, 8.0, {**effect, "wet_only": True})
    assert abs(float(wet_only[at, 0])) < 0.05 and float(np.abs(wet_only[at:]).max()) > 0
    silent_wet, _ = process(processor, clicks, 8.0, {"type": "reverb", "wet_db": -60, "dry_db": -6})
    assert silent_wet[at, 0] == pytest.approx(0.8 * 10 ** (-6 / 20), abs=0.01)


def test_the_reverb_pre_delay_holds_the_wet_back_and_the_stereo_width_splits_the_sides(processor, clicks):
    base = {"type": "reverb", "wet_only": True, "room_size": 30, "wet_db": 0}
    late, _ = process(processor, clicks, 8.0, {**base, "pre_delay_ms": 100})
    onset = int(np.nonzero(np.abs(late[:, 0]) > 1e-5)[0][0]) - round(0.5 * RATE)
    assert onset >= round(0.100 * RATE)
    narrow, _ = process(processor, clicks, 8.0, {**base, "stereo_width": 0})
    wide, _ = process(processor, clicks, 8.0, {**base, "stereo_width": 100})
    assert np.allclose(narrow[:, 0], narrow[:, 1], atol=1e-6)
    assert abs(float(np.corrcoef(wide[:, 0], wide[:, 1])[0, 1])) < 0.3


def test_the_reverb_tail_extends_the_item_when_asked_and_is_cut_at_the_item_end_otherwise(
    processor, tmp_path
):
    source = write_wav_float(tmp_path / "curto.wav", click(1.0, at=0.9), RATE)
    cut, duration = process(processor, source, 1.0, {"type": "reverb", "reverberance": 90, "wet_only": True})
    assert duration == pytest.approx(1.0) and len(cut) == RATE
    extended, extended_duration = process(
        processor, source, 1.0, {"type": "reverb", "reverberance": 90, "wet_only": True, "extend_tail": True}
    )
    assert extended_duration > 4.0 and len(extended) == pytest.approx(extended_duration * RATE, abs=2)
    assert float(np.abs(extended[RATE:]).max()) > 0.001  # a cauda existe depois do fim do item


def test_two_items_with_the_same_room_share_one_impulse_file_and_the_second_run_is_cached(tmp_path, clicks):
    runner = SubprocessRunner(quiet=True)
    runs: list[str] = []
    original = runner.run
    runner.run = lambda command: (runs.append(command.label), original(command))[1]  # type: ignore[method-assign]
    processor = EffectProcessor(runner, tmp_path / "fx")
    chain = tuple(parse_effect(item) for item in ({"type": "reverb"},))
    processor.process(AudioItem(clicks, 8.0, chain))
    processor.process(AudioItem(clicks, 8.0, chain))
    processor.process(AudioItem(clicks, 7.5, chain))
    assert len(runs) == 2  # o segundo item igual vem do cache; o de 7,5 s refaz o grafo
    assert len(list(config.REVERB_IR_DIR.glob("*.wav"))) == 1


# ---------- Tremolo ----------


@pytest.fixture
def tone(tmp_path) -> Path:
    t = np.arange(5 * RATE) / RATE
    wave = (0.5 * np.sin(2 * np.pi * 440.0 * t))[:, None]
    return write_wav_float(tmp_path / "tom.wav", np.repeat(wave, 2, axis=1).astype(np.float32), RATE)


def test_the_tremolo_envelope_oscillates_at_5_hz_with_the_asked_depth(processor, tone):
    samples, _ = process(
        processor, tone, 5.0, {"type": "tremolo", "frequency_hz": 5, "depth": 50, "waveform": "sine"}
    )
    envelope = envelope_peaks(samples)
    assert dominant_frequency(envelope, 0.01) == pytest.approx(5.0, abs=0.05)
    assert float(envelope.max()) == pytest.approx(0.5, abs=0.005)  # o topo é o nível original
    assert float(envelope.min() / envelope.max()) == pytest.approx(0.5, abs=0.02)  # o fundo é 1 - 50%


@pytest.mark.parametrize("waveform", ["sine", "triangle", "sawtooth", "inverse_sawtooth", "square"])
def test_every_tremolo_waveform_follows_the_frequency_and_the_depth(processor, tone, waveform):
    samples, _ = process(
        processor, tone, 5.0, {"type": "tremolo", "frequency_hz": 4, "depth": 80, "waveform": waveform}
    )
    envelope = envelope_peaks(
        samples, 128
    )  # 2,7 ms: mais que o período do tom (2,3 ms) e curto para a rampa não mexer no fundo
    assert dominant_frequency(envelope, 128 / RATE) == pytest.approx(4.0, abs=0.05)
    assert float(envelope.min() / envelope.max()) == pytest.approx(0.2, abs=0.03)


def test_the_tremolo_start_phase_moves_the_wave_and_the_gain_never_exceeds_one(processor, tone):
    first, _ = process(
        processor, tone, 5.0, {"type": "tremolo", "frequency_hz": 2, "depth": 100, "waveform": "triangle"}
    )
    shifted, _ = process(
        processor,
        tone,
        5.0,
        {"type": "tremolo", "frequency_hz": 2, "depth": 100, "waveform": "triangle", "phase_degrees": 180},
    )
    one, two = envelope_peaks(first), envelope_peaks(shifted)
    assert one[0] < 0.03 and two[0] > 0.45  # o triângulo começa embaixo; com 180 graus, em cima
    assert float(np.abs(first).max()) <= 0.5 + 1e-4 and float(np.abs(shifted).max()) <= 0.5 + 1e-4


# ---------- Phaser, Wahwah e Distorção ----------


def white_noise(path: Path, seconds: float = 8.0) -> Path:
    rng = np.random.default_rng(3)
    wave = 0.1 * rng.standard_normal((round(seconds * RATE), 1))
    return write_wav_float(path, np.repeat(wave, 2, axis=1).astype(np.float32), RATE)


def tracked(samples: np.ndarray, low: float, high: float, notch: bool) -> np.ndarray:
    """O ponto mais fundo (ou mais alto) do espectro suavizado entre `low` e `high`, a cada 100 ms."""
    series = []
    for first in range(0, len(samples) - 4800, 4800):
        segment = samples[first : first + 4800, 0] * np.hanning(4800)
        spectrum = np.abs(np.fft.rfft(segment, 16384)) ** 2
        hz = np.fft.rfftfreq(16384, 1 / RATE)
        band = (hz >= low) & (hz <= high)
        smooth = np.convolve(spectrum[band], np.ones(15) / 15, mode="same")
        series.append(hz[band][np.argmin(smooth) if notch else np.argmax(smooth)])
    return np.array(series)


def test_the_phaser_notch_sweeps_at_the_lfo_frequency(processor, tmp_path):
    noise = white_noise(tmp_path / "ruido.wav")
    samples, _ = process(
        processor, noise, 8.0, {"type": "phaser", "stages": 2, "lfo_hz": 0.5, "depth": 100, "output_db": 0}
    )
    notch = tracked(samples, 100, 4000, notch=True)
    assert dominant_frequency(notch, 0.1) == pytest.approx(0.5, abs=0.07)
    assert (
        250 < notch.min() < 400 and 1300 < notch.max() < 1800
    )  # a varredura de 2,35 oitavas em volta de 700 Hz


def test_the_wah_center_sweeps_at_the_lfo_frequency_between_the_pedal_ends(processor, tmp_path):
    noise = white_noise(tmp_path / "ruido.wav")
    samples, _ = process(
        processor,
        noise,
        8.0,
        {"type": "wahwah", "lfo_hz": 1.0, "depth": 100, "offset": 0, "resonance": 4, "output_db": 0},
    )
    center = tracked(samples, 150, 4000, notch=False)
    assert dominant_frequency(center, 0.1) == pytest.approx(1.0, abs=0.1)
    assert center.min() < 450 and center.max() > 1900


def test_a_sample_effect_with_an_interval_leaves_the_rest_of_the_item_untouched(processor, tmp_path):
    noise = white_noise(tmp_path / "ruido.wav", 4.0)
    original = decode(noise)
    samples, duration = process(
        processor,
        noise,
        4.0,
        {
            "type": "distortion",
            "kind": "hard_clip",
            "threshold_db": -40,
            "dc_filter": False,
            "start": 1.0,
            "end": 2.0,
        },
    )
    assert duration == pytest.approx(4.0)
    assert np.array_equal(samples[: round(0.98 * RATE)], original[: round(0.98 * RATE)])
    assert np.array_equal(samples[round(2.02 * RATE) :], original[round(2.02 * RATE) :])
    inside = samples[round(1.1 * RATE) : round(1.9 * RATE)]
    assert float(np.abs(inside).max()) == pytest.approx(10 ** (-40 / 20), rel=1e-3)


# ---------- Vocoder ----------


def test_the_vocoder_turns_a_voice_into_the_pitch_of_the_sawtooth_carrier(processor, speech):
    samples, duration = process(processor, speech, 6.0, {"type": "vocoder"})
    assert duration == pytest.approx(6.0) and samples.shape == (6 * RATE, 2)
    voiced = samples[RATE : 5 * RATE, 0].astype(np.float64)
    spectrum = np.abs(np.fft.rfft(voiced * np.hanning(len(voiced))))
    hz = np.fft.rfftfreq(len(voiced), 1 / RATE)
    low = (hz > 60) & (hz < 600)
    harmonic_comb = [spectrum[np.argmin(np.abs(hz - 110.0 * k))] for k in range(2, 8)]
    between = [spectrum[np.argmin(np.abs(hz - 110.0 * (k + 0.5)))] for k in range(2, 8)]
    # a série harmônica da dente de serra de 110 Hz se vê na região grave: as linhas ficam bem acima do meio entre elas
    assert np.mean(harmonic_comb) > 3 * np.mean(between)
    assert low.any()


def test_the_vocoder_follows_the_voice_in_time_and_takes_any_signal_generator_as_carrier(processor, speech):
    original = decode(speech)
    default, _ = process(processor, speech, 6.0, {"type": "vocoder"})
    noisy, _ = process(
        processor,
        speech,
        6.0,
        {"type": "vocoder", "carrier": {"generator": "noise", "params": {"noise_type": "pink"}}},
    )
    assert not np.allclose(default, noisy)
    block = 4800
    voice_level = np.array(
        [np.sqrt(np.mean(original[i : i + block, 0] ** 2)) for i in range(0, 5 * RATE, block)]
    )
    robot_level = np.array(
        [np.sqrt(np.mean(default[i : i + block, 0] ** 2)) for i in range(0, 5 * RATE, block)]
    )
    assert float(np.corrcoef(voice_level, robot_level)[0, 1]) > 0.8  # o ritmo da fala passa para a portadora


@pytest.mark.skipif(
    os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="modelos reais: defina DMAKER_VOICE_SMOKE=1"
)
def test_the_whisper_still_recognizes_the_test_phrase_after_the_vocoder(processor, tmp_path):
    from dmaker.text.transcribe import WhisperTranscriber
    from dmaker.voice.kokoro import KokoroSynthesizer
    from dmaker.voice.synth import VoiceRequest

    phrase = "Hoje o dia está lindo, e vamos passear no parque com os nossos amigos."
    speech = KokoroSynthesizer(models_dir=config.MODELS_DIR / "kokoro").synthesize(VoiceRequest(phrase, "pt"))
    wave = np.repeat(speech.samples[:, None] * 0.8, 2, axis=1).astype(np.float32)
    source = write_wav_float(tmp_path / "frase_24k.wav", wave, speech.sample_rate)
    resampled = tmp_path / "frase.wav"
    subprocess.run(
        [
            str(config.find_tool("ffmpeg")),
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-ar",
            "48000",
            "-c:a",
            "pcm_f32le",
            str(resampled),
        ],
        check=True,
    )
    duration = len(wave) / speech.sample_rate
    done = processor.process(AudioItem(resampled, duration, (parse_effect({"type": "vocoder"}),)))
    assert done is not None
    robot = tmp_path / "robo.wav"
    subprocess.run(
        [
            str(config.find_tool("ffmpeg")),
            "-y",
            "-v",
            "error",
            "-i",
            str(done.path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(robot),
        ],
        check=True,
    )
    transcript = WhisperTranscriber().transcribe(robot, "pt")
    text = " ".join(word.text.lower().strip(".,!?") for cue in transcript.cues for word in cue.words)
    expected = phrase.lower().replace(",", "").replace(".", "").split()
    hits = sum(word in text.split() for word in expected)
    assert hits / len(expected) >= 0.8, text


# ---------- no render ----------


def no_sync(*_args, **_kwargs):
    return SyncResult(0.0, 0.0, 0.0)


def render_mix(project: Project, folder: Path, name: str) -> np.ndarray:
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, 1, 16000)[:, 0]


def make_video(path: Path, seconds: float = 6.0) -> Path:
    command = [str(config.find_tool("ffmpeg")), "-y", "-v", "error", "-f", "lavfi", "-i"]
    command += [f"color=c=gray:size=320x180:rate=15:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast"]
    subprocess.run([*command, "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def project(folder: Path, **audio) -> Project:
    built = Project.model_validate(
        {
            "name": "criativos",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 6, "mute": True}],
            "audio": {"normalize": "off", **audio},
        }
    )
    built.base_dir = folder
    return built


def test_the_reverb_in_the_master_chain_reaches_the_rendered_mix_and_the_vocoder_is_refused_there(tmp_path):
    make_video(tmp_path / "video.mp4")
    write_wav_float(tmp_path / "rajada.wav", burst(3.0), RATE)
    voice = [{"src": "rajada.wav"}]
    dry = render_mix(project(tmp_path, voiceover=voice), tmp_path, "seco")
    wet = render_mix(
        project(
            tmp_path, voiceover=voice, master_effects=[{"type": "reverb", "reverberance": 70, "wet_db": 0}]
        ),
        tmp_path,
        "molhado",
    )
    tail = slice(round(0.9 * 16000), round(2.5 * 16000))
    assert float(np.abs(dry[tail]).max()) < 0.005
    assert (
        float(np.abs(wet[tail]).max()) > 0.02
    )  # a cauda do reverb aparece depois da rajada, na mixagem final
    with pytest.raises(ValueError, match="amostras"):
        project(tmp_path, voiceover=voice, master_effects=[{"type": "vocoder"}])


def test_the_effects_chain_on_a_voiceover_renders_with_the_new_effects(tmp_path):
    make_video(tmp_path / "video.mp4")
    write_speech_like(tmp_path / "fala.wav", 4.0)
    chain = [
        {"type": "distortion", "kind": "soft_clip"},
        {"type": "tremolo"},
        {"type": "echo", "delay_seconds": 0.2},
    ]
    mixed = render_mix(
        project(tmp_path, voiceover=[{"src": "fala.wav", "effects": chain}]), tmp_path, "cadeia"
    )
    assert float(np.abs(mixed[: 3 * 16000]).max()) > 0.05 and float(np.abs(mixed).max()) <= 1.0


# ---------- o pico, nunca acima de 0 dBFS ----------

CREATIVE_TYPES = ("delay", "echo", "reverb", "distortion", "phaser", "tremolo", "wahwah", "vocoder")
USE_PRESETS = ("phone_voice", "old_radio_voice", "room_narration", "ethereal_music", *REVERB_RT60_RANGES)


# O arquivo processado é de ponto flutuante: nada corta ali, e a normalização final da mistura é que traz o pico para baixo. Num
# sinal sintético o pico depende de onde os picos do som e dos ecos caem juntos (de -0,1 a +1,6 dBFS nas sementes medidas), então
# o que se prende aqui é a ordem de grandeza: um erro de ganho (o dobro, um reverb que sobe 6 dB) passa de 2 dBFS. O número do card,
# o de cada efeito e predefinição sobre fala sintetizada de verdade, é o do teste seguinte (com os modelos de voz).
SYNTHETIC_HEADROOM_DB = 2.0


@pytest.mark.parametrize(
    "chain",
    [pytest.param([{"type": name}], id=name) for name in CREATIVE_TYPES]
    + [pytest.param([dict(e) for e in EFFECT_PRESETS[name].effects], id=name) for name in USE_PRESETS],
)
def test_the_default_effects_and_the_presets_do_not_raise_the_level_beyond_the_synthetic_speech_headroom(
    processor, speech, chain
):
    samples, _ = process(processor, speech, 6.0, *chain)
    assert peak_db(samples) < SYNTHETIC_HEADROOM_DB


@pytest.mark.skipif(
    os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="modelos reais: defina DMAKER_VOICE_SMOKE=1"
)
def test_the_float_peak_of_every_effect_and_preset_on_real_synthesized_speech_stays_below_0_dbfs(
    processor, tmp_path
):
    """A medida do card: cada efeito com os parâmetros padrão e cada predefinição, sobre uma fala do Kokoro a -1 dBFS, no arquivo
    de ponto flutuante (antes da normalização final). Imprime a tabela (pytest -s) que vai para o manual."""
    from dmaker.voice.kokoro import KokoroSynthesizer
    from dmaker.voice.synth import VoiceRequest

    text = "Hoje o dia está lindo, e vamos passear no parque com os nossos amigos. Depois nós voltamos para casa e comemos pizza."
    speech = KokoroSynthesizer(models_dir=config.MODELS_DIR / "kokoro").synthesize(VoiceRequest(text, "pt"))
    mono = speech.samples.astype(np.float64)
    wave = np.repeat(mono[:, None], 2, axis=1)
    raw = write_wav_float(tmp_path / "fala_24k.wav", wave.astype(np.float32), speech.sample_rate)
    source = tmp_path / "fala_real.wav"
    subprocess.run(
        [
            str(config.find_tool("ffmpeg")),
            "-y",
            "-v",
            "error",
            "-i",
            str(raw),
            "-ar",
            "48000",
            "-c:a",
            "pcm_f32le",
            str(source),
        ],
        check=True,
    )
    base = decode(source)
    write_wav_float(source, base * np.float32(10 ** (-1.0 / 20) / np.abs(base).max()), RATE)
    seconds = len(base) / RATE
    over = []
    for name, chain in [
        *[(t, [{"type": t}]) for t in CREATIVE_TYPES],
        *[(p, [dict(e) for e in EFFECT_PRESETS[p].effects]) for p in USE_PRESETS],
    ]:
        samples, _ = process(processor, source, seconds, *chain)
        level = peak_db(samples)
        print(f"{name:28s} pico {level:6.2f} dBFS")
        if level >= 0.0:
            over.append(name)
    assert not over, over
