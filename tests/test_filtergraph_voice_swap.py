"""Comando ffmpeg da troca de voz: o fundo intacto, a fala convertida com o ganho e a imagem sem recodificar."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.filtergraph.voice_swap import CUT_VIDEO_ARGS, voice_swap_command, voice_swap_graph


def test_graph_sums_background_and_converted_voice_without_halving_them():
    graph = voice_swap_graph(voice_input=2, background_input=1, duration=30.0, gain_db=-2.5)
    assert "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[background]" in graph
    assert (
        "[2:a]volume=-2.50dB,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[voice]" in graph
    )
    assert "amix=inputs=2:duration=first:normalize=0" in graph  # sem normalize=0 cada um sairia pela metade
    assert "alimiter=limit=0.891" in graph
    assert "apad=whole_dur=30.000,atrim=duration=30.000" in graph and graph.endswith("[out]")


def test_video_whole_file_copies_the_picture_and_reencodes_only_the_audio(tmp_path: Path):
    command = voice_swap_command(
        tmp_path / "v.mp4", tmp_path / "voz.wav", tmp_path / "fundo.wav", tmp_path / "o.mp4", 30.0, -1.0, True
    )
    args = command.args
    assert args[:2] == ["-i", str(tmp_path / "v.mp4")] and "-t" not in args
    assert args.index(str(tmp_path / "fundo.wav")) < args.index(str(tmp_path / "voz.wav"))
    assert "-ss" not in args
    assert ["-map", "0:v:0", "-c:v", "copy", "-map", "[out]", "-c:a", "aac"] == args[
        args.index("-map") : args.index("-map") + 8
    ]
    assert "+faststart" in args and args[-1] == str(tmp_path / "o.mp4")
    assert "[2:a]" in command.args[command.args.index("-filter_complex") + 1]  # a fala é a terceira entrada
    assert command.total == 30.0 and command.label == "troca de voz"


def test_video_excerpt_is_cut_and_reencoded_so_picture_and_voice_start_together(tmp_path: Path):
    command = voice_swap_command(
        tmp_path / "v.mp4",
        tmp_path / "voz.wav",
        tmp_path / "fundo.wav",
        tmp_path / "o.mp4",
        20.0,
        0.0,
        True,
        12.5,
    )
    args = command.args
    assert args[:6] == ["-ss", "12.500", "-t", "20.000", "-i", str(tmp_path / "v.mp4")]
    assert all(token in args for token in CUT_VIDEO_ARGS)
    assert "copy" not in args


def test_excerpt_from_the_very_start_still_reencodes(tmp_path: Path):
    command = voice_swap_command(
        tmp_path / "v.mp4",
        tmp_path / "voz.wav",
        tmp_path / "fundo.wav",
        tmp_path / "o.mp4",
        20.0,
        0.0,
        True,
        0.0,
    )
    assert (
        "copy" not in command.args and "-ss" not in command.args
    )  # 0 s: nada a pular, mas o fim foi cortado
    assert command.args[:4] == ["-t", "20.000", "-i", str(tmp_path / "v.mp4")]


@pytest.mark.parametrize(
    ("suffix", "codec"), [(".wav", "pcm_s16le"), (".mp3", "libmp3lame"), (".m4a", "aac")]
)
def test_audio_only_source_has_no_video_inputs_and_uses_the_format_codec(
    tmp_path: Path, suffix: str, codec: str
):
    command = voice_swap_command(
        tmp_path / "a.wav", tmp_path / "voz.wav", tmp_path / "fundo.wav", tmp_path / f"o{suffix}", 10.0
    )
    args = command.args
    assert (
        args.count("-i") == 2 and str(tmp_path / "a.wav") not in args
    )  # o original não entra: só fundo e fala
    assert "0:v:0" not in args and codec in args
    assert "[1:a]" in args[args.index("-filter_complex") + 1]


def test_unsupported_audio_format_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="não suportado"):
        voice_swap_command(
            tmp_path / "a.wav", tmp_path / "v.wav", tmp_path / "f.wav", tmp_path / "o.ogg", 5.0
        )
