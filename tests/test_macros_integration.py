"""Macros de áudio com o ffmpeg de verdade: o som que sai de uma pasta tratada, medido em sinais conhecidos.

Tons, ruído de chiado, ronco de 50 Hz e uma "fala" sintética (três tons sob uma envoltória silábica) gerados no próprio teste. Os
números de cada critério do DMK-66 (20 arquivos com o mesmo tratamento, a retomada depois da queda, "Limpar narração" a
-16 LUFS com o ruído mais baixo, o mesmo som de um item tratado no projeto) saem daqui.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_effects import get_effect_preset, save_user_preset
from dmaker.domain.audio_export import ExportRequest
from dmaker.domain.spec import Project
from dmaker.pipeline.audio_service import export_audio_project
from dmaker.pipeline.macro_run import (
    STATE_NAME,
    MacroRunService,
    PipelineFileRenderer,
    plan_macro_run,
)

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48000


def db(value: float) -> float:
    return 20 * np.log10(max(float(value), 1e-12))


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))


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


def decode(path: Path, channels: int = 2) -> np.ndarray:
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path), "-vn"]
    command += ["-ac", str(channels), "-ar", str(RATE), "-f", "f32le", "-"]
    data = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")
    return data.reshape(-1, channels)


def loudness(path: Path) -> dict[str, float]:
    """O LUFS integrado, a LRA e o pico verdadeiro (dBTP) do arquivo, pelo ebur128."""
    command = [str(config.find_tool("ffmpeg")), "-hide_banner", "-nostats", "-i", str(path)]
    command += ["-af", "ebur128=framelog=quiet:peak=true", "-f", "null", "-"]
    report = subprocess.run(command, capture_output=True, text=True).stderr

    def grab(pattern: str) -> float:
        return float(re.search(pattern, report).group(1))

    return {"I": grab(r"I:\s+(-?[\d.]+) LUFS"), "TP": grab(r"Peak:\s+(-?[\d.]+) dBFS")}


def voice(seconds: float) -> np.ndarray:
    """Uma "fala" sintética: três tons sob uma envoltória silábica de 4 Hz."""
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


def band_level(samples: np.ndarray, low: float, high: float) -> float:
    """O pico do espectro de amplitude (dBFS) entre `low` e `high` Hz."""
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)))) / len(samples)
    frequencies = np.fft.rfftfreq(len(samples), 1 / RATE)
    return db(spectrum[(frequencies > low) & (frequencies < high)].max())


class Crash(BaseException):
    """A queda do processo no meio de um arquivo."""


class CountingRenderer(PipelineFileRenderer):
    """O render de verdade, que anota cada arquivo que recebe e pode cair no meio de um deles."""

    def __init__(self, crash_on: str | None = None) -> None:
        super().__init__()
        self.sources: list[str] = []
        self.crash_on = crash_on

    def render(self, source, effects, out, preset, choices, *, sink, log):
        self.sources.append(source.name)
        if source.name == self.crash_on:
            out.write_bytes(b"pela metade")  # o processo caiu com o arquivo aberto
            raise Crash
        return super().render(source, effects, out, preset, choices, sink=sink, log=log)


def lengths_match(a: np.ndarray, b: np.ndarray, tolerance: int = 2400) -> bool:
    return abs(len(a) - len(b)) <= tolerance


# ---------- "Limpar narração" ----------


def test_clean_narration_lowers_the_background_noise_and_delivers_minus_16_lufs(tmp_path):
    """Fala sintética com chiado a -42 dBFS e ronco de 50 Hz somados: o ruído baixa e a fala chega a -16 LUFS ± 0,5."""
    seconds = 8.0
    t = np.arange(round(seconds * RATE)) / RATE
    speech = voice(seconds)
    speech[: round(1.5 * RATE)] = 0  # 1,5 s só de ruído, de onde sai o perfil automático
    hum = (0.02 * np.sin(2 * np.pi * 50 * t)).astype(np.float32)
    samples = np.stack(
        [speech + hum + hiss(seconds, -42.0), 0.9 * speech + hum + hiss(seconds, -42.0, 8)], axis=1
    )
    (tmp_path / "in").mkdir()
    source = write_wav(tmp_path / "in" / "gravacao.wav", samples)
    plan = plan_macro_run(get_effect_preset("clean_narration"), [source], tmp_path / "out", "wav")
    report = MacroRunService().run(plan)
    assert report.done == 1, report.to_text()

    before, after = decode(source), decode(tmp_path / "out" / "gravacao.wav")
    quiet = slice(round(0.2 * RATE), round(1.3 * RATE))  # o começo, sem fala
    noise_drop = db(rms(before[quiet])) - db(rms(after[quiet]))
    hum_drop = band_level(before[quiet, 0], 45, 55) - band_level(after[quiet, 0], 45, 55)
    measured = loudness(tmp_path / "out" / "gravacao.wav")
    print(f"ruído de fundo: {noise_drop:.1f} dB mais baixo; ronco de 50 Hz: {hum_drop:.1f} dB; {measured}")
    assert noise_drop >= 10.0 and hum_drop >= 10.0
    assert measured["I"] == pytest.approx(-16.0, abs=0.5)
    assert measured["TP"] <= -1.0  # o limitador da receita segura o pico
    assert lengths_match(before, after)


def test_a_macro_with_no_loudness_effect_leaves_the_level_alone_because_the_master_is_not_normalized(
    tmp_path,
):
    """ "Nada além do que a macro pede": Fade nas pontas não mexe no nível do meio do arquivo."""
    (tmp_path / "in").mkdir()
    source = write_wav(tmp_path / "in" / "fala.wav", np.stack([voice(6.0), 0.8 * voice(6.0)], axis=1))
    plan = plan_macro_run(get_effect_preset("ends_fade"), [source], tmp_path / "out", "wav")
    assert MacroRunService().run(plan).done == 1
    before, after = decode(source), decode(tmp_path / "out" / "fala.wav")
    middle = slice(round(2 * RATE), round(4 * RATE))
    change = db(rms(after[middle])) - db(rms(before[middle]))
    print(f"mudança de nível no meio: {change:+.3f} dB")
    assert abs(change) < 0.05
    assert rms(after[: round(0.05 * RATE)]) < 0.3 * rms(
        before[: round(0.05 * RATE)]
    )  # a entrada de 0,3 s abre devagar
    assert rms(after[-round(0.05 * RATE) :]) < 0.3 * rms(before[-round(0.05 * RATE) :])  # e a saída fecha


# ---------- 20 arquivos com o mesmo tratamento ----------


def test_one_macro_on_twenty_files_gives_twenty_outputs_with_the_same_treatment(tmp_path):
    """Vinte arquivos de volumes e conteúdos diferentes (tom, fala e chiado) saem todos a -16 LUFS, no tamanho do original."""
    save_user_preset(
        "Padrão da série",
        [
            {"type": "highpass", "frequency_hz": 80, "slope_db": 12},
            {"type": "loudness_normalize", "mode": "lufs", "target_db": -16.0},
            {"type": "limiter", "ceiling_db": -1.0},
        ],
        output={"preset": "audio/wav"},
    )
    folder = tmp_path / "in"
    folder.mkdir()
    for number in range(20):
        seconds = 1.5
        gain = 10 ** (-(10 + number) / 20)  # de -10 a -29 dB: 20 níveis diferentes
        kinds = (
            voice(seconds) * gain / 0.17,
            np.sin(2 * np.pi * (200 + 40 * number) * np.arange(round(seconds * RATE)) / RATE).astype(
                np.float32
            )
            * gain,
            (voice(seconds) / 0.17 * gain * 0.5) + hiss(seconds, -50.0 + number * 0.5, seed=number),
        )
        write_wav(folder / f"fala-{number + 1:02d}.wav", kinds[number % 3])
    renderer = CountingRenderer()
    plan = plan_macro_run(get_effect_preset("padrao-da-serie"), [folder], tmp_path / "out")
    report = MacroRunService(renderer).run(plan)
    assert report.done == 20 and report.failed == 0, report.to_text()
    outputs = sorted((tmp_path / "out").glob("*.wav"))
    assert len(outputs) == 20 and len(renderer.sources) == 20
    levels_in, levels_out = [], []
    for output in outputs:
        original = folder / output.name
        levels_in.append(loudness(original)["I"])
        measured = loudness(output)
        levels_out.append(measured["I"])
        assert measured["I"] == pytest.approx(-16.0, abs=0.5), output.name
        assert measured["TP"] <= -1.0, output.name
        assert lengths_match(decode(original), decode(output)), output.name
    print(
        f"20 saídas: entrada de {min(levels_in):.1f} a {max(levels_in):.1f} LUFS, saída de {min(levels_out):.2f} a {max(levels_out):.2f} LUFS"
    )
    assert max(levels_in) - min(levels_in) > 8  # as entradas eram mesmo diferentes
    assert not list((tmp_path / "out").glob("*.parcial.*"))


# ---------- a queda no meio e a retomada, com o render de verdade ----------


def test_a_crash_in_the_middle_resumes_with_only_the_missing_files_and_the_half_file_is_redone(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    for number in range(1, 7):
        write_wav(folder / f"ep-{number}.wav", voice(1.0) * (0.5 + number / 10))
    macro = get_effect_preset("ends_fade")
    plan = plan_macro_run(macro, [folder], tmp_path / "out", "flac")
    first = CountingRenderer(crash_on="ep-4.wav")
    with pytest.raises(Crash):
        MacroRunService(first).run(plan)
    assert first.sources == ["ep-1.wav", "ep-2.wav", "ep-3.wav", "ep-4.wav"]
    done = sorted(p.name for p in (tmp_path / "out").glob("*.flac") if ".parcial" not in p.name)
    assert done == ["ep-1.flac", "ep-2.flac", "ep-3.flac"]
    half = tmp_path / "out" / "ep-4.parcial.flac"
    assert half.read_bytes() == b"pela metade"  # o arquivo pela metade, que nunca virou ep-4.flac

    second = CountingRenderer()
    report = MacroRunService(second).run(plan, resume=True)
    assert second.sources == ["ep-4.wav", "ep-5.wav", "ep-6.wav"]  # só os que faltavam
    assert report.done == 6 and not half.exists()
    for number in range(1, 7):
        result = decode(tmp_path / "out" / f"ep-{number}.flac")
        assert result.shape[0] > RATE * 0.9, number  # todos decodificam inteiros, inclusive o refeito
    assert [row.state for row in MacroRunService().store(plan.out_dir).load(STATE_NAME).rows] == ["done"] * 6
    print(f"retomada: {len(second.sources)} de 6 arquivos refeitos ({', '.join(second.sources)})")


def test_a_file_that_is_not_audio_fails_alone_and_the_others_are_done(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    write_wav(folder / "bom-1.wav", voice(1.0))
    (folder / "ruim.wav").write_bytes(b"isto nao e audio")
    write_wav(folder / "bom-2.wav", voice(1.0))
    report = MacroRunService().run(
        plan_macro_run(get_effect_preset("ends_fade"), [folder], tmp_path / "out", "wav")
    )
    assert (report.done, report.failed) == (2, 1)
    failed = next(row for row in report.rows if row.state == "failed")
    assert failed.title == "ruim.wav" and failed.error
    assert sorted(p.name for p in (tmp_path / "out").glob("*.wav")) == ["bom-1.wav", "bom-2.wav"]
    assert not list((tmp_path / "out").glob("*.parcial.*"))


# ---------- o mesmo som de um item tratado no projeto ----------


def test_a_file_through_the_macro_sounds_like_the_same_chain_on_a_voice_item_in_a_project(tmp_path):
    """A macro aplicada a um arquivo e a mesma cadeia posta no item de um projeto só de áudio dão o mesmo WAV."""
    (tmp_path / "in").mkdir()
    source = write_wav(
        tmp_path / "in" / "voz.wav", np.stack([voice(5.0) + hiss(5.0, -45.0), voice(5.0)], axis=1)
    )
    macro = get_effect_preset("clean_narration")
    plan = plan_macro_run(macro, [source], tmp_path / "out", "wav")
    assert MacroRunService().run(plan).done == 1
    project = Project.model_validate(
        {
            "name": "mesmo-som",
            "timeline": [],
            "output": {"preset": "audio/wav"},
            "audio": {
                "normalize": "off",
                "voiceover": [{"src": str(source), "effects": [dict(effect) for effect in macro.effects]}],
            },
        }
    )
    spec = project.save(tmp_path / "proj" / "spec.json")
    via_project = tmp_path / "via-projeto.wav"
    export_audio_project(spec, ExportRequest("mix"), out=via_project)
    from_macro, from_project = decode(tmp_path / "out" / "voz.wav"), decode(via_project)
    assert from_macro.shape == from_project.shape
    difference = float(np.max(np.abs(from_macro - from_project)))
    print(f"diferença máxima entre a macro e o item no projeto: {difference:.2e}")
    assert difference < 1e-4


def test_mp3_for_the_standard_macro_writes_mp3_files_with_the_peak_near_minus_one(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    for number in range(3):
        write_wav(folder / f"a{number}.wav", voice(2.0) * (1 + number))
    plan = plan_macro_run(get_effect_preset("mp3_standard"), [folder], tmp_path / "out")
    assert plan.preset.id == "audio/mp3"
    assert MacroRunService().run(plan).done == 3
    for number in range(3):
        result = tmp_path / "out" / f"a{number}.mp3"
        assert result.is_file()
        peak = loudness(result)["TP"]
        assert -1.8 < peak < -0.3, peak  # o MP3 mexe um pouco no pico; o alvo é -1 dBFS
