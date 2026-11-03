"""Gravação atômica da spec e revisão do conteúdo: ninguém lê o arquivo pela metade, e a revisão muda com ele."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from dmaker.domain import atomic_file
from dmaker.domain.atomic_file import content_revision, read_bytes_retrying, write_bytes_atomic
from dmaker.domain.spec import Project
from dmaker.pipeline.projects import (
    load_project_with_revision,
    project_revision,
    save_project,
    spec_revision,
)

SPEC = {
    "name": "revisao",
    "timeline": [{"type": "card", "title": "Um", "duration": 1.0, "motion": "none"}],
    "audio": {"normalize": "off"},
}


def test_revision_is_stable_for_the_same_bytes_and_changes_with_any_byte():
    assert content_revision(b"abc") == content_revision(b"abc")
    assert content_revision(b"abc") != content_revision(b"abd")
    assert len(content_revision(b"abc")) == atomic_file.REVISION_LENGTH


def test_write_replaces_the_file_and_leaves_no_temporary_behind(tmp_path):
    target = tmp_path / "pasta" / "spec.json"  # a pasta ainda não existe
    write_bytes_atomic(target, b"um")
    write_bytes_atomic(target, b"dois")
    assert target.read_bytes() == b"dois"
    assert [p.name for p in target.parent.iterdir()] == ["spec.json"]


def test_a_denied_replace_is_retried_until_the_other_process_lets_go(tmp_path, monkeypatch):
    """No Windows, `os.replace` falha por um instante se alguém está com o arquivo aberto."""
    target = tmp_path / "spec.json"
    target.write_bytes(b"antigo")
    real_replace = os.replace
    attempts = []

    def flaky(source, destination):
        attempts.append(source)
        if len(attempts) < 3:
            raise PermissionError("em uso")
        real_replace(source, destination)

    monkeypatch.setattr(atomic_file.os, "replace", flaky)
    monkeypatch.setattr(atomic_file, "REPLACE_WAIT_SECONDS", 0)
    write_bytes_atomic(target, b"novo")
    assert len(attempts) == 3 and target.read_bytes() == b"novo"


def test_a_replace_that_never_works_raises_and_cleans_the_temporary(tmp_path, monkeypatch):
    target = tmp_path / "spec.json"
    target.write_bytes(b"antigo")

    def denied(source, destination):
        raise PermissionError("em uso")

    monkeypatch.setattr(atomic_file.os, "replace", denied)
    monkeypatch.setattr(atomic_file, "REPLACE_WAIT_SECONDS", 0)
    with pytest.raises(PermissionError):
        write_bytes_atomic(target, b"novo")
    assert target.read_bytes() == b"antigo"  # o arquivo original ficou como estava
    assert [p.name for p in tmp_path.iterdir()] == ["spec.json"]


def test_reading_while_the_file_is_swapped_never_sees_half_of_it(tmp_path):
    """Um escritor troca o arquivo entre dois conteúdos grandes enquanto o leitor lê sem parar: cada leitura é um
    dos dois conteúdos inteiros (com gravação direta, o leitor veria o arquivo truncado ou misturado)."""
    target = tmp_path / "spec.json"
    first, second = b"a" * 400_000, b"b" * 400_000
    target.write_bytes(first)
    stop = threading.Event()
    seen: list[bytes] = []

    def reader() -> None:
        while not stop.is_set():
            seen.append(read_bytes_retrying(target))

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for turn in range(60):
            write_bytes_atomic(target, second if turn % 2 == 0 else first)
    finally:
        stop.set()
        thread.join(10)
    assert seen and all(content in (first, second) for content in seen)


def test_project_save_is_atomic_and_its_revision_is_the_one_of_the_file(tmp_path):
    project = Project.model_validate(SPEC)
    path = project.save(tmp_path / "revisao" / "spec.json")
    assert [p.name for p in path.parent.iterdir()] == ["spec.json"]
    assert path.read_bytes() == project.to_bytes()
    assert content_revision(path.read_bytes()) == project_revision(project) == spec_revision(path)
    assert Project.load(path).name == "revisao"


def test_the_revision_changes_when_the_spec_is_saved_with_other_content(tmp_path):
    path = tmp_path / "spec.json"
    project = Project.model_validate(SPEC)
    project.save(path)
    before = spec_revision(path)
    changed = Project.model_validate(
        {**SPEC, "timeline": [{"type": "card", "title": "Dois", "duration": 1.0}]}
    )
    changed.save(path)
    assert spec_revision(path) != before
    project.save(path)
    assert spec_revision(path) == before  # voltar ao mesmo conteúdo volta à mesma revisão


def test_a_missing_spec_has_no_revision(tmp_path):
    assert spec_revision(tmp_path / "nada" / "spec.json") is None
    with pytest.raises(FileNotFoundError):
        load_project_with_revision(tmp_path / "nada" / "spec.json")


def test_load_with_revision_hashes_the_bytes_it_parsed(tmp_path):
    path = tmp_path / "spec.json"
    Project.model_validate(SPEC).save(path)
    project, revision = load_project_with_revision(path)
    assert revision == content_revision(Path(path).read_bytes())
    assert project.base_dir == tmp_path.resolve()


def test_save_project_writes_in_the_projects_folder(tmp_path):
    project = Project.model_validate(SPEC)
    path = save_project(project, tmp_path / "meu")
    assert path == tmp_path / "meu" / "spec.json" and project.base_dir == (tmp_path / "meu").resolve()
