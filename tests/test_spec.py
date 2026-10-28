import json

import pytest
from pydantic import ValidationError

from dmaker.domain.spec import (
    CardSegment,
    ClipSegment,
    MulticamBlock,
    Output,
    Project,
    SourceRef,
    TextOverlay,
    TrackState,
    Transition,
)

MINIMAL = {
    "name": "teste",
    "output": {"preset": "instagram/reels"},
    "timeline": [{"type": "clip", "src": "a.mp4"}],
}


def test_minimal_project():
    p = Project.model_validate(MINIMAL)
    assert p.output.preset == "instagram/reels"
    assert isinstance(p.timeline[0], ClipSegment)
    assert p.audio.normalize == "two-pass"
    assert p.captions is None


def test_unknown_field_rejected():
    bad = dict(MINIMAL, foo=1)
    with pytest.raises(ValidationError):
        Project.model_validate(bad)


def test_discriminated_segments():
    data = dict(MINIMAL)
    data["timeline"] = [
        {"type": "card", "title": "Abertura", "duration": 2},
        {
            "type": "image",
            "src": "foto.jpg",
            "duration": 3,
            "transition": {"type": "wipeleft", "duration": 0.4},
        },
        {"type": "clip", "src": "a.mp4", "start": 1, "end": 4, "speed": 1.5, "transition": {"type": "cut"}},
    ]
    p = Project.model_validate(data)
    assert isinstance(p.timeline[0], CardSegment)
    assert p.timeline[1].transition.type == "wipeleft"
    assert p.timeline[2].transition.type == "cut"


def test_transition_validation():
    with pytest.raises(ValidationError):
        Transition(type="explosao")
    with pytest.raises(ValidationError):
        Transition(type="fade", duration=0)


def test_clip_range_validation():
    with pytest.raises(ValidationError):
        ClipSegment(src="a.mp4", start=5, end=5)


def test_name_validation():
    with pytest.raises(ValidationError):
        Project.model_validate(dict(MINIMAL, name="a/b"))


def test_texts_enumerates_visible_strings():
    p = Project.model_validate(MINIMAL)
    p.timeline.append(CardSegment(title="Título", subtitle="Sub"))
    p.overlays.append(TextOverlay(text="Gancho", role="hook"))
    where = [w for w, _ in p.texts()]
    assert where == ["timeline[1].title", "timeline[1].subtitle", "overlays[0].text"]


def test_save_and_load_roundtrip(tmp_path):
    p = Project.model_validate(MINIMAL)
    p.output = Output(preset="youtube/shorts", quality="medium")
    path = p.save(tmp_path / "spec.json")
    loaded = Project.load(path)
    assert loaded.output.quality == "medium"
    assert loaded.base_dir == tmp_path.resolve()
    assert "base_dir" not in json.loads(path.read_text(encoding="utf-8"))


def test_resolve_relative_to_spec_dir(tmp_path):
    (tmp_path / "video.mp4").write_bytes(b"x")
    p = Project.model_validate(MINIMAL)
    p.base_dir = tmp_path
    assert p.resolve("video.mp4") == (tmp_path / "video.mp4").resolve()
    assert p.resolve("C:/x/y.mp4").is_absolute()


MULTICAM_BASE = {
    "name": "casamento",
    "sources": {
        "cam1": {"src": "cam1.mp4"},
        "cam2": {"src": "cam2.mp4", "sync": "auto"},
        "altar": {"src": "altar.wav", "sync": "auto"},
    },
    "timeline": [{"type": "clip", "source": "cam1", "start": 0, "end": 5}],
}


def test_multicam_block_accepts_known_sources():
    p = Project.model_validate(
        {
            **MULTICAM_BASE,
            "multicam": {"at": 1, "cameras": ["cam1", "cam2"], "main": "cam1", "audio": "altar"},
        }
    )
    assert isinstance(p.multicam, MulticamBlock)
    assert p.multicam.phases == "casamento"


def test_multicam_block_rejects_unknown_camera():
    with pytest.raises(ValidationError, match="desconhecida"):
        Project.model_validate(
            {
                **MULTICAM_BASE,
                "multicam": {"at": 1, "cameras": ["cam1", "cam9"], "main": "cam1", "audio": "altar"},
            }
        )


def test_multicam_block_rejects_main_outside_cameras():
    with pytest.raises(ValidationError, match="multicam.main"):
        Project.model_validate(
            {
                **MULTICAM_BASE,
                "multicam": {"at": 1, "cameras": ["cam1", "cam2"], "main": "altar", "audio": "altar"},
            }
        )


def test_multicam_block_accepts_audio_only_source_outside_cameras():
    """`audio` pode ser uma fonte só de áudio, que não precisa estar em `cameras`."""
    p = Project.model_validate(
        {
            **MULTICAM_BASE,
            "multicam": {"at": 1, "cameras": ["cam1", "cam2"], "main": "cam1", "audio": "altar"},
        }
    )
    assert p.multicam.audio == "altar"


def test_multicam_block_rejects_at_beyond_timeline():
    with pytest.raises(ValidationError, match="multicam.at"):
        Project.model_validate(
            {
                **MULTICAM_BASE,
                "multicam": {"at": 5, "cameras": ["cam1", "cam2"], "main": "cam1", "audio": "altar"},
            }
        )


def test_multicam_block_accepts_custom_phase_rules():
    p = Project.model_validate(
        {
            **MULTICAM_BASE,
            "multicam": {
                "at": 1,
                "cameras": ["cam1", "cam2"],
                "main": "cam1",
                "audio": "altar",
                "phases": [{"name": "votos", "match": ["te recebo"], "cadence": [60.0, 15.0]}],
            },
        }
    )
    assert p.multicam.phases[0].name == "votos"


def test_source_ref_requires_src_or_parts():
    with pytest.raises(ValidationError, match="um dos dois"):
        SourceRef.model_validate({})
    with pytest.raises(ValidationError, match="um dos dois"):
        SourceRef.model_validate({"src": "a.mp4", "parts": ["b.mp4", "c.mp4"]})
    with pytest.raises(ValidationError, match="um dos dois"):
        SourceRef.model_validate({"parts": []})


def test_source_ref_files_property():
    assert SourceRef.model_validate({"src": "a.mp4"}).files == ["a.mp4"]
    parted = SourceRef.model_validate({"parts": ["a1.mp4", "a2.mp4", "a3.mp4"]})
    assert parted.files == ["a1.mp4", "a2.mp4", "a3.mp4"]


def test_project_accepts_source_with_parts():
    spec = dict(
        MINIMAL,
        sources={"cam1": {"parts": ["a1.mp4", "a2.mp4"]}},
        timeline=[{"type": "clip", "source": "cam1", "start": 0, "end": 10}],
    )
    project = Project.model_validate(spec)
    assert project.sources["cam1"].parts == ["a1.mp4", "a2.mp4"]
    assert project.master_source == "cam1"


# ---------- tracks (mudo/oculto/bloqueio por trilha) ----------


def test_track_state_defaults_to_all_false():
    state = TrackState()
    assert (state.muted, state.hidden, state.locked) == (False, False, False)


def test_project_tracks_defaults_to_empty_dict():
    project = Project.model_validate(MINIMAL)
    assert project.tracks == {}


def test_project_accepts_track_state_by_id():
    spec = dict(MINIMAL, tracks={"A2": {"muted": True}, "TX": {"hidden": True}, "V1": {"locked": True}})
    project = Project.model_validate(spec)
    assert project.tracks["A2"].muted is True
    assert project.tracks["TX"].hidden is True
    assert project.tracks["V1"].locked is True
    assert project.tracks["A2"].hidden is False


def test_track_state_rejects_unknown_field():
    spec = dict(MINIMAL, tracks={"A2": {"invalid": True}})
    with pytest.raises(ValidationError):
        Project.model_validate(spec)


# ---------- narração por texto ----------


def test_narration_defaults_and_roundtrip():
    from dmaker.domain.spec import Narration

    narration = Narration(text="Olá, este é o DMaker.")
    assert narration.start == 0 and narration.volume == 1.0 and narration.speed == 1.0
    assert narration.language == "pt" and narration.voice is None and narration.seed is None
    project = Project.model_validate(
        {**MINIMAL, "audio": {"narration": [{"script": "roteiro.txt", "voice": "ana", "start": 0.5}]}}
    )
    assert project.audio.narration[0].script == "roteiro.txt"
    assert Project.model_validate_json(project.model_dump_json()).audio.narration == project.audio.narration


@pytest.mark.parametrize(
    "fields",
    [{}, {"text": "  "}, {"text": "a", "script": "b.txt"}],
    ids=["nenhum", "texto em branco", "os dois"],
)
def test_narration_needs_exactly_one_of_text_or_script(fields):
    with pytest.raises(ValidationError, match="`text`.*`script`"):
        Project.model_validate({**MINIMAL, "audio": {"narration": [fields]}})


@pytest.mark.parametrize(
    "fields",
    [{"start": -1}, {"volume": 5}, {"speed": 0.2}, {"speed": 3}, {"voz": "x"}],
    ids=["start", "volume", "lento", "rápido", "campo desconhecido"],
)
def test_narration_rejects_out_of_range_values(fields):
    with pytest.raises(ValidationError):
        Project.model_validate({**MINIMAL, "audio": {"narration": [{"text": "oi", **fields}]}})


def test_narration_captions_source_text_is_checked_like_on_screen_text():
    spec = {
        **MINIMAL,
        "audio": {"narration": [{"text": "Antes — depois"}]},
        "captions": {"source": "narration"},
    }
    assert ("audio.narration[0].text", "Antes — depois") in Project.model_validate(spec).texts()
    spec["captions"] = {"source": "auto"}
    assert Project.model_validate(spec).texts() == []


def test_clip_audio_mode_defaults_to_original_and_accepts_voice_and_background():
    def clip(**fields):
        return Project.model_validate({**MINIMAL, "timeline": [{"type": "clip", "src": "a.mp4", **fields}]})

    assert clip().timeline[0].audio_mode == "original"
    assert clip(audio_mode="voice").timeline[0].audio_mode == "voice"
    assert clip(audio_mode="background").timeline[0].audio_mode == "background"
    with pytest.raises(ValidationError):
        clip(audio_mode="instrumental")


def test_audio_mode_is_in_the_json_schema():
    schema = Project.model_json_schema()
    clip = schema["$defs"]["ClipSegment"]["properties"]["audio_mode"]
    assert clip["enum"] == ["original", "voice", "background"] and clip["default"] == "original"


def test_flat_card_needs_no_title_but_a_plain_card_still_does():
    flat = Project.model_validate(
        {**MINIMAL, "timeline": [{"type": "card", "flat": True, "background": "#F1E8D8"}]}
    )
    assert flat.timeline[0].flat and flat.timeline[0].title == ""
    with pytest.raises(ValidationError, match="flat"):
        Project.model_validate({**MINIMAL, "timeline": [{"type": "card"}]})
    assert (
        Project.model_validate({**MINIMAL, "timeline": [{"type": "card", "title": "a"}]}).timeline[0].flat
        is False
    )


def test_regions_and_their_users_are_in_the_json_schema():
    """O que a spec aceita, o que o MCP publica (`spec_schema`) e a interface leem é o mesmo esquema."""
    schema = Project.model_json_schema()
    defs = schema["$defs"]
    assert set(defs["Region"]["properties"]) == {"x", "y", "width", "height"}
    assert "regions" in schema["properties"]
    for overlay in ("TextOverlay", "ImageOverlay", "VideoOverlay"):
        assert "region" in defs[overlay]["properties"], overlay
    assert {"x", "y"} <= set(defs["ImageOverlay"]["properties"])
    assert "focus" in defs["VideoOverlay"]["properties"]
    assert "flat" in defs["CardSegment"]["properties"]
    assert defs["CaptionStyle"]["properties"]["follow_background"]["default"] is True


def test_specs_written_before_regions_validate_and_dump_the_same_overlays():
    spec = {
        **MINIMAL,
        "overlays": [
            {"type": "image", "src": "logo", "position": "top-right"},
            {"type": "video", "src": "cam.mp4", "x": 0.5, "y": 0.5},
        ],
    }
    project = Project.model_validate(spec)
    assert project.regions == {} and project.overlays[0].x is None and project.overlays[1].focus == (0.5, 0.5)
    again = Project.model_validate_json(project.model_dump_json(exclude_none=True))
    assert again == project  # salvar e reabrir (o que o projeto faz) não muda nada


def test_video_focus_must_stay_inside_the_source():
    with pytest.raises(ValidationError, match="focus"):
        Project.model_validate(
            {**MINIMAL, "overlays": [{"type": "video", "src": "a.mp4", "focus": [0.5, 1.4]}]}
        )
