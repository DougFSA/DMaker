"""`dmaker release publish` (DMK-71): a ordem dos comandos do gh, as recusas e a retomada. Nunca toca o GitHub de verdade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.release.checksums import sha256_file
from dmaker.release.publish import (
    NOTES_NAME,
    SUMS_NAME,
    PublishOptions,
    ReleasePublisher,
    parse_release_version,
)
from dmaker.release.runner import RecordedCommand, ReleaseError

FILES = {
    "DMaker-2.0.0-windows-x64.exe": b"setup",
    "DMaker-2.0.0-windows-x64-1.bin": b"dados windows",
    "DMaker-2.0.0-linux-x64.run": b"#!/bin/sh\n",
    "DMaker-2.0.0-linux-x64-1.part": b"dados linux",
}


class FakeGh:
    """Responde ao `git ls-remote` e ao `gh` como o GitHub responderia, e guarda cada comando."""

    def __init__(
        self,
        *,
        tag_exists: bool = True,
        release_exists: bool = False,
        assets: list[dict] | None = None,
        draft: bool = False,
    ):
        self.tag_exists = tag_exists
        self.release_exists = release_exists
        self.assets = assets or []
        self.draft = draft
        self.commands: list[RecordedCommand] = []

    def run(self, command, *, cwd=None, env=None, check=True, quiet=False):
        recorded = tuple(str(part) for part in command)
        self.commands.append(RecordedCommand(recorded, cwd, env, quiet))
        if recorded[:2] == ("git", "ls-remote"):
            return "abc123\trefs/tags/v2\n" if self.tag_exists else ""
        if recorded[:3] == ("gh", "release", "list"):
            return json.dumps([{"tagName": "v2"}] if self.release_exists else [{"tagName": "v1"}])
        if recorded[:3] == ("gh", "release", "view") and "assets,isDraft" in recorded:
            return json.dumps({"assets": self.assets, "isDraft": self.draft})
        if recorded[:3] == ("gh", "release", "view") and "url" in recorded:
            return json.dumps({"url": "https://github.com/DougFSA/DMaker/releases/tag/v2"})
        return ""

    def gh_calls(self) -> list[tuple[str, ...]]:
        return [c.command for c in self.commands if c.command[0] == "gh"]


@pytest.fixture
def release_folder(tmp_path):
    folder = tmp_path / "releases" / "v2.0.0"
    folder.mkdir(parents=True)
    for name, data in FILES.items():
        (folder / name).write_bytes(data)
    (folder / SUMS_NAME).write_text(
        "".join(f"{sha256_file(folder / name)}  {name}\n" for name in FILES), encoding="utf-8"
    )
    (folder / NOTES_NAME).write_text("# notas\n", encoding="utf-8")
    return folder


def publisher(tmp_path, runner, version="2", package_version="2.0.0"):
    options = PublishOptions(
        version=version, main_root=tmp_path, repo_root=tmp_path / "clone", package_version=package_version
    )
    return ReleasePublisher(options, runner, log=lambda _line: None)


def test_version_names():
    assert parse_release_version("2") == ("v2", "2.0.0")
    assert parse_release_version("v2") == ("v2", "2.0.0")
    assert parse_release_version("2.0.0") == ("v2", "2.0.0")
    with pytest.raises(ReleaseError, match="Versão inválida"):
        parse_release_version("2.1.0")
    with pytest.raises(ReleaseError, match="Versão inválida"):
        parse_release_version("dois")


def test_creates_the_release_with_every_file_and_the_sums(tmp_path, release_folder):
    runner = FakeGh()
    result = publisher(tmp_path, runner).publish()
    order = [c.command[:3] for c in runner.commands]
    assert order == [
        ("git", "ls-remote", "--tags"),
        ("gh", "release", "list"),
        ("gh", "release", "create"),
        ("gh", "release", "view"),
    ]
    create = next(c for c in runner.gh_calls() if c[2] == "create")
    assert create[3] == "v2" and "--title" in create and create[create.index("--title") + 1] == "DMaker 2"
    assert create[create.index("--notes-file") + 1].endswith(NOTES_NAME) and "--verify-tag" in create
    uploaded = [
        Path(part).name for part in create if part.startswith(str(tmp_path)) and not part.endswith(NOTES_NAME)
    ]
    assert sorted(uploaded) == sorted([*FILES, SUMS_NAME])
    assert result.created and result.url.endswith("/tag/v2") and sorted(result.uploaded) == sorted(uploaded)


def test_refuses_without_the_tag_on_origin(tmp_path, release_folder):
    runner = FakeGh(tag_exists=False)
    with pytest.raises(ReleaseError, match="A tag v2 não existe no origin"):
        publisher(tmp_path, runner).publish()
    assert runner.gh_calls() == []  # nada foi ao GitHub


def test_refuses_when_the_package_version_does_not_match_the_tag(tmp_path, release_folder):
    runner = FakeGh()
    with pytest.raises(ReleaseError, match="não bate com a tag"):
        publisher(tmp_path, runner, package_version="3.0.0").publish()
    assert runner.gh_calls() == []


def test_refuses_a_file_whose_hash_changed(tmp_path, release_folder):
    (release_folder / "DMaker-2.0.0-linux-x64-1.part").write_bytes(b"adulterado")
    runner = FakeGh()
    with pytest.raises(ReleaseError, match="SHA-256 de DMaker-2.0.0-linux-x64-1.part não bate"):
        publisher(tmp_path, runner).publish()
    assert runner.gh_calls() == []


def test_refuses_a_file_of_two_gib_or_more(tmp_path, release_folder, monkeypatch):
    from dmaker.release import publish as module

    monkeypatch.setattr(module, "GITHUB_FILE_LIMIT", 6)  # "setup" tem 5 bytes; "dados linux" passa
    runner = FakeGh()
    with pytest.raises(ReleaseError, match="passa de 2 GiB"):
        publisher(tmp_path, runner).publish()
    assert runner.gh_calls() == []


def test_refuses_files_the_sums_do_not_list(tmp_path, release_folder):
    (release_folder / "DMaker-2.0.0-linux-x64-2.part").write_bytes(b"sobrou de um build velho")
    with pytest.raises(ReleaseError, match="não lista"):
        publisher(tmp_path, FakeGh()).publish()


def test_refuses_a_missing_file_listed_in_the_sums(tmp_path, release_folder):
    (release_folder / "DMaker-2.0.0-windows-x64-1.bin").unlink()
    with pytest.raises(ReleaseError, match="não está em"):
        publisher(tmp_path, FakeGh()).publish()


def test_resume_uploads_only_what_is_missing(tmp_path, release_folder):
    done = [
        {"name": "DMaker-2.0.0-windows-x64.exe", "size": len(b"setup"), "state": "uploaded"},
        {"name": "DMaker-2.0.0-windows-x64-1.bin", "size": len(b"dados windows"), "state": "uploaded"},
        {"name": "DMaker-2.0.0-linux-x64.run", "size": len(b"#!/bin/sh\n"), "state": "uploaded"},
    ]
    runner = FakeGh(release_exists=True, assets=done)
    result = publisher(tmp_path, runner).publish()
    calls = runner.gh_calls()
    uploads = [c for c in calls if c[2] == "upload"]
    assert [Path(c[4]).name for c in uploads] == ["DMaker-2.0.0-linux-x64-1.part", SUMS_NAME]
    assert not any(c[2] == "create" for c in calls)
    assert len(result.already_there) == 3 and not result.created


def test_resume_replaces_a_file_the_drop_left_half_sent(tmp_path, release_folder):
    assets = [
        {"name": "DMaker-2.0.0-windows-x64.exe", "size": len(b"setup"), "state": "uploaded"},
        {"name": "DMaker-2.0.0-windows-x64-1.bin", "size": 3, "state": "starter"},
    ]
    runner = FakeGh(release_exists=True, assets=assets)
    publisher(tmp_path, runner).publish()
    calls = runner.gh_calls()
    deleted = [c for c in calls if c[2] == "delete-asset"]
    assert [c[4] for c in deleted] == ["DMaker-2.0.0-windows-x64-1.bin"]
    uploaded = [Path(c[4]).name for c in calls if c[2] == "upload"]
    assert "DMaker-2.0.0-windows-x64-1.bin" in uploaded and "DMaker-2.0.0-windows-x64.exe" not in uploaded
    first_delete = calls.index(deleted[0])
    first_upload = next(i for i, c in enumerate(calls) if c[2] == "upload")
    assert first_delete < first_upload  # apaga o pedaço velho antes de subir de novo


def test_a_second_run_with_everything_there_sends_nothing(tmp_path, release_folder):
    assets = [
        {"name": name, "size": (release_folder / name).stat().st_size, "state": "uploaded"}
        for name in [*FILES, SUMS_NAME]
    ]
    runner = FakeGh(release_exists=True, assets=assets)
    result = publisher(tmp_path, runner).publish()
    assert not [c for c in runner.gh_calls() if c[2] in {"upload", "create", "delete-asset"}]
    assert result.uploaded == [] and len(result.already_there) == len(FILES) + 1


def _uploaded(release_folder, names) -> list[dict]:
    return [
        {"name": name, "size": (release_folder / name).stat().st_size, "state": "uploaded"} for name in names
    ]


def test_resume_publishes_the_draft_an_interrupted_upload_left(tmp_path, release_folder):
    """O `gh release create` só publica depois do último arquivo: a queda no meio deixa um rascunho (DMK-76)."""
    some = _uploaded(release_folder, ["DMaker-2.0.0-windows-x64.exe", "DMaker-2.0.0-linux-x64.run"])
    runner = FakeGh(release_exists=True, assets=some, draft=True)
    result = publisher(tmp_path, runner).publish()
    calls = runner.gh_calls()
    edits = [c for c in calls if c[2] == "edit"]
    assert len(edits) == 1 and "--draft=false" in edits[0]
    last_upload = max(i for i, c in enumerate(calls) if c[2] == "upload")
    assert calls.index(edits[0]) > last_upload  # só publica com todos os arquivos lá
    assert result.published_draft and not result.created


def test_resume_publishes_a_complete_draft_without_sending_anything(tmp_path, release_folder):
    """A queda pode vir depois do último arquivo e antes da publicação: sobra só publicar."""
    runner = FakeGh(release_exists=True, assets=_uploaded(release_folder, [*FILES, SUMS_NAME]), draft=True)
    result = publisher(tmp_path, runner).publish()
    calls = runner.gh_calls()
    assert not [c for c in calls if c[2] in {"upload", "create", "delete-asset"}]
    assert [c for c in calls if c[2] == "edit" and "--draft=false" in c]
    assert result.published_draft and result.uploaded == []


def test_resume_of_a_published_release_leaves_the_draft_flag_alone(tmp_path, release_folder):
    runner = FakeGh(release_exists=True, assets=_uploaded(release_folder, [*FILES, SUMS_NAME]))
    result = publisher(tmp_path, runner).publish()
    edits = [c for c in runner.gh_calls() if c[2] == "edit"]
    assert len(edits) == 1 and "--draft=false" not in edits[0]
    assert not result.published_draft


def test_a_new_release_is_not_reported_as_a_published_draft(tmp_path, release_folder):
    result = publisher(tmp_path, FakeGh()).publish()
    assert result.created and not result.published_draft
