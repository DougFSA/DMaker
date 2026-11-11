"""A limpeza e o reparo do áudio com ffmpeg de verdade: sinais sintéticos de nível conhecido e medida em cada critério.

Cobre os critérios do DMK-55: o chiado cai pelo menos 10 dB com 12 dB de redução e a fala não muda; cliques somem sem
mexer no nível da fala; a senoide estourada fica mais perto da original; o Reparar refaz um trecho; nenhuma emenda
estala; e o Truncar Silêncio num clipe encurta a imagem e o som juntos, com o quadro e o som no mesmo instante.
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
from dmaker.media.ffmpeg import RecordingRunner, SubprocessRunner
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.edits import apply_edit_report
from dmaker.pipeline.noise_profiles import ProfileLocator

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def db(value: float) -> float:
    return 20 * np.log10(max(float(value), 1e-12))


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))


def decode(path: Path, rate: int = RATE, channels: int = 2) -> np.ndarray:
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path), "-vn"]
    command += ["-ac", str(channels), "-ar", str(rate), "-f", "f32le", "-"]
    data = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")
    return data.reshape(-1, channels)


def write_wav(path: Path, samples: np.ndarray) -> Path:
    """Grava `(amostras, canais)` como WAV de ponto flutuante estéreo de 48 kHz."""
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


def voice(seconds: float) -> np.ndarray:
    """Uma "fala" sintética de ~-14 dBFS RMS: três tons sob uma envoltória silábica de 4 Hz."""
    t = np.arange(round(seconds * RATE)) / RATE
    tones = (
        np.sin(2 * np.pi * 180 * t)
        + 0.6 * np.sin(2 * np.pi * 540 * t + 0.7)
        + 0.3 * np.sin(2 * np.pi * 1210 * t)
    )
    return (0.17 * tones * (0.55 + 0.45 * np.sin(2 * np.pi * 4 * t) ** 2)).astype(np.float32)


def hiss(seconds: float, level_db: float, seed: int = 7) -> np.ndarray:
    noise = np.random.default_rng(seed).standard_normal(round(seconds * RATE))
    return (noise / rms(noise) * 10 ** (level_db / 20)).astype(np.float32)


def count_clicks(samples: np.ndarray, limit: float = 0.15) -> int:
    """Picos isolados: a segunda diferença de uma fala é pequena (< 0,03), a de um clique tem a altura dele."""
    second = samples[:-2] - 2 * samples[1:-1] + samples[2:]
    groups, last = 0, -10
    for hit in np.flatnonzero(np.abs(second) > limit):
        groups += hit - last > 6
        last = hit
    return int(groups)


def effects(*items: dict) -> tuple:
    return tuple(parse_effect(item) for item in items)


class CountingRunner(SubprocessRunner):
    def __init__(self) -> None:
        super().__init__(quiet=True)
        self.runs = 0

    def run(self, command):
        self.runs += 1
        return super().run(command)


@pytest.fixture
def processor(tmp_path) -> EffectProcessor:
    return EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx")


def process(processor: EffectProcessor, source: Path, chain: tuple, duration: float):
    done = processor.process(AudioItem(source, duration, chain))
    assert done is not None
    return decode(done.path)


# ---------- Redução de ruído ----------


@pytest.fixture
def noisy(tmp_path) -> tuple[Path, np.ndarray]:
    """1,5 s só de chiado a -45 dBFS, depois a fala com o mesmo chiado por baixo."""
    speech = voice(6.0)
    speech[: round(1.5 * RATE)] = 0
    samples = np.stack([speech + hiss(6.0, -45.0), 0.9 * speech + hiss(6.0, -45.0, 8)], axis=1)
    return write_wav(tmp_path / "chiado.wav", samples), samples


def test_twelve_db_of_noise_reduction_takes_the_hiss_down_by_at_least_ten_db_without_touching_the_voice(
    processor, noisy
):
    source, original = noisy
    cleaned = process(processor, source, effects({"type": "noise_reduction", "reduction_db": 12}), 6.0)
    quiet = slice(round(0.3 * RATE), round(1.5 * RATE))
    drop = db(rms(original[quiet, 0])) - db(rms(cleaned[quiet, 0]))
    assert drop >= 10.0 and drop == pytest.approx(12.0, abs=0.5)
    voiced = slice(round(1.5 * RATE), None)
    assert abs(db(rms(cleaned[voiced, 0])) - db(rms(original[voiced, 0]))) < 0.2
    assert len(cleaned) == len(original)


def test_the_reduction_sits_in_a_chain_between_filters_and_keeps_the_order(processor, noisy):
    source, original = noisy
    chain = effects(
        {"type": "amplify", "gain_db": 6}, {"type": "noise_reduction"}, {"type": "amplify", "gain_db": -6}
    )
    cleaned = process(processor, source, chain, 6.0)
    quiet = slice(round(0.3 * RATE), round(1.5 * RATE))
    assert db(rms(original[quiet, 0])) - db(rms(cleaned[quiet, 0])) == pytest.approx(12.0, abs=0.5)
    # a mesma cadeia sem o efeito do meio devolve o sinal de volta: o primeiro e o último ganho se anulam
    plain = process(
        processor, source, effects({"type": "amplify", "gain_db": 6}, {"type": "amplify", "gain_db": -6}), 6.0
    )
    assert np.allclose(plain, original, atol=1e-6)


def test_the_reduction_with_an_interval_leaves_the_rest_alone_and_the_seams_do_not_click(processor, noisy):
    source, original = noisy
    cleaned = process(
        processor,
        source,
        effects({"type": "noise_reduction", "reduction_db": 24, "start": 0.4, "end": 1.4}),
        6.0,
    )
    assert np.array_equal(cleaned[: round(0.38 * RATE)], original[: round(0.38 * RATE)])
    assert np.array_equal(cleaned[round(1.42 * RATE) :], original[round(1.42 * RATE) :])
    # o salto máximo entre amostras vizinhas não passa do que o chiado já tinha: nenhuma emenda estalou
    assert np.abs(np.diff(cleaned[:, 0])).max() <= np.abs(np.diff(original[:, 0])).max() * 1.01


def test_a_named_profile_is_measured_from_its_stretch_and_a_new_stretch_gives_a_new_cache_entry(
    tmp_path, noisy
):
    source, original = noisy
    project = Project.model_validate(
        {
            "name": "perfil",
            "timeline": [{"type": "clip", "src": "x.mp4"}],
            "audio": {
                "voiceover": [{"src": str(source)}],
                "noise_profiles": {"sala": {"target": "audio.voiceover.0", "start": 0.2, "end": 1.4}},
            },
        }
    )
    runner = CountingRunner()
    processor = EffectProcessor(runner, tmp_path / "fx", profiles=ProfileLocator(project, {}))
    chain = effects({"type": "noise_reduction", "profile": "sala"})
    item = AudioItem(source, 6.0, chain)
    cleaned = decode(processor.process(item).path)
    quiet = slice(round(0.3 * RATE), round(1.5 * RATE))
    assert db(rms(original[quiet, 0])) - db(rms(cleaned[quiet, 0])) == pytest.approx(12.0, abs=0.5)
    runs = runner.runs
    processor.process(item)  # o mesmo item de novo sai do cache
    assert runner.runs == runs
    # trocar o trecho do perfil muda a chave, então o arquivo é refeito
    moved = project.model_copy(deep=True)
    moved.audio.noise_profiles["sala"].start = 0.3
    other = EffectProcessor(runner, tmp_path / "fx", profiles=ProfileLocator(moved, {}))
    assert other.key(item) != processor.key(item)


def test_an_unknown_profile_stops_the_render_with_the_names_that_exist(tmp_path, noisy):
    source, _ = noisy
    project = Project.model_validate(
        {"name": "p", "timeline": [{"type": "clip", "src": "x.mp4"}], "audio": {}}
    )
    processor = EffectProcessor(
        SubprocessRunner(quiet=True), tmp_path / "fx", profiles=ProfileLocator(project, {})
    )
    with pytest.raises(ValueError, match="o perfil de ruído 'fantasma' não existe"):
        processor.process(AudioItem(source, 6.0, effects({"type": "noise_reduction", "profile": "fantasma"})))


def test_the_automatic_profile_needs_a_pause_of_only_noise_and_otherwise_takes_nothing_out(
    processor, tmp_path
):
    t = np.arange(round(4 * RATE)) / RATE
    steady = write_wav(tmp_path / "tom.wav", (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32))
    out = process(processor, steady, effects({"type": "noise_reduction"}), 4.0)
    assert abs(db(rms(out)) - db(rms(decode(steady)))) < 0.01  # sem pausa, nenhuma mudança


def test_a_simulated_render_records_the_commands_without_touching_numpy(tmp_path, noisy):
    source, _ = noisy
    runner = RecordingRunner()
    processor = EffectProcessor(runner, tmp_path / "fx")
    chain = effects({"type": "amplify", "gain_db": 3}, {"type": "noise_reduction"}, {"type": "invert"})
    done = processor.process(AudioItem(source, 6.0, chain))
    assert done is not None and not done.path.exists()
    assert len(runner.commands) == 2  # o ffmpeg antes e o de depois; o estágio de amostras do meio é pulado
    assert not list((tmp_path / "fx").glob("*.stages-*"))  # e nada temporário sobra


# ---------- cliques, clipping e reparo ----------


def test_click_removal_makes_the_isolated_peaks_disappear_without_changing_the_voice_level(
    processor, tmp_path
):
    speech = voice(4.0)
    clicked = speech.copy()
    rng = np.random.default_rng(5)
    for position, width in zip(
        (30000, 50000, 70000, 100000, 130000, 160000), (1, 2, 3, 5, 4, 2), strict=True
    ):
        clicked[position : position + width] += rng.choice([-1, 1]) * 0.5
    source = write_wav(tmp_path / "cliques.wav", clicked)
    assert count_clicks(clicked) == 6 and count_clicks(speech) == 0
    out = process(processor, source, effects({"type": "click_removal"}), 4.0)
    assert count_clicks(out[:, 0]) == 0
    assert abs(db(rms(out[:, 0])) - db(rms(speech))) < 0.5
    assert len(out) == len(speech)


def test_clip_fix_rebuilds_a_sine_clipped_at_seventy_percent_closer_to_the_original(processor, tmp_path):
    t = np.arange(round(2 * RATE)) / RATE
    original = (0.55 * np.sin(2 * np.pi * 220 * t) + 0.45 * np.sin(2 * np.pi * 660 * t + 0.4)).astype(
        np.float32
    )
    clipped = np.clip(original, -0.7, 0.7)
    source = write_wav(tmp_path / "estourado.wav", clipped)
    before = rms(clipped - original)
    fixed = process(processor, source, effects({"type": "clip_fix", "threshold_percent": 70}), 2.0)[:, 0]
    after = rms(fixed - original)
    assert after < before * 0.2  # o erro cai mais de 14 dB
    assert float(np.abs(fixed).max()) > 0.75  # os picos achatados em 0,7 foram refeitos para cima
    # o limiar manda: com 100% as amostras de 70% não contam como achatadas e nada muda
    untouched = process(processor, source, effects({"type": "clip_fix", "threshold_percent": 100}), 2.0)[:, 0]
    assert np.allclose(untouched, clipped, atol=1e-5)
    quieter = process(
        processor, source, effects({"type": "clip_fix", "threshold_percent": 70, "reduce_db": 6}), 2.0
    )[:, 0]
    assert db(rms(quieter)) == pytest.approx(db(rms(fixed)) - 6.0, abs=0.05)


def test_repair_rebuilds_a_short_stretch_from_what_comes_before_and_after_it(processor, tmp_path):
    t = np.arange(round(2 * RATE)) / RATE
    original = (0.4 * np.sin(2 * np.pi * 180 * t) + 0.25 * np.sin(2 * np.pi * 540 * t + 0.7)).astype(
        np.float32
    )
    broken = original.copy()
    broken[40000:40100] = np.random.default_rng(2).uniform(-0.8, 0.8, 100)
    source = write_wav(tmp_path / "estalo.wav", broken)
    chain = effects({"type": "repair", "start": 40000 / RATE, "end": 40100 / RATE})
    fixed = process(processor, source, chain, 2.0)[:, 0]
    assert rms(fixed[40000:40100] - original[40000:40100]) < 0.01 * rms(
        broken[40000:40100] - original[40000:40100]
    )
    assert np.array_equal(fixed[:39990], broken[:39990])  # fora do trecho, a amostra é a mesma
    assert np.abs(np.diff(fixed)).max() < 0.1  # e a emenda não estala


# ---------- Truncar Silêncio no clipe: imagem e som juntos ----------


def no_sync(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult(0.0, confidence=0.0)


def make_flash_video(path: Path) -> Path:
    """10 s de 15 quadros por segundo: cinza, com um clarão branco em 6,0 a 6,2 s; o som é um tom de 440 Hz calado de 3 a
    5 s e de 8 a 10 s, com um bipe de 2 kHz exatamente no clarão (para dizer se imagem e som continuam juntos)."""
    sound = (
        "aevalsrc='0.3*sin(2*PI*440*t)*(lt(t,3)+gt(t,5)*lt(t,8))*(1-between(t,6,6.2))"
        f"+0.4*sin(2*PI*2000*t)*between(t,6,6.2)':s={RATE}:d=10"
    )
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=320x180:rate=15:d=10,drawbox=x=0:y=0:w=320:h=180:color=white:t=fill:enable='between(t,6,6.2)'",
        ]
        + ["-f", "lavfi", "-i", sound]
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
            str(path),
        ],
        quiet=True,
    )
    return path


def flash_time(video: Path) -> float:
    """O instante do primeiro quadro claro."""
    command = [
        str(config.find_tool("ffmpeg")),
        "-v",
        "error",
        "-i",
        str(video),
        "-vf",
        "scale=16:9,format=gray,fps=30",
    ]
    raw = subprocess.run([*command, "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 16 * 9)
    return float(np.argmax(frames.mean(axis=1) > 200)) / 30


def beep_time(video: Path) -> float:
    """O instante em que o bipe de 2 kHz começa: onde a energia da banda passa da metade do pico."""
    rate = 16000
    audio = decode(video, rate, 1)[:, 0]
    block = 160  # 10 ms
    frames = audio[: len(audio) // block * block].reshape(-1, block) * np.hanning(block)
    band = np.abs(np.fft.rfft(frames, axis=1))[
        :, int(1900 / (rate / block)) : int(2100 / (rate / block)) + 1
    ].sum(axis=1)
    return float(np.argmax(band > band.max() / 2)) * block / rate


def test_truncating_the_silences_of_a_clip_shortens_image_and_sound_together_and_keeps_them_in_sync(tmp_path):
    make_flash_video(tmp_path / "video.mp4")
    project = Project.model_validate(
        {
            "name": "truncar",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 10}],
            "audio": {"normalize": "off"},
        }
    )
    project.base_dir = tmp_path

    def render(candidate: Project, name: str):
        result = RenderPipeline(
            candidate,
            RenderOptions(preview=True, quiet=True, out=tmp_path / f"{name}.mp4", thumbnail=False),
            offset_finder=no_sync,
            cache_dir=tmp_path / f"mez-{name}",
            jobs_dir=tmp_path / f"jobs-{name}",
        ).run()
        return result.output

    before = render(project, "antes")
    # a imagem e o som estão juntos no original (6,0 s); os dois medidores precisam concordar antes de cortar
    assert flash_time(before) == pytest.approx(6.0, abs=0.07) and beep_time(before) == pytest.approx(
        6.0, abs=0.03
    )

    report = apply_edit_report(
        project, {"type": "audio_truncate_silence", "target": "timeline.0"}, prober=probe
    )
    removed = 10.0 - sum(seg.end - seg.start for seg in report.project.timeline)  # type: ignore[operator]
    assert removed == pytest.approx(3.0, abs=0.1)  # duas pausas de 2 s viram 0,5 s: saem 1,5 s de cada
    after = render(report.project, "depois")
    assert probe(after).duration == pytest.approx(10.0 - removed, abs=0.25)
    # o clarão e o bipe andaram o mesmo tanto (o que saiu antes deles) e ainda caem no mesmo instante, a um quadro
    moved_flash, moved_beep = flash_time(after), beep_time(after)
    assert moved_flash < 6.0 - 1.3  # a pausa de antes do clarão encolheu
    assert abs(moved_flash - moved_beep) <= 1 / 15 + 0.01
    # nenhuma emenda estalou: as duas emendas caem no silêncio, e ali o som cortado não dá salto nenhum entre amostras
    sound = decode(after, 16000, 1)[:, 0]
    pieces = [seg.end - seg.start for seg in report.project.timeline]  # type: ignore[operator]
    seam = 0.0
    for length in pieces[:-1]:
        seam += length
        around = sound[round((seam - 0.05) * 16000) : round((seam + 0.05) * 16000)]
        assert np.abs(np.diff(around)).max() < 0.01
