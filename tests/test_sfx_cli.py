"""Comandos `dmaker sfx`: listar a biblioteca e gerá-la de novo."""

from __future__ import annotations

from typer.testing import CliRunner

from dmaker.cli import app
from dmaker.sfx import library_names

runner = CliRunner()


def test_sfx_list_shows_every_library_sound_as_present():
    result = runner.invoke(app, ["sfx", "list"])
    assert result.exit_code == 0
    for name in library_names():
        assert name in result.output
    assert "dmaker sfx build" not in result.output  # a biblioteca versionada está inteira no disco


def test_sfx_build_writes_the_library_to_the_chosen_folder(tmp_path):
    result = runner.invoke(app, ["sfx", "build", "--out", str(tmp_path / "sons")])
    assert result.exit_code == 0
    written = sorted(path.name for path in (tmp_path / "sons").iterdir())
    assert written == sorted([*(f"{name}.wav" for name in library_names()), "LICENSES"])


def test_the_sfx_group_is_on_the_cli():
    result = runner.invoke(app, ["--help"])
    assert "sfx" in result.output
