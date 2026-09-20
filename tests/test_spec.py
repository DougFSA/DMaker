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
