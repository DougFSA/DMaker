"""Grafo e comando das trilhas separadas da dublagem: entradas, mesmas cadeias da mixagem, duração e formato."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.filtergraph.dub import DubClip, dub_mix_graph
from dmaker.filtergraph.dub_stems import StemOutputs, dub_stems_command, dub_stems_graph

CLIPS = [
    DubClip(Path("a.wav"), start=1.0, gain_db=2.5),
    DubClip(Path("b.wav"), start=4.25, gain_db=-1.0, tempo=1.1, max_seconds=2.0),
]
OUTPUTS = StemOutputs(Path("t/voz-dublada.wav"), Path("t/fundo.wav"), Path("t/voz-original.wav"))


def test_the_dubbed_voice_uses_the_same_clip_chains_as_the_video_mix():
    stems = dub_stems_graph(CLIPS, 30.0).split(";")
    mix = dub_mix_graph(CLIPS, first_clip_input=2, background_input=0, duration=30.0).split(";")
    assert [line for line in mix if "[dub" in line and "amix" not in line] == stems[2:4]


def test_voice_is_summed_without_normalizing_and_following_the_longest_clip():
    voice = dub_stems_graph(CLIPS, 30.0).split(";")[-1]
    assert voice.startswith("[dub0][dub1]amix=inputs=2:duration=longest:normalize=0,")
    assert voice.endswith("[voice]")


def test_every_track_has_the_video_duration_starting_at_zero_and_no_finishing():
    graph = dub_stems_graph(CLIPS, 30.04)  # 1.441.920 quadros de áudio a 48 kHz
    assert graph.count("apad=whole_len=1441920,atrim=end_sample=1441920,asetpts=PTS-STARTPTS") == 3
    assert "alimiter" not in graph and "loudnorm" not in graph


def test_background_and_original_voice_are_stereo_48k_without_gain():
    background, original = dub_stems_graph(CLIPS, 30.0).split(";")[:2]
    assert background.startswith("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad")
    assert original.startswith("[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad")
    assert "volume" not in background and "volume" not in original


def test_command_writes_three_pcm_wavs_in_one_pass_with_the_graph_in_a_file():
    built = dub_stems_command(Path("bg.wav"), Path("vo.wav"), CLIPS, OUTPUTS, Path("g.txt"), 30.0)
    args = built.command.args
    assert [args[i + 1] for i, a in enumerate(args) if a == "-i"] == ["bg.wav", "vo.wav", "a.wav", "b.wav"]
    assert args[args.index("-/filter_complex") + 1] == "g.txt"
    assert [args[i + 1] for i, a in enumerate(args) if a == "-map"] == [
        "[voice]",
        "[background]",
        "[original]",
    ]
    assert args.count("pcm_s16le") == 3 and args.count("48000") == 3 and args.count("2") == 3
    written = [
        a
        for a in args
        if a in {str(p) for p in (OUTPUTS.voice_dubbed, OUTPUTS.background, OUTPUTS.voice_original)}
    ]
    assert written == [str(OUTPUTS.voice_dubbed), str(OUTPUTS.background), str(OUTPUTS.voice_original)]
    assert built.command.total == 30.0 and built.command.label == "trilhas"
    assert built.graph == dub_stems_graph(CLIPS, 30.0)


def test_without_dubbed_clips_there_is_no_voice_track_to_export():
    with pytest.raises(ValueError, match="Sem falas dubladas"):
        dub_stems_command(Path("bg.wav"), Path("vo.wav"), [], OUTPUTS, Path("g.txt"), 30.0)


def test_a_stretched_video_retimes_background_and_original_voice_and_fixes_the_new_duration():
    from dmaker.voice.dub_retime import StretchWindow, plan_retime

    plan = plan_retime([StretchWindow(10.0, 14.0, 1.25)], 30.0, fps=25.0)  # 30 s viram 31 s
    graph = dub_stems_graph(CLIPS, plan.total_seconds, plan)
    lines = graph.split(";")
    assert any("[backgroundfull]asplit=3" in line for line in lines)
    assert any("[originalfull]asplit=3" in line for line in lines)
    assert graph.count("atempo=0.800000") == 2  # fundo e voz original; a fala dublada já vem na posição nova
    assert graph.count("apad=whole_len=1488000,atrim=end_sample=1488000") == 3  # 31 s a 48 kHz
    assert dub_stems_graph(CLIPS, 30.0, None) == dub_stems_graph(CLIPS, 30.0)


def test_the_command_takes_the_duration_of_the_retime_plan():
    from dmaker.voice.dub_retime import IDENTITY, StretchWindow, plan_retime

    plan = plan_retime([StretchWindow(10.0, 14.0, 1.25)], 30.0, fps=25.0)
    built = dub_stems_command(Path("bg.wav"), Path("vo.wav"), CLIPS, OUTPUTS, Path("g.txt"), 30.0, plan)
    assert built.command.total == pytest.approx(31.0) and "whole_len=1488000" in built.graph
    same = dub_stems_command(Path("bg.wav"), Path("vo.wav"), CLIPS, OUTPUTS, Path("g.txt"), 30.0, IDENTITY)
    assert same.command.total == 30.0 and "full]" not in same.graph
