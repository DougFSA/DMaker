"""Volume e dinâmica com ffmpeg de verdade: sinais de nível conhecido e a medida de cada critério do DMK-52.

Compressor (a LRA cai), Limitador (nenhum pico verdadeiro acima do teto), Noise Gate (o silêncio cai a redução e o começo
das palavras fica inteiro), Normalização de loudness (duas falas chegam ao mesmo alvo) e Auto Duck (a faixa de fundo cai
a quantidade pedida só enquanto a outra fala).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_effects import parse_effect
from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.preview_audio import PreviewAudioBuilder

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def db(value: float) -> float:
    return 20 * np.log10(max(float(value), 1e-12))


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))


def write_wav(path: Path, samples: np.ndarray) -> Path:
    if samples.ndim == 1:
        samples = np.stack([samples, samples], axis=1)
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
    subprocess.run(
        [*command, "-i", "-", "-c:a", "pcm_f32le", str(path)],
        input=samples.astype("<f4").tobytes(),
        check=True,
    )
    return path


def decode(path: Path, rate: int = RATE, channels: int = 2) -> np.ndarray:
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path), "-vn"]
    command += ["-ac", str(channels), "-ar", str(rate), "-f", "f32le", "-"]
    data = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")
    return data.reshape(-1, channels)


def loudness(path: Path) -> dict[str, float]:
    """O LUFS integrado, a LRA e o pico verdadeiro (dBTP) do arquivo, pelo ebur128."""
    command = [str(config.find_tool("ffmpeg")), "-hide_banner", "-nostats", "-i", str(path)]
    command += ["-af", "ebur128=framelog=quiet:peak=true", "-f", "null", "-"]
    report = subprocess.run(command, capture_output=True, text=True).stderr

    def grab(pattern: str) -> float:
        return float(re.search(pattern, report).group(1))

    return {
        "I": grab(r"I:\s+(-?[\d.]+) LUFS"),
        "LRA": grab(r"LRA:\s+(-?[\d.]+) LU"),
        "TP": grab(r"Peak:\s+(-?[\d.]+) dBFS"),
    }


def speech(phrases: list[tuple[float, float]], seed: int = 3) -> np.ndarray:
    """Frases (segundos, dBFS RMS) separadas por pausas de 0,6 s de chiado a -55 dB."""
    rng = np.random.default_rng(seed)
    parts = []
    for seconds, level in phrases:
        t = np.arange(round(seconds * RATE)) / RATE
        tones = (
            np.sin(2 * np.pi * 180 * t)
            + 0.6 * np.sin(2 * np.pi * 540 * t + 0.7)
            + 0.3 * np.sin(2 * np.pi * 1210 * t)
        )
        body = tones * (0.45 + 0.55 * np.sin(2 * np.pi * 4 * t) ** 2)
        parts.append(body / rms(body) * 10 ** (level / 20))
        pause = rng.standard_normal(round(0.6 * RATE))
        parts.append(pause / rms(pause) * 10 ** (-55 / 20))
    return np.concatenate(parts).astype(np.float32)


def effects(*items: dict) -> tuple:
    return tuple(parse_effect(item) for item in items)


@pytest.fixture
def processor(tmp_path) -> EffectProcessor:
    return EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx")


def process(processor: EffectProcessor, source: Path, chain: tuple, seconds: float):
    done = processor.process(AudioItem(source, seconds, chain))
    assert done is not None
    return done


# ---------- Compressor ----------


def test_compressor_4_to_1_at_minus_20_db_narrows_the_loudness_range_and_keeps_the_length(
    tmp_path, processor
):
    signal = speech([(3, -14), (3, -30), (3, -20), (3, -38), (3, -16), (3, -26)])
    source = write_wav(tmp_path / "fala.wav", signal)
    before = loudness(source)
    done = process(
        processor,
        source,
        effects(
            {
                "type": "compressor",
                "threshold_db": -20,
                "ratio": 4,
                "knee_db": 6,
                "attack_ms": 10,
                "release_ms": 100,
            }
        ),
        len(signal) / RATE,
    )
    after = loudness(done.path)
    assert after["LRA"] < before["LRA"] - 3  # medido: 15,3 LU antes, 9,8 LU depois
    assert len(decode(done.path)) == len(signal)


def test_the_compressor_lookahead_is_compensated_so_the_sound_does_not_move(tmp_path, processor):
    t = np.arange(round(3 * RATE)) / RATE
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    source = write_wav(tmp_path / "tom.wav", tone)
    chain = effects({"type": "compressor", "threshold_db": -60, "ratio": 1, "knee_db": 0, "lookahead_ms": 5})
    out = decode(process(processor, source, chain, 3.0).path)
    correlation = np.correlate(out[:20000, 0], tone[:20000], "full")
    assert int(np.argmax(correlation)) - 19999 == 0
    assert len(out) == len(tone)
    assert db(np.abs(out).max() / 0.3) == pytest.approx(0.0, abs=0.05)


# ---------- Limitador ----------


@pytest.mark.parametrize("kind", ["hard", "soft"])
def test_the_limiter_keeps_every_true_peak_under_the_ceiling(tmp_path, processor, kind):
    t = np.arange(round(3 * RATE)) / RATE
    rng = np.random.default_rng(1)
    signals = {
        "fala": np.clip(speech([(3, -8), (3, -6)]) * 1.6, -1.5, 1.5),
        "seno 11 kHz": 1.8 * np.sin(2 * np.pi * 11025 * t + 0.3),
        "ruido": 0.9 * rng.standard_normal(len(t)),  # 12 dB de pico: o pior caso para o pico entre amostras
    }
    for name, signal in signals.items():
        source = write_wav(tmp_path / f"{name.split()[0]}.wav", signal.astype(np.float32))
        chain = effects({"type": "limiter", "limit_type": kind, "ceiling_db": -1})
        done = process(processor, source, chain, len(signal) / RATE)
        assert loudness(done.path)["TP"] <= -1.0, name
        assert len(decode(done.path)) == len(signal)


# ---------- Noise Gate ----------


def test_the_gate_closes_the_hiss_by_the_chosen_reduction_and_leaves_the_start_of_each_word(
    tmp_path, processor
):
    rng = np.random.default_rng(5)
    parts, starts = [], []
    position = 0
    for k in range(6):
        n = round(0.45 * RATE)
        t = np.arange(n) / RATE
        word = (np.sin(2 * np.pi * (140 + 20 * k) * t) + 0.5 * np.sin(2 * np.pi * 800 * t + k)) * (
            np.minimum(t / 0.004, 1.0) * np.minimum((0.45 - t) / 0.05, 1.0)
        )
        parts.append(word / rms(word) * 10 ** (-22 / 20))
        starts.append(position)
        hiss = rng.standard_normal(round(0.7 * RATE))
        parts.append(hiss / rms(hiss) * 10 ** (-48 / 20))
        position += n + len(hiss)
    signal = np.concatenate(parts).astype(np.float32)
    source = write_wav(tmp_path / "palavras.wav", signal)
    gated = decode(
        process(
            processor,
            source,
            effects(
                {
                    "type": "noise_gate",
                    "threshold_db": -28,
                    "reduction_db": 18,
                    "attack_ms": 10,
                    "hold_ms": 50,
                }
            ),
            len(signal) / RATE,
        ).path
    )
    for s in starts:
        gap = slice(s + round(0.7 * RATE), s + round(1.1 * RATE))
        assert db(rms(signal[gap])) - db(rms(gated[gap, 0])) >= 18 - 0.5
        first = slice(s, s + round(0.02 * RATE))  # os 20 ms do começo da palavra
        assert db(rms(gated[first, 0])) == pytest.approx(db(rms(signal[first])), abs=0.1)


# ---------- Normalização de loudness ----------


def test_two_narrations_of_different_loudness_normalized_per_item_to_minus_16_lufs_measure_minus_16(
    tmp_path, processor
):
    loud = write_wav(tmp_path / "a.wav", speech([(4, -12), (4, -14)]))
    soft = write_wav(tmp_path / "b.wav", speech([(4, -30), (4, -33)], seed=9))
    assert abs(loudness(loud)["I"] - loudness(soft)["I"]) > 10
    chain = effects({"type": "loudness_normalize", "mode": "lufs", "target_db": -16})
    for source in (loud, soft):
        assert loudness(process(processor, source, chain, 8.6).path)["I"] == pytest.approx(-16.0, abs=0.5)


def test_loudness_in_rms_mode_and_the_mono_dual_mono_choice(tmp_path, processor):
    mono = speech([(4, -26), (4, -28)])
    path = tmp_path / "mono.wav"
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
        "1",
    ]
    subprocess.run([*command, "-i", "-", "-c:a", "pcm_f32le", str(path)], input=mono.tobytes(), check=True)
    dual = process(processor, path, effects({"type": "loudness_normalize", "target_db": -16}), 8.6).path
    single = process(
        processor, path, effects({"type": "loudness_normalize", "target_db": -16, "dual_mono": False}), 8.6
    ).path
    assert loudness(dual)["I"] == pytest.approx(-16.0, abs=0.5)
    assert loudness(single)["I"] - loudness(dual)["I"] == pytest.approx(3.0, abs=0.2)  # mono mede 3 LU abaixo
    rms_chain = effects({"type": "loudness_normalize", "mode": "rms", "target_db": -20})
    assert db(rms(decode(process(processor, path, rms_chain, 8.6).path))) == pytest.approx(-20.0, abs=0.2)


# ---------- Auto Duck ----------


def no_sync(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult(0.0, confidence=0.0)


def tone_at(
    hz: float, amp: float, seconds: float, bursts: list[tuple[float, float]] | None = None
) -> np.ndarray:
    t = np.arange(round(seconds * RATE)) / RATE
    signal = amp * np.sin(2 * np.pi * hz * t)
    if bursts is not None:
        gate = np.zeros_like(t)
        for first, last in bursts:
            gate[(t >= first) & (t < last)] = 1.0
        signal = signal * gate
    return signal.astype(np.float32)


def band_level(samples: np.ndarray, hz: float, first: float, last: float, rate: int = 16000) -> float:
    """O nível (dB) da componente de `hz` no trecho: os dois tons da mistura têm frequências bem separadas."""
    piece = samples[int(first * rate) : int(last * rate)]
    spectrum = np.abs(np.fft.rfft(piece * np.hanning(len(piece)))) / (len(piece) / 4)
    freqs = np.fft.rfftfreq(len(piece), 1 / rate)
    return db(spectrum[(freqs > hz - 20) & (freqs < hz + 20)].max())


def duck_project(folder: Path, ducks: list[dict], **audio) -> Project:
    ffmpeg.run(
        ["-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=15:d=10"]
        + ["-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo"]
        + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
        + [str(folder / "video.mp4")],
        quiet=True,
    )
    write_wav(folder / "dj.wav", tone_at(440, 0.2, 10))
    write_wav(folder / "celebrante.wav", tone_at(1000, 0.3, 10, [(3.0, 5.0), (7.0, 8.0)]))
    project = Project.model_validate(
        {
            "name": "duck",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "sources": {
                "cam": {"src": "video.mp4"},
                "dj": {"src": "dj.wav", "sync": 0.0},
                "celebrante": {"src": "celebrante.wav", "sync": 0.0},
            },
            "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 10, "mute": True}],
            "audio": {
                "tracks": [{"source": "dj"}, {"source": "celebrante"}],
                "normalize": "off",
                "ducks": ducks,
                **audio,
            },
        }
    )
    project.base_dir = folder
    return project


def render_pcm(project: Project, folder: Path, name: str) -> np.ndarray:
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, 16000, 1)[:, 0]


def test_auto_duck_between_two_external_tracks_lowers_the_background_only_while_the_other_speaks(tmp_path):
    rule = {"background": "A2", "key": "A3", "amount_db": -12}
    plain = render_pcm(duck_project(tmp_path, []), tmp_path, "plain")
    ducked = render_pcm(duck_project(tmp_path, [rule]), tmp_path, "ducked")
    # a chave fala de 3 a 5 s e de 7 a 8 s; a descida de 0,5 s termina quando ela começa e a subida começa quando ela cala
    for first, last, expected in [
        (0.3, 2.3, 0.0),
        (3.2, 4.8, -12.0),
        (5.7, 6.4, 0.0),
        (7.2, 7.8, -12.0),
        (8.8, 9.7, 0.0),
    ]:
        drop = band_level(ducked, 440, first, last) - band_level(plain, 440, first, last)
        assert drop == pytest.approx(expected, abs=0.5), (first, last)
    # a chave não muda (a regra só mexe na faixa de fundo)
    assert band_level(ducked, 1000, 3.2, 4.8) == pytest.approx(band_level(plain, 1000, 3.2, 4.8), abs=0.3)


def test_the_preview_ducks_the_same_way_and_a_rule_change_invalidates_it(tmp_path):
    builder = PreviewAudioBuilder(offset_finder=no_sync, cache_dir=tmp_path / "pa", jobs_dir=tmp_path / "pj")
    plain = builder.build(duck_project(tmp_path, []))
    ducked = builder.build(duck_project(tmp_path, [{"background": "A2", "key": "A3", "amount_db": -12}]))
    assert ducked.key != plain.key
    drop = band_level(decode(ducked.path, 16000, 1)[:, 0], 440, 3.2, 4.8) - band_level(
        decode(plain.path, 16000, 1)[:, 0], 440, 3.2, 4.8
    )
    assert drop == pytest.approx(-12.0, abs=0.5)


def test_a_music_rule_replaces_the_old_ducking_and_follows_the_voice(tmp_path):
    write_wav(tmp_path / "musica.wav", tone_at(220, 0.3, 10))
    write_wav(tmp_path / "fala.wav", tone_at(1000, 0.3, 4.0))
    music = {"src": "musica.wav", "volume": 0.5, "ducking": True}
    voice = [{"src": "fala.wav", "start": 3.0}]
    old = duck_project(tmp_path, [], music=music, voiceover=voice, tracks=[])
    new = duck_project(
        tmp_path,
        [{"background": "MUS", "key": "VO", "amount_db": -15}],
        music=music,
        voiceover=voice,
        tracks=[],
    )
    before, after = render_pcm(old, tmp_path, "old"), render_pcm(new, tmp_path, "new")
    # fora da voz a música está no nível de sempre; sob a voz cai 15 dB (a regra) e não o que o compressor antigo fazia
    assert band_level(after, 220, 0.3, 2.3) == pytest.approx(band_level(before, 220, 0.3, 2.3), abs=0.3)
    assert band_level(after, 220, 3.3, 6.5) - band_level(after, 220, 0.3, 2.3) == pytest.approx(
        -15.0, abs=0.7
    )
    assert band_level(before, 220, 3.3, 6.5) - band_level(before, 220, 0.3, 2.3) != pytest.approx(
        -15.0, abs=1.5
    )


# ---------- as ações de efeito ----------


def test_analyze_noise_suggests_the_noise_level_plus_six_db_from_the_quietest_stretch(tmp_path):
    from dmaker.pipeline.effect_actions import run_effect_action

    signal = speech([(3, -18), (3, -20)])  # pausas de 0,6 s de chiado a -55 dB RMS entre as frases
    write_wav(tmp_path / "fala.wav", signal)
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=320x180:rate=15:d=7",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={RATE}:cl=stereo",
        ]
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
            str(tmp_path / "video.mp4"),
        ],
        quiet=True,
    )
    project = Project.model_validate(
        {
            "name": "gate",
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 7, "mute": True}],
            "audio": {"voiceover": [{"src": "fala.wav"}], "normalize": "off"},
        }
    )
    project.base_dir = tmp_path
    answer = run_effect_action(project, "noise_gate", "analyze_noise", {"target": "audio.voiceover.0"})
    assert answer["source"] == "trecho mais quieto do item"
    assert -50.0 < answer["noise_db"] < -35.0  # o pico de 5 ms de um chiado de -55 dB RMS
    assert answer["fills"] == {"threshold_db": round(answer["noise_db"] + 6.0, 1)}
    with pytest.raises(Exception, match="perfil de ruído 'nenhum'"):
        run_effect_action(project, "noise_gate", "analyze_noise", {"profile": "nenhum"})
