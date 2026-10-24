"""Modelo do projeto de dublagem: validação, edição de uma fala e ida e volta pelo disco."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmaker.domain.dub import DubProject, DubSegment, DubSpeaker, load_dub_project, save_dub_project


def segment(id: str = "s1", start: float = 1.0, end: float = 3.0, **extra) -> DubSegment:
    return DubSegment(id=id, start=start, end=end, source_text="Olá.", text="Hello.", **extra)


def project(**extra) -> DubProject:
    options = {
        "source": "video.mp4",
        "target_language": "en",
        "segments": [segment("s1"), segment("s2", 4.0, 6.0)],
    }
    return DubProject(**{**options, **extra})


def test_defaults_describe_a_single_voice_free_dubbing():
    p = project()
    assert (p.source_language, p.speaker_mode, p.voice, p.keep_original_db) == (
        "pt",
        "per_segment",
        None,
        None,
    )
    assert p.segments[0].speaker is None and p.segments[0].locked is False and p.segments[0].duration == 2.0


def test_a_segment_must_end_after_it_starts_and_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="maior que o início"):
        segment(start=3.0, end=3.0)
    with pytest.raises(ValidationError):
        DubSegment(id="s1", start=0, end=1, source_text="a", text="b", cor="azul")
    with pytest.raises(ValidationError):
        project(speaker_mode="coro")


def test_segment_ids_must_be_unique():
    with pytest.raises(ValidationError, match="repetidos: s1"):
        project(segments=[segment("s1"), segment("s1", 4.0, 5.0)])


def test_the_original_voice_level_cannot_be_above_zero_db():
    assert project(keep_original_db=-18.0).keep_original_db == -18.0
    with pytest.raises(ValidationError):
        project(keep_original_db=3.0)


def test_edited_changes_one_segment_and_returns_a_copy():
    p = project()
    changed = p.edited("s2", text="Bye.", locked=True)
    assert (changed.segment("s2").text, changed.segment("s2").locked) == ("Bye.", True)
    assert changed.segment("s1") == p.segment("s1") and p.segment("s2").text == "Hello."
    assert p.edited("s1", locked=True).segment("s1").text == "Hello."  # só a trava
    with pytest.raises(KeyError, match="s9"):
        p.edited("s9", text="x")


def test_save_and_load_roundtrip_with_accents_and_folders(tmp_path: Path):
    p = project(translator_model="gpt-oss:20b", glossary=["DMaker"])
    p = p.edited("s1", text="Olá, são João!")
    path = save_dub_project(p, tmp_path / "pasta" / "v.en.dub.json")
    assert "são João" in path.read_text(encoding="utf-8")  # sem escapes \u: o JSON é editável à mão
    assert load_dub_project(path) == p


def test_loading_a_missing_or_invalid_project_explains(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        load_dub_project(tmp_path / "nada.dub.json")
    broken = tmp_path / "x.dub.json"
    broken.write_text('{"source": "a"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_dub_project(broken)


# ---------- falantes (diarização) ----------


def speakers_project() -> DubProject:
    return project(
        speaker_mode="per_speaker",
        speakers=[
            DubSpeaker(name="Falante 1", reference_start=1.0, reference_end=6.0, reference_text="uma frase"),
            DubSpeaker(name="Falante 2"),
        ],
        segments=[segment("s1", speaker="Falante 1"), segment("s2", 4.0, 6.0, speaker="Falante 2")],
    )


def test_a_project_without_speakers_still_loads_as_before(tmp_path: Path):
    path = tmp_path / "antigo.dub.json"
    save_dub_project(project(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["speakers"]  # um projeto gravado antes da diarização não tem o campo
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_dub_project(path)
    assert loaded.speakers == [] and loaded.speaker_names == [] and loaded.speaker_mode == "per_segment"


def test_the_per_speaker_project_goes_through_the_disk(tmp_path: Path):
    saved = save_dub_project(speakers_project(), tmp_path / "p.dub.json")
    loaded = load_dub_project(saved)
    assert loaded == speakers_project() and loaded.speaker_names == ["Falante 1", "Falante 2"]
    assert loaded.speakers[0].has_reference and not loaded.speakers[1].has_reference


def test_a_speaker_reference_needs_both_ends_in_order_and_its_text():
    with pytest.raises(ValidationError, match="início e fim juntos"):
        DubSpeaker(name="Falante 1", reference_start=1.0)
    with pytest.raises(ValidationError, match="maior que o início"):
        DubSpeaker(name="Falante 1", reference_start=5.0, reference_end=5.0, reference_text="x")
    with pytest.raises(ValidationError, match="texto falado"):
        DubSpeaker(name="Falante 1", reference_start=1.0, reference_end=5.0)


def test_segments_may_only_name_speakers_the_project_lists():
    with pytest.raises(ValidationError, match="Falante 3"):
        project(speakers=[DubSpeaker(name="Falante 1")], segments=[segment("s1", speaker="Falante 3")])
    with pytest.raises(ValidationError, match="repetidos"):
        project(speakers=[DubSpeaker(name="Falante 1"), DubSpeaker(name="Falante 1")])


def test_edited_swaps_the_speaker_of_one_segment_only():
    changed = speakers_project().edited("s1", speaker="Falante 2")
    assert [s.speaker for s in changed.segments] == ["Falante 2", "Falante 2"]
    assert changed.segment("s1").text == "Hello." and speakers_project().segment("s1").speaker == "Falante 1"


def test_edited_refuses_an_unknown_speaker_and_says_which_exist():
    with pytest.raises(ValueError, match="Falante 9.*Falante 1, Falante 2"):
        speakers_project().edited("s1", speaker="Falante 9")
    with pytest.raises(ValueError, match="per_speaker"):
        project().edited("s1", speaker="Falante 1")
