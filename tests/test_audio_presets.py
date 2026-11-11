"""Presets de saída só de áudio: o catálogo, a resolução das opções, os alvos de loudness e as etiquetas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmaker.domain.audio_metadata import ffmpeg_tags, merge_metadata
from dmaker.domain.audio_presets import (
    AUDIO_PRESETS,
    AudioFormatError,
    AudioPreset,
    EncodingChoices,
    get_audio_preset,
    is_audio_preset,
    register_audio_preset,
    resolve_encoding,
)
from dmaker.domain.loudness import LOUDNESS_TARGETS, parse_loudness_target
from dmaker.domain.outputs import frame_preset, output_kind, resolve_output
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import Project

FORMATS = ("wav", "mp3", "flac", "ogg", "opus", "m4a", "aiff")


def test_every_audio_format_of_the_card_is_registered():
    assert {preset.format for preset in AUDIO_PRESETS.values()} >= set(FORMATS)
    assert all(preset.id == f"audio/{preset.format}" for preset in AUDIO_PRESETS.values())


@pytest.mark.parametrize("alias", ["mp3", "MP3", "audio/mp3", " audio/MP3 "])
def test_a_format_is_found_by_id_or_by_alias(alias):
    assert get_audio_preset(alias).id == "audio/mp3"
    assert is_audio_preset(alias)


def test_a_video_preset_is_not_an_audio_preset_and_the_other_way_around():
    assert not is_audio_preset("instagram/reels") and not is_audio_preset(None) and not is_audio_preset("")
    assert output_kind("youtube/shorts") == "video" and output_kind("audio/flac") == "audio"
    with pytest.raises(KeyError, match="preset de áudio"):
        get_preset("audio/mp3")  # o preset de vídeo recusa o de áudio com uma mensagem que explica


def test_resolve_output_returns_the_right_type_and_lists_the_options_on_a_miss():
    assert resolve_output("instagram/reels").width == 1080
    assert resolve_output("wav").extension == ".wav"
    with pytest.raises(KeyError, match="Opções"):
        resolve_output("nao-existe")


def test_the_frame_stand_in_never_leaks_an_audio_preset_into_the_picture_maths():
    assert frame_preset("audio/mp3").width > 0
    assert frame_preset("instagram/reels").id == "instagram/reels"


def test_the_defaults_are_the_ones_of_the_audacity_export_window():
    assert resolve_encoding(get_audio_preset("wav")).bit_depth == 16
    mp3 = resolve_encoding(get_audio_preset("mp3"))
    assert (mp3.bitrate_mode, mp3.bitrate_k, mp3.sample_rate, mp3.channels) == ("cbr", 192, 48000, 2)
    assert resolve_encoding(get_audio_preset("ogg")).quality == 5
    assert resolve_encoding(get_audio_preset("flac")).bit_depth == 16


def test_choices_override_the_defaults_and_unset_ones_keep_them():
    encoding = resolve_encoding(get_audio_preset("wav"), EncodingChoices(sample_rate=44100, bit_depth=24))
    assert (encoding.sample_rate, encoding.bit_depth, encoding.channels) == (44100, 24, 2)
    mono = resolve_encoding(
        get_audio_preset("mp3"), EncodingChoices(channels=1, bitrate_mode="abr", bitrate_k=96)
    )
    assert (mono.channels, mono.bitrate_mode, mono.bitrate_k) == (1, "abr", 96)


@pytest.mark.parametrize(
    ("name", "choices", "message"),
    [
        ("mp3", EncodingChoices(bit_depth=24), "formato com perda"),
        ("wav", EncodingChoices(bitrate_k=128), "sem perda"),
        ("flac", EncodingChoices(bit_depth=32), "16, 24"),
        ("opus", EncodingChoices(sample_rate=44100), "taxas de amostragem"),
        ("m4a", EncodingChoices(bitrate_mode="vbr"), "modos de taxa de bits"),
        ("mp3", EncodingChoices(quality=15), "qualidade"),
        ("wav", EncodingChoices(channels=1), None),
    ],
)
def test_an_option_the_format_cannot_honour_is_refused_not_ignored(name, choices, message):
    if message is None:
        assert resolve_encoding(get_audio_preset(name), choices).channels == 1
        return
    with pytest.raises(AudioFormatError, match=message):
        resolve_encoding(get_audio_preset(name), choices)


def test_a_new_format_enters_by_registration_without_touching_the_others():
    extra = AudioPreset(
        "audio/test-tta",
        "TTA",
        "test-tta",
        ".tta",
        "tta",
        "vorbis",
        lossless=True,
        bit_depths=(16,),
        bit_depth=16,
    )
    try:
        register_audio_preset(extra)
        assert get_audio_preset("audio/test-tta") is extra and is_audio_preset("audio/test-tta")
    finally:
        AUDIO_PRESETS.pop("audio/test-tta", None)
    assert not is_audio_preset("audio/test-tta")
    with pytest.raises(ValueError, match="começa por"):
        register_audio_preset(AudioPreset("mp9", "x", "mp9", ".mp9", "mp9", "vorbis"))


def test_labels_for_the_screens():
    assert get_audio_preset("wav").default_label == "16 bits"
    assert get_audio_preset("mp3").default_label == "CBR 192 kbps"
    assert get_audio_preset("ogg").default_label == "VBR, qualidade 5"
    assert get_audio_preset("mp3").resolution == "48 kHz estéreo"


# ---------- na spec ----------


def _audio_spec(**output) -> dict:
    return {
        "name": "x",
        "output": {"preset": "audio/mp3", **output},
        "audio": {"voiceover": [{"src": "v.wav"}]},
    }


def test_a_project_with_an_audio_output_may_have_no_video_segments():
    project = Project.model_validate(_audio_spec())
    assert project.timeline == []


def test_a_video_output_still_needs_at_least_one_segment():
    with pytest.raises(ValidationError, match="timeline precisa de pelo menos um trecho"):
        Project.model_validate({"name": "x", "output": {"preset": "instagram/reels"}})


def test_the_audio_format_of_the_spec_is_checked_against_the_preset():
    ok = Project.model_validate(_audio_spec(audio_format={"bitrate_k": 128, "bitrate_mode": "abr"}))
    assert ok.output.audio_format.bitrate_k == 128
    with pytest.raises(ValidationError, match="output.audio_format"):
        Project.model_validate(_audio_spec(audio_format={"bit_depth": 24}))


def test_an_old_spec_is_saved_byte_for_byte_without_the_new_fields():
    project = Project.model_validate(
        {"name": "old", "timeline": [{"type": "card", "title": "t", "duration": 1}]}
    )
    text = project.to_bytes().decode("utf-8")
    assert "audio_format" not in text and "metadata" not in text and "markers" not in text


def test_metadata_numbers_become_text():
    project = Project.model_validate(_audio_spec(metadata={"track": 3, "year": 2026, "title": "T"}))
    assert (project.output.metadata.track, project.output.metadata.year) == ("3", "2026")


# ---------- alvos de loudness ----------


@pytest.mark.parametrize(
    ("value", "lufs"),
    [
        ("redes", -14),
        ("podcast", -16),
        ("broadcast", -23),
        ("EBU", -23),
        ("-16", -16),
        (-14, -14),
        ("-16 LUFS", -16),
        ("-16,5", -16.5),
    ],
)
def test_loudness_targets_by_name_or_number(value, lufs):
    assert parse_loudness_target(value) == pytest.approx(lufs)


def test_the_three_usual_targets_are_offered():
    assert LOUDNESS_TARGETS == {"redes": -14.0, "podcast": -16.0, "broadcast": -23.0}


@pytest.mark.parametrize("value", ["alto", "-3", -40, True])
def test_an_unknown_or_out_of_range_target_is_refused_with_the_options(value):
    with pytest.raises(ValueError):
        parse_loudness_target(value)


# ---------- etiquetas ----------


def test_the_spec_tags_win_over_the_brand_template_and_an_empty_one_erases():
    template = {"artist": "Marca", "album": "Temporada 1", "comment": "da marca", "outra": "ignorada"}
    merged = merge_metadata(template, {"artist": "Episódio", "comment": "", "title": "T", "genre": None})
    assert merged == {"artist": "Episódio", "album": "Temporada 1", "title": "T"}


def test_each_format_stores_the_tags_in_its_own_way_and_aiff_keeps_only_three():
    tags = {
        "artist": "A",
        "title": "T",
        "album": "L",
        "track": "3",
        "year": "2026",
        "genre": "G",
        "comment": "C",
    }
    pairs, ignored = ffmpeg_tags(get_audio_preset("mp3"), tags)
    assert pairs == [
        ("artist", "A"),
        ("title", "T"),
        ("album", "L"),
        ("track", "3"),
        ("date", "2026"),
        ("genre", "G"),
        ("comment", "C"),
    ]
    assert ignored == []
    aiff, lost = ffmpeg_tags(get_audio_preset("aiff"), tags)
    assert aiff == [("author", "A"), ("title", "T"), ("comment", "C")]
    assert lost == ["álbum", "faixa", "ano", "gênero"]
