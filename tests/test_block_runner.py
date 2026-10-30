"""Execução da montagem em blocos: grafo gravado antes do comando, pasta temporária que some e o ffmpeg só gravado."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.filtergraph.blocks import MAX_INPUTS, GraphStep
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.wavio import write_wav
from dmaker.pipeline.block_runner import block_workspace, run_steps
from dmaker.pipeline.narration import NarrationService, concat_narration

from .conftest import WINDOWS_LINE_LIMIT, command_line_length, fake_ffmpeg_output


def final_inputs(args: list[str]) -> list[Path]:
    return [Path(args[index + 1]) for index, arg in enumerate(args) if arg == "-i"]


def test_the_workspace_is_a_fresh_folder_inside_the_parent_and_goes_away(tmp_path: Path):
    with block_workspace(tmp_path / "cache") as first, block_workspace(tmp_path / "cache") as second:
        assert first != second and first.parent == second.parent == tmp_path / "cache"
        (first / "bloco.wav").write_bytes(b"x")
    assert not first.exists() and not second.exists()
    assert list((tmp_path / "cache").iterdir()) == []


def test_the_workspace_goes_away_even_when_the_assembly_fails(tmp_path: Path):
    with pytest.raises(RuntimeError, match="ffmpeg caiu"), block_workspace(tmp_path) as folder:
        (folder / "bloco.wav").write_bytes(b"x")
        raise RuntimeError("ffmpeg caiu")
    assert list(tmp_path.iterdir()) == []


def test_each_graph_file_is_written_just_before_its_command_runs_and_in_order(tmp_path: Path):
    first, second = tmp_path / "sub" / "a.graph.txt", tmp_path / "b.graph.txt"
    seen: list[tuple[str, str | None]] = []

    def on_run(command: FFmpegCommand) -> None:
        args = command.args
        graph_file = Path(args[args.index("-/filter_complex") + 1]) if "-/filter_complex" in args else None
        seen.append((command.label, graph_file.read_text(encoding="utf-8") if graph_file else None))

    steps = [
        GraphStep(FFmpegCommand(["-/filter_complex", str(first)], label="um"), "grafo um", first),
        GraphStep(FFmpegCommand(["-/filter_complex", str(second)], label="dois"), "grafo dois", second),
        GraphStep(FFmpegCommand(["-filter_complex", "grafo inline"], label="inline")),
    ]
    run_steps(RecordingRunner(on_run=on_run), steps)
    assert seen == [("um", "grafo um"), ("dois", "grafo dois"), ("inline", None)]


def tiny_wavs(folder: Path, count: int) -> list[tuple[Path, float]]:
    tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(240) / 24000)).astype(np.float32)
    folder.mkdir(parents=True, exist_ok=True)
    return [
        (write_wav(folder / f"fala-{i:05d}.wav", tone, 24000), 0.1 if i % 4 == 0 else 0.0)
        for i in range(count)
    ]


def test_a_short_narration_runs_one_plain_command_and_leaves_no_folder_behind(tmp_path: Path):
    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    parts = tiny_wavs(tmp_path / "falas", MAX_INPUTS)
    concat_narration(runner, tmp_path / "cache", parts, tmp_path / "saida" / "n.wav")
    (command,) = runner.commands
    assert "-filter_complex" in command and "-/filter_complex" not in command
    assert list((tmp_path / "cache").iterdir()) == []


def test_a_long_narration_runs_the_blocks_first_then_one_command_that_joins_them(tmp_path: Path):
    seen_inputs: list[list[Path]] = []

    def on_run(command: FFmpegCommand) -> None:
        seen_inputs.append(final_inputs(command.args))
        assert all(path.exists() for path in seen_inputs[-1])  # todo bloco já existe quando o seguinte o lê
        fake_ffmpeg_output(command)

    runner = RecordingRunner(on_run=on_run)
    parts = tiny_wavs(tmp_path / "falas", 1200)
    out = tmp_path / "saida" / "capitulo.wav"
    concat_narration(
        runner, tmp_path / "cache", parts, out, total=70.0, provenance="DMaker: voz gerada por IA (v1)"
    )

    *blocks, final = runner.commands
    assert len(blocks) == 19 and all("-/filter_complex" in c for c in blocks)
    assert max(command_line_length(c) for c in runner.commands) < WINDOWS_LINE_LIMIT
    assert final[-1] == str(out) and "-filter_complex" in final
    assert "DMaker: voz gerada por IA (v1)" in " ".join(final)
    assert len(final_inputs(final)) == 19 and all("montagem-" in str(p) for p in final_inputs(final))
    assert list((tmp_path / "cache").iterdir()) == []  # intermediários e grafos sumiram


def test_the_narration_service_assembles_a_chapter_of_hundreds_of_speeches_in_blocks(tmp_path: Path):
    from .test_narration import FakeSynthesizer

    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    service = NarrationService(FakeSynthesizer(), runner, tmp_path / "cache")
    text = " ".join(f"Esta é a fala número {i} do capítulo." for i in range(300))

    result = service.render(text, tmp_path / "saida" / "capitulo.wav", voice=None)

    assert len(result.cues) == 300
    blocks = [c for c in runner.commands if "-/filter_complex" in c]
    assert len(blocks) == 5  # 300 falas em blocos de 60
    assert max(command_line_length(c) for c in runner.commands) < WINDOWS_LINE_LIMIT
    assert runner.commands[-1][-1] == str(tmp_path / "saida" / "capitulo.wav")
    assert [p for p in (tmp_path / "cache").iterdir() if p.is_dir()] == []
