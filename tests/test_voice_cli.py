"""Subcomandos `dmaker voice`: biblioteca pela linha de comando (sem carregar o modelo)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def temporary_library(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "VOICES_DIR", tmp_path / "voices")


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


@pytest.fixture
def temporary_lexicons(monkeypatch, tmp_path):
    root = tmp_path / "assets"
    (root / "brands" / "medlycare").mkdir(parents=True)
    monkeypatch.setattr(config, "LEXICON_DIR", root)
    return root


def test_lexicon_add_list_and_remove_roundtrip(temporary_lexicons):
    empty = runner.invoke(app, ["voice", "lexicon", "list"])
    assert empty.exit_code == 0 and "Nenhum termo" in empty.output

    added = runner.invoke(app, ["voice", "lexicon", "add", "DMaker", "Di Meiker"])
    assert added.exit_code == 0, added.output
    assert "DMaker" in added.output and "Di Meiker" in added.output
    assert (temporary_lexicons / "pronunciation.json").is_file()

    listed = runner.invoke(app, ["voice", "lexicon", "list"])
    assert "DMaker" in listed.output and "Di Meiker" in listed.output and "global" in listed.output

    removed = runner.invoke(app, ["voice", "lexicon", "remove", "dmaker"])
    assert (
        removed.exit_code == 0 and "Nenhum termo" in runner.invoke(app, ["voice", "lexicon", "list"]).output
    )


def test_lexicon_with_brand_shows_global_and_brand_terms(temporary_lexicons):
    runner.invoke(app, ["voice", "lexicon", "add", "API", "êi-pi-ai"])
    runner.invoke(app, ["voice", "lexicon", "add", "MedlyCare", "Médli Quér", "--brand", "medlycare"])

    only_global = runner.invoke(app, ["voice", "lexicon", "list"]).output
    assert "API" in only_global and "MedlyCare" not in only_global

    with_brand = runner.invoke(app, ["voice", "lexicon", "list", "--brand", "medlycare"]).output
    assert "API" in with_brand and "MedlyCare" in with_brand and "medlycare" in with_brand
    assert (temporary_lexicons / "brands" / "medlycare" / "pronunciation.json").is_file()

    removed = runner.invoke(app, ["voice", "lexicon", "remove", "MedlyCare", "--brand", "medlycare"])
    assert removed.exit_code == 0
    assert "MedlyCare" not in runner.invoke(app, ["voice", "lexicon", "list", "--brand", "medlycare"]).output


def test_lexicon_errors_are_reported_in_portuguese_with_exit_code_1(temporary_lexicons):
    unknown_term = runner.invoke(app, ["voice", "lexicon", "remove", "fantasma"])
    assert unknown_term.exit_code == 1 and "não está no dicionário" in unknown_term.output

    unknown_brand = runner.invoke(
        app, ["voice", "lexicon", "add", "DMaker", "Di Meiker", "--brand", "nenhuma"]
    )
    assert unknown_brand.exit_code == 1 and "não encontrada" in unknown_brand.output

    bad_list = runner.invoke(app, ["voice", "lexicon", "list", "--brand", "../x"])
    assert bad_list.exit_code == 1 and "inválido" in bad_list.output


def test_say_passes_the_brand_to_the_narration(monkeypatch, tmp_path):
    from dmaker.pipeline.narration import NarrationResult

    received = {}

    def fake_speak(script, out, **options):
        received.update(options, script=script)
        return NarrationResult(tmp_path / "saida.wav", 1.0)

    monkeypatch.setattr("dmaker.pipeline.voices.build_synthesizer", lambda device: object())
    monkeypatch.setattr("dmaker.pipeline.voices.speak", fake_speak)

    result = runner.invoke(app, ["voice", "say", "O DMaker edita.", "--brand", "medlycare"])

    assert result.exit_code == 0, result.output
    assert received["brand"] == "medlycare" and received["script"] == "O DMaker edita."


def test_lexicon_commands_take_a_language_that_defaults_to_portuguese(temporary_lexicons):
    runner.invoke(app, ["voice", "lexicon", "add", "DMaker", "Di Mêiker"])
    added = runner.invoke(app, ["voice", "lexicon", "add", "MedlyCare", "Medly Care", "--language", "en-US"])
    assert added.exit_code == 0 and "en-US" in added.output

    everything = runner.invoke(app, ["voice", "lexicon", "list"]).output
    assert "DMaker" in everything and "MedlyCare" in everything and "idioma" in everything
    only_english = runner.invoke(app, ["voice", "lexicon", "list", "--language", "en"]).output
    assert "MedlyCare" in only_english and "DMaker" not in only_english

    wrong = runner.invoke(app, ["voice", "lexicon", "remove", "MedlyCare"])  # padrão pt: não existe lá
    assert wrong.exit_code == 1 and "idioma pt" in wrong.output
    right = runner.invoke(app, ["voice", "lexicon", "remove", "MedlyCare", "--language", "en"])
    assert right.exit_code == 0
    assert "MedlyCare" not in runner.invoke(app, ["voice", "lexicon", "list"]).output


def test_lexicon_list_reads_the_old_flat_json_as_portuguese(temporary_lexicons):
    (temporary_lexicons / "pronunciation.json").write_text('{"DMaker": "Di Mêiker"}', encoding="utf-8")

    listed = runner.invoke(app, ["voice", "lexicon", "list", "--language", "pt-BR"])

    assert listed.exit_code == 0 and "DMaker" in listed.output
