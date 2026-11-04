"""Os fades e o crossfade de trilhas com ffmpeg de verdade: tons e ruído gerados no teste, medida numérica de cada critério.

O arquivo processado pelo `EffectProcessor` é WAV de ponto flutuante, onde a medida é exata; o render sai em AAC, onde a
tolerância é de décimos de dB.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_effects import parse_effect
from dmaker.domain.fade_curves import FADE_CURVES, crossfade_gains, fade_in_gain, monotonic
from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.edits import apply_edit

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def db(value: float) -> float:
    return 20 * math.log10(value)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def decode(path: Path, rate: int = RATE) -> np.ndarray:
    command = [
        str(config.find_tool("ffmpeg")),
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(rate),
    ]
    command += ["-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")


def make_source(path: Path, expression: str, seconds: float) -> Path:
    ffmpeg.run(
        ["-f", "lavfi", "-i", f"{expression}:s={RATE}:d={seconds}", "-c:a", "pcm_f32le", str(path)],
        quiet=True,
    )
    return path


def tone(path: Path, hz: float = 440.0, amp: float = 0.5, seconds: float = 4.0) -> Path:
    return make_source(path, f"aevalsrc={amp}*sin(2*PI*{hz}*t)|{amp}*sin(2*PI*{hz}*t)", seconds)


def noise(path: Path, seconds: float = 4.0) -> Path:
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=d={seconds}:c=white:r={RATE}:a=0.5:seed=7",
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(path),
        ],
        quiet=True,
    )
    return path


def process(folder: Path, source: Path, *chain: dict, seconds: float = 4.0) -> np.ndarray:
    processor = EffectProcessor(SubprocessRunner(quiet=True), folder / "fx")
    done = processor.process(AudioItem(source, seconds, tuple(parse_effect(item) for item in chain)))
    assert done is not None
    return decode(done.path)


def blocks(samples: np.ndarray, block: float = 0.05) -> list[float]:
    """O RMS de cada bloco de `block` segundos."""
    size = int(block * RATE)
    return [rms(samples[start : start + size]) for start in range(0, len(samples) - size + 1, size)]


def band_energy(samples: np.ndarray, low_hz: float) -> float:
    """A energia do espectro acima de `low_hz` (janela de Hann)."""
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)))) ** 2
    frequencies = np.fft.rfftfreq(len(samples), 1 / RATE)
    return float(spectrum[frequencies > low_hz].sum())


@pytest.fixture
def work(tmp_path) -> Path:
    return tmp_path


# ---------- as cinco curvas ----------


def test_the_five_curves_give_different_monotonic_envelopes_that_match_the_pure_functions(work):
    source = tone(work / "tom.wav", amp=0.5, seconds=2.0)
    reference = rms(decode(source))
    envelopes = {}
    for curve in FADE_CURVES:
        out = process(work, source, {"type": "fade_in", "duration": 2.0, "curve": curve}, seconds=2.0)
        envelope = np.array(blocks(out, 0.05)) / reference
        envelopes[curve] = envelope
        assert monotonic(list(envelope), rising=True) or np.all(
            np.diff(envelope) > -0.02
        )  # o RMS por bloco oscila pouco
        centres = (np.arange(len(envelope)) + 0.5) * 0.05 / 2.0
        expected = np.array([fade_in_gain(curve, u) for u in centres])
        keep = expected > 0.02  # a exponencial é -100 dB no começo: o ruído numérico do bloco não conta
        assert np.max(np.abs(envelope[keep] - expected[keep])) < 0.06, curve
    names = list(FADE_CURVES)
    for index, one in enumerate(names):
        for other in names[index + 1 :]:
            assert np.max(np.abs(envelopes[one] - envelopes[other])) > 0.1, f"{one} e {other} saíram iguais"


def test_a_fade_out_is_the_mirror_and_a_fade_with_an_interval_fills_the_interval(work):
    source = tone(work / "tom.wav", seconds=4.0)
    reference = rms(decode(source))
    out = process(work, source, {"type": "fade_out", "duration": 1.0, "curve": "sine"})
    envelope = np.array(blocks(out)) / reference
    assert envelope[: int(2.8 / 0.05)].min() > 0.98  # antes do fade o som passa intacto
    assert monotonic(list(envelope[int(3.0 / 0.05) :]), rising=False) or np.all(
        np.diff(envelope[int(3.0 / 0.05) :]) < 0.02
    )
    ranged = process(
        work, source, {"type": "fade_in", "start": 1.0, "end": 3.0, "curve": "linear", "duration": 0.1}
    )
    level = np.array(blocks(ranged)) / reference
    assert level[int(0.2 / 0.05)] > 0.97  # antes do intervalo, intacto
    middle = level[int(2.0 / 0.05)]
    assert middle == pytest.approx(0.5, abs=0.06)  # o fade ocupa o intervalo de 2 s, não os 0,1 s da duração
    assert level[int(3.5 / 0.05)] > 0.97


# ---------- Fade Ajustável: o fade parcial ----------


def test_a_partial_fade_from_100_to_40_percent_ends_8_db_below_the_start_without_reaching_silence(work):
    source = tone(work / "tom.wav", seconds=4.0)
    out = process(work, source, {"type": "adjustable_fade", "start_gain": 100, "end_gain": 40})
    start, end = rms(out[: int(0.1 * RATE)]), rms(out[-int(0.1 * RATE) :])
    assert db(end / start) == pytest.approx(-7.96, abs=0.5)  # 40% são -7,96 dB
    assert min(blocks(out)) > 0.3 * rms(decode(source))  # nunca chega ao silêncio
    assert monotonic(blocks(out)[::-1], rising=True) or np.all(np.diff(blocks(out)) < 0.01)


def test_the_adjustable_fade_in_decibels_and_in_s_shape_follows_its_curve(work):
    source = tone(work / "tom.wav", seconds=4.0)
    reference = rms(decode(source))
    out = process(
        work,
        source,
        {"type": "adjustable_fade", "shape": "s_up", "start_gain": -12, "end_gain": 0, "unit": "db"},
    )
    envelope = np.array(blocks(out)) / reference
    assert db(envelope[0]) == pytest.approx(-12.0, abs=0.5)
    assert db(envelope[-1]) == pytest.approx(0.0, abs=0.3)
    middle = envelope[len(envelope) // 2]
    assert middle == pytest.approx(
        (10 ** (-12 / 20) + 1.0) / 2, abs=0.04
    )  # o S cruza o meio no meio do caminho


# ---------- Studio Fade Out ----------


def test_the_studio_fade_out_has_less_energy_above_5_khz_at_the_end_than_a_linear_fade(work):
    source = noise(work / "ruido.wav", seconds=4.0)
    studio = process(work, source, {"type": "studio_fade_out", "duration": 3.0})
    linear = process(work, source, {"type": "fade_out", "duration": 3.0, "curve": "linear"})
    tail = slice(int(3.5 * RATE), int(3.9 * RATE))
    studio_hf, linear_hf = band_energy(studio[tail], 5000), band_energy(linear[tail], 5000)
    assert studio_hf < linear_hf
    # a parte dos agudos na energia total também cai: o filtro fecha, não só o volume
    assert studio_hf / band_energy(studio[tail], 0) < 0.2 * (linear_hf / band_energy(linear[tail], 0))
    assert rms(studio[: int(0.9 * RATE)]) == pytest.approx(
        rms(decode(source)[: int(0.9 * RATE)]), rel=0.03
    )  # antes: intacto
    assert studio[-int(0.05 * RATE) :].std() < 0.02  # e termina quase mudo


# ---------- crossfade de trilhas, no render ----------


def no_sync(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult(0.0, confidence=0.0)


def crossfaded_mix(work: Path, kind: str, second_hz: float, first_hz: float = 440.0) -> np.ndarray:
    """Duas vozes gravadas de mesmo nível que se cruzam de 1 s a 3 s, e o som renderizado (mono, 16 kHz)."""
    tone(work / "um.wav", hz=first_hz, amp=0.4, seconds=3.0)
    tone(work / "dois.wav", hz=second_hz, amp=0.4, seconds=2.0)
    project = Project.model_validate(
        {
            "name": "cruza-trilhas",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 4, "mute": True}],
            "audio": {
                "normalize": "off",
                "voiceover": [{"src": "um.wav", "start": 0}, {"src": "dois.wav", "start": 1.0}],
            },
        }
    )
    project.base_dir = work
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=160x90:rate=15:d=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(work / "video.mp4"),
        ],
        quiet=True,
    )
    project = apply_edit(
        project,
        {
            "type": "audio_crossfade_tracks",
            "out_target": "audio.voiceover.0",
            "in_target": "audio.voiceover.1",
            "start": 1.0,
            "end": 3.0,
            "kind": kind,
        },
    )
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=work / f"{kind}-{second_hz:g}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=work / f"mez-{kind}-{second_hz:g}",
        jobs_dir=work / f"jobs-{kind}-{second_hz:g}",
    ).run()
    return decode(result.output, 16000)


def middle_variation(mix: np.ndarray) -> tuple[float, float]:
    """O nível do meio do cruzamento (1,8 s a 2,2 s) menos o da voz sozinha antes dele (0,5 s a 0,9 s), em dB, e o RMS do meio."""
    rate = 16000
    edge = rms(mix[int(0.5 * rate) : int(0.9 * rate)])
    middle = rms(mix[int(1.8 * rate) : int(2.2 * rate)])
    return db(middle / edge), middle


def test_constant_power_between_two_tones_of_equal_level_does_not_dip_in_the_middle(work):
    """Sinais diferentes não se correlacionam: as potências somam, e a potência constante mantém o nível (< 1 dB)."""
    mix = crossfaded_mix(work, "constant_power_1", second_hz=660.0)
    delta, _ = middle_variation(mix)
    assert abs(delta) < 1.0
    # e o nível não cai em nenhum ponto do cruzamento inteiro (1,2 s a 2,8 s), medido de 0,1 em 0,1 s
    edge = rms(mix[int(0.5 * 16000) : int(0.9 * 16000)])
    inside = mix[int(1.2 * 16000) : int(2.8 * 16000)]
    size = int(0.1 * 16000)
    deviations = [
        abs(db(rms(inside[start : start + size]) / edge)) for start in range(0, len(inside) - size, size)
    ]
    assert max(deviations) < 1.0


def test_constant_gain_between_two_different_tones_dips_3_db_in_the_middle(work):
    mix = crossfaded_mix(work, "constant_gain", second_hz=660.0)
    delta, _ = middle_variation(mix)
    assert delta == pytest.approx(-3.0, abs=1.0)  # cada tom a -6 dB: dois tons descorrelacionados somam -3 dB


def test_the_same_tone_in_phase_rises_3_db_with_constant_power_and_stays_flat_with_constant_gain(work):
    """O mesmo sinal em fase dos dois lados: a potência constante SOBE 3 dB no meio (as amplitudes somam), e quem fica
    plano é o ganho constante. É física, não defeito: o manual diz qual escolher em cada caso."""
    power = crossfaded_mix(work, "constant_power_1", second_hz=440.0)
    gain = crossfaded_mix(work, "constant_gain", second_hz=440.0)
    up, _ = middle_variation(power)
    flat, _ = middle_variation(gain)
    assert up == pytest.approx(3.0, abs=1.0)
    assert abs(flat) < 1.0
    # a conta pura prevê os dois números
    out, entering = crossfade_gains("constant_power_1", 0.5)
    assert db(out + entering) == pytest.approx(3.01, abs=0.01)
    out, entering = crossfade_gains("constant_gain", 0.5)
    assert db(out + entering) == pytest.approx(0.0, abs=0.01)


def test_the_studio_fade_out_closes_the_whole_mix_when_put_in_the_master_chain(work):
    """O Studio Fade Out é filtro do ffmpeg, então vale no grafo ao vivo do master (os efeitos de amostras não valem)."""
    tone(work / "musica.wav", hz=440.0, amp=0.4, seconds=6.0)
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=160x90:rate=15:d=6",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(work / "video.mp4"),
        ],
        quiet=True,
    )
    project = Project.model_validate(
        {
            "name": "fim-de-radio",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 6, "mute": True}],
            "audio": {
                "normalize": "off",
                "music": {"src": "musica.wav", "volume": 1.0, "ducking": False, "fade_in": 0, "fade_out": 0},
                "master_effects": [{"type": "studio_fade_out", "duration": 2.0}],
            },
        }
    )
    project.base_dir = work
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=work / "radio.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=work / "mez-radio",
        jobs_dir=work / "jobs-radio",
    ).run()
    mix = decode(result.output, 16000)
    body = rms(mix[int(1.0 * 16000) : int(3.0 * 16000)])
    assert db(rms(mix[int(3.5 * 16000) : int(3.9 * 16000)]) / body) == pytest.approx(
        0.0, abs=0.5
    )  # até 4 s, intacto
    # no meio do fade (5 s, a metade dos 2 s que ele dura) a curva quadrática dá (1 - 0,5)^2 = -12 dB
    assert db(rms(mix[int(4.9 * 16000) : int(5.1 * 16000)]) / body) == pytest.approx(-12.0, abs=2.0)
    assert db(rms(mix[-int(0.1 * 16000) :]) / body) < -30  # fecha ao silêncio no fim da mistura


def test_an_edge_fade_on_a_clip_is_applied_inside_the_mezzanine(work):
    ffmpeg.run(
        ["-f", "lavfi", "-i", "color=c=gray:size=160x90:rate=15:d=6"]
        + ["-f", "lavfi", "-i", f"aevalsrc=0.4*sin(2*PI*440*t)|0.4*sin(2*PI*440*t):s={RATE}:d=6"]
        + [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(work / "clip.mp4"),
        ],
        quiet=True,
    )
    project = Project.model_validate(
        {
            "name": "fade-clipe",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [
                {
                    "type": "clip",
                    "src": "clip.mp4",
                    "start": 0,
                    "end": 6,
                    "effects": [
                        {"type": "fade_in", "duration": 1.0, "curve": "linear"},
                        {"type": "fade_out", "duration": 1.0, "curve": "linear"},
                    ],
                }
            ],
            "audio": {"normalize": "off"},
        }
    )
    project.base_dir = work
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=work / "fade.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=work / "mez-fade",
        jobs_dir=work / "jobs-fade",
    ).run()
    mix = decode(result.output, 16000)
    body = rms(mix[int(2 * 16000) : int(3 * 16000)])
    assert db(rms(mix[: int(0.1 * 16000)]) / body) < -15  # abre do silêncio
    assert db(rms(mix[int(0.45 * 16000) : int(0.55 * 16000)]) / body) == pytest.approx(
        -6.0, abs=1.0
    )  # meio do fade linear
    assert db(rms(mix[-int(0.1 * 16000) :]) / body) < -15  # fecha ao silêncio
