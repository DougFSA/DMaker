"""A versão do pacote: uma fonte só, no formato X.Y.Z, a mesma da versão lançada (DMK-48)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from dmaker import __version__
from dmaker.cli import app

REPO = Path(__file__).resolve().parents[1]
cli = CliRunner()


def test_package_version_is_x_y_z():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_pyproject_reads_the_version_from_the_package_instead_of_repeating_it():
    """O número vive em `dmaker.__version__`: um segundo `version` no pyproject voltaria a divergir."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in pyproject["project"]
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "dmaker.__version__"}


def _last_closed_release() -> str | None:
    """O nome da versão do cabeçalho `## vX — AAAA-MM-DD` mais recente do CHANGELOG (o `[Não lançado]` não conta)."""
    for line in (REPO / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        found = re.match(r"## v(\d+(?:\.\d+){0,2})\b", line)
        if found:
            return found.group(1)
    return None


def _as_x_y_z(release: str) -> str:
    parts = release.split(".")
    return ".".join(parts + ["0"] * (3 - len(parts)))


def test_package_version_is_the_last_release_closed_in_the_changelog():
    """Fechar a versão no CHANGELOG sem subir o `__version__` deixaria o `dmaker --version` mentindo."""
    release = _last_closed_release()
    assert release is not None, "o CHANGELOG não tem nenhuma versão fechada"
    assert __version__ == _as_x_y_z(release), (
        f"o CHANGELOG fechou a v{release}, então o __version__ de src/dmaker/__init__.py tem que ser "
        f"{_as_x_y_z(release)} (dmaker-producao, passo 7)"
    )


def test_as_x_y_z_completes_a_release_name():
    assert _as_x_y_z("2") == "2.0.0"
    assert _as_x_y_z("3.1") == "3.1.0"
    assert _as_x_y_z("3.1.4") == "3.1.4"


def test_version_option_prints_the_version_and_exits_zero_without_a_command():
    result = cli.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"dmaker {__version__}"


def test_version_option_wins_over_the_command_that_follows_it():
    """Eager: a versão sai antes de qualquer comando ser lido ou rodado."""
    result = cli.invoke(app, ["--version", "doctor"])
    assert result.exit_code == 0
    assert result.output.strip() == f"dmaker {__version__}"


def test_help_still_lists_the_commands_and_the_version_option():
    result = cli.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in result.output and "Mostra a versão." in result.output
    assert "doctor" in result.output and "render" in result.output


def test_running_without_a_command_still_shows_the_help():
    result = cli.invoke(app, [])
    assert "Usage" in result.output and "doctor" in result.output
