"""Montagem em blocos com o ffmpeg de verdade e WAVs mínimos: o resultado é o de um comando só, e as muitas falas cabem."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker.filtergraph.blocks import MAX_INPUTS
from dmaker.filtergraph.dub import DubClip, dub_mix_command
from dmaker.filtergraph.dub_blocks import premix_dub_clips
from dmaker.filtergraph.dub_stems import StemOutputs, dub_stems_command
from dmaker.filtergraph.voice import narration_concat_command, narration_concat_plan
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.probe import probe
from dmaker.media.wavio import read_wav_channels, write_wav
from dmaker.pipeline.block_runner import block_workspace, run_steps
from dmaker.pipeline.narration import concat_narration

from .conftest import WINDOWS_LINE_LIMIT, requires_ffmpeg

pytestmark = requires_ffmpeg

SPEECH_RATE = 24000
MIX_RATE = 48000
ONE_STEP = 2 / 32768  # um degrau do WAV de 16 bits; a soma em blocos troca a ordem das somas em float


def tone(seconds: float, frequency: float = 440.0) -> np.ndarray:
    return (0.3 * np.sin(2 * np.pi * frequency * np.arange(int(seconds * SPEECH_RATE)) / SPEECH_RATE)).astype(
        np.float32
    )


def speeches(folder: Path, count: int, seconds: float = 0.01) -> list[tuple[Path, float]]:
    """`count` falas mínimas e as pausas depois delas (uma pausa a cada quatro falas, a última sem)."""
    folder.mkdir(parents=True, exist_ok=True)
    return [
        (
            write_wav(folder / f"fala-{index:05d}.wav", tone(seconds, 200 + index % 50 * 10), SPEECH_RATE),
            0.1 if index % 4 == 0 and index < count - 1 else 0.0,
        )
        for index in range(count)
    ]


# ---------- narração ----------


@pytest.mark.parametrize("extension", ["wav", "mp3"])
def test_a_narration_assembled_in_blocks_is_the_same_file_as_the_single_command(
    tmp_path: Path, extension: str
):
    parts = speeches(tmp_path / "falas", 40, seconds=0.07)
    runner = SubprocessRunner(quiet=True)
    single = tmp_path / f"unico.{extension}"
    runner.run(narration_concat_command(parts, single))

    blocked = tmp_path / f"blocos.{extension}"
    plan = narration_concat_plan(
        parts, blocked, tmp_path / "montagem", limit=6
    )  # 40 -> 7 -> 2 -> o comando final
    run_steps(runner, plan)

    assert len(plan) == 7 + 2 + 1
    assert blocked.read_bytes() == single.read_bytes()


def test_the_m4a_of_a_narration_in_blocks_has_the_same_length_as_the_single_command(tmp_path: Path):
    parts = speeches(tmp_path / "falas", 40, seconds=0.07)
    runner = SubprocessRunner(quiet=True)
    single, blocked = tmp_path / "unico.m4a", tmp_path / "blocos.m4a"
    runner.run(narration_concat_command(parts, single))
    run_steps(runner, narration_concat_plan(parts, blocked, tmp_path / "montagem", limit=6))
    assert probe(blocked).duration == pytest.approx(probe(single).duration, abs=0.01)


def test_a_narration_that_fits_in_one_command_is_the_file_of_the_old_command(tmp_path: Path):
    parts = speeches(tmp_path / "falas", 12, seconds=0.2)
    old, new = tmp_path / "antigo.wav", tmp_path / "novo.wav"
    SubprocessRunner(quiet=True).run(narration_concat_command(parts, old))
    concat_narration(SubprocessRunner(quiet=True), tmp_path / "cache", parts, new)
    assert new.read_bytes() == old.read_bytes()


def test_a_chapter_of_1200_speeches_that_overflowed_the_command_line_assembles_with_the_exact_length(
    tmp_path: Path,
):
    """1.200 falas de 10 ms e uma pausa de 0,1 s a cada quatro: 12 s de fala + 30 s de pausa = 42 s."""
    parts = speeches(tmp_path / "falas", 1200)
    out = tmp_path / "saida" / "capitulo.wav"
    out.parent.mkdir()
    old = narration_concat_command(parts, out)
    assert len(subprocess.list2cmdline(old.full())) > WINDOWS_LINE_LIMIT  # o comando de antes não cabia

    concat_narration(SubprocessRunner(quiet=True), tmp_path / "cache", parts, out)

    pauses = sum(pause for _, pause in parts)
    info = probe(out)
    assert info.duration == pytest.approx(1200 * 0.01 + pauses, abs=0.002)
    assert info.sample_rate == MIX_RATE and info.channels == 1
    assert list((tmp_path / "cache").iterdir()) == []  # os intermediários não ficam


# ---------- dublagem ----------


def dub_clips(folder: Path, count: int, spacing: float, seconds: float) -> list[DubClip]:
    """Falas que podem se sobrepor (se a duração passa do espaçamento), com ganho, corte e começos em empate da grade."""
    folder.mkdir(parents=True, exist_ok=True)
    return [
        DubClip(
            write_wav(folder / f"d{index:04d}.wav", tone(seconds, 150 + index % 40 * 15), SPEECH_RATE),
            start=round(index * spacing, 2),
            gain_db=((index % 5) - 2) * 1.5,
            max_seconds=seconds * 0.7 if index % 3 == 0 else None,
        )
        for index in range(count)
    ]


def background(path: Path, seconds: float) -> Path:
    count = int(seconds * MIX_RATE)
    return write_wav(
        path, (0.05 * np.sin(2 * np.pi * 110 * np.arange(count) / MIX_RATE)).astype(np.float32), MIX_RATE
    )


def run_mix(
    tmp_path: Path, clips: list[DubClip], bg: Path, out: Path, seconds: float, limit: int = MAX_INPUTS
) -> None:
    runner = SubprocessRunner(quiet=True)
    graph_file = tmp_path / f"{out.stem}.graph.txt"
    with block_workspace(tmp_path / "cache") as work:
        reduction = premix_dub_clips(clips, work, limit)
        mix = dub_mix_command(Path("sem-video"), bg, reduction.items, out, graph_file, seconds, False)
        run_steps(runner, reduction.steps)
        graph_file.write_text(mix.graph, encoding="utf-8")
        runner.run(mix.command)


def test_a_dub_mixed_in_blocks_matches_the_single_mix_within_one_quantization_step(tmp_path: Path):
    clips = dub_clips(tmp_path / "falas", 30, spacing=0.37, seconds=0.9)
    bg = background(tmp_path / "fundo.wav", 14.0)
    single, blocked = tmp_path / "unico.wav", tmp_path / "blocos.wav"
    run_mix(tmp_path, clips, bg, single, 14.0, limit=1000)  # nenhum bloco: o comando de antes
    run_mix(tmp_path, clips, bg, blocked, 14.0, limit=4)  # 30 -> 8 -> 2 blocos

    expected, _ = read_wav_channels(single)
    got, _ = read_wav_channels(blocked)
    assert got.shape == expected.shape == (14 * MIX_RATE, 2)
    assert np.abs(got - expected).max() <= ONE_STEP
    assert np.sqrt((expected**2).mean()) > 0.1  # o teste não compara silêncio com silêncio


def test_the_stems_assembled_in_blocks_match_the_single_command(tmp_path: Path):
    clips = dub_clips(tmp_path / "falas", 30, spacing=0.37, seconds=0.9)
    bg = background(tmp_path / "fundo.wav", 14.0)
    runner = SubprocessRunner(quiet=True)
    results: dict[str, np.ndarray] = {}
    for name, limit in (("unico", 1000), ("blocos", 4)):
        folder = tmp_path / name
        folder.mkdir()
        outputs = StemOutputs(folder / "voz-dublada.wav", folder / "fundo.wav", folder / "voz-original.wav")
        graph_file = tmp_path / f"{name}.graph.txt"
        with block_workspace(tmp_path / "cache") as work:
            reduction = premix_dub_clips(clips, work, limit)
            built = dub_stems_command(bg, bg, reduction.items, outputs, graph_file, 14.0)
            run_steps(runner, reduction.steps)
            graph_file.write_text(built.graph, encoding="utf-8")
            runner.run(built.command)
        results[name] = read_wav_channels(outputs.voice_dubbed)[0]
    assert results["blocos"].shape == results["unico"].shape == (14 * MIX_RATE, 2)
    assert np.abs(results["blocos"] - results["unico"]).max() <= ONE_STEP


def test_a_dubbing_of_200_clips_mixes_each_one_at_its_position(tmp_path: Path):
    """200 falas de 0,1 s, uma a cada 0,2 s, num fundo mudo de 40 s: cada fala toca na sua janela e só nela."""
    clips = dub_clips(tmp_path / "falas", 200, spacing=0.2, seconds=0.1)
    silent_background = write_wav(tmp_path / "fundo.wav", np.zeros(40 * MIX_RATE, dtype=np.float32), MIX_RATE)
    out = tmp_path / "dublado.wav"

    run_mix(tmp_path, clips, silent_background, out, 40.0)

    mixed, rate = read_wav_channels(out)
    assert rate == MIX_RATE and mixed.shape == (40 * MIX_RATE, 2)
    voice = np.abs(mixed[:, 0])

    def level(start: float, end: float) -> float:
        return float(voice[int(start * rate) : int(end * rate)].max())

    for index in (0, 1, 137, 199):
        start = index * 0.2
        assert level(start + 0.02, start + 0.07) > 0.05  # a fala toca na janela dela
        assert level(start + 0.12, start + 0.18) < 0.001  # e o intervalo até a próxima está mudo
    assert level(39.95, 40.0) < 0.001  # depois da última fala o arquivo segue mudo até o fim do fundo
    assert list((tmp_path / "cache").iterdir()) == []
