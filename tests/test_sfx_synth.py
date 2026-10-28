"""Síntese e biblioteca dos efeitos sonoros: determinismo, duração, pico, sem DC, sem estalo, origem registrada."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.media.wavio import read_wav_channels
from dmaker.sfx import (
    PEAK_DBFS,
    SAMPLE_RATE,
    SfxNotFound,
    library_names,
    resolve_sound,
    sound_def,
    synthesize,
    write_library,
)
from dmaker.sfx.library import LICENSES_FILE, library_path, licenses_text

REQUIRED = ("whoosh", "pop", "click", "riser", "impact")  # os cinco da decisão do chamado
QUANTIZATION_DB = 0.01  # tolerância do pico depois de gravar em 16 bits


def test_library_has_the_required_sounds():
    assert set(REQUIRED) <= set(library_names())
    assert len(set(library_names())) == len(library_names())


@pytest.mark.parametrize("name", library_names())
def test_synthesis_is_deterministic(name):
    assert np.array_equal(synthesize(name).samples, synthesize(name).samples)


@pytest.mark.parametrize("name", library_names())
def test_duration_matches_the_recipe(name):
    sound = synthesize(name)
    assert sound.sample_rate == SAMPLE_RATE
    assert sound.duration == pytest.approx(sound_def(name).duration, abs=1 / SAMPLE_RATE)
    assert 0.05 <= sound.duration <= 3.0  # efeito curto: nada de trilha disfarçada


@pytest.mark.parametrize("name", library_names())
def test_peak_is_exactly_minus_three_dbfs(name):
    assert synthesize(name).peak_dbfs == pytest.approx(PEAK_DBFS, abs=1e-9)


@pytest.mark.parametrize("name", library_names())
def test_no_dc_offset(name):
    samples = synthesize(name).samples
    assert abs(float(np.mean(samples))) < 0.005 * float(np.max(np.abs(samples)))


@pytest.mark.parametrize("name", library_names())
def test_starts_and_ends_at_zero_without_a_click(name):
    samples = synthesize(name).samples
    peak = float(np.max(np.abs(samples)))
    assert samples[0] == 0.0 and samples[-1] == 0.0
    # o som chega a zero por uma rampa, e não por um degrau: as primeiras e as últimas amostras já são ~0
    assert float(np.max(np.abs(samples[:3]))) < 0.01 * peak
    assert float(np.max(np.abs(samples[-3:]))) < 0.01 * peak


@pytest.mark.parametrize("name", library_names())
def test_sound_is_not_silent_or_clipped(name):
    samples = synthesize(name).samples
    assert np.sqrt(np.mean(samples**2)) > 0.01
    assert np.all(np.isfinite(samples)) and float(np.max(np.abs(samples))) < 1.0


def test_unknown_sound_lists_the_library():
    with pytest.raises(KeyError, match="whoosh"):
        synthesize("nao-existe")


def test_whoosh_sweeps_upward_and_riser_grows():
    """A varredura do whoosh sobe de frequência e o riser cresce até o fim: o que dá o caráter de cada um."""

    def centroid(part: np.ndarray) -> float:
        spectrum = np.abs(np.fft.rfft(part * np.hanning(len(part))))
        return float((spectrum * np.fft.rfftfreq(len(part), 1 / SAMPLE_RATE)).sum() / spectrum.sum())

    whoosh = np.array_split(synthesize("whoosh").samples, 3)
    assert centroid(whoosh[0]) < centroid(whoosh[1]) < centroid(whoosh[2])
    riser = np.array_split(synthesize("riser").samples, 3)
    levels = [float(np.sqrt(np.mean(part**2))) for part in riser]
    assert levels[0] < levels[1] < levels[2]


def test_impact_is_low_and_decays():
    samples = synthesize("impact").samples
    spectrum = np.abs(np.fft.rfft(samples))
    frequencies = np.fft.rfftfreq(len(samples), 1 / SAMPLE_RATE)
    assert float(frequencies[int(np.argmax(spectrum))]) < 200.0
    halves = [float(np.sqrt(np.mean(part**2))) for part in np.array_split(samples, 4)]
    assert halves[0] > halves[1] > halves[2] > halves[3]


# ---------- biblioteca em arquivos ----------


def test_write_library_writes_stereo_wavs_with_the_peak_and_the_licenses(tmp_path):
    written = write_library(tmp_path)
    assert {path.stem for path in written} == set(library_names())
    for path in written:
        frames, rate = read_wav_channels(path)
        assert rate == SAMPLE_RATE and frames.shape[1] == 2
        assert np.array_equal(
            frames[:, 0], frames[:, 1]
        )  # dois canais iguais: o mono desceria 3 dB no ffmpeg
        peak_db = 20 * np.log10(float(np.max(np.abs(frames))))
        assert peak_db == pytest.approx(PEAK_DBFS, abs=QUANTIZATION_DB)
    licenses = (tmp_path / LICENSES_FILE).read_text(encoding="utf-8")
    assert licenses == licenses_text()


def test_the_shipped_library_matches_the_registry_and_registers_every_origin():
    """Todo arquivo de assets/sfx tem origem e licença registradas, e nenhum é de terceiros."""
    directory = config.SFX_DIR
    wavs = sorted(path.stem for path in directory.glob("*.wav"))
    assert wavs == sorted(library_names())
    licenses = (directory / LICENSES_FILE).read_text(encoding="utf-8")
    assert licenses == licenses_text(), "o LICENSES envelheceu: rode `dmaker sfx build`"
    for name in library_names():
        line = next(line for line in licenses.splitlines() if line.startswith(f"{name}.wav:"))
        assert "Origem: sintetizado pelo DMaker" in line and "Licença: MIT" in line
    others = [
        path.name for path in directory.iterdir() if path.suffix != ".wav" and path.name != LICENSES_FILE
    ]
    assert not others  # nada solto na pasta que o LICENSES não cubra


@pytest.mark.parametrize("name", library_names())
def test_the_shipped_files_have_the_standard_level_and_are_clean(name):
    frames, rate = read_wav_channels(library_path(name))
    mono = frames[:, 0]
    peak = float(np.max(np.abs(mono)))
    assert rate == SAMPLE_RATE and frames.shape[1] == 2
    assert 20 * np.log10(peak) == pytest.approx(PEAK_DBFS, abs=QUANTIZATION_DB)
    assert len(mono) / rate == pytest.approx(sound_def(name).duration, abs=1 / rate)
    assert abs(float(np.mean(mono))) < 0.005 * peak
    assert abs(float(mono[0])) < 0.001 and abs(float(mono[-1])) < 0.001


# ---------- resolução do som da spec ----------


def test_resolve_sound_prefers_the_library_name(tmp_path):
    assert resolve_sound("whoosh", lambda ref: tmp_path / ref) == library_path("whoosh")


def test_resolve_sound_takes_a_project_path(tmp_path):
    own = tmp_path / "meu.wav"
    own.write_bytes(b"x")
    assert resolve_sound("meu.wav", lambda ref: tmp_path / ref) == own


def test_resolve_sound_reports_a_missing_file_with_the_library_names(tmp_path):
    with pytest.raises(SfxNotFound, match="whoosh.*biblioteca|biblioteca.*whoosh"):
        resolve_sound("sumiu.wav", lambda ref: tmp_path / ref)


def test_resolve_sound_tells_how_to_rebuild_a_missing_library_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SFX_DIR", tmp_path / "vazia")
    with pytest.raises(SfxNotFound, match="dmaker sfx build"):
        resolve_sound("pop", lambda ref: Path(ref))


def test_no_network_in_the_sfx_path():
    """Os sons ficam em assets/sfx: nenhum módulo da síntese ou da biblioteca fala com a rede."""
    import dmaker.sfx.library as library
    import dmaker.sfx.synth as synth

    for module in (library, synth):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not any(word in source for word in ("urllib", "requests", "http://", "https://", "socket"))
