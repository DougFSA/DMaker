"""Comandos `dmaker autocut`, `cuts` e `uncut` e as ferramentas MCP do corte automático, com Whisper falso."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from dmaker import cli, mcp_server
from dmaker.cli import app
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline import autocut as autocut_module
from dmaker.pipeline.autocut import AutoCutService, load_cut_report
from dmaker.pipeline.projects import load_project, project_path

from .test_autocut_service import FakeTranscriber, fake_prober, writes_the_recording

runner = CliRunner()


@pytest.fixture(autouse=True)
def fake_service(monkeypatch):
    def build(log=lambda message: None) -> AutoCutService:
        return AutoCutService(
            runner=RecordingRunner(on_run=writes_the_recording),
            prober=fake_prober,
            transcriber=FakeTranscriber(),
            log=log,
        )

    monkeypatch.setattr(autocut_module, "default_autocut_service", build)
    monkeypatch.setattr(mcp_server, "_autocut_service", lambda job=None: build())
    monkeypatch.setattr(cli, "console", Console(width=200))


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    path = tmp_path / "entrevista.mp4"
    path.write_bytes(b"\x00" * 64)
    return path


def test_autocut_creates_the_project_and_prints_the_summary_and_the_cut_table(recording):
    result = runner.invoke(
        app, ["autocut", str(recording), "--name", "cli-corte", "--intensity", "agressiva"]
    )

    assert result.exit_code == 0, result.output
    out = result.output
    assert "a menos" in out and "intensidade agressiva" in out
    for label in ("vício de fala", "frase repetida", "Hoje eu vou"):
        assert label in out
    assert "dmaker cuts cli-corte" in out and "dmaker uncut cli-corte" in out
    assert load_project("cli-corte").timeline
    assert load_cut_report(project_path("cli-corte").parent) is not None


def test_the_default_name_comes_from_the_recording(recording):
    result = runner.invoke(app, ["autocut", str(recording)])
    assert result.exit_code == 0, result.output
    assert project_path("entrevista-corte").exists()


def test_cuts_lists_and_uncut_gives_a_cut_back(recording):
    runner.invoke(app, ["autocut", str(recording), "--name", "volta"])
    report = load_cut_report(project_path("volta").parent)
    assert report is not None
    first = report.cuts[0]

    listing = runner.invoke(app, ["cuts", "volta"])
    assert listing.exit_code == 0 and str(first.id) in listing.output

    undone = runner.invoke(app, ["uncut", "volta", str(first.id)])
    assert undone.exit_code == 0, undone.output
    assert "(desfeito)" in undone.output
    assert load_cut_report(project_path("volta").parent).find(first.id).undone


def test_errors_are_printed_in_portuguese_with_a_failing_exit_code(recording, tmp_path):
    missing = runner.invoke(app, ["autocut", str(tmp_path / "nao-existe.mp4")])
    assert missing.exit_code == 1 and "não encontrada" in missing.output
    wrong = runner.invoke(app, ["autocut", str(recording), "--intensity", "brutal"])
    assert wrong.exit_code == 1 and "intensidade inválida" in wrong.output
    no_list = runner.invoke(app, ["cuts", "inexistente"])
    assert no_list.exit_code == 1 and "não tem lista de cortes" in no_list.output
    runner.invoke(app, ["autocut", str(recording), "--name", "dup"])
    again = runner.invoke(app, ["autocut", str(recording), "--name", "dup"])
    assert again.exit_code == 1 and "já existe um projeto" in again.output
    assert runner.invoke(app, ["autocut", str(recording), "--name", "dup", "--overwrite"]).exit_code == 0


def test_the_mcp_tools_start_the_job_list_the_cuts_and_undo(recording):
    started = mcp_server.autocut(str(recording), "mcp-corte", intensity="agressiva", wait_seconds=30)
    assert started["status"] == "done", started
    assert started["result"]["project"] == "mcp-corte"

    listed = mcp_server.list_cuts("mcp-corte")
    assert listed["counts"]["filler"] == 2 and listed["cuts"][0]["id"] == 1

    after = mcp_server.undo_cut("mcp-corte", 1)
    assert after["cuts"][0]["undone"] is True
    assert after["duration_after_s"] > listed["duration_after_s"]


def test_the_mcp_tool_refuses_a_bad_request_before_starting_a_job(tmp_path):
    with pytest.raises(FileNotFoundError):
        mcp_server.autocut(str(tmp_path / "nao-existe.mp4"), "x")
    with pytest.raises(ValueError, match="não tem lista de cortes"):
        mcp_server.list_cuts("inexistente")
