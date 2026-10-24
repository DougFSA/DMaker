"""Grafo e comando ffmpeg da dublagem: posições, volume, aceleração, corte, voz original e saída."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.filtergraph.dub import (
    DubClip,
    _atempo_chain,
    audio_retime_lines,
    dub_clip_lines,
    dub_mix_command,
    dub_mix_graph,
    video_retime_lines,
)
from dmaker.voice.dub_retime import IDENTITY, StretchWindow, plan_retime

CLIPS = [
    DubClip(Path("a.wav"), start=1.0, gain_db=2.5),
    DubClip(Path("b.wav"), start=4.25, gain_db=-1.0, tempo=1.1, max_seconds=2.0),
]


def graph(**options) -> str:
    defaults = {"first_clip_input": 2, "background_input": 1, "duration": 30.0}
    return dub_mix_graph(CLIPS, **{**defaults, **options})


# ---------- grafo ----------


def test_each_clip_is_delayed_to_its_position_in_milliseconds_on_all_channels():
    text = graph()
    assert "[2:a]volume=2.50dB" in text and "adelay=delays=1000:all=1[dub0]" in text
    assert "[3:a]atempo=1.1000,volume=-1.00dB" in text and "adelay=delays=4250:all=1[dub1]" in text


def test_a_clip_with_no_speedup_and_room_has_no_atempo_and_no_cut():
    first_chain = graph().split(";")[1]
    assert "atempo" not in first_chain and "atrim" not in first_chain and "afade" not in first_chain


def test_a_clip_that_did_not_fit_is_cut_with_a_short_fade_out():
    second_chain = graph().split(";")[2]
    assert "atrim=duration=2.000,afade=t=out:st=1.920:d=0.08" in second_chain
    assert second_chain.index("atempo") < second_chain.index("atrim")  # primeiro acelera, depois corta


def test_everything_is_stereo_48k_so_amix_accepts_the_inputs():
    text = graph()
    assert (
        text.count("aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo") == 3
    )  # fundo + 2 falas


def test_the_mix_sums_without_normalizing_limits_and_fixes_the_duration():
    mix = graph().split(";")[-1]
    assert mix.startswith("[background][dub0][dub1]amix=inputs=3:duration=first:normalize=0,")
    assert "alimiter=limit=0.891:level=disabled" in mix
    assert mix.endswith("apad=whole_dur=30.000,atrim=duration=30.000,asetpts=PTS-STARTPTS[out]")


def test_the_original_voice_enters_attenuated_before_the_dubbed_clips():
    text = graph(original_voice_input=3, original_voice_db=-18.0, first_clip_input=4)
    assert "[3:a]volume=-18.0dB,aresample=48000" in text and "[original]" in text
    assert "[background][original][dub0][dub1]amix=inputs=4" in text
    assert "[4:a]" in text and "[5:a]" in text


def test_no_clips_is_just_the_background():
    text = dub_mix_graph([], 2, 1, 10.0)
    assert "amix=inputs=1" in text and "[dub0]" not in text


# ---------- comando ----------


def test_video_command_copies_the_picture_and_reads_the_graph_from_a_file(tmp_path: Path):
    mix = dub_mix_command(
        Path("video.mp4"), Path("fundo.wav"), CLIPS, tmp_path / "saida.mp4", tmp_path / "g.txt", 30.0, True
    )
    args = mix.command.args
    inputs = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
    assert inputs == ["video.mp4", "fundo.wav", "a.wav", "b.wav"]
    assert args[args.index("-/filter_complex") + 1] == str(tmp_path / "g.txt")
    assert "-filter_complex" not in args  # o grafo vai em arquivo, não na linha de comando
    assert args[args.index("-c:v") + 1] == "copy" and args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-b:a") + 1] == "192k" and "+faststart" in args
    assert args[args.index("-map") + 1] == "0:v:0" and "[out]" in args
    assert args[-1] == str(tmp_path / "saida.mp4") and mix.command.total == 30.0
    assert mix.graph.startswith("[1:a]")  # o fundo é a entrada 1 (a 0 é o vídeo)
    assert "[2:a]" in mix.graph and "[3:a]" in mix.graph


def test_audio_only_command_has_no_video_input_and_encodes_by_extension(tmp_path: Path):
    mix = dub_mix_command(
        Path("a.wav"), Path("fundo.wav"), CLIPS, tmp_path / "s.mp3", tmp_path / "g.txt", 12.0, False
    )
    args = mix.command.args
    assert [args[i + 1] for i, a in enumerate(args) if a == "-i"] == ["fundo.wav", "a.wav", "b.wav"]
    assert "-c:v" not in args and "libmp3lame" in args
    assert mix.graph.startswith("[0:a]")


def test_original_voice_adds_an_input_and_shifts_the_clips(tmp_path: Path):
    mix = dub_mix_command(
        Path("v.mp4"),
        Path("fundo.wav"),
        CLIPS,
        tmp_path / "s.mp4",
        tmp_path / "g.txt",
        30.0,
        True,
        original_voice=Path("voz.wav"),
        original_voice_db=-20.0,
    )
    args = mix.command.args
    assert [args[i + 1] for i, a in enumerate(args) if a == "-i"] == [
        "v.mp4",
        "fundo.wav",
        "voz.wav",
        "a.wav",
        "b.wav",
    ]
    assert "[2:a]volume=-20.0dB" in mix.graph and "[3:a]volume=2.50dB" in mix.graph


# ---------- vídeo esticado ----------

PLAN = plan_retime([StretchWindow(10.0, 14.0, 1.25)], 30.0, fps=25.0)  # 30 s viram 31 s


def test_the_video_graph_trims_each_piece_stretches_only_the_marked_one_and_joins_them():
    lines = video_retime_lines(PLAN, video_input=0, fps=25.0)
    assert lines[0] == "[0:v]split=3[vs0][vs1][vs2]"
    assert lines[1] == "[vs0]trim=start=0.000000:end=10.000000,setpts=PTS-STARTPTS[vp0]"
    assert lines[2] == "[vs1]trim=start=10.000000:end=14.000000,setpts=(PTS-STARTPTS)*1.250000[vp1]"
    assert lines[3] == "[vs2]trim=start=14.000000:end=30.000000,setpts=PTS-STARTPTS[vp2]"
    assert lines[4].startswith("[vp0][vp1][vp2]concat=n=3:v=1:a=0,fps=25,")
    assert lines[4].endswith("trim=end=31.000000[vout]")


def test_the_frame_rate_is_an_exact_fraction_so_the_stretched_video_does_not_drift():
    ntsc = plan_retime([StretchWindow(10.0, 14.0, 1.25)], 30.0, fps=30000 / 1001)
    assert "fps=30000/1001," in video_retime_lines(ntsc, 0, 30000 / 1001)[-1]
    assert "fps=25," in video_retime_lines(PLAN, 0, 25.0)[-1]


def test_stretching_the_video_without_knowing_its_frame_rate_is_an_error():
    with pytest.raises(ValueError, match="taxa de quadros"):
        video_retime_lines(PLAN, 0, 0.0)


def test_the_audio_follows_each_piece_slowing_down_by_the_inverse_of_the_factor_without_changing_pitch():
    lines = audio_retime_lines(PLAN, "[bed]", "background")
    assert lines[0] == "[bed]asplit=3[backgrounds0][backgrounds1][backgrounds2]"
    assert lines[1] == "[backgrounds0]atrim=start=0.000000:end=10.000000,asetpts=PTS-STARTPTS[backgroundp0]"
    stretched = lines[2]
    assert "atrim=start=10.000000:end=14.000000,asetpts=PTS-STARTPTS,atempo=0.800000," in stretched
    assert stretched.endswith("apad=whole_dur=5.000000,atrim=duration=5.000000[backgroundp1]")  # 4 s * 1,25
    assert lines[-1] == "[backgroundp0][backgroundp1][backgroundp2]concat=n=3:v=0:a=1[background]"


def test_atempo_is_chained_when_the_speed_leaves_the_range_one_instance_accepts():
    assert _atempo_chain(0.8) == ["atempo=0.800000"]
    assert _atempo_chain(0.5) == ["atempo=0.500000"]
    assert _atempo_chain(0.2) == ["atempo=0.5", "atempo=0.5", "atempo=0.800000"]  # 0,5 * 0,5 * 0,8 = 0,2
    assert _atempo_chain(3.0) == ["atempo=2.0", "atempo=1.500000"]


def test_the_mix_graph_retimes_background_and_original_voice_but_not_the_dubbed_clips():
    shifted = [DubClip(Path("a.wav"), start=1.0), DubClip(Path("b.wav"), start=16.25)]
    text = dub_mix_graph(
        shifted,
        first_clip_input=3,
        background_input=1,
        duration=PLAN.total_seconds,
        original_voice_input=2,
        retime=PLAN,
        video_input=0,
        fps=25.0,
    )
    assert text.startswith("[0:v]split=3")
    assert "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[backgroundfull]" in text
    assert "[backgroundfull]asplit=3" in text and "concat=n=3:v=0:a=1[background]" in text
    assert "[2:a]volume=-18.0dB,aresample=48000" in text and "[originalfull]asplit=3" in text
    assert "concat=n=3:v=0:a=1[original]" in text
    assert "adelay=delays=16250:all=1[dub1]" in text  # a fala já vem na linha do tempo nova
    assert text.count("atempo=0.800000") == 2  # fundo e voz original; a fala dublada fica na velocidade dela
    assert "[background][original][dub0][dub1]amix=inputs=4" in text
    assert text.endswith("apad=whole_dur=31.000,atrim=duration=31.000,asetpts=PTS-STARTPTS[out]")


def test_an_identity_plan_leaves_the_graph_as_it_always_was():
    assert dub_mix_graph(CLIPS, 2, 1, 30.0, retime=IDENTITY, video_input=0, fps=25.0) == graph()


def test_the_command_reencodes_the_picture_only_when_something_was_stretched(tmp_path: Path):
    mix = dub_mix_command(
        Path("video.mp4"),
        Path("fundo.wav"),
        CLIPS,
        tmp_path / "saida.mp4",
        tmp_path / "g.txt",
        30.0,
        True,
        retime=PLAN,
        fps=25.0,
    )
    args = mix.command.args
    assert "-c:v" in args and args[args.index("-c:v") + 1] == "libx264" and "copy" not in args
    assert args[args.index("-crf") + 1] == "18" and args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[args.index("-map") + 1] == "[vout]" and "0:v:0" not in args and "[out]" in args
    assert "+faststart" in args and mix.command.total == pytest.approx(31.0)
    assert mix.graph.startswith("[0:v]split=3") and "apad=whole_dur=31.000" in mix.graph

    untouched = dub_mix_command(
        Path("video.mp4"),
        Path("fundo.wav"),
        CLIPS,
        tmp_path / "s.mp4",
        tmp_path / "g.txt",
        30.0,
        True,
        retime=IDENTITY,
        fps=25.0,
    )
    assert untouched.command.args[untouched.command.args.index("-c:v") + 1] == "copy"
    assert "[vout]" not in untouched.graph and untouched.command.total == 30.0


def test_audio_only_never_gets_a_video_stretch(tmp_path: Path):
    mix = dub_mix_command(
        Path("a.wav"),
        Path("fundo.wav"),
        CLIPS,
        tmp_path / "s.mp3",
        tmp_path / "g.txt",
        30.0,
        False,
        retime=PLAN,
        fps=25.0,
    )
    assert "[vout]" not in mix.graph and "-c:v" not in mix.command.args and mix.command.total == 30.0


def test_without_the_limiter_the_mix_is_the_pre_finish_sum_of_the_stems():
    mix = graph(limit_peaks=False).split(";")[-1]
    assert "alimiter" not in mix
    assert mix.startswith("[background][dub0][dub1]amix=inputs=3:duration=first:normalize=0,apad=")
    assert graph(limit_peaks=False).split(";")[:-1] == graph().split(";")[:-1]  # as cadeias não mudam


def test_clip_lines_are_shared_by_the_mix_and_the_stems_with_labels_in_order():
    lines, labels = dub_clip_lines(CLIPS, first_clip_input=5)
    assert labels == ["[dub0]", "[dub1]"]
    assert lines[0].startswith("[5:a]volume=2.50dB") and lines[1].startswith("[6:a]atempo=1.1000")
    assert all(line in graph(first_clip_input=5).split(";") for line in lines)
