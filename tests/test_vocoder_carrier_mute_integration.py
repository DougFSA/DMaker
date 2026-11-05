"""A portadora do Vocoder com faixa externa muda ou fora do solo, com ffmpeg de verdade (ajuste do DMK-70).

O sinal é conhecido: três faixas externas, cada uma um tom bem separado (A2 = 330 Hz, A3 = 1000 Hz, A4 = 2900 Hz), e uma voz gravada
em ruído branco cujo Vocoder tem a A3 como portadora. Com `noise_level=0` e `original_level=0` o que o Vocoder entrega é a portadora
recortada pelo ruído, então o tom mais forte do arquivo processado diz qual faixa ele leu. Cada cenário usa a própria pasta de
efeitos em cache, para o arquivo processado da voz ser o único dela e a comparação ser entre arquivos gerados de verdade.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.preview_audio import PreviewAudioBuilder

from .conftest import requires_ffmpeg
from .test_dynamics_integration import RATE, decode, no_sync, write_wav
from .test_narration import FakeSynthesizer
from .test_vocoder_carrier_track_integration import make_video, noise

pytestmark = requires_ffmpeg

TONES = {"a": 330.0, "b": 1000.0, "d": 2900.0}  # A2, A3 e A4
TRACK_VOLUME = 0.02  # as faixas entram baixas na mixagem; o Vocoder sai no nível da voz
WARNING_PART = (
    "o Vocoder pede a portadora da trilha A3, que está muda ou fora do solo; usa a portadora gerada."
)


def tone(hz: float, seconds: float = 6.0) -> np.ndarray:
    return (0.5 * np.sin(2 * np.pi * hz * np.arange(round(seconds * RATE)) / RATE)).astype(np.float32)


def build_project(folder: Path, states: dict, carrier: str | None) -> Project:
    folder.mkdir(parents=True, exist_ok=True)
    make_video(folder, 6.0)
    write_wav(folder / "fala.wav", noise(3.0))
    sources = {"cam": {"src": "video.mp4"}}
    for name, hz in TONES.items():
        write_wav(folder / f"{name}.wav", tone(hz))
        sources[name] = {"src": f"{name}.wav", "sync": 0.0}
    vocoder = {"type": "vocoder", "noise_level": 0, "original_level": 0}
    project = Project.model_validate(
        {
            "name": "portadora-muda",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "sources": sources,
            "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 6, "mute": True}],
            "audio": {
                "normalize": "off",
                "tracks": [{"source": name, "volume": TRACK_VOLUME} for name in TONES],
                "voiceover": [
                    {
                        "src": "fala.wav",
                        "start": 1.0,
                        "effects": [{**vocoder, **({"carrier_track": carrier} if carrier else {})}],
                    }
                ],
            },
            "tracks": states,
        }
    )
    project.base_dir = folder
    return project


def render(project: Project, folder: Path) -> tuple[np.ndarray, list[str]]:
    runner = SubprocessRunner(quiet=True)
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / "saida.mp4", thumbnail=False),
        runner=runner,
        offset_finder=no_sync,
        narrator=NarrationService(FakeSynthesizer(), runner, folder / "voz"),
        cache_dir=folder / "mez",
        jobs_dir=folder / "jobs",
    ).run()
    return decode(result.output, RATE, 1)[:, 0], list(result.warnings)


def processed_voice() -> np.ndarray:
    """O único arquivo processado da voz na pasta de efeitos deste cenário (as portadoras ficam em `carriers/`)."""
    found = sorted(Path(config.AUDIO_FX_DIR).glob("*.wav"))
    assert len(found) == 1, found
    return decode(found[0], RATE, 1)[:, 0]


def dominant_hz(samples: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64) * np.hanning(len(samples))))
    freqs = np.fft.rfftfreq(len(samples), 1 / RATE)
    band = (freqs > 150) & (freqs < 5000)
    return float(freqs[band][np.argmax(spectrum[band])])


def tone_level(samples: np.ndarray, hz: float) -> float:
    """A energia (dB) em volta de `hz`, +-40 Hz."""
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64) * np.hanning(len(samples)))) / len(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / RATE)
    near = (freqs > hz - 40) & (freqs < hz + 40)
    return float(20 * np.log10(np.sqrt(np.sum(spectrum[near] ** 2)) + 1e-12))


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    def run(name: str, states: dict, carrier: str | None = "A3"):
        monkeypatch.setattr(config, "AUDIO_FX_DIR", tmp_path / f"fx-{name}")
        folder = tmp_path / name
        project = build_project(folder, states, carrier)
        mix, warnings = render(project, folder)
        return project, folder, mix, warnings, processed_voice()

    return run


def test_muting_a_lower_track_keeps_reading_the_same_source(scenario):
    _, _, _, _, base = scenario("base", {})
    _, _, _, warnings, muted = scenario("a2-muda", {"A2": {"muted": True}})
    assert dominant_hz(base) == pytest.approx(TONES["b"], abs=15)
    assert dominant_hz(muted) == pytest.approx(TONES["b"], abs=15)  # a A3 virou a A2 e segue sendo a fonte b
    assert float(np.max(np.abs(muted - base))) < 1e-4
    assert not any(WARNING_PART in warning for warning in warnings)  # só renumerou, nada foi perdido


def test_muting_the_carrier_track_itself_falls_back_to_the_generated_carrier_and_warns(scenario):
    _, _, _, warnings, muted = scenario("a3-muda", {"A3": {"muted": True}})
    _, _, _, _, generated = scenario("gerada", {}, carrier=None)
    assert float(np.max(np.abs(muted - generated))) == 0.0
    assert any(warning.endswith(WARNING_PART) and "audio.voiceover[0]" in warning for warning in warnings)


def test_a_track_outside_the_solo_is_not_a_carrier_either(scenario):
    _, _, _, warnings, outside = scenario("solo", {"VO": {"solo": True}})
    _, _, _, _, generated = scenario("gerada", {"VO": {"solo": True}}, carrier=None)
    assert float(np.max(np.abs(outside - generated))) == 0.0
    assert any(warning.endswith(WARNING_PART) for warning in warnings)


def test_the_preview_reads_the_same_carrier_as_the_render(scenario, tmp_path):
    states = {"A2": {"muted": True}}
    project, folder, render_mix, _, _ = scenario("a2-muda", states)
    builder = PreviewAudioBuilder(offset_finder=no_sync, cache_dir=folder / "pa", jobs_dir=folder / "pj")
    preview = decode(builder.build(project).path, RATE, 1)[:, 0]
    window = slice(round(1.2 * RATE), round(3.8 * RATE))
    assert dominant_hz(preview[window]) == pytest.approx(TONES["b"], abs=15)
    assert dominant_hz(render_mix[window]) == pytest.approx(TONES["b"], abs=15)
    gap = abs(tone_level(preview[window], TONES["b"]) - tone_level(render_mix[window], TONES["b"]))
    assert gap < 1.5  # a prévia e o render soam iguais nessa medida


def test_the_preview_also_warns_when_the_carrier_track_is_muted(scenario):
    project, folder, _, _, _ = scenario("a3-muda", {"A3": {"muted": True}})
    builder = PreviewAudioBuilder(offset_finder=no_sync, cache_dir=folder / "pa", jobs_dir=folder / "pj")
    assert any(warning.endswith(WARNING_PART) for warning in builder.build(project).warnings)
