"""Os efeitos de fade, o crossfade de trilhas e o crossfade de som entre clipes: spec, grafo e edições, sem ffmpeg.

As medidas de som (RMS, energia, tons) estão em `test_audio_fades_integration.py` e `test_audio_clip_crossfade_integration.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.audio_crossfade import MIN_HALF_SECONDS, CutSide, plan_cut
from dmaker.domain.audio_edits import rebase_effects, set_edge_fade
from dmaker.domain.audio_effects import EFFECT_PRESETS, catalog_payload, chain_duration, parse_effect
from dmaker.domain.edits import EditError
from dmaker.domain.spec import AudioCrossfade, ClipSegment, Project
from dmaker.filtergraph.audio_effects import chain_lines
from dmaker.filtergraph.audio_effects.fades import STUDIO_MAX_STEPS, studio_cutoff_commands
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.crossfade_lint import crossfade_warnings
from dmaker.pipeline.edits import apply_edit

DURATIONS = {"video.mp4": 20.0, "outro.mp4": 20.0, "fala.wav": 6.0, "musica.wav": 30.0}


def prober(path: Path) -> MediaInfo:
    video = path.suffix == ".mp4"
    return MediaInfo(
        path,
        DURATIONS.get(path.name, 5.0),
        1280 if video else 0,
        720 if video else 0,
        30.0,
        video,
        True,
        False,
    )


@pytest.fixture
def folder(tmp_path) -> Path:
    for name in DURATIONS:
        (tmp_path / name).write_bytes(b"\x00" * 16)
    return tmp_path


def make(folder: Path, **parts) -> Project:
    data = {
        "name": "fades",
        "timeline": [
            {"type": "clip", "src": "video.mp4", "start": 2, "end": 8},
            {"type": "clip", "src": "outro.mp4", "start": 5, "end": 11},
        ],
        **parts,
    }
    project = Project.model_validate(data)
    project.base_dir = folder
    return project


def edit(project: Project, **op) -> Project:
    return apply_edit(project, op, prober=prober)


def graph(*effects: dict, duration: float = 4.0) -> str:
    return ";".join(chain_lines("[a]", "[b]", [parse_effect(effect) for effect in effects], duration))


# ---------- o catálogo e a spec ----------


def test_the_fade_family_is_in_the_catalog_with_ranges_and_choices():
    by_type = {info["type"]: info for info in catalog_payload()["effects"]}
    for name in ("fade_in", "fade_out", "adjustable_fade", "studio_fade_out"):
        assert name in by_type
    fade = {param["name"]: param for param in by_type["fade_in"]["parameters"]}
    assert fade["curve"]["kind"] == "choice"
    assert fade["curve"]["options"] == ["linear", "logarithmic", "exponential", "sine", "quadratic"]
    assert fade["duration"]["minimum"] == 0 and fade["duration"]["maximum"] == 3600
    adjustable = {param["name"]: param for param in by_type["adjustable_fade"]["parameters"]}
    assert adjustable["unit"]["options"] == ["percent", "db"]
    assert adjustable["mid_adjust"]["minimum"] == -100 and adjustable["mid_adjust"]["maximum"] == 100
    assert by_type["fade_in"]["audacity_name"] == "Fade In"
    assert by_type["studio_fade_out"]["audacity_name"] == "Studio Fade Out"


def test_the_adjustable_fade_gains_must_fit_the_unit():
    with pytest.raises(ValueError, match="porcentagem"):
        parse_effect({"type": "adjustable_fade", "start_gain": -10})
    with pytest.raises(ValueError, match="dB"):
        parse_effect({"type": "adjustable_fade", "unit": "db", "start_gain": 30})
    assert parse_effect({"type": "adjustable_fade", "unit": "db", "start_gain": -12, "end_gain": 0})


def test_a_fade_with_zero_duration_or_an_unknown_curve_is_refused():
    with pytest.raises(ValueError):
        parse_effect({"type": "fade_in", "duration": 0})
    with pytest.raises(ValueError):
        parse_effect({"type": "fade_out", "curve": "zigzag"})


def test_a_fade_does_not_change_the_duration_of_the_item():
    chain = [parse_effect({"type": "fade_in"}), parse_effect({"type": "studio_fade_out"})]
    assert chain_duration(chain, 10.0) == 10.0


# ---------- o grafo ----------


def test_fade_in_and_out_are_afade_with_the_matching_curve():
    assert "afade=t=in:st=0.000000:d=2.000000:curve=hsin" in graph(
        {"type": "fade_in", "duration": 2, "curve": "sine"}
    )
    assert "afade=t=out:st=2.500000:d=1.500000:curve=qua" in graph(
        {"type": "fade_out", "duration": 1.5, "curve": "quadratic"}
    )
    assert "curve=tri" in graph({"type": "fade_in"})
    assert "curve=log" in graph({"type": "fade_in", "curve": "logarithmic"})
    assert "curve=exp" in graph({"type": "fade_out", "curve": "exponential"})


def test_a_fade_longer_than_the_item_is_cut_to_the_item():
    assert "afade=t=in:st=0.000000:d=4.000000" in graph({"type": "fade_in", "duration": 30})


def test_with_an_interval_the_fade_fills_the_interval_and_the_duration_does_not_count():
    text = graph({"type": "fade_out", "duration": 0.2, "start": 1.0, "end": 3.0})
    assert "afade=t=out:st=0.000000:d=2.000000" in text  # o trecho recortado dura 2 s e o fade ocupa todo ele
    assert "atrim=start_sample=48000:end_sample=144000" in text


def test_the_adjustable_fade_is_a_volume_expression_from_the_envelope_points():
    text = graph({"type": "adjustable_fade", "start_gain": 100, "end_gain": 40})
    assert "volume='pow(10," in text and "eval=frame" in text and "asetnsamples=n=64" in text
    flat = graph({"type": "adjustable_fade", "start_gain": 50, "end_gain": 50})
    assert "volume=-6.02" in flat and "eval=frame" not in flat  # ganhos iguais: um ganho só


def test_the_studio_fade_out_closes_a_lowpass_with_asendcmd_and_fades_the_volume():
    text = graph({"type": "studio_fade_out", "duration": 3, "final_cutoff": 300}, duration=5.0)
    assert "asendcmd=c='" in text and "lowpass@fx0_lp=f=20000:p=2:enable='gte(t,2.000000)'" in text
    assert "afade=t=out:st=2.000000:d=3.000000:curve=qua" in text
    assert "2.0000 lowpass@fx0_lp f 20000.00" in text and "5.0000 lowpass@fx0_lp f 300.00" in text


def test_the_studio_cutoff_falls_in_equal_octaves_and_the_command_count_is_capped():
    steps = studio_cutoff_commands(0.0, 3.0, 200.0)
    cutoffs = [hz for _, hz in steps]
    assert cutoffs[0] == 20000.0 and cutoffs[-1] == 200.0
    assert all(a > b for a, b in zip(cutoffs, cutoffs[1:], strict=False))
    ratios = [b / a for a, b in zip(cutoffs, cutoffs[1:], strict=False)]
    assert max(ratios) - min(ratios) < 1e-3  # a mesma razão em cada passo: oitavas iguais
    assert len(steps) == STUDIO_MAX_STEPS + 1  # 3 s a cada 10 ms seriam 300 passos: o teto é 150
    assert len(studio_cutoff_commands(0.0, 0.2, 200.0)) == 21  # um fade curto leva um passo a cada 10 ms
    assert len(studio_cutoff_commands(0.0, 600.0, 200.0)) == STUDIO_MAX_STEPS + 1


# ---------- fade na borda: a edição ----------


def test_the_edge_fade_edit_creates_updates_and_removes_the_fade(folder):
    project = make(folder)
    one = set_edge_fade(project, "timeline.0", "in", 1.5, {"curve": "sine"})
    fade = one.timeline[0].effects[0]
    assert (fade.type, fade.duration, fade.curve) == ("fade_in", 1.5, "sine")
    two = set_edge_fade(one, "timeline.0", "in", 2.5, {})
    assert [(e.type, e.duration, e.curve) for e in two.timeline[0].effects] == [("fade_in", 2.5, "sine")]
    three = set_edge_fade(two, "timeline.0", "out", 1.0, None)
    assert [e.type for e in three.timeline[0].effects] == ["fade_in", "fade_out"]
    four = set_edge_fade(three, "timeline.0", "in", 0.0, None)
    assert [e.type for e in four.timeline[0].effects] == ["fade_out"]
    with pytest.raises(EditError, match="in"):
        set_edge_fade(project, "timeline.0", "left", 1.0, None)


def test_the_audio_fade_operation_goes_through_edit_project(folder):
    edited = edit(
        make(folder), type="audio_fade", target="timeline.1", side="out", duration=2, curve="exponential"
    )
    fade = edited.timeline[1].effects[0]
    assert (fade.type, fade.duration, fade.curve) == ("fade_out", 2.0, "exponential")
    with pytest.raises(EditError, match="duration"):
        edit(make(folder), type="audio_fade", target="timeline.1", side="out", duration=-1)
    with pytest.raises(EditError, match="mistura"):
        edit(make(folder), type="audio_fade", target="audio.master", side="out", duration=1)


def test_an_edge_fade_follows_a_split_only_where_its_edge_is(folder):
    """O Fade In fica na primeira metade e o Fade Out na segunda; o que a divisão cortou encurta."""
    project = make(folder)
    project = set_edge_fade(project, "timeline.0", "in", 2.0, {})
    project = set_edge_fade(project, "timeline.0", "out", 2.0, {})
    chain = project.timeline[0].effects
    first = rebase_effects(chain, 0.0, 6.0, 12.0)  # a metade de antes de um item de 12 s
    second = rebase_effects(chain, 6.0, 6.0, 12.0)
    assert [e.type for e in first] == ["fade_in"] and [e.type for e in second] == ["fade_out"]
    partly = rebase_effects(chain, 1.0, 11.0, 12.0)  # o item sem o primeiro segundo: o Fade In perde 1 s
    assert [(e.type, e.duration) for e in partly] == [("fade_in", 1.0), ("fade_out", 2.0)]
    gone = rebase_effects(chain, 2.0, 10.0, 12.0)
    assert [e.type for e in gone] == ["fade_out"]


def test_splitting_a_clip_with_edge_fades_keeps_each_fade_on_its_side(folder):
    project = set_edge_fade(make(folder), "timeline.0", "in", 1.0, {})
    project = set_edge_fade(project, "timeline.0", "out", 1.0, {})
    edited = edit(project, type="split", index=0, at=3.0)
    assert [e.type for e in edited.timeline[0].effects] == ["fade_in"]
    assert [e.type for e in edited.timeline[1].effects] == ["fade_out"]


# ---------- predefinições do Fade Ajustável ----------


def test_the_adjustable_fade_presets_are_registered_and_each_one_is_a_valid_single_effect():
    ids = {name for name in EFFECT_PRESETS if name.startswith("fade_")}
    for case in ("linear", "exponential", "logarithmic", "rounded", "cosine", "s_curve"):
        assert {f"fade_{case}_in", f"fade_{case}_out"} <= ids
    assert {"fade_partial", "fade_soft_up", "fade_soft_down"} <= ids
    for name in ids:
        (effect,) = EFFECT_PRESETS[name].effects
        assert parse_effect(dict(effect)).type == "adjustable_fade"
    partial = parse_effect(dict(EFFECT_PRESETS["fade_partial"].effects[0]))
    assert (partial.start_gain, partial.end_gain, partial.unit) == (100.0, 40.0, "percent")


def test_a_preset_goes_into_the_chain_through_audio_effect(folder):
    edited = edit(
        make(folder), type="audio_effect", action="preset", target="timeline.0", preset="fade_cosine_out"
    )
    (fade,) = edited.timeline[0].effects
    assert (fade.shape, fade.start_gain, fade.end_gain) == ("sine_down", 100.0, 0.0)


# ---------- crossfade de trilhas ----------


def voices(folder: Path) -> Project:
    return make(
        folder,
        audio={
            "voiceover": [
                {"src": "fala.wav", "start": 0, "end": 5},
                {"src": "fala.wav", "start": 2, "end": 5},
            ]
        },
    )


def test_the_track_crossfade_writes_one_adjustable_fade_in_each_item_with_matched_curves(folder):
    edited = edit(
        voices(folder),
        type="audio_crossfade_tracks",
        out_target="audio.voiceover.0",
        in_target="audio.voiceover.1",
        start=2,
        end=5,
        kind="constant_power_1",
    )
    (leaving,) = edited.audio.voiceover[0].effects
    (entering,) = edited.audio.voiceover[1].effects
    assert (leaving.shape, leaving.start_gain, leaving.end_gain) == ("sine_down", 100.0, 0.0)
    assert (entering.shape, entering.start_gain, entering.end_gain) == ("sine_up", 0.0, 100.0)
    assert (leaving.start, leaving.end) == (2.0, 5.0)  # tempo do item: a voz 0 começa em 0
    assert (entering.start, entering.end) == (0.0, 3.0)  # a voz 1 começa em 2 s da linha do tempo


@pytest.mark.parametrize(
    ("kind", "shapes", "mids"),
    [
        ("constant_gain", ("up", "up"), (0.0, 0.0)),
        ("constant_power_2", ("down", "up"), (-50.0, -50.0)),
    ],
)
def test_each_crossfade_type_picks_its_pair_of_curves(folder, kind, shapes, mids):
    edited = edit(
        voices(folder),
        type="audio_crossfade_tracks",
        out_target="audio.voiceover.0",
        in_target="audio.voiceover.1",
        start=2,
        end=5,
        kind=kind,
    )
    leaving, entering = edited.audio.voiceover[0].effects[0], edited.audio.voiceover[1].effects[0]
    assert (leaving.shape, entering.shape) == shapes
    assert (leaving.mid_adjust, entering.mid_adjust) == mids


def test_the_custom_crossfade_takes_the_curve_and_the_mid_adjust(folder):
    edited = edit(
        voices(folder),
        type="audio_crossfade_tracks",
        out_target="audio.voiceover.0",
        in_target="audio.voiceover.1",
        start=2,
        end=5,
        kind="custom",
        curve="s_up",
        mid_adjust=25,
    )
    leaving, entering = edited.audio.voiceover[0].effects[0], edited.audio.voiceover[1].effects[0]
    assert (entering.shape, entering.mid_adjust, entering.end_gain) == ("s_up", 25.0, 100.0)
    assert (leaving.shape, leaving.start_gain) == ("s_up", 100.0)


def test_the_track_crossfade_is_one_step_and_refuses_what_makes_no_sense(folder):
    base = {
        "type": "audio_crossfade_tracks",
        "out_target": "audio.voiceover.0",
        "in_target": "audio.voiceover.1",
        "start": 2,
        "end": 5,
    }
    with pytest.raises(EditError, match="diferentes"):
        edit(voices(folder), **{**base, "in_target": "audio.voiceover.0"})
    with pytest.raises(EditError, match="desconhecido"):
        edit(voices(folder), **{**base, "kind": "zigzag"})
    with pytest.raises(EditError, match="cobrir"):
        edit(voices(folder), **{**base, "start": 0})  # a voz 1 só soa a partir de 2 s
    with pytest.raises(EditError, match="mistura"):
        edit(voices(folder), **{**base, "in_target": "audio.master"})


# ---------- crossfade de som entre clipes ----------


def test_the_clip_crossfade_field_is_out_of_the_dump_and_the_hash_when_empty(folder):
    plain = make(folder)
    assert "audio_crossfade" not in plain.timeline[1].model_dump(mode="json")
    edited = edit(plain, type="audio_crossfade_clips", index=1, duration=0.5)
    assert edited.timeline[1].audio_crossfade == AudioCrossfade(duration=0.5, curve="constant_power_1")
    assert edited.timeline[1].model_dump(mode="json")["audio_crossfade"] == {
        "duration": 0.5,
        "curve": "constant_power_1",
    }
    cleared = edit(edited, type="audio_crossfade_clips", index=1, duration=0)
    assert "audio_crossfade" not in cleared.timeline[1].model_dump(mode="json")
    assert plain.to_bytes() == cleared.to_bytes()


def test_the_clip_crossfade_keeps_the_curve_when_only_the_duration_changes(folder):
    one = edit(make(folder), type="audio_crossfade_clips", index=1, duration=0.4, curve="constant_gain")
    two = edit(one, type="audio_crossfade_clips", index=1, duration=0.8)
    assert (two.timeline[1].audio_crossfade.duration, two.timeline[1].audio_crossfade.curve) == (
        0.8,
        "constant_gain",
    )


def test_the_clip_crossfade_refuses_the_first_clip_non_clips_and_bad_values(folder):
    with pytest.raises(EditError, match="primeiro"):
        edit(make(folder), type="audio_crossfade_clips", index=0, duration=0.5)
    with pytest.raises(EditError, match="constant_gain"):
        edit(make(folder), type="audio_crossfade_clips", index=1, duration=0.5, curve="custom")
    with pytest.raises(EditError, match="duration"):
        edit(make(folder), type="audio_crossfade_clips", index=1, duration=9)
    cards = make(
        folder,
        timeline=[
            {"type": "card", "title": "Abertura"},
            {"type": "clip", "src": "video.mp4", "start": 0, "end": 4},
        ],
    )
    with pytest.raises(EditError, match="entre dois clipes"):
        edit(cards, type="audio_crossfade_clips", index=1, duration=0.5)


def test_the_crossfade_field_only_stays_on_the_first_piece_of_a_split_source():
    segment = ClipSegment(src="a.mp4", start=0, end=4, audio_crossfade=AudioCrossfade())
    assert segment.audio_crossfade is not None
    assert "audio_crossfade" not in ClipSegment(src="a.mp4", start=0, end=4).model_dump(mode="json")


# ---------- a conta do cruzamento ----------


def side(room: float = 5.0, length: float = 4.0, audible: bool = True, blocked: str | None = None) -> CutSide:
    return CutSide(audible, room, length, blocked)


def test_the_crossfade_takes_half_the_requested_time_on_each_side():
    plan = plan_cut(0.5, side(), side(), "timeline[1]")
    assert (plan.half, plan.width, plan.note) == (0.25, 0.5, None)


def test_the_crossfade_shortens_to_the_smallest_room_and_says_so():
    plan = plan_cut(0.5, side(room=0.1), side(), "timeline[1]")
    assert plan.half == 0.1 and plan.width == pytest.approx(0.2)
    assert plan.note is not None and "encurtou para 0.20 s" in plan.note and "timeline[1]" in plan.note
    short_clip = plan_cut(0.5, side(), side(length=0.12), "timeline[1]")
    assert short_clip.half == 0.12


def test_the_crossfade_is_off_when_there_is_no_room_no_sound_or_a_blocked_clip():
    none = plan_cut(0.5, side(room=0.0), side(), "timeline[2]")
    assert none.half == 0.0 and none.note is not None and "não coube" in none.note
    muted = plan_cut(0.5, side(audible=False), side(), "timeline[2]")
    assert muted.half == 0.0 and "sem som" in (muted.note or "")
    blocked = plan_cut(0.5, side(), side(blocked="ele tem o som deslocado (audio_offset)"), "timeline[2]")
    assert blocked.half == 0.0 and "audio_offset" in (blocked.note or "")
    assert MIN_HALF_SECONDS > 0


# ---------- avisos antes de renderizar ----------


def infos(project: Project) -> list[MediaInfo]:
    return [prober(Path(segment.src)) for segment in project.timeline]  # type: ignore[union-attr]


def test_the_lint_warns_when_the_crossfade_is_ignored_or_shortened(folder):
    ok = edit(make(folder), type="audio_crossfade_clips", index=1, duration=0.5)
    assert crossfade_warnings(ok, [6.0, 6.0], infos(ok), None) == []

    short = make(
        folder,
        timeline=[
            {"type": "clip", "src": "video.mp4", "start": 2, "end": 19.95},
            {"type": "clip", "src": "outro.mp4", "start": 5, "end": 11, "audio_crossfade": {"duration": 0.5}},
        ],
    )
    notes = crossfade_warnings(short, [17.95, 6.0], infos(short), None)
    assert len(notes) == 1 and "encurtou" in notes[0]

    first = make(
        folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 4, "audio_crossfade": {}}]
    )
    assert "não existe trecho anterior" in crossfade_warnings(first, [4.0], infos(first), None)[0]

    faded = make(
        folder,
        timeline=[
            {"type": "clip", "src": "video.mp4", "start": 2, "end": 8},
            {
                "type": "clip",
                "src": "outro.mp4",
                "start": 5,
                "end": 11,
                "audio_crossfade": {},
                "transition": {"type": "fade", "duration": 0.5},
            },
        ],
    )
    assert "transição de imagem" in crossfade_warnings(faded, [6.0, 6.0], infos(faded), None)[0]
