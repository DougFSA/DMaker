"""Tempo e afinação com ffmpeg de verdade: tons e ruído gerados no teste, e a medida de cada critério do card.

O arquivo processado pelo `EffectProcessor` é WAV de ponto flutuante, onde a frequência e a duração se medem sem a perda do
AAC. A frequência sai da contagem de cruzamentos por zero (interpolada), que num tom puro erra menos de 0,01 Hz.
"""

from __future__ import annotations

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
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.preview_audio import PreviewAudioBuilder

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def decode(path: Path, rate: int = RATE, channels: int = 2) -> np.ndarray:
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path), "-vn"]
    command += ["-ac", str(channels), "-ar", str(rate), "-f", "f32le", "-"]
    data = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")
    return data.reshape(-1, channels)


def tone(path: Path, hz: float = 440.0, amp: float = 0.5, seconds: float = 5.0) -> Path:
    expression = f"aevalsrc={amp}*sin(2*PI*{hz}*t)|{amp}*sin(2*PI*{hz}*t):s={RATE}:d={seconds}"
    ffmpeg.run(["-f", "lavfi", "-i", expression, "-c:a", "pcm_f32le", str(path)], quiet=True)
    return path


def noise(path: Path, seconds: float = 5.0, amp: float = 0.3) -> Path:
    command = ["-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=white:r={RATE}:a={amp}:seed=5", "-ac", "2"]
    ffmpeg.run([*command, "-c:a", "pcm_f32le", str(path)], quiet=True)
    return path


def frequency(samples: np.ndarray, start: float = 1.0, stop: float | None = None) -> float:
    """A frequência de um tom em Hz, pelos cruzamentos por zero de subida com interpolação linear entre as amostras."""
    window = samples[int(start * RATE) : int((stop or len(samples) / RATE - 1.0) * RATE), 0]
    rising = np.nonzero(np.diff(np.signbit(window).astype(np.int8)) == 1)[0]
    crossing = rising + window[rising] / (window[rising] - window[rising + 1])
    return float((len(crossing) - 1) / ((crossing[-1] - crossing[0]) / RATE))


def process(folder: Path, source: Path, *chain: dict, seconds: float = 5.0) -> tuple[np.ndarray, float]:
    processor = EffectProcessor(SubprocessRunner(quiet=True), folder / "fx")
    done = processor.process(AudioItem(source, seconds, tuple(parse_effect(item) for item in chain)))
    assert done is not None
    return decode(done.path), done.duration


def block_levels(samples: np.ndarray, block: float = 0.05) -> np.ndarray:
    size = int(block * RATE)
    mono = samples[:, 0].astype(np.float64)
    return np.array([np.sqrt(np.mean(mono[i : i + size] ** 2)) for i in range(0, len(mono) - size + 1, size)])


@pytest.fixture
def work(tmp_path) -> Path:
    return tmp_path


# ---------- Mudar Tom ----------


def test_change_pitch_plus_two_semitones_on_440_hz_gives_493_9_hz_and_keeps_the_duration(work):
    out, declared = process(work, tone(work / "a440.wav"), {"type": "change_pitch", "semitones": 2})
    assert frequency(out) == pytest.approx(493.883, abs=0.5)  # o critério pede 493,9 Hz com 1 Hz de folga
    assert abs(len(out) / RATE - 5.0) < 0.010  # a duração muda menos de 10 ms
    assert declared == 5.0


@pytest.mark.parametrize(
    "effect, expected",
    [
        ({"mode": "notes", "from_note": "A", "from_octave": 4, "to_note": "C", "to_octave": 5}, 523.251),
        ({"mode": "percent", "percent": 50}, 660.0),
        ({"semitones": -12}, 220.0),
        ({"semitones": 0, "cents": 100}, 466.164),
    ],
)
def test_change_pitch_by_note_percent_octave_and_cents_lands_on_the_right_frequency(work, effect, expected):
    out, _ = process(work, tone(work / "a440.wav"), {"type": "change_pitch", **effect})
    assert frequency(out) == pytest.approx(expected, abs=0.5)
    assert abs(len(out) / RATE - 5.0) < 0.010


def test_change_pitch_with_formants_preserved_has_the_same_pitch_and_duration(work):
    out, _ = process(
        work, tone(work / "a440.wav"), {"type": "change_pitch", "semitones": 2, "preserve_formants": True}
    )
    assert frequency(out) == pytest.approx(493.883, abs=0.5) and abs(len(out) / RATE - 5.0) < 0.010


def test_change_pitch_inside_an_interval_moves_only_that_stretch_and_keeps_the_seams_smooth(work):
    source = tone(work / "a440.wav", amp=0.5)
    out, _ = process(work, source, {"type": "change_pitch", "semitones": 12, "start": 2.0, "end": 3.5})
    assert len(out) / RATE == pytest.approx(5.0, abs=0.010)
    assert frequency(out, 0.5, 1.8) == pytest.approx(440.0, abs=0.3)  # antes: intacto
    assert frequency(out, 2.2, 3.3) == pytest.approx(880.0, abs=1.5)  # dentro: uma oitava acima
    assert frequency(out, 3.8, 4.5) == pytest.approx(440.0, abs=0.3)  # depois: intacto
    assert np.abs(np.diff(out[:, 0])).max() < 0.5 * 2 * np.pi * 880 / RATE * 1.5  # sem degrau nas emendas


# ---------- Mudar Andamento ----------


def test_change_tempo_from_120_to_128_bpm_shortens_by_120_over_128_and_keeps_the_pitch(work):
    effect = {"type": "change_tempo", "mode": "bpm", "bpm_from": 120, "bpm_to": 128}
    out, declared = process(work, tone(work / "a440.wav"), effect)
    assert len(out) / RATE == pytest.approx(5.0 * 120 / 128, abs=0.005)
    assert (len(out) / RATE) / 5.0 == pytest.approx(120 / 128, rel=0.001)
    assert declared == pytest.approx(len(out) / RATE, abs=0.005)  # o que a vista mostra é o que o arquivo tem
    assert frequency(out) == pytest.approx(440.0, abs=0.3)  # o tom não mudou


@pytest.mark.parametrize(
    "effect, ratio",
    [
        ({"mode": "percent", "percent": -50}, 0.5),
        ({"mode": "duration", "length_from": 5, "length_to": 4}, 1.25),  # 5 s passam a durar 4 s
        ({"mode": "percent", "percent": 100}, 2.0),
    ],
)
def test_change_tempo_by_percent_and_by_duration(work, effect, ratio):
    out, declared = process(work, tone(work / "a440.wav"), {"type": "change_tempo", **effect})
    assert len(out) / RATE == pytest.approx(5.0 / ratio, abs=0.01)
    assert declared == pytest.approx(len(out) / RATE, abs=0.01)
    assert frequency(out, 0.6, len(out) / RATE - 0.6) == pytest.approx(440.0, abs=0.3)


def test_change_tempo_inside_an_interval_changes_only_that_stretch(work):
    effect = {"type": "change_tempo", "percent": 100, "start": 1.0, "end": 3.0}
    out, declared = process(work, tone(work / "a440.wav"), effect)
    assert len(out) / RATE == pytest.approx(4.0, abs=0.01) and declared == pytest.approx(4.0, abs=0.01)
    assert frequency(out, 0.2, 0.9) == pytest.approx(440.0, abs=0.3)
    assert frequency(out, 1.3, 1.8) == pytest.approx(440.0, abs=0.5)


# ---------- Mudar Velocidade e Tom ----------


def test_change_speed_from_45_to_33_and_a_third_rpm_lowers_pitch_and_speed_together(work):
    effect = {"type": "change_speed", "mode": "rpm", "rpm_from": 45, "rpm_to": 100 / 3}
    out, declared = process(work, tone(work / "a440.wav"), effect)
    ratio = (100 / 3) / 45
    assert frequency(out) == pytest.approx(440 * ratio, rel=0.001)  # 325,9 Hz
    assert (len(out) / RATE) == pytest.approx(5.0 / ratio, rel=0.001)  # 6,75 s
    assert declared == pytest.approx(len(out) / RATE, abs=0.002)


@pytest.mark.parametrize("rpm_to, ratio", [(78, 78 / 45), (45, 1.0)])
def test_change_speed_to_78_and_to_the_same_rpm(work, rpm_to, ratio):
    effect = {"type": "change_speed", "mode": "rpm", "rpm_from": 45, "rpm_to": rpm_to}
    out, _ = process(work, tone(work / "a440.wav"), effect)
    assert frequency(out) == pytest.approx(440 * ratio, rel=0.001)
    assert len(out) / RATE == pytest.approx(5.0 / ratio, rel=0.001)


# ---------- Esticar Gradualmente ----------


def test_sliding_stretch_slows_down_and_lowers_the_pitch_by_steps_without_a_click_and_lasts_as_declared(work):
    effect = {
        "type": "sliding_stretch",
        "tempo_start": 0,
        "tempo_end": -50,
        "pitch_start": 0,
        "pitch_end": -12,
    }
    out, declared = process(work, tone(work / "a440.wav", amp=0.5), effect)
    assert len(out) / RATE == pytest.approx(declared, abs=0.020)  # a integral do andamento bate com o arquivo
    assert 6.5 < declared < 7.2  # 5 ln(2) / 0,5 = 6,93 s
    early, middle = frequency(out, 0.3, 0.8), frequency(out, declared / 2 - 0.25, declared / 2 + 0.25)
    late = frequency(out, declared - 1.0, declared - 0.3)
    assert (
        0.88 * 440 < early < 440 and late < 0.62 * 440 and early > middle > late
    )  # o tom desce o tempo todo
    assert (
        np.abs(np.diff(out[:, 0])).max() < 1.2 * 0.5 * 2 * np.pi * 440 / RATE
    )  # nenhum salto maior que o do tom puro
    levels = block_levels(out)[2:-2]  # sem o ataque e o rabo do próprio filtro
    assert levels.min() > 0.75 * np.median(levels)  # nem um bloco de 50 ms some no meio


# ---------- Paulstretch ----------


def test_paulstretch_8x_of_five_seconds_gives_forty_seconds_without_a_click_or_a_gap(work):
    source = noise(work / "ruido.wav", amp=0.3)
    out, declared = process(work, source, {"type": "paulstretch", "stretch_factor": 8})
    assert len(out) == pytest.approx(40 * RATE, abs=2) and declared == 40.0
    original = decode(source)[:, 0]
    steps, original_steps = np.diff(out[:, 0]), np.diff(original)
    # A maior diferença entre amostras vizinhas, medida em desvios padrão da própria diferença: o ruído de 40 s tem 8 vezes
    # mais amostras que o de 5 s e, por isso, extremos maiores. Um estalo seria dezenas de desvios; o ruído gaussiano, uns 5.
    assert np.abs(steps).max() / steps.std() < 6.5
    assert (
        np.abs(steps).max() < 2.5 * np.abs(original_steps).max()
    )  # e em valor absoluto, no mesmo nível do original
    levels = block_levels(out)
    assert levels.min() > 0.8 * np.median(levels)  # o pior bloco de 50 ms ainda tem o nível do resto
    assert float(np.sqrt(np.mean(out[:, 0].astype(np.float64) ** 2))) == pytest.approx(
        float(np.sqrt(np.mean(original.astype(np.float64) ** 2))), rel=0.05
    )  # a energia se conserva


def test_paulstretch_keeps_the_pitch_of_a_chord_and_stays_continuous(work):
    expression = (
        f"aevalsrc=0.15*(sin(2*PI*220*t)+sin(2*PI*277.18*t)+sin(2*PI*329.63*t))|0.15*(sin(2*PI*220*t)+sin(2*PI*277.18*t)"
        f"+sin(2*PI*329.63*t)):s={RATE}:d=5"
    )
    source = work / "acorde.wav"
    ffmpeg.run(["-f", "lavfi", "-i", expression, "-c:a", "pcm_f32le", str(source)], quiet=True)
    out, _ = process(work, source, {"type": "paulstretch", "stretch_factor": 8})
    assert len(out) == pytest.approx(40 * RATE, abs=2)
    spectrum = np.abs(np.fft.rfft(out[10 * RATE : 20 * RATE, 0] * np.hanning(10 * RATE)))
    frequencies = np.fft.rfftfreq(10 * RATE, 1 / RATE)
    top = frequencies[np.argsort(spectrum)[-30:]]
    for note in (220.0, 277.18, 329.63):  # as três notas continuam no espectro
        assert np.abs(top - note).min() < 8.0
    assert block_levels(out).min() > 0.3 * np.median(block_levels(out))  # sem silêncio no meio


def test_the_stretched_item_is_cached_and_a_second_pass_does_not_run_it_again(work):
    source = noise(work / "ruido.wav", seconds=2.0)
    processor = EffectProcessor(SubprocessRunner(quiet=True), work / "fx")
    item = AudioItem(source, 2.0, (parse_effect({"type": "paulstretch", "stretch_factor": 4}),))
    first = processor.process(item)
    stamp = first.path.stat().st_mtime_ns
    second = processor.process(item)
    assert second.path == first.path and second.path.stat().st_mtime_ns == stamp and first.duration == 8.0
    other = processor.process(
        AudioItem(
            source, 2.0, (parse_effect({"type": "paulstretch", "stretch_factor": 4, "time_resolution": 0.5}),)
        )
    )
    assert other.path != first.path


def test_the_processor_refuses_a_stretch_above_twenty_minutes_before_spending_any_work(work):
    source = noise(work / "ruido.wav", seconds=5.0)
    processor = EffectProcessor(SubprocessRunner(quiet=True), work / "fx")
    item = AudioItem(source, 5.0, (parse_effect({"type": "paulstretch", "stretch_factor": 300}),))  # 25 min
    with pytest.raises(ValueError, match="teto"):
        processor.process(item)
    assert not (work / "fx").exists() or not list((work / "fx").glob("*"))


def test_a_chain_of_tempo_pitch_and_stretch_runs_in_order_and_adds_up_the_durations(work):
    chain = (
        {"type": "change_tempo", "percent": 100},  # 5 s -> 2,5 s
        {"type": "paulstretch", "stretch_factor": 4},  # -> 10 s
        {"type": "change_pitch", "semitones": 12},  # sem mudar a duração
    )
    out, declared = process(work, tone(work / "a440.wav"), *chain)
    assert declared == pytest.approx(10.0, abs=0.01) and len(out) / RATE == pytest.approx(10.0, abs=0.02)
    assert frequency(out, 2.0, 8.0) == pytest.approx(880.0, abs=3.0)


# ---------- no render, na vista e na prévia ----------


def no_sync(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult(0.0, confidence=0.0)


def spec(folder: Path, **audio) -> Project:
    project = Project.model_validate(
        {
            "name": "tempo",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 8, "mute": True}],
            "audio": {"normalize": "off", **audio},
        }
    )
    project.base_dir = folder
    return project


@pytest.fixture
def media(work) -> Path:
    ffmpeg.run(
        ["-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=15:d=8"]
        + ["-f", "lavfi", "-i", f"aevalsrc=0.2*sin(2*PI*330*t):s={RATE}:d=8"]
        + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
        + [str(work / "video.mp4")],
        quiet=True,
    )
    tone(work / "fala.wav", hz=440.0, amp=0.4, seconds=3.0)
    tone(work / "musica.wav", hz=220.0, amp=0.3, seconds=8.0)
    return work


def render_audio(project: Project, folder: Path, name: str) -> np.ndarray:
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, 16000, 1)[:, 0]


def test_a_recorded_voice_sped_up_by_the_render_plays_for_the_declared_length(media):
    chain = [{"type": "change_tempo", "percent": 100}, {"type": "change_pitch", "semitones": 2}]
    played = render_audio(
        spec(media, voiceover=[{"src": "fala.wav", "start": 1.0, "effects": chain}]), media, "voz"
    )
    level = np.abs(played)
    active = np.nonzero(np.convolve(level, np.ones(800) / 800, mode="same") > 0.05)[0]
    assert active[0] / 16000 == pytest.approx(1.0, abs=0.1)
    assert active[-1] / 16000 == pytest.approx(2.5, abs=0.1)  # 3 s a 2x tocam por 1,5 s, a partir de 1 s


def test_the_music_stretched_by_paulstretch_covers_the_video_instead_of_ending_early(media):
    short = spec(media, music={"src": "musica.wav", "volume": 1.0, "ducking": False, "loop": False})
    long = spec(
        media,
        music={
            "src": "musica.wav",
            "volume": 1.0,
            "ducking": False,
            "loop": False,
            "effects": [{"type": "change_tempo", "percent": -50}],  # 8 s -> 16 s
        },
    )
    base, slow = render_audio(short, media, "mus"), render_audio(long, media, "mus-lenta")
    assert np.abs(base[int(7 * 16000) : int(7.8 * 16000)]).max() > 0.05
    assert np.abs(slow[int(7 * 16000) : int(7.8 * 16000)]).max() > 0.05
    assert len(slow) == pytest.approx(len(base), abs=800)  # o vídeo continua com 8 s


def test_the_preview_follows_a_change_of_the_pitch_and_sounds_like_the_render(media):
    plain = spec(media, voiceover=[{"src": "fala.wav", "start": 1.0}])
    changed = spec(
        media,
        voiceover=[
            {
                "src": "fala.wav",
                "start": 1.0,
                "effects": [
                    {"type": "change_pitch", "semitones": 12},
                    {"type": "change_tempo", "percent": 50},
                ],
            }
        ],
    )
    builder = PreviewAudioBuilder(
        offset_finder=no_sync, cache_dir=media / "preview-audio", jobs_dir=media / "preview-jobs"
    )
    before, after = builder.build(plain), builder.build(changed)
    assert after.key != before.key  # o campo novo entra na receita da prévia
    rendered = render_audio(changed, media, "paridade")
    played = decode(after.path, 16000, 1)[:, 0]
    size = min(len(played), len(rendered))
    a, b = played[:size] - played[:size].mean(), rendered[:size] - rendered[:size].mean()
    assert float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))) > 0.97
    assert after.duration == pytest.approx(probe(media / "paridade.mp4").duration, abs=0.1)
