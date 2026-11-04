"""Geradores de som com o ffmpeg de verdade: os critérios do DMK-58 medidos no som.

O Tom e o Ruído passam pelo ffmpeg (`aevalsrc`, `anoisesrc`), os outros são numpy gravado em WAV de ponto flutuante, e a
medida sai de FFT e Goertzel sobre o arquivo, então o que se espera vem de conta. A mistura é medida no WAV do render com a
normalização desligada, onde o nível do gerador chega ao arquivo sem ganho de loudnorm.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.audio_export import ExportRequest
from dmaker.domain.spec import GeneratedSound, Project
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.wavio import read_wav_channels, read_wav_float
from dmaker.pipeline import RenderOptions, create_renderer
from dmaker.pipeline.audio_export import AudioExporter
from dmaker.pipeline.audio_render import AudioRenderPipeline
from dmaker.pipeline.generated_sounds import GeneratedSoundRenderer
from dmaker.pipeline.preview_audio import PreviewAudioBuilder

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def sound(generator: str, duration: float, **params) -> GeneratedSound:
    return GeneratedSound(generator=generator, params=params, duration=duration)


def generate(tmp_path: Path, item: GeneratedSound, resolve=None) -> np.ndarray:
    """O WAV que o gerador faz, lido de volta como `(quadros, canais)` em ponto flutuante."""
    renderer = GeneratedSoundRenderer(SubprocessRunner(quiet=True), tmp_path / "gen")
    path = renderer.render(item, resolve or (lambda name: tmp_path / name))
    samples, rate = read_wav_float(path)
    assert rate == RATE
    return samples


def peak_db(samples: np.ndarray) -> float:
    return 20 * np.log10(float(np.max(np.abs(samples))))


def peak_hz(samples: np.ndarray) -> float:
    """A frequência do pico da FFT, refinada por interpolação parabólica em torno do bin máximo (janela de Hann)."""
    windowed = samples * np.hanning(len(samples))
    magnitude = np.abs(np.fft.rfft(windowed))
    k = int(np.argmax(magnitude))
    a, b, c = np.log(magnitude[k - 1 : k + 2] + 1e-20)
    shift = 0.5 * (a - c) / (a - 2 * b + c)
    return (k + shift) * RATE / len(samples)


def octave_slope_db(samples: np.ndarray, low: float = 100.0, high: float = 10000.0) -> float:
    """A inclinação do espectro de potência em dB por oitava: reta ajustada aos níveis médios por terço de oitava."""
    segment = 16384
    window = np.hanning(segment)
    total, count = 0.0, 0
    for start in range(0, len(samples) - segment, segment // 2):
        total = total + np.abs(np.fft.rfft(samples[start : start + segment] * window)) ** 2
        count += 1
    power = total / count
    freqs = np.fft.rfftfreq(segment, 1 / RATE)
    centers = low * 2 ** (np.arange(0, np.log2(high / low), 1 / 3) + 1 / 6)
    levels = []
    for center in centers:
        band = (freqs >= center / 2 ** (1 / 6)) & (freqs < center * 2 ** (1 / 6))
        levels.append(10 * np.log10(power[band].mean()))
    return float(np.polyfit(np.log2(centers), levels, 1)[0])


# ---------- critério 1: o Tom ----------


def test_a_1_khz_tone_at_minus_6_dbfs_measures_minus_6_dbfs_peak_and_1000_hz_by_fft(tmp_path):
    samples = generate(tmp_path, sound("tone", 2.0, frequency_hz=1000, amplitude_db=-6))
    assert samples.shape == (2 * RATE, 2)
    assert peak_db(samples) == pytest.approx(-6.0, abs=0.02)
    assert peak_hz(samples[:, 0]) == pytest.approx(1000.0, abs=1.0)
    assert np.array_equal(
        samples[:, 0], samples[:, 1]
    )  # os dois canais iguais, sem os -3 dB do mono para estéreo


def test_square_and_sawtooth_tones_have_the_requested_peak_and_period(tmp_path):
    for waveform in ("square", "sawtooth", "square_bandlimited"):
        samples = generate(tmp_path, sound("tone", 1.0, waveform=waveform, frequency_hz=500, amplitude_db=-6))
        assert peak_db(samples) == pytest.approx(-6.0, abs=0.9), waveform
        assert peak_hz(samples[:, 0]) == pytest.approx(500.0, abs=1.0), waveform


def test_the_chirp_goes_from_the_start_to_the_end_frequency_linearly_and_in_octaves(tmp_path):
    def frequency_near(samples: np.ndarray, second: float) -> float:
        piece = samples[int((second - 0.1) * RATE) : int((second + 0.1) * RATE), 0]
        return peak_hz(piece)

    linear = generate(tmp_path, sound("chirp", 4.0, start_hz=200, end_hz=2200, start_db=-6, end_db=-6))
    assert frequency_near(linear, 0.5) == pytest.approx(200 + 2000 * 0.5 / 4, rel=0.04)
    assert frequency_near(linear, 2.0) == pytest.approx(1200.0, rel=0.03)
    assert frequency_near(linear, 3.5) == pytest.approx(200 + 2000 * 3.5 / 4, rel=0.02)

    log = generate(
        tmp_path,
        sound("chirp", 4.0, start_hz=200, end_hz=3200, interpolation="logarithmic", start_db=-6, end_db=-6),
    )
    assert frequency_near(log, 2.0) == pytest.approx(800.0, rel=0.03)  # no meio, a média geométrica: 200·√16


def test_the_chirp_amplitude_follows_the_line_in_db_between_the_ends(tmp_path):
    samples = generate(tmp_path, sound("chirp", 2.0, start_hz=1000, end_hz=1000, start_db=-6, end_db=-26))
    start = peak_db(samples[: int(0.05 * RATE)])
    middle = peak_db(samples[int(0.975 * RATE) : int(1.025 * RATE)])
    end = peak_db(samples[-int(0.05 * RATE) :])
    assert start == pytest.approx(-6.0, abs=1.0) and end == pytest.approx(-26.0, abs=1.0)
    assert middle == pytest.approx(-16.0, abs=0.7)


# ---------- critério 2: o Ruído ----------


@pytest.mark.parametrize(
    ("kind", "slope", "low"), [("pink", -3.0, 100.0), ("brown", -6.0, 400.0), ("white", 0.0, 100.0)]
)
def test_the_noise_spectrum_slopes_by_the_color_in_db_per_octave(tmp_path, kind, slope, low):
    """O rosa tem -3 dB por oitava de 100 Hz a 10 kHz. O marrom do ffmpeg é um integrador com perda: chega aos -6 dB por
    oitava acima de uns 400 Hz (abaixo, o espectro achata), e é daí que se mede."""
    samples = generate(tmp_path, sound("noise", 20.0, noise_type=kind, amplitude_db=-6))
    assert octave_slope_db(samples[:, 0], low=low) == pytest.approx(slope, abs=0.5)


def test_the_same_seed_gives_the_same_noise_and_another_seed_a_different_one(tmp_path):
    first = generate(tmp_path, sound("noise", 1.0, noise_type="pink", seed=3))
    again = generate(tmp_path, sound("noise", 1.0, noise_type="pink", seed=3))
    other = generate(tmp_path, sound("noise", 1.0, noise_type="pink", seed=4))
    assert np.array_equal(first, again) and not np.array_equal(first, other)


def test_the_white_noise_peak_does_not_pass_the_requested_amplitude(tmp_path):
    samples = generate(tmp_path, sound("noise", 3.0, noise_type="white", amplitude_db=-6))
    assert peak_db(samples) <= -5.99


# ---------- os outros pelo arquivo ----------


def test_every_generator_makes_a_stereo_float_wav_with_the_exact_item_duration(tmp_path):
    (tmp_path / "dados.txt").write_text(
        "\n".join(f"{np.sin(i / 10):.5f}" for i in range(2000)), encoding="utf-8"
    )
    cases = [
        sound("tone", 0.75),
        sound("chirp", 0.75),
        sound("noise", 0.75),
        sound("dtmf", 0.75, sequence="123"),
        sound("silence", 0.75),
        sound("pluck", 0.75),
        sound("risset_drum", 0.75),
        sound("rhythm_track", 0.75),
        sound("sample_data", 0.75, src="dados.txt", sample_rate=8000),
    ]
    for item in cases:
        samples = generate(tmp_path, item)
        assert samples.shape == (round(0.75 * RATE), 2), item.generator
        assert np.isfinite(samples).all(), item.generator


# ---------- na mistura ----------


def make_project(tmp_path: Path, generated: list[dict], **audio) -> Project:
    project = Project.model_validate(
        {
            "name": "gerados",
            "timeline": [],
            "output": {"preset": "audio/wav"},
            "audio": {"normalize": "off", "generated": generated, **audio},
        }
    )
    project.base_dir = tmp_path
    return project


def render_mix(tmp_path: Path, project: Project, name: str = "mix.wav") -> np.ndarray:
    out = tmp_path / name
    create_renderer(project, RenderOptions(quiet=True, out=out), runner=SubprocessRunner(quiet=True)).run()
    samples, _ = read_wav_channels(out)
    return samples


def rms_db(samples: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))), 1e-9))


def test_a_generated_tone_lands_on_its_instant_with_its_own_level_and_nothing_around_it(tmp_path):
    project = make_project(
        tmp_path,
        [
            {
                "generator": "tone",
                "params": {"frequency_hz": 1000, "amplitude_db": -6},
                "start": 1.0,
                "duration": 0.5,
            }
        ],
    )
    # um segundo de silêncio antes e depois: o projeto só de áudio dura até o fim do som gerado
    mix = render_mix(tmp_path, project)
    assert len(mix) == pytest.approx(round(1.5 * RATE), abs=2400)
    assert np.max(np.abs(mix[: int(0.99 * RATE)])) < 1e-4  # antes do instante, nada
    on = mix[int(1.02 * RATE) : int(1.48 * RATE)]
    assert 20 * np.log10(np.max(np.abs(on))) == pytest.approx(-6.0, abs=0.1)  # sem nivelar contra a voz
    assert peak_hz(on[:, 0]) == pytest.approx(1000.0, abs=3.0)


def test_the_item_volume_and_the_sfx_track_gain_both_scale_the_tone(tmp_path):
    items = [{"generator": "tone", "params": {"amplitude_db": -6}, "duration": 1.0, "volume": 0.5}]
    base = render_mix(tmp_path, make_project(tmp_path, items), "a.wav")
    assert 20 * np.log10(np.max(np.abs(base))) == pytest.approx(-12.0, abs=0.1)  # volume 0,5 são -6 dB
    boosted_project = make_project(tmp_path, items, voiceover=[])
    boosted_project = Project.model_validate(
        {**__import__("json").loads(boosted_project.to_bytes()), "tracks": {"SFX": {"gain_db": 6}}}
    )
    boosted_project.base_dir = tmp_path
    boosted = render_mix(tmp_path, boosted_project, "b.wav")
    assert 20 * np.log10(np.max(np.abs(boosted))) == pytest.approx(-6.0, abs=0.1)
    muted_project = Project.model_validate(
        {**__import__("json").loads(boosted_project.to_bytes()), "tracks": {"SFX": {"muted": True}}}
    )
    muted_project.base_dir = tmp_path
    assert np.max(np.abs(render_mix(tmp_path, muted_project, "c.wav"))) < 1e-4


def test_the_effect_chain_runs_on_the_generated_sound(tmp_path):
    items = [
        {
            "generator": "tone",
            "params": {"amplitude_db": -6},
            "duration": 2.0,
            "effects": [{"type": "fade_out", "duration": 1.0}],
        }
    ]
    mix = render_mix(tmp_path, make_project(tmp_path, items))
    first = mix[int(0.1 * RATE) : int(0.3 * RATE)]
    last = mix[int(1.8 * RATE) : int(1.99 * RATE)]
    assert rms_db(last) < rms_db(first) - 12  # o fade fecha o som no fim do item


def test_a_generated_sound_does_not_duck_the_music(tmp_path):
    music = tmp_path / "musica.wav"
    SubprocessRunner(quiet=True).run(
        __import__("dmaker.media.ffmpeg", fromlist=["FFmpegCommand"]).FFmpegCommand(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=f=330:d=4:r=48000",
                "-af",
                "aformat=channel_layouts=stereo",
                str(music),
            ]
        )
    )
    with_music = {"music": {"src": "musica.wav", "volume": 0.5, "ducking": True}}
    # um silêncio de 4 s nos dois projetos: a duração do projeto é a mesma, e a música não tem o fim dela a menos num deles
    quiet = {"generator": "silence", "duration": 4}
    plain = render_mix(tmp_path, make_project(tmp_path, [quiet], **with_music), "sem.wav")
    tone = {"generator": "tone", "params": {"frequency_hz": 1000}, "start": 1, "duration": 2}
    with_tone = render_mix(tmp_path, make_project(tmp_path, [quiet, tone], **with_music), "com.wav")
    window = slice(int(1.5 * RATE), int(2.5 * RATE))

    # a 330 Hz continua com o mesmo nível: o gerador soma no barramento SFX e o sidechain só enxerga a voz
    def at_330(samples: np.ndarray) -> float:
        piece = samples[window, 0].astype(np.float64)
        t = np.arange(len(piece)) / RATE
        return (
            2
            * abs(np.sum(piece * np.hanning(len(piece)) * np.exp(-2j * np.pi * 330 * t)))
            / np.sum(np.hanning(len(piece)))
        )

    assert 20 * np.log10(at_330(with_tone) / at_330(plain)) == pytest.approx(0.0, abs=0.2)


def test_the_stems_of_a_project_with_a_generated_sound_add_up_to_the_mix_and_name_the_sfx(tmp_path):
    project = make_project(
        tmp_path,
        [{"generator": "dtmf", "params": {"sequence": "123"}, "start": 0.5, "duration": 1.5}],
    )

    def pipeline(**options) -> AudioRenderPipeline:
        return AudioRenderPipeline(
            project,
            RenderOptions(quiet=True, **options),
            runner=SubprocessRunner(quiet=True),
            output_dir=tmp_path / "saida",
        )

    mix = AudioExporter(pipeline(out=tmp_path / "mix.wav")).run(ExportRequest(mode="mix"))
    stems = AudioExporter(pipeline()).run(ExportRequest(mode="stems"))
    assert [f.track for f in stems.files] == ["SFX"]
    assert all(
        "normalize" in warning for warning in stems.warnings
    )  # o único aviso é o de loudness desligado
    reference, _ = read_wav_channels(mix.files[0].path)
    stem, _ = read_wav_channels(stems.files[0].path)
    assert len(stem) == len(reference) and float(np.max(np.abs(stem.astype(np.float64) - reference))) < 0.001


def test_the_timeline_preview_mixes_the_generated_sound_like_the_render(tmp_path):
    project = Project.model_validate(
        {
            "name": "previa",
            "timeline": [{"type": "card", "title": "Teste", "duration": 3}],
            "audio": {
                "normalize": "off",
                "generated": [
                    {"generator": "tone", "params": {"amplitude_db": -6}, "start": 1, "duration": 1}
                ],
            },
        }
    )
    project.base_dir = tmp_path
    builder = PreviewAudioBuilder(
        runner=SubprocessRunner(quiet=True), cache_dir=tmp_path / "previa", jobs_dir=tmp_path / "jobs"
    )
    built = builder.build(project)
    import subprocess

    from dmaker import config

    pcm = subprocess.run(
        [
            str(config.find_tool("ffmpeg")),
            "-v",
            "error",
            "-i",
            str(built.path),
            "-ac",
            "2",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = np.frombuffer(pcm, dtype="<f4").reshape(-1, 2)
    assert np.max(np.abs(samples[: int(0.9 * RATE)])) < 0.01
    assert 20 * np.log10(np.max(np.abs(samples[int(1.1 * RATE) : int(1.9 * RATE)]))) == pytest.approx(
        -6.0, abs=0.7
    )  # AAC
    # o som gerado entra na chave da prévia: outro tom, outra mixagem
    other = Project.model_validate(
        {
            **__import__("json").loads(project.to_bytes()),
            "audio": {
                "normalize": "off",
                "generated": [
                    {"generator": "tone", "params": {"frequency_hz": 880}, "start": 1, "duration": 1}
                ],
            },
        }
    )
    other.base_dir = tmp_path
    assert builder.key(other) != builder.key(project)


def test_a_project_without_a_generated_sound_keeps_its_preview_key(tmp_path):
    """O projeto antigo: a chave da mixagem da prévia não muda com a existência do campo novo."""
    project = Project.model_validate(
        {
            "name": "antigo",
            "timeline": [{"type": "card", "title": "A", "duration": 2}],
            "audio": {"normalize": "off"},
        }
    )
    project.base_dir = tmp_path
    builder = PreviewAudioBuilder(runner=SubprocessRunner(quiet=True), cache_dir=tmp_path / "previa")
    assert "generated" not in project.audio.model_dump(mode="json")
    assert builder.key(project) == builder.key(Project.model_validate_json(project.to_bytes()))
