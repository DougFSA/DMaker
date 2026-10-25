"""Grafo e comando de montagem da narração (puros)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.filtergraph.voice import (
    BROADCAST_MASTER_FILTERS,
    SpeechFinish,
    narration_concat_command,
    narration_concat_graph,
    speech_finish_command,
    speech_finish_filters,
)


def test_graph_pads_each_part_with_its_pause_and_concatenates():
    graph = narration_concat_graph([0.35, 0.0, 0.7])
    assert (
        "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,apad=pad_dur=0.350[p0]" in graph
    )
    assert (
        "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono[p1]" in graph
    )  # sem pausa, sem apad
    assert "apad=pad_dur=0.700[p2]" in graph
    assert "[p0][p1][p2]concat=n=3:v=0:a=1[out]" in graph
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


def test_concatenation_is_always_dry_the_finish_is_per_utterance_before_the_watermark():
    graph = narration_concat_graph([0.5, 0.0])
    assert graph.endswith("concat=n=2:v=0:a=1[out]")
    for filter_name in ("acompressor", "alimiter", "highpass", "bass", "treble"):
        assert filter_name not in graph
    args = narration_concat_command([(Path("a.wav"), 0.0)], Path("o.wav")).args
    assert "acompressor" not in args[args.index("-filter_complex") + 1]


def test_broadcast_finish_has_the_voicestudio_chain_in_order():
    chain = ",".join(speech_finish_filters(SpeechFinish(broadcast=True)))
    for expected in (
        "highpass=f=60",
        "acompressor=threshold=-15dB:ratio=1.5:attack=2:release=100",
        "highpass=f=80",
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=80",
        "bass=g=1.5",
        "treble=g=2",
        "alimiter=limit=0.891:level=disabled",
    ):
        assert expected in chain
    assert chain.index("highpass=f=60") < chain.index("highpass=f=80") < chain.index("alimiter")
    assert speech_finish_filters(SpeechFinish(broadcast=True)) == list(BROADCAST_MASTER_FILTERS)


def test_tempo_finish_speeds_up_first_and_the_broadcast_chain_closes_the_speech():
    filters = speech_finish_filters(SpeechFinish(broadcast=True, tempo=1.15))
    assert filters[0] == "atempo=1.150000" and filters[1:] == list(BROADCAST_MASTER_FILTERS)
    assert speech_finish_filters(SpeechFinish(tempo=0.9)) == ["atempo=0.900000"]


def test_a_plain_finish_has_no_filters_and_no_cache_tag():
    plain = SpeechFinish()
    assert plain.is_plain and plain.cache_tag == "" and speech_finish_filters(plain) == []
    assert SpeechFinish(tempo=1.00001).is_plain  # diferença abaixo do que o atempo resolve


def test_the_cache_tag_tells_apart_with_and_without_finish_and_each_tempo():
    tags = {
        SpeechFinish().cache_tag,
        SpeechFinish(broadcast=True).cache_tag,
        SpeechFinish(tempo=1.15).cache_tag,
        SpeechFinish(tempo=1.1).cache_tag,
        SpeechFinish(broadcast=True, tempo=1.15).cache_tag,
    }
    assert len(tags) == 5


def test_finish_command_writes_mono_16_bit_wav_keeping_the_rate():
    command = speech_finish_command(Path("fala.wav"), Path("pronta.wav"), SpeechFinish(tempo=1.15))
    args = command.args
    assert args[:2] == ["-i", "fala.wav"] and args[-1] == "pronta.wav"
    assert args[args.index("-af") + 1] == "atempo=1.150000"
    assert args[args.index("-ac") + 1] == "1" and args[args.index("-c:a") + 1] == "pcm_s16le"
    assert "-ar" not in args
