"""Argumentos do ffmpeg para a saída só de áudio, o grafo das trilhas e a importação de áudio bruto (funções puras)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.audio_presets import EncodingChoices, get_audio_preset, resolve_encoding
from dmaker.domain.spec import AudioSettings, Music
from dmaker.filtergraph.audio import StemTaps, audio_graph, silent_base
from dmaker.filtergraph.audio_output import (
    downmix_filter,
    encode_args,
    format_filters,
    linear_normalization_applies,
    trim_filter,
)
from dmaker.filtergraph.common import Inputs
from dmaker.filtergraph.raw_import import RAW_ENCODINGS, raw_demuxer, raw_duration, raw_import_command

TAGS = [("artist", "Fulano"), ("title", "Episódio 1")]


def args_for(name: str, **choices) -> list[str]:
    encoding = resolve_encoding(get_audio_preset(name), EncodingChoices(**choices))
    return encode_args(encoding, TAGS, "saida", duration=12.5)


def pair(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


@pytest.mark.parametrize("name", ["wav", "mp3", "flac", "ogg", "opus", "m4a", "aiff"])
def test_no_audio_command_carries_video(name):
    args = args_for(name)
    assert "-vn" in args
    assert not {"-c:v", "-vcodec", "libx264", "-pix_fmt", "-r"} & set(args)
    assert pair(args, "-metadata") == "artist=Fulano" and args.count("-metadata") == 2
    assert pair(args, "-t") == "12.500000" and args[-1] == "saida"


@pytest.mark.parametrize(("depth", "codec"), [(16, "pcm_s16le"), (24, "pcm_s24le"), (32, "pcm_f32le")])
def test_wav_bit_depths_choose_the_pcm_codec(depth, codec):
    args = args_for("wav", bit_depth=depth)
    assert pair(args, "-c:a") == codec and pair(args, "-f") == "wav"


def test_aiff_is_big_endian_pcm():
    assert pair(args_for("aiff", bit_depth=24), "-c:a") == "pcm_s24be"


def test_flac_24_bits_uses_the_32_bit_sample_format():
    assert pair(args_for("flac", bit_depth=24), "-sample_fmt") == "s32"
    assert pair(args_for("flac"), "-sample_fmt") == "s16"


def test_mp3_modes_cbr_vbr_abr_and_the_id3_version():
    cbr = args_for("mp3", bitrate_k=192)
    assert (pair(cbr, "-c:a"), pair(cbr, "-b:a"), "-abr" in cbr) == ("libmp3lame", "192k", False)
    assert pair(cbr, "-id3v2_version") == "3"  # ID3v2.3
    vbr = args_for("mp3", bitrate_mode="vbr", quality=2)
    assert pair(vbr, "-q:a") == "2" and "-b:a" not in vbr
    abr = args_for("mp3", bitrate_mode="abr", bitrate_k=128)
    assert pair(abr, "-abr") == "1" and pair(abr, "-b:a") == "128k"


def test_ogg_quality_and_the_constant_rate_with_floor_and_ceiling():
    assert pair(args_for("ogg"), "-q:a") == "5"
    cbr = args_for("ogg", bitrate_mode="cbr", bitrate_k=128)
    assert (pair(cbr, "-minrate"), pair(cbr, "-maxrate"), pair(cbr, "-b:a")) == ("128k", "128k", "128k")
    abr = args_for("ogg", bitrate_mode="abr", bitrate_k=128)
    assert "-minrate" not in abr and pair(abr, "-b:a") == "128k"


@pytest.mark.parametrize(("mode", "vbr"), [("cbr", "off"), ("vbr", "on"), ("abr", "constrained")])
def test_opus_maps_the_rate_mode_to_its_vbr_option(mode, vbr):
    args = args_for("opus", bitrate_mode=mode, bitrate_k=96)
    assert (pair(args, "-c:a"), pair(args, "-b:a"), pair(args, "-vbr")) == ("libopus", "96k", vbr)


def test_m4a_is_aac_in_the_ipod_container_with_the_index_up_front():
    args = args_for("m4a")
    assert (pair(args, "-c:a"), pair(args, "-f"), pair(args, "-movflags")) == ("aac", "ipod", "+faststart")


def test_the_sample_rate_and_channels_always_reach_the_encoder():
    args = args_for("wav", sample_rate=44100, channels=1)
    assert pair(args, "-ar") == "44100" and pair(args, "-ac") == "1"


def test_16_bit_lossless_gets_dither_and_the_rest_does_not():
    wav16 = format_filters(resolve_encoding(get_audio_preset("wav")))
    assert wav16 == ["aresample=out_sample_fmt=s16:dither_method=triangular_hp"]
    assert format_filters(resolve_encoding(get_audio_preset("wav"), EncodingChoices(bit_depth=24))) == []
    assert format_filters(resolve_encoding(get_audio_preset("mp3"))) == []
    resampled = format_filters(
        resolve_encoding(get_audio_preset("wav"), EncodingChoices(sample_rate=44100, channels=1))
    )
    assert resampled[0] == downmix_filter(1) == "pan=mono|c0=0.5*c0+0.5*c1"
    assert resampled[1] == "aresample=out_sample_rate=44100:out_sample_fmt=s16:dither_method=triangular_hp"


def test_the_trim_resets_the_time_so_the_file_does_not_start_with_a_gap():
    assert trim_filter(10, 22.5) == "atrim=start=10.000000:end=22.500000,asetpts=PTS-STARTPTS"
    assert trim_filter(3, None) == "atrim=start=3.000000,asetpts=PTS-STARTPTS"


# ---------- quando o loudnorm aplica mesmo um ganho linear ----------

MEASURED = {"input_i": "-24.0", "input_tp": "-8.0", "input_lra": "4.0", "input_thresh": "-34.0"}


def test_the_linear_gain_applies_when_the_peak_fits_and_the_variation_is_small():
    # pico depois do ganho: -12 + (-16 + 24) = -4 dBTP, abaixo do teto de -1,5
    assert linear_normalization_applies({**MEASURED, "input_tp": "-12.0"}, -16)


def test_it_does_not_apply_when_the_gain_would_exceed_the_peak_ceiling():
    # pico depois do ganho: -6 + 8 = +2 dBTP, acima do teto: o loudnorm cai no modo dinâmico
    assert not linear_normalization_applies({**MEASURED, "input_tp": "-6.0"}, -16)


def test_it_does_not_apply_for_a_wide_loudness_range_or_a_constant_signal():
    assert not linear_normalization_applies({**MEASURED, "input_tp": "-12.0", "input_lra": "14.0"}, -16)
    assert not linear_normalization_applies({**MEASURED, "input_tp": "-12.0", "input_lra": "0.0"}, -16)
    assert not linear_normalization_applies({}, -16)


# ---------- o grafo das trilhas ----------


class FakeVoice:
    def __init__(self, name: str, start: float = 0.0):
        self.path, self.start, self.volume = Path(name), start, 1.0
        self.offset, self.duration = 0.0, 5.0


def build(stems: StemTaps | None, *, music: bool = True) -> list[str]:
    inputs = Inputs()
    lines: list[str] = []
    base = silent_base(lines, inputs, 20.0)
    audio = AudioSettings(music=Music(src="m.wav") if music else None)
    audio_graph(
        lines,
        inputs,
        base,
        audio,
        Path("m.wav") if music else None,
        20.0,
        narrations=[FakeVoice("n1.wav"), FakeVoice("n2.wav", 6)],
        voice_files=[FakeVoice("v.wav")],
        stems=stems,
    )
    return lines


def test_the_silent_base_is_an_input_of_the_project_length():
    inputs, lines = Inputs(), []
    assert silent_base(lines, inputs, 12.5) == "[ta_base]"
    assert inputs.args == ["-f", "lavfi", "-t", "12.500", "-i", "anullsrc=r=48000:cl=stereo"]
    assert lines == ["[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[ta_base]"]


def test_asking_for_no_stems_leaves_the_mix_graph_exactly_as_it_was():
    assert build(None) == build(StemTaps(frozenset()))
    assert not any("stem_" in line for line in build(None))


def test_each_requested_track_is_split_off_before_the_normalization():
    taps = StemTaps(frozenset({"NAR", "VO", "MUS"}))
    lines = build(taps)
    assert set(taps.labels) == {"NAR", "VO", "MUS"}
    graph = ";".join(lines)
    assert "[nar0]asplit=2[stem_NAR0_main][stem_NAR0_tap]" in graph
    assert "[stem_NAR0_tap][stem_NAR1_tap]amix=inputs=2" in graph  # as duas narrações se somam na trilha NAR
    assert "[vf0]asplit=2[stem_VO0_main][stem_VO0_tap]" in graph
    assert "[musd]asplit=2[stem_MUS_main][stem_MUS_tap]" in graph  # a música sai já abaixada pelo ducking
    assert "[voice][stem_MUS_main]amix" in graph  # e o resto da mixagem continua com a cópia principal
    # nenhuma trilha leva ganho nem normalização: o ganho único é aplicado depois, na saída de cada arquivo
    assert all("loudnorm" not in line and "volume=" not in line for line in lines if "stem_" in line)


def test_the_music_tap_also_works_without_ducking():
    taps = StemTaps(frozenset({"MUS"}))
    audio = AudioSettings(music=Music(src="m.wav", ducking=False))
    inputs, lines = Inputs(), []
    audio_graph(lines, inputs, silent_base(lines, inputs, 10.0), audio, Path("m.wav"), 10.0, stems=taps)
    graph = ";".join(lines)
    assert "[mus0]asplit=2[stem_MUS_main][stem_MUS_tap]" in graph and "[stem_MUS_main]amix" in graph


# ---------- áudio bruto ----------


@pytest.mark.parametrize(
    ("encoding", "order", "demuxer"),
    [
        ("s16", "little", "s16le"),
        ("s16", "big", "s16be"),
        ("f32", "little", "f32le"),
        ("u8", "little", "u8"),
        ("ulaw", "big", "mulaw"),
    ],
)
def test_the_raw_demuxer_comes_from_the_encoding_and_the_byte_order(encoding, order, demuxer):
    assert raw_demuxer(encoding, order) == demuxer


def test_an_unknown_encoding_or_byte_order_is_refused():
    with pytest.raises(ValueError, match="codificação desconhecida"):
        raw_demuxer("s12", "little")
    with pytest.raises(ValueError, match="ordem de bytes"):
        raw_demuxer("s16", "middle")


def test_the_raw_duration_counts_frames_after_the_offset():
    assert raw_duration(48000 * 2 * 10, "s16", 1, 48000) == 10.0  # 16 bits, mono, 48 kHz, 10 s
    assert raw_duration(48000 * 4 * 10 + 44, "s16", 2, 48000, offset_bytes=44) == 10.0
    assert raw_duration(10, "s16", 1, 48000, offset_bytes=100) == 0.0
    assert all(spec.bytes_per_sample >= 1 for spec in RAW_ENCODINGS.values())


def test_the_raw_import_command_describes_the_bytes_and_writes_a_wav_without_video():
    command = raw_import_command(
        Path("a.raw"),
        Path("a.wav"),
        encoding="s16",
        byte_order="little",
        channels=1,
        sample_rate=48000,
        offset_bytes=44,
        duration=2.5,
    )
    args = command.args
    assert args[args.index("-f") + 1] == "s16le" and args[args.index("-ar") + 1] == "48000"
    assert args.index("-skip_initial_bytes") < args.index("-i")  # opção de entrada, antes do -i
    assert args[args.index("-c:a") + 1] == "pcm_s16le" and "-vn" in args and args[-1] == "a.wav"
    assert args[args.index("-t") + 1] == "2.500000"
