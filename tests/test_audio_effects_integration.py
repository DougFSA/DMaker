"""A cadeia de efeitos de áudio com ffmpeg de verdade: tons gerados no teste, medida numérica de cada critério.

Os sinais têm amplitude conhecida (`aevalsrc`), então o pico e o RMS esperados saem de conta e não de comparação com
uma execução anterior. O arquivo processado é WAV de ponto flutuante, onde dá para medir sem a perda do AAC; o render
e a prévia saem em AAC, onde a tolerância é de décimos de dB.
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
from dmaker.pipeline.preview_audio import PreviewAudioBuilder
from dmaker.pipeline.timeline_service import project_timeline_view
from dmaker.pipeline.voicefiles import voice_file_playtimes

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def db(value: float) -> float:
    return 20 * np.log10(value)


def make_tone(path: Path, *, amp=0.5, hz=440.0, seconds=3.0, right_amp=None, decay=0.0, dc=0.0) -> Path:
    """Um tom estéreo de 48 kHz em ponto flutuante: `amp` à esquerda, `right_amp` (ou `amp`) à direita."""
    right = amp if right_amp is None else right_amp
    envelope = f"*exp(-{decay}*t)" if decay else ""
    expr = f"{dc}+{{a}}*sin(2*PI*{hz}*t){envelope}"
    source = f"aevalsrc={expr.format(a=amp)}|{expr.format(a=right)}:s={RATE}:d={seconds}"
    ffmpeg.run(["-f", "lavfi", "-i", source, "-c:a", "pcm_f32le", str(path)], quiet=True)
    return path


def make_video_with_tone(path: Path, *, amp=0.3, hz=330.0, seconds=8.0) -> Path:
    ffmpeg.run(
        ["-f", "lavfi", "-i", f"color=c=gray:size=320x180:rate=15:d={seconds}"]
        + [
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={amp}*sin(2*PI*{hz}*t)|{amp}*sin(2*PI*{hz}*t):s={RATE}:d={seconds}",
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
            str(path),
        ],
        quiet=True,
    )
    return path


def decode(path: Path, rate: int = RATE, channels: int = 2) -> np.ndarray:
    """O áudio do arquivo como ponto flutuante, de forma (amostras, canais)."""
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path), "-vn"]
    command += ["-ac", str(channels), "-ar", str(rate), "-f", "f32le", "-"]
    data = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")
    return data.reshape(-1, channels)


def peak(samples: np.ndarray) -> float:
    return float(np.abs(samples).max())


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def effects(*items: dict) -> tuple:
    return tuple(parse_effect(item) for item in items)


class CountingRunner(SubprocessRunner):
    """Conta quantas vezes o ffmpeg foi chamado, para provar o cache."""

    def __init__(self) -> None:
        super().__init__(quiet=True)
        self.runs = 0
        self.captures = 0

    def run(self, command):
        self.runs += 1
        return super().run(command)

    def capture(self, args, label="ffmpeg"):
        self.captures += 1
        return super().capture(args, label)


@pytest.fixture
def work(tmp_path) -> Path:
    return tmp_path


@pytest.fixture
def processor(work) -> EffectProcessor:
    return EffectProcessor(SubprocessRunner(quiet=True), work / "fx")


def process(processor: EffectProcessor, source: Path, chain: tuple, duration: float = 3.0, **kwargs):
    done = processor.process(AudioItem(source, duration, chain, **kwargs))
    assert done is not None
    return done, decode(done.path)


# ---------- cada critério de aceite, no arquivo processado ----------


def test_amplify_6_db_raises_the_peak_by_exactly_6_db(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.25)
    done, out = process(processor, tone, effects({"type": "amplify", "gain_db": 6}))
    assert db(peak(out) / peak(decode(tone))) == pytest.approx(6.0, abs=0.01)
    assert done.duration == 3.0


def test_amplify_without_clipping_never_goes_past_0_dbfs_and_keeps_the_gain_it_can(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.5)  # -6 dBFS
    _, limited = process(
        processor, tone, effects({"type": "amplify", "gain_db": 20, "prevent_clipping": True})
    )
    assert peak(limited) <= 1.0 + 1e-6
    assert db(peak(limited)) == pytest.approx(0.0, abs=0.01)  # usou toda a folga que havia
    _, free = process(processor, tone, effects({"type": "amplify", "gain_db": 20}))
    assert db(peak(free)) == pytest.approx(
        db(0.5) + 20, abs=0.01
    )  # sem a opção, o ganho passa de 0 dBFS (sem cortar)
    _, small = process(processor, tone, effects({"type": "amplify", "gain_db": 3, "prevent_clipping": True}))
    assert db(peak(small)) == pytest.approx(db(0.5) + 3, abs=0.01)  # com folga, o ganho pedido inteiro


def test_normalize_to_minus_1_dbfs_lands_within_a_tenth_of_a_db(work, processor):
    for amp in (0.05, 0.3, 0.9):
        tone = make_tone(work / f"tom{amp}.wav", amp=amp)
        _, out = process(processor, tone, effects({"type": "normalize", "peak_db": -1}))
        assert db(peak(out)) == pytest.approx(-1.0, abs=0.1)


def test_normalize_keeps_the_channel_balance_unless_asked_for_independent_channels(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.5, right_amp=0.125)
    _, together = process(processor, tone, effects({"type": "normalize", "peak_db": -2, "remove_dc": False}))
    assert db(peak(together[:, 0])) == pytest.approx(-2.0, abs=0.01)
    assert db(peak(together[:, 0]) / peak(together[:, 1])) == pytest.approx(
        12.04, abs=0.05
    )  # mesma razão de antes
    _, apart = process(
        processor, tone, effects({"type": "normalize", "peak_db": -2, "stereo_independent": True})
    )
    assert db(peak(apart[:, 0])) == pytest.approx(-2.0, abs=0.01)
    assert db(peak(apart[:, 1])) == pytest.approx(-2.0, abs=0.01)


def test_normalize_removes_the_dc_offset_before_it_scales(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.2, dc=0.1)  # a onda vai de -0.1 a 0.3
    _, kept = process(processor, tone, effects({"type": "normalize", "peak_db": -6, "remove_dc": False}))
    assert abs(float(kept[:, 0].mean())) > 0.02  # o deslocamento continua lá
    _, centered = process(processor, tone, effects({"type": "normalize", "peak_db": -6, "remove_dc": True}))
    assert abs(float(centered.mean())) < 1e-3
    assert db(peak(centered)) == pytest.approx(-6.0, abs=0.05)


def test_inverting_twice_gives_back_the_exact_same_samples(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.5, decay=0.3)
    _, once = process(processor, tone, effects({"type": "invert"}))
    _, twice = process(processor, tone, effects({"type": "invert"}, {"type": "invert"}))
    original = decode(tone)
    assert np.array_equal(once, -original)
    assert np.array_equal(twice, original)  # diferença nula, amostra a amostra


def test_reverse_plays_the_item_backwards_with_the_same_duration(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.5, decay=0.8)
    done, out = process(processor, tone, effects({"type": "reverse"}))
    original = decode(tone)
    assert done.duration == 3.0 and len(out) == len(original)
    assert np.array_equal(out, original[::-1])


def test_repeat_doubles_a_recorded_voice_and_the_declared_duration_matches_the_file(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.5, decay=0.8)
    done, out = process(processor, tone, effects({"type": "repeat", "times": 2}))
    original = decode(tone)
    assert done.duration == pytest.approx(6.0)
    assert len(out) == pytest.approx(6 * RATE, abs=2)
    assert np.array_equal(out[: len(original)], original) and np.array_equal(
        out[len(original) : 2 * len(original)], original
    )


def test_repeat_inside_an_interval_grows_only_that_stretch(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.5, decay=0.8)
    done, out = process(processor, tone, effects({"type": "repeat", "times": 3, "start": 1.0, "end": 2.0}))
    original = decode(tone)
    assert done.duration == pytest.approx(5.0) and len(out) == pytest.approx(5 * RATE, abs=2)
    assert np.array_equal(out[:RATE], original[:RATE])  # o começo, intacto
    assert np.array_equal(out[RATE : 2 * RATE], original[RATE : 2 * RATE])  # o trecho, três vezes
    assert np.array_equal(out[3 * RATE : 4 * RATE], original[RATE : 2 * RATE])
    assert np.array_equal(out[4 * RATE :], original[2 * RATE :])  # o fim, depois


# o trecho começa fora de um cruzamento por zero da onda (440 Hz): é aí que um corte seco daria degrau
FIRST = 48034
LAST = FIRST + RATE


def test_an_interval_changes_only_that_stretch_and_the_seams_have_no_step(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.5, hz=440, seconds=3.0)
    original = decode(tone)
    chain = effects({"type": "amplify", "gain_db": 6, "start": FIRST / RATE, "end": LAST / RATE})
    _, out = process(processor, tone, chain)
    seam = round(0.010 * RATE)
    assert np.array_equal(out[:FIRST], original[:FIRST])  # antes: idêntico, bit a bit
    assert np.array_equal(out[LAST:], original[LAST:])  # depois: idêntico
    inside = out[FIRST + seam : LAST - seam]
    assert np.allclose(inside, original[FIRST + seam : LAST - seam] * 10 ** (6 / 20), atol=1e-6)  # +6 dB
    # degrau de amostra: nenhuma amostra pula mais do que a onda mais alta (o dobro da original) pula sozinha
    natural_step = float(np.abs(np.diff(original[:, 0])).max()) * 2
    assert float(np.abs(np.diff(out, axis=0)).max()) <= natural_step * 1.01
    # na emenda o ganho sobe de 1x a 2x numa rampa, sem passar de nenhum dos dois
    gain = out[FIRST : FIRST + seam, 0] / np.where(
        original[FIRST : FIRST + seam, 0] == 0, 1, original[FIRST : FIRST + seam, 0]
    )
    solid = np.abs(original[FIRST : FIRST + seam, 0]) > 0.05
    assert gain[solid].min() >= 1.0 - 1e-3 and gain[solid].max() <= 10 ** (6 / 20) + 1e-3
    assert np.all(np.diff(gain[solid]) >= -1e-3)  # e só cresce


def test_a_hard_switch_would_step_but_the_seam_does_not(work, processor):
    """Prova que o teste de degrau enxerga o defeito: o mesmo ganho, cortado seco, pula muito mais."""
    tone = make_tone(work / "tom.wav", amp=0.5, hz=440, seconds=3.0)
    original = decode(tone)
    hard = original.copy()
    hard[FIRST:LAST] *= 2.0
    natural_step = float(np.abs(np.diff(original[:, 0])).max()) * 2
    assert float(np.abs(np.diff(hard, axis=0)).max()) > natural_step * 1.2
    chain = effects({"type": "amplify", "gain_db": 6, "start": FIRST / RATE, "end": LAST / RATE})
    _, smooth = process(processor, tone, chain)
    assert float(np.abs(np.diff(smooth, axis=0)).max()) <= natural_step * 1.01


def test_normalize_with_an_interval_measures_only_that_stretch(work, processor):
    first = make_tone(work / "a.wav", amp=0.1, seconds=2.0)
    loud = make_tone(work / "b.wav", amp=0.8, seconds=2.0)
    joined = work / "juntos.wav"
    ffmpeg.run(
        [
            "-i",
            str(first),
            "-i",
            str(loud),
            "-filter_complex",
            "concat=n=2:v=0:a=1",
            "-c:a",
            "pcm_f32le",
            str(joined),
        ],
        quiet=True,
    )
    # o trecho de 0 a 2 s tem pico 0.1: normalizar só ele a -6 dBFS o leva a 0.5, e o resto fica como estava
    _, out = process(
        processor,
        joined,
        effects({"type": "normalize", "peak_db": -6, "start": 0.0, "end": 2.0}),
        duration=4.0,
    )
    assert db(peak(out[: RATE * 2 - 480])) == pytest.approx(-6.0, abs=0.05)
    assert peak(out[2 * RATE :]) == pytest.approx(0.8, abs=1e-4)


def test_a_chain_runs_in_order_and_each_normalize_sees_the_effects_before_it(work, processor):
    tone = make_tone(work / "tom.wav", amp=0.1)
    # amplificar +20 dB (pico 1.0) e normalizar a -6 dBFS: o Normalizar mede o sinal já amplificado
    _, out = process(
        processor, tone, effects({"type": "amplify", "gain_db": 20}, {"type": "normalize", "peak_db": -6})
    )
    assert db(peak(out)) == pytest.approx(-6.0, abs=0.05)
    _, reversed_order = process(
        processor, tone, effects({"type": "normalize", "peak_db": -6}, {"type": "amplify", "gain_db": 6})
    )
    assert db(peak(reversed_order)) == pytest.approx(0.0, abs=0.05)  # -6 e depois +6


def test_the_item_is_the_stretch_of_the_file_it_uses_not_the_whole_file(work, processor):
    first = make_tone(work / "a.wav", amp=0.1, seconds=2.0)
    loud = make_tone(work / "b.wav", amp=0.8, seconds=2.0)
    joined = work / "juntos.wav"
    ffmpeg.run(
        [
            "-i",
            str(first),
            "-i",
            str(loud),
            "-filter_complex",
            "concat=n=2:v=0:a=1",
            "-c:a",
            "pcm_f32le",
            str(joined),
        ],
        quiet=True,
    )
    # só os 2 s do começo (pico 0.1) entram na conta: o pico do trecho que soa é o que normaliza
    done, out = process(processor, joined, effects({"type": "normalize", "peak_db": -6}), duration=2.0)
    assert done.duration == 2.0 and len(out) == pytest.approx(2 * RATE, abs=2)
    assert db(peak(out)) == pytest.approx(-6.0, abs=0.05)
    done2, out2 = process(processor, joined, effects({"type": "invert"}), duration=1.0, start=2.0)
    assert peak(out2) == pytest.approx(0.8, abs=1e-4) and len(out2) == pytest.approx(RATE, abs=2)


# ---------- cache ----------


def test_the_processed_item_is_cached_by_what_decides_the_sound(work):
    tone = make_tone(work / "tom.wav", amp=0.5)
    runner = CountingRunner()
    processor = EffectProcessor(runner, work / "fx")
    chain = effects({"type": "amplify", "gain_db": 6, "prevent_clipping": True})
    first = processor.process(AudioItem(tone, 3.0, chain))
    assert (runner.runs, runner.captures) == (1, 1)  # uma medida (o "não clipar" pede) e uma execução
    again = processor.process(AudioItem(tone, 3.0, chain))
    assert again == first and (runner.runs, runner.captures) == (1, 1)  # do cache: nem a medida se repete

    changed = processor.process(AudioItem(tone, 3.0, effects({"type": "amplify", "gain_db": 5})))
    assert changed.path != first.path and runner.runs == 2  # mudar um parâmetro refaz só aquele item
    off = effects({"type": "amplify", "gain_db": 6}, {"type": "invert", "enabled": False})
    plain = processor.process(AudioItem(tone, 3.0, effects({"type": "amplify", "gain_db": 6})))
    assert processor.process(AudioItem(tone, 3.0, off)).path == plain.path  # desligado é como não ter


def test_no_enabled_effect_means_no_processing_at_all(work):
    tone = make_tone(work / "tom.wav")
    runner = CountingRunner()
    processor = EffectProcessor(runner, work / "fx")
    assert processor.process(AudioItem(tone, 3.0, ())) is None
    assert processor.process(AudioItem(tone, 3.0, effects({"type": "invert", "enabled": False}))) is None
    assert runner.runs == 0 and not (work / "fx").exists()


def test_the_cache_key_follows_the_file_content(work):
    tone = make_tone(work / "tom.wav", amp=0.5)
    processor = EffectProcessor(SubprocessRunner(quiet=True), work / "fx")
    chain = effects({"type": "invert"})
    before = processor.process(AudioItem(tone, 3.0, chain))
    make_tone(tone, amp=0.25, seconds=3.5)  # outro conteúdo no mesmo caminho
    after = processor.process(AudioItem(tone, 3.0, chain))
    assert before.path != after.path


def test_the_simulation_only_records_the_commands_and_never_measures(work):
    tone = make_tone(work / "tom.wav")
    runner = RecordingRunner()
    processor = EffectProcessor(runner, work / "fx")
    done = processor.process(AudioItem(tone, 3.0, effects({"type": "normalize"}, {"type": "reverse"})))
    assert done is not None and not done.path.exists()
    text = " ".join(" ".join(command) for command in runner.commands)
    assert "areverse" in text and "anull" in text  # sem medida, o Normalizar cai no neutro


# ---------- no render e na prévia ----------


def no_sync(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult(0.0, confidence=0.0)


def render_audio(project: Project, folder: Path, name: str) -> tuple[np.ndarray, object]:
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, 16000, 1)[:, 0], result


def spec(folder: Path, overlays: list[dict] | None = None, **audio) -> Project:
    project = Project.model_validate(
        {
            "name": "efeitos",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 8, "mute": True}],
            "overlays": overlays or [],
            "audio": {"normalize": "off", **audio},
        }
    )
    project.base_dir = folder
    return project


@pytest.fixture
def media(work) -> Path:
    make_video_with_tone(work / "video.mp4")
    make_tone(work / "fala.wav", amp=0.4, hz=440, seconds=3.0)
    make_tone(work / "musica.wav", amp=0.3, hz=220, seconds=8.0)
    return work


def window(samples: np.ndarray, start: float, end: float) -> np.ndarray:
    return samples[int(start * 16000) : int(end * 16000)]


def test_amplify_6_db_on_a_recorded_voice_raises_the_rendered_level_by_6_db(media):
    base, _ = render_audio(spec(media, voiceover=[{"src": "fala.wav"}]), media, "base")
    loud, _ = render_audio(
        spec(media, voiceover=[{"src": "fala.wav", "effects": [{"type": "amplify", "gain_db": 6}]}]),
        media,
        "alto",
    )
    gain = db(rms(window(loud, 0.3, 2.7)) / rms(window(base, 0.3, 2.7)))
    assert gain == pytest.approx(6.0, abs=0.2)  # o render sai em AAC; o arquivo processado é exato
    assert rms(window(loud, 4.0, 8.0)) < 1e-3  # fora da voz continua silêncio
    assert len(list(config.AUDIO_FX_DIR.glob("*.wav"))) == 1


def test_the_master_chain_is_applied_to_the_whole_mix(media):
    voice = [{"src": "fala.wav"}]
    music = {"src": "musica.wav", "volume": 0.5, "ducking": False}
    base, _ = render_audio(spec(media, voiceover=voice, music=music), media, "m-base")
    quiet, _ = render_audio(
        spec(media, voiceover=voice, music=music, master_effects=[{"type": "amplify", "gain_db": -6}]),
        media,
        "m-baixo",
    )
    assert db(rms(quiet) / rms(base)) == pytest.approx(-6.0, abs=0.2)  # a voz e a música, juntas
    inverted, _ = render_audio(
        spec(media, voiceover=voice, music=music, master_effects=[{"type": "invert"}]), media, "m-inv"
    )
    assert float(np.dot(base, inverted) / (np.linalg.norm(base) * np.linalg.norm(inverted))) < -0.98


def test_the_master_normalize_brings_the_mix_peak_to_the_target(media):
    voice = [{"src": "fala.wav"}]
    music = {"src": "musica.wav", "volume": 0.5, "ducking": False}
    _, result = render_audio(
        spec(media, voiceover=voice, music=music, master_effects=[{"type": "normalize", "peak_db": -3}]),
        media,
        "m-norm",
    )
    stereo = decode(result.output)  # o pico se mede por canal: reduzir a mono soma os dois e engana
    assert db(peak(stereo)) == pytest.approx(-3.0, abs=0.5)  # AAC sobrepassa um pouco o pico de uma onda


def test_the_master_normalize_comes_before_the_final_loudness_normalization(media):
    """Com a normalização final ligada, ela continua valendo por cima do master: o nível sai no alvo de LUFS."""
    voice = [{"src": "fala.wav"}]
    project = spec(media, voiceover=voice, master_effects=[{"type": "amplify", "gain_db": -20}])
    project.audio.normalize = "two-pass"
    project.audio.target_lufs = -16
    out, result = render_audio(project, media, "m-lufs")
    assert result.duration > 0
    measured = ffmpeg_loudness(media / "m-lufs.mp4")
    assert measured == pytest.approx(-16.0, abs=1.0)


def ffmpeg_loudness(path: Path) -> float:
    runner = SubprocessRunner(quiet=True)
    stderr = runner.capture(
        ["-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"], label="loudness"
    )
    summary = stderr.rsplit("Integrated loudness:", 1)[1]
    return float(summary.split("I:")[1].split("LUFS")[0])


def test_the_clip_sound_chain_is_applied_inside_the_mezzanine(media):
    plain = spec(media)
    plain.timeline[0].mute = False
    base, _ = render_audio(plain, media, "c-base")
    boosted = spec(media)
    boosted.timeline[0].mute = False
    boosted.timeline[0].effects = list(effects({"type": "invert"}, {"type": "amplify", "gain_db": 6}))
    out, _ = render_audio(boosted, media, "c-fx")
    assert float(np.dot(base, out) / (np.linalg.norm(base) * np.linalg.norm(out))) < -0.98
    assert db(rms(out) / rms(base)) == pytest.approx(6.0, abs=0.3)


def test_a_project_without_effects_renders_the_same_mezzanine_and_sound_as_with_empty_lists(media):
    plain = spec(media, voiceover=[{"src": "fala.wav"}])
    explicit = spec(media, voiceover=[{"src": "fala.wav", "effects": []}], master_effects=[])
    explicit.timeline[0].effects = []
    one, first = render_audio(plain, media, "igual-a")
    two, second = render_audio(explicit, media, "igual-b")

    def mezzanines(folder: str) -> list[str]:
        return sorted(path.name for path in (media / folder).glob("*.mov"))

    assert mezzanines("mez-igual-a") == mezzanines("mez-igual-b") and mezzanines("mez-igual-a")  # mesmo hash
    assert np.array_equal(one, two)  # e o mesmo som
    assert not (config.AUDIO_FX_DIR.exists() and list(config.AUDIO_FX_DIR.glob("*.wav")))


def test_the_preview_sounds_like_the_render_with_effects_on_every_kind_of_item(media):
    project = spec(
        media,
        voiceover=[
            {
                "src": "fala.wav",
                "start": 1.0,
                "effects": [
                    {"type": "reverse"},
                    {"type": "repeat", "times": 2},
                    {"type": "amplify", "gain_db": 2},
                ],
            }
        ],
        music={
            "src": "musica.wav",
            "volume": 0.4,
            "ducking": False,
            "effects": [{"type": "amplify", "gain_db": -3}],
        },
        master_effects=[
            {"type": "amplify", "gain_db": 3, "prevent_clipping": True},
            {"type": "normalize", "peak_db": -4},
        ],
        normalize="two-pass",
    )
    project.timeline[0].mute = False
    project.timeline[0].effects = list(effects({"type": "invert"}, {"type": "amplify", "gain_db": 3}))

    builder = PreviewAudioBuilder(
        offset_finder=no_sync, cache_dir=media / "preview-audio", jobs_dir=media / "preview-jobs"
    )
    preview = builder.build(project)
    rendered, result = render_audio(project, media, "paridade")
    played = decode(preview.path, 16000, 1)[:, 0]

    assert preview.duration == pytest.approx(result.duration, abs=0.05)
    size = min(len(played), len(rendered))
    a, b = played[:size] - played[:size].mean(), rendered[:size] - rendered[:size].mean()
    assert float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))) > 0.98
    assert (
        abs(db(rms(played[:size]) / rms(rendered[:size]))) < 0.3
    )  # o mesmo nível, medido pela diferença de RMS


def test_the_preview_cache_is_invalidated_by_a_change_in_the_chain(media):
    project = spec(media, voiceover=[{"src": "fala.wav"}])
    builder = PreviewAudioBuilder(
        offset_finder=no_sync, cache_dir=media / "preview-audio", jobs_dir=media / "preview-jobs"
    )
    plain = builder.build(project)
    changed = spec(media, voiceover=[{"src": "fala.wav", "effects": [{"type": "amplify", "gain_db": 6}]}])
    louder = builder.build(changed)
    assert louder.key != plain.key
    assert decode(louder.path, 16000, 1).std() > decode(plain.path, 16000, 1).std() * 1.5


# ---------- os outros caminhos do som: faixa externa, PiP, narração e música ----------


def dominant_hz(samples: np.ndarray, rate: int = 16000) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / rate)[int(np.argmax(spectrum))])


def test_an_external_track_chain_runs_on_the_whole_file_before_it_is_sliced_per_clip(media):
    """Reverter a faixa inteira entrega ao primeiro clipe o FIM do arquivo; reverter fatia por fatia entregaria a
    mesma fatia ao contrário. A mesa tem um tom diferente a cada 2 s (300, 500, 700, 900 Hz) para dizer qual foi."""
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc=0.5*sin(2*PI*(300+200*floor(t/2))*t)|0.5*sin(2*PI*(300+200*floor(t/2))*t):s={RATE}:d=8",
        ]
        + ["-c:a", "pcm_f32le", str(media / "mesa.wav")],
        quiet=True,
    )
    project = Project.model_validate(
        {
            "name": "faixa-efeitos",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "sources": {"cam": {"src": "video.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
            "timeline": [
                {"type": "clip", "source": "cam", "start": 0, "end": 2, "mute": True},
                {
                    "type": "clip",
                    "source": "cam",
                    "start": 4,
                    "end": 6,
                    "mute": True,
                    "transition": {"type": "cut"},
                },
            ],
            "audio": {"tracks": [{"source": "mesa", "effects": [{"type": "reverse"}]}], "normalize": "off"},
        }
    )
    project.base_dir = media
    out, result = render_audio(project, media, "faixa")
    assert dominant_hz(window(out, 0.3, 1.7)) == pytest.approx(
        900, abs=15
    )  # o fim da mesa, de trás para a frente
    assert dominant_hz(window(out, 2.3, 3.7)) == pytest.approx(
        500, abs=15
    )  # de 4 a 6 s do arquivo virou 2 a 4 s
    preview = PreviewAudioBuilder(offset_finder=no_sync, cache_dir=media / "pa", jobs_dir=media / "pj").build(
        project
    )
    heard = decode(preview.path, 16000, 1)[:, 0]
    assert dominant_hz(window(heard, 0.3, 1.7)) == pytest.approx(900, abs=15)  # a prévia soa igual
    assert dominant_hz(window(heard, 2.3, 3.7)) == pytest.approx(500, abs=15)
    assert result.duration == pytest.approx(4.0, abs=0.1)


def test_a_pip_audio_chain_replaces_the_pip_sound_in_the_mix(media):
    make_video_with_tone(media / "pip.mp4", amp=0.3, hz=550.0, seconds=4.0)
    pip = {"type": "video", "src": "pip.mp4", "start": 0.0, "end": 4.0}
    quiet, _ = render_audio(spec(media, overlays=[pip]), media, "pip-plain")
    boosted = {**pip, "effects": [{"type": "amplify", "gain_db": 6}]}
    loud, _ = render_audio(spec(media, overlays=[boosted]), media, "pip-fx")
    assert rms(window(quiet, 0.5, 3.5)) > 0.05  # o som do PiP está na mistura
    assert db(rms(window(loud, 0.5, 3.5)) / rms(window(quiet, 0.5, 3.5))) == pytest.approx(6.0, abs=0.3)


def test_a_narration_chain_swaps_the_synthesized_file_for_the_processed_one(media):
    from dmaker.domain.brand import load_theme
    from dmaker.domain.presets import get_preset
    from dmaker.pipeline.audio_effects import processed_voiceovers
    from dmaker.pipeline.context import RenderContext
    from dmaker.pipeline.voiceover import PreparedVoiceover

    speech = make_tone(media / "fala-sintetica.wav", amp=0.25)
    ctx = RenderContext(
        project=spec(media),
        options=RenderOptions(),
        theme=load_theme(None, None),
        preset=get_preset("instagram/reels"),
        fps=30,
        job_dir=media / "job",
        cache_dir=media / "mez",
        runner=SubprocessRunner(quiet=True),
        prober=probe,
    )
    plain = PreparedVoiceover(speech, 1.0, 1.0, 3.0)
    boosted = PreparedVoiceover(speech, 2.0, 0.8, 3.0, effects=effects({"type": "amplify", "gain_db": 6}))
    first, second = processed_voiceovers(ctx, [plain, boosted])
    assert first is plain  # sem efeito, o mesmo objeto
    assert second.path != speech and (second.start, second.volume, second.duration) == (2.0, 0.8, 3.0)
    assert db(peak(decode(second.path)) / peak(decode(speech))) == pytest.approx(6.0, abs=0.01)


def test_a_music_chain_applies_to_the_whole_file_and_repeat_makes_it_longer(media):
    from dmaker.domain.brand import load_theme
    from dmaker.domain.presets import get_preset
    from dmaker.pipeline.audio_effects import processed_music
    from dmaker.pipeline.context import RenderContext

    project = spec(media, music={"src": "musica.wav", "effects": [{"type": "repeat", "times": 2}]})
    ctx = RenderContext(
        project=project,
        options=RenderOptions(),
        theme=load_theme(None, None),
        preset=get_preset("instagram/reels"),
        fps=30,
        job_dir=media / "job",
        cache_dir=media / "mez",
        runner=SubprocessRunner(quiet=True),
        prober=probe,
    )
    path = processed_music(ctx, media / "musica.wav")
    assert path != media / "musica.wav" and probe(path).duration == pytest.approx(16.0, abs=0.05)
    untouched = spec(media, music={"src": "musica.wav"})
    ctx.project = untouched
    assert processed_music(ctx, media / "musica.wav") == media / "musica.wav"


# ---------- duração na vista ----------


def test_repeat_twice_on_a_recorded_voice_doubles_its_length_in_the_timeline_view(media):
    plain = spec(media, voiceover=[{"src": "fala.wav", "start": 1.0}])
    doubled = spec(
        media, voiceover=[{"src": "fala.wav", "start": 1.0, "effects": [{"type": "repeat", "times": 2}]}]
    )
    before = next(t for t in project_timeline_view(plain).to_dict()["tracks"] if t["id"] == "VO")["items"][0]
    after = next(t for t in project_timeline_view(doubled).to_dict()["tracks"] if t["id"] == "VO")["items"][0]
    assert before["end"] - before["start"] == pytest.approx(3.0, abs=0.05)
    assert after["end"] - after["start"] == pytest.approx(6.0, abs=0.05)  # dobrou
    assert after["start"] == before["start"] == 1.0 and after["kind"] == "voiceover"
    assert voice_file_playtimes(doubled, probe) == [pytest.approx(6.0, abs=0.05)]


def test_validate_reports_the_new_length_of_a_voice_that_now_runs_past_the_end(media):
    from dmaker.pipeline.projects import summarize

    short = spec(
        media, voiceover=[{"src": "fala.wav", "start": 6.0, "effects": [{"type": "repeat", "times": 2}]}]
    )
    warnings = summarize(short).warnings
    assert any(
        "audio.voiceover[0]" in w and "6.0s" in w for w in warnings
    )  # o que o efeito faz com a duração
    assert any("depois do fim do vídeo" in w for w in warnings)  # 6 s + 6 s passa dos 8 s do vídeo
