"""Adaptadores do isolamento vocal: `dmaker audio isolate` e a ferramenta MCP `isolate_vocals`,
com separador falso (sem Demucs) e o ffmpeg gravado pelo RecordingRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import dmaker.mcp_server as mcp_server
from dmaker import config
from dmaker.cli import app
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.pipeline.isolation import IsolationService
from tests.test_isolation import FakeSeparator

cli = CliRunner()


def touch_any_output(command: FFmpegCommand) -> None:
    out = Path(command.args[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"audio")


@pytest.fixture
def media(tmp_path: Path) -> Path:
    path = tmp_path / "fala.mp4"
    path.write_bytes(b"video")
    return path


@pytest.fixture
def separator() -> FakeSeparator:
    return FakeSeparator()


@pytest.fixture(autouse=True)
def fake_backends(monkeypatch, tmp_path: Path, separator: FakeSeparator):
    runner = RecordingRunner(on_run=touch_any_output)
    monkeypatch.setattr(config, "STEMS_DIR", tmp_path / "stems")
    monkeypatch.setattr("dmaker.media.separation.DemucsSeparator", lambda device="auto": separator)
    monkeypatch.setattr("dmaker.media.ffmpeg.SubprocessRunner", lambda quiet=False, sink=None: runner)
    monkeypatch.setattr(
        "dmaker.pipeline.isolation.default_isolation_service",
        lambda runner_arg, log=None: IsolationService(separator, runner, log=log),
    )
    return runner


# ---------- CLI ----------


def test_cli_isolate_writes_voice_and_background_and_prints_the_paths(media: Path, tmp_path: Path):
    out = tmp_path / "saida"
    result = cli.invoke(
        app, ["audio", "isolate", str(media), "--start", "0", "--end", "30", "--out-dir", str(out)]
    )

    assert result.exit_code == 0, result.output
    assert (out / "fala_0-30s_voz.wav").read_bytes() == b"voz"
    assert (out / "fala_0-30s_fundo.wav").read_bytes() == b"fundo"
    assert "fala_0-30s_voz.wav" in result.output and "fala_0-30s_fundo.wav" in result.output
    assert "30.0s de áudio" in result.output and "fator" in result.output


def test_cli_isolate_reuses_the_cache(media: Path, tmp_path: Path, separator: FakeSeparator):
    args = ["audio", "isolate", str(media), "--start", "1", "--end", "5", "--out-dir", str(tmp_path / "o")]
    assert cli.invoke(app, args).exit_code == 0
    assert cli.invoke(app, args).exit_code == 0
    assert len(separator.calls) == 1


def test_cli_isolate_mp3_format(media: Path, tmp_path: Path, fake_backends: RecordingRunner):
    out = tmp_path / "mp3"
    result = cli.invoke(
        app, ["audio", "isolate", str(media), "--end", "4", "--format", "mp3", "--out-dir", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "fala_0-4s_voz.mp3").exists() and (out / "fala_0-4s_fundo.mp3").exists()


def test_cli_isolate_errors_are_portuguese_with_exit_code_1(media: Path, tmp_path: Path):
    missing = cli.invoke(app, ["audio", "isolate", str(tmp_path / "nada.mp4"), "--end", "5"])
    assert missing.exit_code == 1 and "não encontrado" in missing.output

    wrong_format = cli.invoke(app, ["audio", "isolate", str(media), "--end", "5", "--format", "ogg"])
    assert wrong_format.exit_code == 1 and "wav ou mp3" in wrong_format.output

    backwards = cli.invoke(app, ["audio", "isolate", str(media), "--start", "9", "--end", "3"])
    assert backwards.exit_code == 1 and "maior que start" in backwards.output


# ---------- MCP ----------


def test_isolate_vocals_runs_as_a_job_and_returns_the_paths(media: Path, tmp_path: Path):
    out = tmp_path / "mcp"
    started = mcp_server.isolate_vocals(str(media), start=2, end=12, out_dir=str(out))
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)

    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "done", status.get("error")
    assert status["result"] == {
        "voice": str(out / "fala_2-12s_voz.wav"),
        "background": str(out / "fala_2-12s_fundo.wav"),
    }
    assert status["progress"]["label"] == "bloco 2 de 2" and status["progress"]["percent"] == 100


def test_isolate_vocals_rejects_a_missing_file_immediately(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        mcp_server.isolate_vocals(str(tmp_path / "nada.mp4"))


def test_isolate_vocals_is_listed_as_a_tool():
    import asyncio

    tools = asyncio.run(mcp_server.server.list_tools())
    assert "isolate_vocals" in {tool.name for tool in tools}
