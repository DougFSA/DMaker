"""Subcomandos `dmaker models`: listar, baixar, apagar e limpar sobras, numa pasta de cache temporária."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.pipeline.models_service import ModelService

runner = CliRunner()


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", folder)
    # a tabela tem seis colunas: em 80 colunas (o padrão sem terminal) o Rich cortaria os textos
    monkeypatch.setattr("dmaker.cli.console", Console(width=200))
    return folder


def write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_list_shows_every_model_with_license_purpose_state_and_the_total(models_dir: Path):
    write(models_dir / "demucs" / "peso.bin", 84_025_501)
    write(models_dir / "sobra" / "x.bin", 2048)
    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0, result.output
    out = result.output
    for model_id in ("omnivoice", "kokoro-int8", "demucs-htdemucs", "whisper-small", "rvm-resnet50"):
        assert model_id in out
    assert "baixado" in out and "ausente" in out and "Apache-2.0" in out and "MIT" in out
    assert "80,1 MB" in out  # tamanho medido em disco
    assert "Sobras" in out and "sobra" in out
    assert "Total ocupado" in out and "livre no disco" in out


def test_remove_asks_before_deleting_and_says_what_stops_working(models_dir: Path):
    write(models_dir / "demucs" / "peso.bin", 84_025_501)
    refused = runner.invoke(app, ["models", "remove", "demucs-htdemucs"], input="n\n")
    assert (
        refused.exit_code == 0
        and "Isolamento vocal" in refused.output
        and "Nada foi apagado" in refused.output
    )
    assert (models_dir / "demucs" / "peso.bin").exists()
    accepted = runner.invoke(app, ["models", "remove", "demucs-htdemucs"], input="s\n")
    assert accepted.exit_code == 0 and "Apagado" in accepted.output
    assert not (models_dir / "demucs").exists()


def test_remove_with_yes_skips_the_question_but_still_shows_the_warning(models_dir: Path):
    write(models_dir / "demucs" / "peso.bin", 84_025_501)
    result = runner.invoke(app, ["models", "remove", "demucs-htdemucs", "--yes"])
    assert result.exit_code == 0 and "deixam de funcionar" in result.output
    assert not (models_dir / "demucs").exists()


def test_remove_reports_errors_in_portuguese_with_exit_code_1(models_dir: Path):
    unknown = runner.invoke(app, ["models", "remove", "fantasma", "--yes"])
    assert unknown.exit_code == 1 and "fantasma" in unknown.output and "omnivoice" in unknown.output
    absent = runner.invoke(app, ["models", "remove", "omnivoice", "--yes"])
    assert absent.exit_code == 1 and "não está baixado" in absent.output


def test_prune_lists_the_leftovers_and_deletes_only_them_after_confirmation(models_dir: Path):
    write(models_dir / "demucs" / "peso.bin", 84_025_501)
    write(models_dir / "sobra" / "x.bin", 10)
    refused = runner.invoke(app, ["models", "prune"], input="n\n")
    assert "sobra" in refused.output and "Nada foi apagado" in refused.output
    assert (models_dir / "sobra" / "x.bin").exists()
    done = runner.invoke(app, ["models", "prune", "--yes"])
    assert done.exit_code == 0 and "Sobras apagadas" in done.output
    assert not (models_dir / "sobra").exists() and (models_dir / "demucs" / "peso.bin").exists()
    nothing = runner.invoke(app, ["models", "prune", "--yes"])
    assert "Não há sobras" in nothing.output


def test_download_shows_progress_and_checks_the_result(models_dir: Path, monkeypatch):
    def fake_fetch(directory: Path, variant: str) -> None:
        write(directory / "demucs" / "peso.bin", 84_025_501)

    monkeypatch.setattr(
        "dmaker.cli._models_service",
        lambda: ModelService(fetcher_for=lambda dotted: fake_fetch, disk_free=lambda path: 10**12),
    )
    result = runner.invoke(app, ["models", "download", "demucs-htdemucs"])
    assert result.exit_code == 0, result.output
    assert "Pronto" in result.output and "80,1 MB" in result.output
    again = runner.invoke(app, ["models", "download", "fantasma"])
    assert again.exit_code == 1 and "fantasma" in again.output
