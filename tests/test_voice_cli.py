"""Subcomandos `dmaker voice`: biblioteca pela linha de comando (sem carregar o modelo)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from dmaker.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def temporary_library(monkeypatch, tmp_path):
    monkeypatch.setattr("dmaker.voice.library.VOICES_DIR", tmp_path / "voices")


def test_design_list_and_remove_roundtrip():
    initial = runner.invoke(app, ["voice", "list"]).output
    assert "dora" in initial and "kokoro" in initial and "locutora" not in initial

    created = runner.invoke(app, ["voice", "design", "Locutora", "--gender", "feminino", "--pitch", "grave"])
    assert created.exit_code == 0, created.output
    assert "locutora" in created.output and "female, low pitch" in created.output

    listed = runner.invoke(app, ["voice", "list"])
    assert "locutora" in listed.output and "design" in listed.output and "omnivoice" in listed.output

    removed = runner.invoke(app, ["voice", "remove", "locutora"])
    assert removed.exit_code == 0 and "locutora" not in runner.invoke(app, ["voice", "list"]).output


def test_errors_are_reported_in_portuguese_with_exit_code_1():
    unknown = runner.invoke(app, ["voice", "remove", "fantasma"])
    assert unknown.exit_code == 1 and "fantasma" in unknown.output

    preset = runner.invoke(app, ["voice", "remove", "dora"])
    assert preset.exit_code == 1 and "voz pronta" in preset.output

    invalid = runner.invoke(app, ["voice", "design", "Estranha", "--gender", "robô"])
    assert invalid.exit_code == 1 and "Gênero inválido" in invalid.output

    empty = runner.invoke(app, ["voice", "design", "Vazia"])
    assert empty.exit_code == 1 and "pelo menos um atributo" in empty.output


def test_say_without_text_asks_for_it():
    result = runner.invoke(app, ["voice", "say"])
    assert result.exit_code == 1 and "Informe o texto" in result.output
