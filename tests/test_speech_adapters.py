"""Adaptadores da correção de fala: `dmaker voice words|fix` e as ferramentas MCP `speech_words` e `fix_speech`,
sobre o mesmo serviço com dublês (sem Whisper, Demucs nem OmniVoice)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

import dmaker.mcp_server as mcp_server
from dmaker.cli import app
from tests.test_speech_fix import Harness

cli = CliRunner()


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


@pytest.fixture
def wired(monkeypatch, harness: Harness) -> Harness:
    monkeypatch.setattr(
        "dmaker.pipeline.speech_fix.default_speech_fix_service", lambda *args, **kwargs: harness.service
    )
    monkeypatch.setattr(mcp_server, "_speech_fix_service", lambda job: harness.service)
    monkeypatch.setattr("dmaker.voice.library.VOICES_DIR", harness.tmp_path / "voices")
    return harness


# ---------- CLI ----------


def test_cli_words_groups_the_words_by_breath(wired: Harness):
    result = cli.invoke(app, ["voice", "words", str(wired.src)])
    assert result.exit_code == 0, result.output
    assert "de João e Maria." in result.output
    assert "Hoje é casamento," in result.output
    assert "21.7 a 22.9 s" in result.output


def test_cli_words_detail_lists_one_word_per_line_with_times(wired: Harness):
    result = cli.invoke(app, ["voice", "words", str(wired.src), "--words"])
    assert result.exit_code == 0, result.output
    assert "João" in result.output and "21.80" in result.output and "22.20" in result.output


def test_cli_fix_by_text_reports_the_change_the_rule_and_the_time(wired: Harness, tmp_path: Path):
    out = tmp_path / "corrigido.mp4"
    result = cli.invoke(
        app, ["voice", "fix", str(wired.src), "--find", "joao", "--text", "Pedro", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "Pronto" in result.output and "corrigido.mp4" in result.output
    assert '"João" -> "Pedro"' in result.output
    assert "duração do trecho original mantida" in result.output
    assert "tempo de processamento" in result.output
    assert out.exists()
    assert wired.synthesizer.requests[0].text == "de Pedro e Maria."


def test_cli_fix_by_time_with_no_expand_and_draft(wired: Harness, tmp_path: Path):
    result = cli.invoke(
        app,
        [
            "voice",
            "fix",
            str(wired.src),
            "--start",
            "21.8",
            "--end",
            "22.2",
            "--text",
            "Pedro",
            "--no-expand",
            "--draft",
            "--out",
            str(tmp_path / "saida.mp4"),
        ],
    )
    assert result.exit_code == 0, result.output
    request = wired.synthesizer.requests[0]
    assert request.text == "Pedro" and request.steps == 8


def test_cli_fix_errors_are_portuguese_with_exit_code_1(wired: Harness, tmp_path: Path):
    neither = cli.invoke(app, ["voice", "fix", str(wired.src), "--text", "x"])
    assert neither.exit_code == 1 and "texto (find) ou por tempo" in neither.output

    missing = cli.invoke(app, ["voice", "fix", str(tmp_path / "nada.mp4"), "--find", "a", "--text", "b"])
    assert missing.exit_code == 1 and "não encontrado" in missing.output

    unknown = cli.invoke(app, ["voice", "fix", str(wired.src), "--find", "Joana", "--text", "b"])
    assert unknown.exit_code == 1 and "Não achei" in unknown.output and "dmaker voice words" in unknown.output

    no_text = cli.invoke(app, ["voice", "fix", str(wired.src), "--find", "João"])
    assert no_text.exit_code != 0  # --text é obrigatório


# ---------- MCP ----------


def test_speech_words_runs_as_a_job_and_returns_the_words(wired: Harness):
    started = mcp_server.speech_words(str(wired.src))
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)
    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "done", status.get("error")
    words = status["result"]["words"]
    assert [21.8, 22.2, "João"] in words and status["result"]["text"].startswith("a0 a1")


def test_fix_speech_runs_as_a_job_and_reports_what_changed(wired: Harness, tmp_path: Path):
    out = tmp_path / "mcp.mp4"
    started = mcp_server.fix_speech(str(wired.src), "Pedro", find="João", out=str(out))
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)
    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "done", status.get("error")
    result = status["result"]
    assert result["output"] == str(out) and result["old_text"] == "João" and result["new_text"] == "Pedro"
    assert result["spoken"] == "de Pedro e Maria." and "mantida" in result["duration_rule"]
    assert result["squeezed"] is False and result["voice"].startswith("falante-")
    assert status["progress"]["percent"] >= 95


def test_fix_speech_rejects_bad_calls_immediately(wired: Harness, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        mcp_server.fix_speech(str(tmp_path / "nada.mp4"), "x", find="a")
    with pytest.raises(ValueError, match="texto \\(find\\) ou por tempo"):
        mcp_server.fix_speech(str(wired.src), "x")
    with pytest.raises(ValueError, match="fantasma"):
        mcp_server.fix_speech(str(wired.src), "x", find="João", voice="fantasma")
    with pytest.raises(FileNotFoundError):
        mcp_server.speech_words(str(tmp_path / "nada.mp4"))


def test_fix_speech_job_failure_carries_the_message(wired: Harness):
    started = mcp_server.fix_speech(str(wired.src), "Joana", find="Joana inexistente")
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)
    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "error" and "Não achei" in status["error"]


def test_speech_tools_are_listed():
    tools = asyncio.run(mcp_server.server.list_tools())
    names = {tool.name for tool in tools}
    assert {"fix_speech", "speech_words"} <= names
