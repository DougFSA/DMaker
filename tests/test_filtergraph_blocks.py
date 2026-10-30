"""Montagem em blocos: o plano é puro e nenhum comando passa do limite da linha de comando do Windows."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dmaker.filtergraph.blocks import (
    MAX_INPUTS,
    BlockSlot,
    GraphStep,
    reduce_in_blocks,
    split_evenly,
)
from dmaker.filtergraph.dub import DubClip, dub_mix_command
from dmaker.filtergraph.dub_blocks import dub_block_step, premix_dub_clips
from dmaker.filtergraph.dub_stems import StemOutputs, dub_stems_command
from dmaker.filtergraph.voice import (
    narration_block_step,
    narration_concat_command,
    narration_concat_graph,
    narration_concat_plan,
)
from dmaker.media.ffmpeg import FFmpegCommand
from dmaker.voice.watermark import delay_on_detector_grid

from .conftest import WINDOWS_LINE_LIMIT, command_line_length

# O pior caso de verdade: todo arquivo num caminho do tamanho do MAX_PATH do Windows (260).
WORK = Path("C:\\" + "w" * 235 + "\\montagem")


def long_path(index: int) -> Path:
    return Path("C:\\" + "d" * 235 + f"\\fala-{index:05d}.wav")


def line_length(command: FFmpegCommand) -> int:
    return command_line_length(command.args)


def parts_of(count: int) -> list[tuple[Path, float]]:
    return [(long_path(index), (0.0, 0.35, 0.7)[index % 3]) for index in range(count)]


def inputs_of(command: FFmpegCommand) -> list[Path]:
    args = command.args
    return [Path(args[index + 1]) for index, arg in enumerate(args) if arg == "-i"]


# ---------- divisão em blocos ----------


@pytest.mark.parametrize("count", [1, 2, 63, 64, 65, 128, 129, 1162, 5000])
def test_split_evenly_covers_every_position_once_with_no_block_over_the_limit(count):
    spans = split_evenly(count)
    assert [i for span in spans for i in span] == list(range(count))
    assert all(len(span) <= MAX_INPUTS for span in spans)
    assert max(len(s) for s in spans) - min(len(s) for s in spans) <= 1
    assert len(spans) == -(-count // MAX_INPUTS)


def test_split_evenly_never_leaves_a_block_of_one_input_to_merge_nothing():
    assert [len(span) for span in split_evenly(65)] == [33, 32]
    assert all(len(span) >= 2 for span in split_evenly(129))


def test_split_evenly_has_nothing_to_split_without_items_and_refuses_a_block_that_joins_nothing():
    assert split_evenly(0) == []
    with pytest.raises(ValueError, match="pelo menos duas"):
        split_evenly(10, limit=1)


def test_up_to_the_limit_there_is_no_block_and_the_items_come_back_untouched():
    def builder(block, slot):
        raise AssertionError("não deveria montar bloco nenhum")

    items = [f"x{i}" for i in range(MAX_INPUTS)]
    reduction = reduce_in_blocks(items, WORK, builder)
    assert reduction.steps == [] and reduction.items == items


def test_the_reduction_climbs_levels_until_the_rest_fits_and_uses_every_item_once():
    def builder(block, slot: BlockSlot):
        return GraphStep(FFmpegCommand(["-i", *block, str(slot.out)])), f"({'+'.join(block)})"

    items = [f"x{i}" for i in range(70)]
    reduction = reduce_in_blocks(items, WORK, builder, limit=4)
    assert len(reduction.items) <= 4
    assert len(reduction.steps) == 18 + 5 + 2  # 70 -> 18 -> 5 -> 2
    assert re.findall(r"x\d+", "".join(reduction.items)) == items  # cada fala uma vez, na ordem
    outputs = [Path(step.command.args[-1]) for step in reduction.steps]
    assert len(set(outputs)) == len(outputs) and all(out.parent == WORK for out in outputs)


def test_each_block_has_its_own_output_and_graph_file_and_a_label_for_the_progress():
    seen: list[BlockSlot] = []

    def builder(block, slot: BlockSlot):
        seen.append(slot)
        return GraphStep(FFmpegCommand([])), "-"

    reduce_in_blocks(list("abcdefghij"), WORK, builder, limit=3)  # 10 -> 4 blocos -> 2 blocos
    assert [slot.label for slot in seen] == [
        "bloco 1 de 4",
        "bloco 2 de 4",
        "bloco 3 de 4",
        "bloco 4 de 4",
        "junção 2: 1 de 2",
        "junção 2: 2 de 2",
    ]
    assert len({slot.out for slot in seen}) == len({slot.graph_file for slot in seen}) == len(seen)


# ---------- narração ----------


def test_a_narration_that_fits_is_one_command_identical_to_the_old_one():
    parts = parts_of(MAX_INPUTS)
    out = Path("narracao.wav")
    plan = narration_concat_plan(parts, out, WORK, total=12.5, provenance="DMaker: voz gerada por IA (v1)")
    assert plan == [
        GraphStep(
            narration_concat_command(parts, out, total=12.5, provenance="DMaker: voz gerada por IA (v1)")
        )
    ]
    assert plan[0].graph is None and plan[0].graph_file is None  # grafo inline, como sempre


def test_a_narration_block_reads_its_graph_from_a_file_and_writes_a_float_wav():
    parts = [(Path("a.wav"), 0.5), (Path("b.wav"), 0.0), (Path("c.wav"), 0.7)]
    slot = BlockSlot(Path("bloco.wav"), Path("bloco.graph.txt"), "bloco 2 de 9")
    step, produced = narration_block_step(parts, slot)
    args = step.command.args
    assert inputs_of(step.command) == [Path("a.wav"), Path("b.wav"), Path("c.wav")]
    assert args[args.index("-/filter_complex") + 1] == "bloco.graph.txt" and "-filter_complex" not in args
    assert args[args.index("-c:a") + 1] == "pcm_f32le" and args[-1] == "bloco.wav"
    assert step.graph == narration_concat_graph([0.5, 0.0, 0.7]) and step.graph_file == slot.graph_file
    assert step.command.label == "narração, bloco 2 de 9"
    # no nível seguinte o bloco é uma parte sem pausa: a pausa da última fala já está dentro dele
    assert produced == (Path("bloco.wav"), 0.0)


@pytest.mark.parametrize(
    ("count", "commands"),
    [
        (MAX_INPUTS + 1, 3),
        (160, 4),
        (1162, 20),
        (1200, 20),
        (5000, 82),
    ],  # 5000: 79 blocos, 2 junções e o final
)
def test_no_narration_command_passes_the_windows_limit_even_with_the_longest_paths(count, commands):
    plan = narration_concat_plan(parts_of(count), WORK / "narracao.m4a", WORK, provenance="x" * 200)
    assert max(line_length(step.command) for step in plan) < WINDOWS_LINE_LIMIT
    assert len(plan) == commands


def test_the_blocks_take_every_speech_once_in_order_and_the_final_command_takes_only_blocks():
    parts = parts_of(1200)
    plan = narration_concat_plan(parts, Path("narracao.wav"), WORK)
    *blocks, final = plan
    assert [path for step in blocks for path in inputs_of(step.command)] == [path for path, _ in parts]
    assert inputs_of(final.command) == [Path(step.command.args[-1]) for step in blocks]
    assert final.graph is None  # o comando final cabe inline


def test_every_pause_of_the_script_lands_in_exactly_one_block_so_the_total_is_the_same():
    parts = parts_of(300)
    plan = narration_concat_plan(parts, Path("narracao.wav"), WORK)
    *blocks, final = plan
    padded = [m for step in blocks for m in re.findall(r"apad=pad_dur=([\d.]+)", step.graph or "")]
    assert padded == [f"{pause:.3f}" for _, pause in parts if pause > 0]
    assert "apad" not in (final.command.args[final.command.args.index("-filter_complex") + 1])


def test_the_levels_chain_when_even_the_blocks_do_not_fit_one_command():
    plan = narration_concat_plan(parts_of(70), Path("narracao.wav"), WORK, limit=4)
    produced = {Path(step.command.args[-1]) for step in plan[:-1]}
    done: set[Path] = set()
    for step in plan:  # todo passo lê só falas ou blocos de passos anteriores, nunca o que ainda não existe
        assert all(path in done or path not in produced for path in inputs_of(step.command))
        done.add(Path(step.command.args[-1]))
    assert set(inputs_of(plan[-1].command)) <= produced and len(inputs_of(plan[-1].command)) <= 4


# ---------- dublagem ----------


def clips_of(count: int) -> list[DubClip]:
    """Falas espaçadas, com sobreposição, ganhos, cortes e começos em empate de arredondamento (10 ms de resto na grade)."""
    return [
        DubClip(
            long_path(index),
            start=round(index * 0.37, 2),  # nos índices ímpares cai no meio da grade de 20 ms
            gain_db=((index % 5) - 2) * 1.5,
            max_seconds=1.2 if index % 3 == 0 else None,
        )
        for index in range(count)
    ]


def test_a_few_clips_need_no_block_and_come_back_untouched():
    clips = clips_of(MAX_INPUTS)
    reduction = premix_dub_clips(clips, WORK)
    assert reduction.steps == [] and reduction.items == clips


def test_a_dub_block_sums_its_clips_with_the_same_chains_and_writes_a_float_wav():
    slot = BlockSlot(Path("bloco.wav"), Path("bloco.graph.txt"), "bloco 1 de 2")
    clips = [DubClip(Path("a.wav"), 10.0, 2.0), DubClip(Path("b.wav"), 10.5, -1.0, max_seconds=0.8)]
    step, produced = dub_block_step(clips, slot)
    assert step.graph == ";".join(
        [
            "[0:a]volume=2.00dB,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            "adelay=delays=0:all=1[dub0]",
            "[1:a]volume=-1.00dB,atrim=duration=0.800,afade=t=out:st=0.720:d=0.08,"
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay=delays=500:all=1[dub1]",
            "[dub0][dub1]amix=inputs=2:duration=longest:normalize=0[out]",
        ]
    )
    args = step.command.args
    assert args[args.index("-c:a") + 1] == "pcm_f32le" and args[-1] == "bloco.wav"
    assert inputs_of(step.command) == [Path("a.wav"), Path("b.wav")]
    # a fala que o bloco devolve começa onde a primeira começava, sem ganho nem corte (já estão dentro dele)
    assert produced == DubClip(Path("bloco.wav"), start=10.0)


def absolute_delays(reduction) -> dict[Path, int]:
    """Atraso (ms) de cada fala original no arquivo, somando o de cada bloco por onde ela passa."""
    by_output = {Path(step.command.args[-1]): step for step in reduction.steps}

    def walk(path: Path, offset: int, found: dict[Path, int]) -> None:
        step = by_output.get(path)
        if step is None:
            found[path] = offset
            return
        local = {
            int(m.group(1)): int(m.group(2))
            for m in re.finditer(r"\[(\d+):a\][^;]*?adelay=delays=(\d+):all=1", step.graph or "")
        }
        for index, source in enumerate(inputs_of(step.command)):
            walk(source, offset + local[index], found)

    found: dict[Path, int] = {}
    for item in reduction.items:
        walk(item.path, delay_on_detector_grid(item.start), found)
    return found


@pytest.mark.parametrize(("count", "limit"), [(200, MAX_INPUTS), (50, 4), (1162, MAX_INPUTS)])
def test_every_clip_lands_on_the_same_millisecond_it_would_alone_even_through_several_levels(count, limit):
    clips = clips_of(count)
    reduction = premix_dub_clips(clips, WORK, limit)
    assert absolute_delays(reduction) == {c.path: delay_on_detector_grid(c.start) for c in clips}
    assert len(reduction.items) <= limit


@pytest.mark.parametrize("count", [MAX_INPUTS + 1, 400, 1200, 5000])
def test_no_dub_command_passes_the_windows_limit_even_with_the_longest_paths(count):
    reduction = premix_dub_clips(clips_of(count), WORK)
    graph_file = WORK / "entrevista.en.graph.txt"
    mix = dub_mix_command(
        long_path(90001),
        long_path(90002),
        reduction.items,
        WORK / "saida.mp4",
        graph_file,
        3600.0,
        True,
        original_voice=long_path(90003),
        provenance="x" * 200,
    )
    outputs = StemOutputs(long_path(90004), long_path(90005), long_path(90006))
    stems = dub_stems_command(
        long_path(90002), long_path(90003), reduction.items, outputs, graph_file, 3600.0, provenance="x" * 200
    )
    commands = [step.command for step in reduction.steps] + [mix.command, stems.command]
    assert max(line_length(command) for command in commands) < WINDOWS_LINE_LIMIT


def test_the_mix_and_the_stems_read_the_blocks_as_if_they_were_clips():
    reduction = premix_dub_clips(clips_of(200), WORK)
    assert len(reduction.items) == 4 and all(item.gain_db == 0.0 for item in reduction.items)
    mix = dub_mix_command(
        Path("v.mp4"), Path("fundo.wav"), reduction.items, Path("o.mp4"), WORK / "g.txt", 90.0, True
    )
    assert "amix=inputs=5:duration=first:normalize=0" in mix.graph  # o fundo e os 4 blocos
    stems = dub_stems_command(
        Path("fundo.wav"),
        Path("voz.wav"),
        reduction.items,
        StemOutputs(Path("a.wav"), Path("b.wav"), Path("c.wav")),
        WORK / "g.txt",
        90.0,
    )
    assert "amix=inputs=4:duration=longest:normalize=0" in stems.graph
