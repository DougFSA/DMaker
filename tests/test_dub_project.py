"""Modelo do projeto de dublagem: validação, edição de uma fala e ida e volta pelo disco."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from dmaker.domain.dub import DubProject, DubSegment, load_dub_project, save_dub_project


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
