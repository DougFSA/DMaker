"""A cadeia de efeitos de áudio na spec: registro, catálogo, compatibilidade com projeto antigo e edição."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmaker.domain.audio_effects import (
    EFFECT_CLASSES,
    EFFECT_TARGETS,
    active_effects,
    catalog,
    catalog_payload,
    chain_duration,
    chain_signature,
    parse_effect,
)
from dmaker.domain.audio_effects.basic import Amplify, Invert, Normalize, Repeat, Reverse
from dmaker.domain.edits import EditError
from dmaker.domain.effect_edits import apply_effect_op
from dmaker.domain.spec import (
    AudioSettings,
    AudioTrack,
    ClipSegment,
    Music,
    Narration,
    Project,
    TrackState,
    VideoOverlay,
    VoiceoverClip,
)
from dmaker.domain.tracks import apply_track_state, known_track_ids
from dmaker.pipeline.preview_audio import mix_recipe, piece_recipe
from dmaker.pipeline.segments import cache_key


def project_with(**audio) -> Project:
    return Project.model_validate(
        {
            "name": "efeitos",
            "timeline": [{"type": "clip", "src": "a.mp4", "start": 1.0, "end": 4.0, "volume": 0.8}],
            "audio": {
                "music": {"src": "m.mp3"},
                "narration": [{"text": "oi"}],
                "voiceover": [{"src": "v.wav", "start": 1.0}],
                **audio,
            },
            "overlays": [{"type": "video", "src": "p.mp4"}],
        }
    )


# ---------- registro e catálogo ----------


def test_the_basic_and_the_wave_editing_effects_are_registered():
    assert list(EFFECT_CLASSES) == [
        "amplify",
        "normalize",
        "invert",
        "reverse",
        "repeat",
        "compressor",
        "limiter",
        "noise_gate",
        "loudness_normalize",
        "silence",
        "cut",
        "envelope",
        "channels",
        "noise_reduction",
        "click_removal",
        "clip_fix",
        "repair",
    ]
    assert [info.type for info in catalog()] == list(EFFECT_CLASSES)


def test_the_catalog_tells_name_audacity_name_and_each_parameter_with_unit_range_and_default():
    by_type = {info.type: info for info in catalog()}
    amplify = by_type["amplify"]
    assert (amplify.label, amplify.audacity_name) == ("Amplificar", "Amplify")
    gain = {param.name: param for param in amplify.parameters}["gain_db"]
    assert (gain.kind, gain.unit, gain.default, gain.minimum, gain.maximum) == (
        "number",
        "dB",
        0.0,
        -100.0,
        100.0,
    )
    normalize = {param.name: param for param in by_type["normalize"].parameters}
    assert normalize["peak_db"].default == -1.0 and normalize["peak_db"].maximum == 0.0
    assert normalize["remove_dc"].kind == "boolean" and normalize["remove_dc"].default is True
    assert normalize["stereo_independent"].default is False
    assert by_type["invert"].parameters == () and by_type["reverse"].parameters == ()
    times = by_type["repeat"].parameters[0]
    assert (times.name, times.kind, times.default, times.minimum, times.maximum) == (
        "times",
        "integer",
        2,
        1,
        100,
    )
    assert by_type["repeat"].changes_duration and not amplify.changes_duration


def test_the_catalog_payload_is_json_and_lists_common_fields_and_targets():
    payload = catalog_payload()
    json.dumps(payload)  # tudo serializável: é a resposta da API e do MCP
    assert [common["name"] for common in payload["common"]] == ["enabled", "start", "end"]
    assert {target["target"] for target in payload["targets"]} == {t["target"] for t in EFFECT_TARGETS}
    assert [e["type"] for e in catalog_payload("reverse")["effects"]] == ["reverse"]
    with pytest.raises(ValueError, match="desconhecido"):
        catalog_payload("eco")


def test_an_unknown_effect_type_is_refused_in_portuguese_listing_the_known_ones():
    with pytest.raises(ValueError, match="Efeito de áudio desconhecido: 'eco'.*amplify"):
        parse_effect({"type": "eco"})
    with pytest.raises(ValidationError):
        ClipSegment(src="a.mp4", effects=[{"type": "eco"}])


def test_effect_parameters_are_validated_with_the_catalog_ranges():
    with pytest.raises(ValidationError):
        Amplify(gain_db=101)
    with pytest.raises(ValidationError):
        Normalize(peak_db=1)
    with pytest.raises(ValidationError):
        Repeat(times=0)
    with pytest.raises(ValidationError, match="end"):
        Amplify(start=2, end=1)
    with pytest.raises(ValidationError):
        Amplify(gain_db=3, nope=1)


# ---------- projeto antigo continua igual ----------

# Os valores abaixo foram calculados na `develop` ANTES de o campo `effects` existir (commit 3f77aa7): a spec sem
# efeitos tem que gerar exatamente as mesmas chaves de cache, senão o Douglas refaria todos os mezaninos.
OLD_CLIP_KEY = "f36078819fda939c"
OLD_PIECE_KEY = "9420ccbf7456cb1b"
OLD_MIX_KEY = "9f3af4b65c7b0225"


def test_a_project_without_effects_keeps_the_same_cache_keys_as_before_the_field_existed():
    segment = ClipSegment(src="a.mp4", start=1.0, end=4.0, speed=1.0, volume=0.8)
    assert cache_key(segment.model_dump(mode="json")) == OLD_CLIP_KEY
    assert cache_key(piece_recipe(segment)) == OLD_PIECE_KEY
    project = Project.model_validate(
        {
            "name": "golden",
            "timeline": [{"type": "clip", "src": "a.mp4", "start": 1.0, "end": 4.0, "volume": 0.8}],
            "audio": {
                "music": {"src": "m.mp3"},
                "tracks": [],
                "narration": [{"text": "oi"}],
                "voiceover": [{"src": "v.wav", "start": 1.0}],
            },
            "overlays": [{"type": "video", "src": "p.mp4"}],
        }
    )
    assert cache_key(mix_recipe(project)) == OLD_MIX_KEY


def test_empty_effect_lists_never_enter_the_dump_or_the_saved_spec():
    project = project_with()
    dumped = project.model_dump(mode="json")
    assert "effects" not in dumped["timeline"][0]
    assert "master_effects" not in dumped["audio"]
    for item in (dumped["audio"]["music"], dumped["audio"]["narration"][0], dumped["audio"]["voiceover"][0]):
        assert "effects" not in item
    assert "effects" not in dumped["overlays"][0]
    assert b"effects" not in project.to_bytes()


def test_a_chain_that_is_present_is_dumped_loaded_and_saved_back():
    project = project_with(
        voiceover=[{"src": "v.wav", "effects": [{"type": "amplify", "gain_db": 6}, {"type": "invert"}]}],
        master_effects=[{"type": "normalize", "peak_db": -3}],
    )
    again = Project.from_bytes(project.to_bytes(), Path("."))
    assert [effect.type for effect in again.audio.voiceover[0].effects] == ["amplify", "invert"]
    assert again.audio.master_effects[0].peak_db == -3
    assert again.audio.voiceover[0].effects[0].enabled is True


def test_an_item_with_effects_changes_its_own_hash_only():
    plain = ClipSegment(src="a.mp4", start=1.0, end=4.0)
    boosted = ClipSegment(src="a.mp4", start=1.0, end=4.0, effects=[Amplify(gain_db=6)])
    assert cache_key(plain.model_dump(mode="json")) != cache_key(boosted.model_dump(mode="json"))
    assert cache_key(piece_recipe(plain)) != cache_key(piece_recipe(boosted))  # a prévia também se invalida
    other = ClipSegment(src="b.mp4", start=1.0, end=4.0)
    assert cache_key(other.model_dump(mode="json")) == cache_key(
        ClipSegment(src="b.mp4", start=1.0, end=4.0, effects=[]).model_dump(mode="json")
    )


def test_effects_of_every_audio_item_and_of_the_master_are_part_of_the_preview_mix_recipe():
    base = cache_key(mix_recipe(project_with()))
    chain = [{"type": "amplify", "gain_db": 3}]
    variants = [
        project_with(music={"src": "m.mp3", "effects": chain}),
        project_with(narration=[{"text": "oi", "effects": chain}]),
        project_with(voiceover=[{"src": "v.wav", "start": 1.0, "effects": chain}]),
        project_with(master_effects=chain),
    ]
    keys = {cache_key(mix_recipe(variant)) for variant in variants}
    assert base not in keys and len(keys) == 4


# ---------- onde cada efeito é aceito ----------


@pytest.mark.parametrize(
    "build",
    [
        lambda: ClipSegment(src="a.mp4", effects=[Repeat()]),
        lambda: VideoOverlay(src="p.mp4", effects=[Repeat()]),
        lambda: AudioTrack(source="mesa", effects=[Repeat()]),
        lambda: Narration(text="oi", effects=[Repeat()]),
        lambda: AudioSettings(master_effects=[Repeat()]),
    ],
)
def test_repeat_is_refused_where_the_item_duration_cannot_grow(build):
    with pytest.raises(ValidationError, match="Repetir muda a duração.*voz gravada.*música"):
        build()


def test_repeat_is_accepted_on_recorded_voice_and_music_and_other_effects_everywhere():
    VoiceoverClip(src="v.wav", effects=[Repeat(times=2)])
    Music(src="m.mp3", effects=[Repeat(times=3)])
    for build in (
        lambda: ClipSegment(src="a.mp4", effects=[Reverse(), Invert(), Amplify(), Normalize()]),
        lambda: VideoOverlay(src="p.mp4", effects=[Reverse()]),
        lambda: AudioTrack(source="mesa", effects=[Normalize()]),
        lambda: Narration(text="oi", effects=[Invert()]),
        lambda: AudioSettings(master_effects=[Amplify(gain_db=-3)]),
    ):
        build()


def test_the_error_names_the_place_that_refused():
    with pytest.raises(ValidationError, match="clipe"):
        ClipSegment(src="a.mp4", effects=[Repeat()])
    with pytest.raises(ValidationError, match=r"áudio mestre \(audio.master_effects\)"):
        AudioSettings(master_effects=[Repeat()])


# ---------- contas da cadeia ----------


def test_repeat_doubles_the_duration_and_inside_an_interval_only_that_stretch_grows():
    assert chain_duration([Repeat(times=2)], 10.0) == 20.0
    assert chain_duration([Repeat(times=3)], 4.0) == 12.0
    assert chain_duration([Repeat(times=2, start=1, end=3)], 10.0) == 12.0
    assert chain_duration([Repeat(times=2), Repeat(times=2)], 5.0) == 20.0
    assert chain_duration([Repeat(times=4, enabled=False), Reverse()], 5.0) == 5.0  # desligado não conta
    assert chain_duration([], 7.5) == 7.5


def test_a_disabled_effect_is_left_out_of_the_cache_signature_and_keeps_its_position():
    chain = [Amplify(gain_db=3), Invert(enabled=False), Reverse()]
    assert [index for index, _ in active_effects(chain)] == [0, 2]
    assert [entry["type"] for entry in chain_signature(chain)] == ["amplify", "reverse"]
    assert chain_signature([Amplify(gain_db=3), Reverse()]) == chain_signature(chain)


def test_the_span_is_none_for_the_whole_item_and_clamped_otherwise():
    effect = Amplify(start=1, end=3)
    assert effect.span(10.0) == (1.0, 3.0)
    assert effect.span(2.0) == (1.0, 2.0)
    assert Amplify().span(10.0) is None
    assert Amplify(start=0, end=10).span(10.0) is None


# ---------- operação de edição ----------


def test_edit_add_remove_move_enable_disable_and_set():
    project = project_with()
    op = {"action": "add", "target": "audio.voiceover.0", "effect": {"type": "amplify", "gain_db": 6}}
    project = apply_effect_op(project, op)
    project = apply_effect_op(project, {**op, "effect": {"type": "reverse"}})
    project = apply_effect_op(project, {**op, "effect": {"type": "invert"}, "index": 0})
    assert [e.type for e in project.audio.voiceover[0].effects] == ["invert", "amplify", "reverse"]

    project = apply_effect_op(project, {"action": "move", "target": "audio.voiceover.0", "index": 2, "to": 0})
    assert [e.type for e in project.audio.voiceover[0].effects] == ["reverse", "invert", "amplify"]
    project = apply_effect_op(project, {"action": "disable", "target": "audio.voiceover.0", "index": 1})
    assert [e.enabled for e in project.audio.voiceover[0].effects] == [True, False, True]
    project = apply_effect_op(project, {"action": "enable", "target": "audio.voiceover.0", "index": 1})
    assert all(e.enabled for e in project.audio.voiceover[0].effects)
    project = apply_effect_op(
        project, {"action": "set", "target": "audio.voiceover.0", "index": 2, "params": {"gain_db": -4}}
    )
    assert project.audio.voiceover[0].effects[2].gain_db == -4
    project = apply_effect_op(project, {"action": "remove", "target": "audio.voiceover.0", "index": 0})
    assert [e.type for e in project.audio.voiceover[0].effects] == ["invert", "amplify"]


@pytest.mark.parametrize(
    ("target", "read"),
    [
        ("timeline.0", lambda p: p.timeline[0].effects),
        ("overlays.0", lambda p: p.overlays[0].effects),
        ("audio.voiceover.0", lambda p: p.audio.voiceover[0].effects),
        ("audio.narration.0", lambda p: p.audio.narration[0].effects),
        ("audio.music", lambda p: p.audio.music.effects),
        ("audio.master", lambda p: p.audio.master_effects),
    ],
)
def test_edit_reaches_the_chain_of_every_kind_of_item(target, read):
    edited = apply_effect_op(
        project_with(), {"action": "add", "target": target, "effect": {"type": "amplify", "gain_db": 2}}
    )
    assert [e.type for e in read(edited)] == ["amplify"]


def test_edit_adds_to_an_external_track_chain():
    project = Project.model_validate(
        {
            "name": "t",
            "sources": {"mesa": {"src": "mesa.wav"}},
            "timeline": [{"type": "clip", "source": "mesa", "start": 0, "end": 3}],
            "audio": {"tracks": [{"source": "mesa"}]},
        }
    )
    edited = apply_effect_op(
        project, {"action": "add", "target": "audio.tracks.0", "effect": {"type": "reverse"}}
    )
    assert edited.audio.tracks[0].effects == [Reverse()]


@pytest.mark.parametrize(
    ("op", "message"),
    [
        ({"action": "pular", "target": "audio.master"}, "ação de efeito desconhecida"),
        ({"action": "add"}, "informe o `target`"),
        ({"action": "add", "target": "audio.master"}, "informe o `effect`"),
        ({"action": "add", "target": "audio.master", "effect": {"type": "eco"}}, "desconhecido"),
        ({"action": "add", "target": "audio.master", "effect": {"type": "repeat"}}, "Repetir muda a duração"),
        ({"action": "add", "target": "timeline.0", "effect": {"type": "repeat"}}, "Repetir muda a duração"),
        ({"action": "add", "target": "timeline.9", "effect": {"type": "reverse"}}, "fora do intervalo"),
        ({"action": "add", "target": "voz", "effect": {"type": "reverse"}}, "alvo de efeito inválido"),
        ({"action": "remove", "target": "audio.master", "index": 0}, "fora do intervalo"),
        ({"action": "remove", "target": "audio.master"}, "informe o `index`"),
        (
            {"action": "set", "target": "audio.music", "index": 0, "params": {"gain_db": 1}},
            "fora do intervalo",
        ),
        (
            {"action": "add", "target": "audio.master", "effect": {"type": "amplify"}, "index": 5},
            "posição fora",
        ),
    ],
)
def test_edit_refuses_a_bad_request_in_portuguese(op, message):
    with pytest.raises(EditError, match=message):
        apply_effect_op(project_with(), op)


def test_edit_refuses_music_that_does_not_exist_and_a_non_video_overlay_or_card():
    no_music = Project.model_validate({"name": "t", "timeline": [{"type": "clip", "src": "a.mp4"}]})
    with pytest.raises(EditError, match="não tem música"):
        apply_effect_op(no_music, {"action": "add", "target": "audio.music", "effect": {"type": "reverse"}})
    card = Project.model_validate({"name": "t", "timeline": [{"type": "card", "title": "Oi"}]})
    with pytest.raises(EditError, match="só o trecho de vídeo"):
        apply_effect_op(card, {"action": "add", "target": "timeline.0", "effect": {"type": "reverse"}})


def test_edit_set_keeps_the_other_parameters_of_the_effect():
    project = apply_effect_op(
        project_with(),
        {
            "action": "add",
            "target": "audio.master",
            "effect": {"type": "normalize", "peak_db": -3, "remove_dc": False},
        },
    )
    project = apply_effect_op(
        project, {"action": "set", "target": "audio.master", "index": 0, "params": {"peak_db": -6}}
    )
    effect = project.audio.master_effects[0]
    assert (effect.peak_db, effect.remove_dc) == (-6, False)
    with pytest.raises(EditError):
        apply_effect_op(
            project, {"action": "set", "target": "audio.master", "index": 0, "params": {"peak_db": 5}}
        )


# ---------- trilha da voz gravada ----------


def test_the_voiceover_track_can_be_muted_and_is_a_known_track_id():
    project = project_with()
    assert "VO" in known_track_ids(project)
    muted = project.model_copy(update={"tracks": {"VO": TrackState(muted=True)}})
    assert apply_track_state(muted).audio.voiceover == []
    assert "VO" not in known_track_ids(
        Project.model_validate({"name": "t", "timeline": [{"type": "clip", "src": "a.mp4"}]})
    )
