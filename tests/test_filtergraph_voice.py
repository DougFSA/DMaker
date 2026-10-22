"""Grafo e comando de montagem da narração (puros)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.filtergraph.voice import narration_concat_command, narration_concat_graph


def test_graph_pads_each_part_with_its_pause_and_concatenates():
    graph = narration_concat_graph([0.35, 0.0, 0.7])
    assert (
        "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,apad=pad_dur=0.350[p0]" in graph
    )
    assert (
        "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono[p1]" in graph
    )  # sem pausa, sem apad
    assert "apad=pad_dur=0.700[p2]" in graph
    assert "[p0][p1][p2]concat=n=3:v=0:a=1[joined]" in graph
    assert graph.endswith("[out]")


def test_graph_requires_at_least_one_part():
    with pytest.raises(ValueError):
        narration_concat_graph([])


def test_command_lists_inputs_in_order_and_maps_output():
    parts = [(Path("a.wav"), 0.5), (Path("b.wav"), 0.0)]
    command = narration_concat_command(parts, Path("out.wav"))
    args = command.args
    assert args[:4] == ["-i", "a.wav", "-i", "b.wav"]
    assert args[args.index("-map") + 1] == "[out]"
    assert args[args.index("-c:a") + 1] == "pcm_s16le"
    assert args[-1] == "out.wav"


@pytest.mark.parametrize(
    "name, codec", [("saida.mp3", "libmp3lame"), ("saida.m4a", "aac"), ("SAIDA.WAV", "pcm_s16le")]
)
def test_command_picks_codec_from_extension(name, codec):
    args = narration_concat_command([(Path("a.wav"), 0.0)], Path(name)).args
    assert args[args.index("-c:a") + 1] == codec


def test_unknown_extension_is_rejected():
    with pytest.raises(ValueError, match=r"\.ogg"):
        narration_concat_command([(Path("a.wav"), 0.0)], Path("saida.ogg"))


def test_graph_masters_the_voice_with_the_voicestudio_broadcast_chain():
    graph = narration_concat_graph([0.0])
    mastering = graph.split("[joined]")[-1]
    for expected in (
        "highpass=f=60",
        "acompressor=threshold=-15dB:ratio=1.5:attack=2:release=100",
        "highpass=f=80",
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=80",
        "bass=g=1.5",
        "treble=g=2",
        "alimiter=limit=0.891:level=disabled",
    ):
        assert expected in mastering
    assert mastering.index("highpass=f=60") < mastering.index("highpass=f=80") < mastering.index("alimiter")


def test_graph_without_master_leaves_the_voice_raw():
    graph = narration_concat_graph([0.5, 0.0], master=False)
    assert graph.endswith("concat=n=2:v=0:a=1[out]") and "acompressor" not in graph
    args = narration_concat_command([(Path("a.wav"), 0.0)], Path("o.wav"), master=False).args
    assert "acompressor" not in args[args.index("-filter_complex") + 1]
