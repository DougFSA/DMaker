"""Comandos ffmpeg da regravação de fala: a emenda com crossfade, o ganho, o remux e a referência."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.filtergraph.speech_edit import (
    corrected_suffix,
    speaker_reference_command,
    speech_splice_command,
    speech_splice_graph,
)
from dmaker.voice.speech_edit import plan_splice


@pytest.fixture
def plan():
    return plan_splice(11.7, 12.9, "de João e Maria", "de Pedro e Maria", 0.6, 1.1)


def graph_lines(graph: str) -> list[str]:
    return graph.split(";")


def test_graph_crossfades_both_seams_with_the_declared_duration(plan):
    graph = speech_splice_graph(plan, background_offset=3900.0)
    assert graph.count("acrossfade=d=0.030:c1=qsin:c2=qsin") == 2
    assert f"atrim=end={plan.region_start + 0.03:.3f}" in graph  # o original até a primeira emenda
    assert f"atrim=start={plan.region_end - 0.03:.3f}" in graph  # e a partir da segunda
    assert "[head][patch]" in graph and "[joined_head][tail]" in graph and graph.endswith("[out]")


def test_graph_patch_is_background_of_the_region_plus_the_new_speech(plan):
    graph = speech_splice_graph(plan, background_offset=11.0)
    region = plan.region_end - plan.region_start
    assert f"[1:a]atrim=start={plan.region_start - 11.0:.3f}:duration={region:.3f}" in graph
    assert "amix=inputs=2:duration=longest:normalize=0" in graph
    assert f"atrim=duration={region:.3f}" in graph


def test_graph_applies_gain_delay_and_tempo_to_the_new_speech_only(plan):
    graph = speech_splice_graph(plan, 0.0, gain_db=-3.5, tempo=1.1)
    speech_line = next(line for line in graph_lines(graph) if line.startswith("[2:a]"))
    assert "atempo=1.1000" in speech_line and "volume=-3.50dB" in speech_line
    delay_ms = round((plan.speech_start - plan.region_start) * 1000)
    assert f"adelay=delays={delay_ms}:all=1" in speech_line
    assert "atempo" not in speech_splice_graph(plan, 0.0)
    assert "volume=0.00dB" in speech_splice_graph(plan, 0.0)


def test_graph_normalizes_every_branch_to_the_same_rate_and_layout(plan):
    graph = speech_splice_graph(plan, 0.0, sample_rate=44100, layout="mono")
    assert graph.count("aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono") == 4


def test_graph_without_head_or_tail_has_no_extra_seam(plan):
    no_head = speech_splice_graph(plan, 0.0, has_head=False)
    assert no_head.count("acrossfade") == 1 and "[0:a:0]atrim=start=" in no_head and "asplit" not in no_head
    no_tail = speech_splice_graph(plan, 0.0, has_tail=False)
    assert no_tail.count("acrossfade") == 1 and "[joined_head]anull[out]" in no_tail
    neither = speech_splice_graph(plan, 0.0, has_head=False, has_tail=False)
    assert "acrossfade" not in neither and neither.endswith("[patch]anull[out]")


def test_graph_splits_the_source_once_when_it_feeds_head_and_tail(plan):
    graph = speech_splice_graph(plan, 0.0)
    assert graph.count("[0:a:0]") == 1 and "asplit=2[whole_head][whole_tail]" in graph


def test_command_for_video_copies_the_video_and_reencodes_only_the_audio(plan, tmp_path: Path):
    command = speech_splice_command(
        tmp_path / "v.mp4",
        tmp_path / "bg.wav",
        tmp_path / "fala.wav",
        tmp_path / "out.mp4",
        plan,
        background_offset=0.0,
        has_video=True,
        source_duration=60.0,
    )
    args = command.args
    assert args[:6] == [
        "-i",
        str(tmp_path / "v.mp4"),
        "-i",
        str(tmp_path / "bg.wav"),
        "-i",
        str(tmp_path / "fala.wav"),
    ]
    assert "-filter_complex" in args
    joined = " ".join(args)
    assert "-map 0:v:0 -c:v copy -map [out] -c:a aac -b:a 192k" in joined
    assert "-movflags +faststart" in joined
    assert args[-1] == str(tmp_path / "out.mp4") and command.total == 60.0


def test_command_for_audio_uses_the_codec_of_the_extension(plan, tmp_path: Path):
    wav = speech_splice_command(
        tmp_path / "a.wav", tmp_path / "bg.wav", tmp_path / "f.wav", tmp_path / "o.wav", plan, 0.0
    )
    assert "-c:a pcm_s16le" in " ".join(wav.args) and "-c:v" not in wav.args
    mp3 = speech_splice_command(
        tmp_path / "a.mp3", tmp_path / "bg.wav", tmp_path / "f.wav", tmp_path / "o.mp3", plan, 0.0
    )
    assert "libmp3lame" in mp3.args
    with pytest.raises(ValueError, match="não suportado"):
        speech_splice_command(
            tmp_path / "a.wav", tmp_path / "bg.wav", tmp_path / "f.wav", tmp_path / "o.flac", plan, 0.0
        )


def test_command_drops_the_tail_when_the_region_reaches_the_end_of_the_file(plan, tmp_path: Path):
    command = speech_splice_command(
        tmp_path / "a.wav",
        tmp_path / "bg.wav",
        tmp_path / "f.wav",
        tmp_path / "o.wav",
        plan,
        0.0,
        source_duration=plan.region_end,
    )
    graph = command.args[command.args.index("-filter_complex") + 1]
    assert graph.count("acrossfade") == 1


def test_corrected_suffix_keeps_what_ffmpeg_can_write():
    assert corrected_suffix(".MP4", True) == ".mp4"
    assert corrected_suffix(".mkv", True) == ".mkv"
    assert corrected_suffix(".webm", True) == ".mp4"
    assert corrected_suffix(".m4a", False) == ".m4a"
    assert corrected_suffix(".ogg", False) == ".wav"


def test_speaker_reference_is_cut_from_the_stem_as_mono_24k(tmp_path: Path):
    command = speaker_reference_command(tmp_path / "vocals.wav", 3.0, 11.5, tmp_path / "ref.wav")
    assert " ".join(command.args).startswith("-ss 3.000 -t 8.500 -i ")
    assert "-ac 1 -ar 24000 -c:a pcm_s16le" in " ".join(command.args)
    assert command.args[-1] == str(tmp_path / "ref.wav") and command.total == 8.5
