import json

import pytest
from pydantic import ValidationError

from dmaker.domain.spec import CardSegment, ClipSegment, Output, Project, TextOverlay, Transition

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
