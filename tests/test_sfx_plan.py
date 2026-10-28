"""Efeitos sonoros na spec: validação, forma curta do campo `sound` e o plano que junta todos os instantes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmaker.domain import sfx as sfx_plan
from dmaker.domain.sfx import SfxItem, default_entry_sound, entry_sound, plan_sfx
from dmaker.domain.spec import AudioSettings, EntrySound, Project, SfxCue
from dmaker.domain.timeline import timeline_spans, transitions_of


def _project(**overrides) -> Project:
    data = {
        "name": "sfx",
        "timeline": [
            {"type": "card", "title": "Um", "duration": 4},
            {"type": "card", "title": "Dois", "duration": 4, "transition": {"type": "fade", "duration": 0.5}},
            {"type": "card", "title": "Tres", "duration": 4, "transition": {"type": "cut"}},
        ],
    }
    data.update(overrides)
    return Project.model_validate(data)


def _plan(project: Project) -> list[SfxItem]:
    segments = project.timeline
    durations = [seg.duration for seg in segments]  # só cartões nestes testes
    return plan_sfx(project, timeline_spans(durations, transitions_of(segments)))


# ---------- spec ----------


def test_a_project_without_sfx_has_an_empty_plan():
    project = _project()
    assert project.audio.sfx == []
    assert _plan(project) == []


def test_sfx_cue_defaults_and_limits():
    cue = SfxCue(sound="whoosh", at=12.4)
    assert cue.volume == 1.0
    for bad in ({"sound": "", "at": 1}, {"sound": "pop", "at": -1}, {"sound": "pop", "at": 1, "volume": 2}):
        with pytest.raises(ValidationError):
            SfxCue.model_validate(bad)
    with pytest.raises(ValidationError):  # campo inventado não passa em silêncio
        SfxCue.model_validate({"sound": "pop", "at": 1, "vol": 0.5})


def test_sound_field_accepts_true_a_name_or_an_object_on_every_entry_type():
    project = _project(
        overlays=[
            {"type": "text", "text": "A", "start": 1, "sound": True},
            {"type": "image", "src": "logo", "start": 2, "sound": "click"},
            {"type": "video", "src": "pip.mp4", "start": 3, "sound": {"sound": "whip", "volume": 0.5}},
            {"type": "progress-bar"},
        ]
    )
    assert [getattr(o, "sound", None) for o in project.overlays][:3] == [
        True,
        "click",
        EntrySound(sound="whip", volume=0.5),
    ]


def test_the_progress_bar_has_no_entry_sound():
    with pytest.raises(ValidationError):
        Project.model_validate(
            {**_project().model_dump(), "overlays": [{"type": "progress-bar", "sound": True}]}
        )


def test_the_json_schema_publishes_the_new_fields():
    """O `spec_schema` do MCP sai daqui: quem monta a spec descobre `audio.sfx` e `sound` pelo esquema."""
    schema = Project.model_json_schema()
    defs = schema["$defs"]
    assert set(defs["SfxCue"]["properties"]) == {"sound", "at", "volume"}
    assert defs["SfxCue"]["required"] == ["sound", "at"]
    assert "sfx" in defs["AudioSettings"]["properties"]
    for model in ("TextOverlay", "ImageOverlay", "VideoOverlay", "Transition"):
        assert "sound" in defs[model]["properties"], model
    assert set(defs["EntrySound"]["properties"]) == {"sound", "volume", "offset"}


def test_a_saved_project_with_sounds_reopens_equal():
    """Salvar e reabrir (o que o projeto faz) não muda as três formas do campo `sound`."""
    project = _project(
        overlays=[
            {"type": "text", "text": "A", "start": 1, "sound": True},
            {"type": "image", "src": "logo", "start": 2, "sound": "click"},
            {
                "type": "video",
                "src": "pip.mp4",
                "start": 3,
                "sound": {"sound": "whip", "volume": 0.5, "offset": -0.1},
            },
        ],
        audio={"sfx": [{"sound": "whoosh", "at": 12.4, "volume": 0.8}]},
    )
    again = Project.model_validate_json(project.model_dump_json(exclude_none=True))
    assert again == project and _plan(again) == _plan(project)


def test_the_mcp_schema_tool_publishes_the_new_fields():
    from dmaker.mcp_server import spec_schema

    defs = spec_schema()["$defs"]
    assert "sfx" in defs["AudioSettings"]["properties"] and "SfxCue" in defs and "EntrySound" in defs


# ---------- forma curta ----------


def test_entry_sound_normalizes_the_three_forms():
    assert entry_sound(None, "pop") is None and entry_sound(False, "pop") is None
    assert entry_sound(True, "pop") == EntrySound(sound="pop")
    assert entry_sound("whip", "pop") == EntrySound(sound="whip")
    custom = EntrySound(sound="click", volume=0.4, offset=-0.1)
    assert entry_sound(custom, "pop") is custom


def test_default_sound_depends_on_the_kind_and_falls_back():
    assert default_entry_sound("text") == "pop"
    assert default_entry_sound("transition") == "whoosh"
    assert default_entry_sound("tipo-que-ainda-nao-existe") == sfx_plan.FALLBACK_ENTRY_SOUND


# ---------- plano ----------


def test_plan_lists_explicit_sfx_in_time_order():
    project = _project(
        audio=AudioSettings(
            sfx=[SfxCue(sound="impact", at=9.0), SfxCue(sound="whoosh", at=2.5, volume=0.5)]
        ).model_dump()
    )
    assert _plan(project) == [
        SfxItem("whoosh", 2.5, 0.5, "audio.sfx[1]"),
        SfxItem("impact", 9.0, 1.0, "audio.sfx[0]"),
    ]


def test_entry_sound_is_off_by_default_and_plays_at_the_overlay_start():
    off = _project(overlays=[{"type": "text", "text": "A", "start": 2}])
    assert _plan(off) == []
    on = _project(
        overlays=[
            {"type": "text", "text": "A", "start": 2, "sound": True},
            {"type": "image", "src": "logo", "start": 5.25, "sound": "click"},
            {"type": "text", "text": "B", "start": 7, "sound": False},
            {"type": "progress-bar"},
        ]
    )
    assert _plan(on) == [
        SfxItem("pop", 2.0, 1.0, "overlays[0]"),
        SfxItem("click", 5.25, 1.0, "overlays[1]"),
    ]


def test_entry_sound_offset_moves_the_sound_but_never_before_zero():
    project = _project(
        overlays=[
            {"type": "text", "text": "A", "start": 3, "sound": {"sound": "whoosh", "offset": -0.15}},
            {"type": "text", "text": "B", "start": 0.05, "sound": {"offset": -0.5, "volume": 0.8}},
        ]
    )
    items = _plan(project)
    assert [(i.sound, round(i.at, 3), i.volume) for i in items] == [("pop", 0.0, 0.8), ("whoosh", 2.85, 1.0)]


def test_a_muted_entry_sound_leaves_the_plan():
    project = _project(overlays=[{"type": "text", "text": "A", "start": 1, "sound": {"volume": 0}}])
    assert _plan(project) == []


def test_transition_sound_plays_at_the_start_of_the_entering_segment():
    project = _project(
        timeline=[
            {"type": "card", "title": "Um", "duration": 4},
            {
                "type": "card",
                "title": "Dois",
                "duration": 4,
                "transition": {"type": "fade", "duration": 0.5, "sound": True},
            },
            {"type": "card", "title": "Tres", "duration": 4, "transition": {"type": "cut", "sound": "click"}},
        ]
    )
    # o segundo trecho começa em 4 - 0.5 (a transição o puxa para dentro do primeiro); o corte, em 3.5 + 4
    assert _plan(project) == [
        SfxItem("whoosh", 3.5, 1.0, "timeline[1].transition"),
        SfxItem("click", 7.5, 1.0, "timeline[2].transition"),
    ]


def test_the_transition_of_the_first_segment_is_ignored():
    project = _project(
        timeline=[
            {"type": "card", "title": "Um", "duration": 4, "transition": {"type": "fade", "sound": True}},
            {"type": "card", "title": "Dois", "duration": 4},
        ]
    )
    assert _plan(project) == []


def test_a_new_overlay_type_joins_the_plan_by_declaring_the_field(monkeypatch):
    """Ponto de extensão: um tipo futuro (infográfico) só precisa de `start` e `sound`, e de uma linha no
    registro de padrões se quiser um som próprio. O plano não conhece os tipos."""

    class Infographic:
        type = "infographic"
        start = 6.0
        sound = True

    project = _project()
    object.__setattr__(project, "overlays", [Infographic()])
    assert _plan(project) == [SfxItem("pop", 6.0, 1.0, "overlays[0]")]  # sem registro: o padrão geral
    monkeypatch.setitem(sfx_plan.ENTRY_SOUND_DEFAULTS, "infographic", "impact")
    assert _plan(project) == [SfxItem("impact", 6.0, 1.0, "overlays[0]")]


def test_explicit_entry_and_transition_sounds_merge_in_time_order():
    project = _project(
        timeline=[
            {"type": "card", "title": "Um", "duration": 4},
            {
                "type": "card",
                "title": "Dois",
                "duration": 4,
                "transition": {"type": "fade", "duration": 0.5, "sound": True},
            },
        ],
        overlays=[{"type": "text", "text": "A", "start": 1, "sound": True}],
        audio={"sfx": [{"sound": "riser", "at": 2.0}]},
    )
    assert [(i.sound, i.at, i.origin) for i in _plan(project)] == [
        ("pop", 1.0, "overlays[0]"),
        ("riser", 2.0, "audio.sfx[0]"),
        ("whoosh", 3.5, "timeline[1].transition"),
    ]
