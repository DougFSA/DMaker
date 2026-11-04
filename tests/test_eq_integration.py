"""Equalização e filtros com ffmpeg de verdade: os cinco critérios do DMK-54 medidos no som.

Os sinais são gerados no teste (tons, voz sintética de harmônicos, ruído rosa) e a medida sai de FFT em numpy, então o que
se espera vem de conta e não de comparação com uma execução anterior. O arquivo processado é WAV de ponto flutuante, onde
dá para medir sem a perda do AAC; o render completo, que sai em AAC, só entra onde a tolerância é de décimos de dB.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_effects import get_effect_preset, parse_effect
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects import frequency_response
from dmaker.media import ffmpeg
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def db(value: float) -> float:
    return 20 * np.log10(max(float(value), 1e-12))


def write_wav(path: Path, samples: np.ndarray) -> Path:
    stereo = np.stack([samples, samples], axis=1).astype("<f4")
    command = [
        str(config.find_tool("ffmpeg")),
        "-v",
        "error",
        "-y",
        "-f",
        "f32le",
        "-ar",
        str(RATE),
        "-ac",
        "2",
    ]
    subprocess.run([*command, "-i", "-", "-c:a", "pcm_f32le", str(path)], input=stereo.tobytes(), check=True)
    return path


def decode(path: Path, rate: int = RATE) -> np.ndarray:
    """O canal esquerdo do arquivo (os sinais do teste são iguais nos dois; misturar em mono somaria +3 dB)."""
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path), "-vn", "-ac", "2"]
    command += ["-ar", str(rate), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")[0::2]


def tone(freq: float, seconds: float = 4.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(round(seconds * RATE)) / RATE
    return amp * np.sin(2 * np.pi * freq * t)


def pink_noise(seconds: float = 20.0, seed: int = 1) -> np.ndarray:
    """Ruído rosa (potência proporcional a 1/f) normalizado a 0,5 de pico."""
    n = round(seconds * RATE)
    spectrum = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    freqs[0] = 1.0
    noise = np.fft.irfft(spectrum / np.sqrt(freqs), n)
    return noise / np.max(np.abs(noise)) * 0.5


def amplitude_at(samples: np.ndarray, freq: float, rate: int = RATE) -> float:
    """A amplitude do componente de `freq` Hz (um bin de DFT sobre a parte estável, com janela de Hann)."""
    part = samples[int(0.5 * rate) : int(3.5 * rate)].astype(np.float64)
    t = np.arange(len(part)) / rate
    window = np.hanning(len(part))
    return float(2 * abs(np.sum(part * window * np.exp(-2j * np.pi * freq * t))) / np.sum(window))


def welch(samples: np.ndarray, segment: int = 16384) -> tuple[np.ndarray, np.ndarray]:
    window = np.hanning(segment)
    total, count = 0.0, 0
    for start in range(0, len(samples) - segment, segment // 2):
        total = total + np.abs(np.fft.rfft(samples[start : start + segment] * window)) ** 2
        count += 1
    return np.fft.rfftfreq(segment, 1 / RATE)[1:], (total / count)[1:]


def measured_response(before: np.ndarray, after: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    freqs, power_before = welch(before)
    _, power_after = welch(after)
    return freqs, 10 * np.log10(power_after / power_before)


@pytest.fixture
def processor(tmp_path) -> EffectProcessor:
    return EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx")


def run_chain(processor: EffectProcessor, tmp_path: Path, signal: np.ndarray, *items: dict) -> np.ndarray:
    source = write_wav(tmp_path / "entrada.wav", signal)
    done = processor.process(
        AudioItem(source, len(signal) / RATE, tuple(parse_effect(item) for item in items))
    )
    assert done is not None
    return decode(done.path)


# ---------- critério 1: passa-alta 80 Hz a 24 dB por oitava ----------


def test_highpass_80_hz_24_db_drops_40_hz_by_at_least_22_db_and_moves_1_khz_by_less_than_half_a_db(
    tmp_path, processor
):
    chain = {"type": "highpass", "frequency_hz": 80, "slope_db": 24}
    low = tone(40.0)
    drop = db(amplitude_at(run_chain(processor, tmp_path, low, chain), 40.0) / amplitude_at(low, 40.0))
    mid = tone(1000.0)
    change = db(amplitude_at(run_chain(processor, tmp_path, mid, chain), 1000.0) / amplitude_at(mid, 1000.0))
    assert drop <= -22.0  # medido: -24,1 dB, o que a ordem 4 de Butterworth dá
    assert abs(change) < 0.5  # medido: menos de 0,001 dB


# ---------- critério 2: Notch em 60 Hz ----------


def test_notch_60_hz_removes_the_hum_of_a_synthetic_recording_and_leaves_the_voice(tmp_path, processor):
    voice_hz = (220.0, 660.0, 1500.0, 2700.0)
    voice = sum(tone(f, amp=0.12) for f in voice_hz)
    recording = voice + tone(60.0, amp=0.1)
    out = run_chain(processor, tmp_path, recording, {"type": "notch", "frequency_hz": 60, "q": 10})
    hum = db(amplitude_at(out, 60.0) / amplitude_at(recording, 60.0))
    assert hum < -30.0  # medido: mais de 80 dB
    for f in voice_hz:
        assert abs(db(amplitude_at(out, f) / amplitude_at(recording, f))) < 0.5, f


def test_the_60_hz_hum_preset_takes_out_the_harmonics_too(tmp_path, processor):
    hums = (60.0, 120.0, 180.0, 240.0, 300.0)
    voice = tone(550.0, amp=0.2) + tone(1800.0, amp=0.1)
    recording = voice + sum(tone(f, amp=0.05) for f in hums)
    chain = [dict(effect) for effect in get_effect_preset("hum_60hz").effects]
    out = run_chain(processor, tmp_path, recording, *chain)
    for f in hums:
        assert db(amplitude_at(out, f) / amplitude_at(recording, f)) < -30.0, f
    for f in (550.0, 1800.0):
        assert abs(db(amplitude_at(out, f) / amplitude_at(recording, f))) < 0.1, f


# ---------- critério 3: EQ Gráfico ----------


def test_graphic_eq_plus_6_db_at_3150_hz_measures_plus_6_on_pink_noise(tmp_path, processor):
    gains = [0.0] * 31
    gains[22] = 6.0  # a banda de 3,15 kHz
    noise = pink_noise()
    out = run_chain(processor, tmp_path, noise, {"type": "graphic_eq", "gains_db": gains})
    assert len(out) == len(noise)
    freqs, change = measured_response(noise, out)
    power_before = welch(noise)[1]
    power_after = welch(out)[1]
    third = (freqs >= 3150 * 2 ** (-1 / 6)) & (freqs <= 3150 * 2 ** (1 / 6))
    band = 10 * np.log10(power_after[third].sum() / power_before[third].sum())
    center = change[np.argmin(np.abs(freqs - 3150))]
    assert band == pytest.approx(6.0, abs=1.0)  # medido: +5,8 dB na banda de um terço de oitava
    assert center == pytest.approx(6.0, abs=0.2)  # medido: +6,0 dB no centro
    far = (freqs < 1000) | (freqs > 8000)
    assert np.max(np.abs(change[far & (freqs > 60)])) < 0.3  # as outras bandas ficam onde estavam


# ---------- critério 4: o gráfico bate com o render ----------

CASES = [
    ({"type": "bass_treble", "bass_db": 8, "treble_db": -6, "volume_db": 2}, 0.1),
    ({"type": "low_shelf", "frequency_hz": 300, "gain_db": -10, "slope": 0.7}, 0.1),
    ({"type": "high_shelf", "frequency_hz": 5000, "gain_db": 9}, 0.1),
    ({"type": "highpass", "frequency_hz": 100, "slope_db": 12}, 0.2),
    ({"type": "lowpass", "frequency_hz": 3000, "slope_db": 36}, 0.1),
    ({"type": "notch", "frequency_hz": 1000, "q": 2}, 0.3),
    (
        {
            "type": "classic_filter",
            "family": "chebyshev1",
            "mode": "lowpass",
            "order": 6,
            "frequency_hz": 2000,
        },
        0.15,
    ),
    (
        {
            "type": "classic_filter",
            "family": "chebyshev2",
            "mode": "highpass",
            "order": 6,
            "frequency_hz": 2000,
        },
        0.15,
    ),
    (
        {
            "type": "graphic_eq",
            "gains_db": [
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                2,
                4,
                5,
                3,
                0,
                0,
                -2,
                -4,
                -4,
                -2,
                0,
                0,
                1,
                3,
                6,
                4,
                0,
                0,
                0,
                -3,
                -6,
                -6,
                -3,
            ],
        },
        0.7,
    ),
    (
        {
            "type": "graphic_eq",
            "interpolation": "cubic",
            "gains_db": [
                3,
                3,
                2,
                1,
                0,
                0,
                0,
                1,
                2,
                3,
                4,
                4,
                3,
                1,
                0,
                -1,
                -2,
                -3,
                -3,
                -2,
                0,
                1,
                2,
                3,
                3,
                2,
                1,
                0,
                -2,
                -4,
                -5,
            ],
        },
        0.4,
    ),
    (
        {
            "type": "filter_curve_eq",
            "points": [
                {"hz": 30, "db": -12},
                {"hz": 100, "db": 6},
                {"hz": 400, "db": -4},
                {"hz": 1500, "db": 8},
                {"hz": 6000, "db": -9},
                {"hz": 16000, "db": 3},
            ],
        },
        0.4,
    ),
]


@pytest.mark.parametrize(
    ("effect", "tolerance"), CASES, ids=[case[0]["type"] + str(i) for i, case in enumerate(CASES)]
)
def test_the_curve_the_interface_draws_matches_the_response_measured_in_the_render(
    tmp_path, processor, effect, tolerance
):
    """Ruído rosa de 20 s pelo efeito, e a razão entre os espectros contra `frequency_response` do mesmo efeito. Vale de
    80 Hz a 18 kHz e onde o ganho esperado passa de -25 dB (mais fundo, o vazamento da janela do espectro mede a conta, não o filtro). Abaixo de
    80 Hz o FIR de 8191 amostras do EQ por pontos não separa bandas coladas (ver o manual)."""
    noise = pink_noise()
    out = run_chain(processor, tmp_path, noise, effect)
    assert len(out) == len(noise)
    freqs, measured = measured_response(noise, out)
    drawn = frequency_response(parse_effect(effect), freqs)
    usable = (freqs > 80) & (freqs < 18000) & (drawn > -25)
    worst = np.max(np.abs(measured[usable] - drawn[usable]))
    assert worst < tolerance, f"{effect['type']}: erro máximo {worst:.3f} dB"


def test_the_eq_does_not_move_the_sound_or_change_its_length_even_inside_an_interval(tmp_path, processor):
    signal = pink_noise(6.0)
    curve = {
        "type": "filter_curve_eq",
        "points": [{"hz": 200, "db": -8}, {"hz": 3000, "db": 8}],
        "length": 2047,
    }
    whole = run_chain(processor, tmp_path, signal, curve)
    assert len(whole) == len(signal)
    lag = int(np.argmax(np.correlate(whole[:20000], signal[:20000], "full"))) - 19999
    assert lag == 0  # o atraso do FIR é compensado
    part = run_chain(processor, tmp_path, signal, {**curve, "start": 2.0, "end": 4.0})
    assert len(part) == len(signal)
    untouched = slice(0, round(1.9 * RATE))
    assert np.max(np.abs(part[untouched] - signal[untouched])) < 1e-6  # fora do intervalo o som passa intacto
    inside = slice(round(2.2 * RATE), round(3.8 * RATE))
    assert np.max(np.abs(part[inside] - signal[inside])) > 0.01


# ---------- o render completo ----------


def no_sync(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult(0.0, confidence=0.0)


def render_mix(folder: Path, name: str, **audio) -> np.ndarray:
    project = Project.model_validate(
        {
            "name": "eq",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 4, "mute": True}],
            "audio": {"normalize": "off", **audio},
        }
    )
    project.base_dir = folder
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, 16000)


def test_a_voiceover_chain_and_a_master_chain_are_applied_by_the_real_render(tmp_path):
    ffmpeg.run(
        ["-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=15:d=4"]
        + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(tmp_path / "video.mp4")],
        quiet=True,
    )
    write_wav(tmp_path / "fala.wav", tone(40.0, 4.0, 0.2) + tone(1000.0, 4.0, 0.2))
    voice = {"src": "fala.wav"}
    highpass = {"type": "highpass", "frequency_hz": 80, "slope_db": 24}
    base = render_mix(tmp_path, "base", voiceover=[voice])
    item = render_mix(tmp_path, "item", voiceover=[{**voice, "effects": [highpass]}])
    master = render_mix(tmp_path, "master", voiceover=[voice], master_effects=[highpass])
    for name, rendered in (("item", item), ("master", master)):
        low = db(amplitude_at(rendered, 40.0, 16000) / amplitude_at(base, 40.0, 16000))
        mid = db(amplitude_at(rendered, 1000.0, 16000) / amplitude_at(base, 1000.0, 16000))
        assert low <= -22.0, name
        assert abs(mid) < 0.5, name
