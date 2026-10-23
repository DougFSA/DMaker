"""Adaptadores da troca de voz: `dmaker voice convert`, a ferramenta MCP `convert_voice` e a rota
`/api/speech/convert`, todos sobre o mesmo serviço com dublês (sem Demucs nem modelo de voz)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import dmaker.mcp_server as mcp_server
from dmaker import config
from dmaker.cli import app
from dmaker.ui import server
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.lexicon_store import LexiconStore
from tests.test_voice_conversion_service import ServiceHarness

cli = CliRunner()


@pytest.fixture
def harness(tmp_path: Path, monkeypatch) -> ServiceHarness:
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "voice-cache")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr("dmaker.voice.library.VOICES_DIR", tmp_path / "media" / "voices")
    return ServiceHarness(tmp_path / "media")


@pytest.fixture
def wired(monkeypatch, harness: ServiceHarness) -> ServiceHarness:
    monkeypatch.setattr(
        "dmaker.pipeline.voice_conversion.default_voice_conversion_service",
        lambda *args, **kwargs: harness.conversion,
    )
    return harness


# ---------- CLI ----------


def test_cli_convert_reports_voice_blocks_gain_and_time(wired: ServiceHarness, tmp_path: Path):
    out = tmp_path / "trocado.mp4"
    result = cli.invoke(app, ["voice", "convert", str(wired.src), "--voice", "dora", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Pronto" in result.output and "trocado.mp4" in result.output
    assert "voz: dora; 40.0s em 2 bloco(s)" in result.output
    assert "separação" in result.output and "tempo:" in result.output
    assert out.exists()


def test_cli_convert_passes_the_window_to_the_service(wired: ServiceHarness, tmp_path: Path):
    result = cli.invoke(
        app,
        [
            "voice",
            "convert",
            str(wired.src),
            "--voice",
            "alex",
            "--start",
            "5",
            "--end",
            "25",
            "--out",
            str(tmp_path / "s.mp4"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert wired.isolation.calls == [(5.0, 25.0)]


def test_cli_convert_errors_are_portuguese_with_exit_code_1(wired: ServiceHarness, tmp_path: Path):
    unknown = cli.invoke(app, ["voice", "convert", str(wired.src), "--voice", "fantasma"])
    assert unknown.exit_code == 1 and "fantasma" in unknown.output and "Vozes disponíveis" in unknown.output
    missing = cli.invoke(app, ["voice", "convert", str(tmp_path / "nada.mp4"), "--voice", "dora"])
    assert missing.exit_code == 1 and "não encontrado" in missing.output
    backwards = cli.invoke(
        app, ["voice", "convert", str(wired.src), "--voice", "dora", "--start", "9", "--end", "3"]
    )
    assert backwards.exit_code == 1 and "maior que start" in backwards.output
    assert cli.invoke(app, ["voice", "convert", str(wired.src)]).exit_code != 0  # --voice é obrigatório


# ---------- MCP ----------


def test_convert_voice_runs_as_a_job_and_reports_the_output(
    monkeypatch, harness: ServiceHarness, tmp_path: Path
):
    monkeypatch.setattr(
        "dmaker.pipeline.voice_conversion.default_voice_conversion_service",
        lambda *args, **kwargs: harness.conversion,
    )
    monkeypatch.setattr(mcp_server, "_voice_library", lambda: harness.library)
    out = tmp_path / "mcp.mp4"
    started = mcp_server.convert_voice(str(harness.src), "dora", out=str(out))
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)
    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "done", status.get("error")
    result = status["result"]
    assert result["output"] == str(out) and result["voice"] == "dora" and result["blocks"] == 2
    assert result["engine"] == "fake-convert:1" and set(result["timings"]) >= {"conversão", "montagem"}


def test_convert_voice_rejects_bad_calls_immediately(monkeypatch, harness: ServiceHarness, tmp_path: Path):
    monkeypatch.setattr(mcp_server, "_voice_library", lambda: harness.library)
    with pytest.raises(FileNotFoundError):
        mcp_server.convert_voice(str(tmp_path / "nada.mp4"), "dora")
    with pytest.raises(ValueError, match="fantasma"):
        mcp_server.convert_voice(str(harness.src), "fantasma")
    with pytest.raises(ValueError, match="maior que start"):
        mcp_server.convert_voice(str(harness.src), "dora", start=8, end=2)


def test_convert_voice_is_listed_among_the_tools():
    names = {tool.name for tool in asyncio.run(mcp_server.server.list_tools())}
    assert "convert_voice" in names


# ---------- interface ----------


@pytest.fixture
def client(harness: ServiceHarness, tmp_path: Path):
    services = VoiceServices(
        library=harness.library,
        runner=harness.runner,
        synthesizer=harness.synthesizer,
        lexicons=LexiconStore(tmp_path / "assets"),
        isolation=harness.isolation,
        prober=harness.conversion.prober,
        converter=harness.converter,
    )
    server.app.dependency_overrides[get_voice_services] = lambda: services
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.pop(get_voice_services, None)


def finished(job_id: str):
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 30)
    return job


def test_convert_route_runs_a_job_and_returns_both_players(client, harness: ServiceHarness):
    response = client.post("/api/speech/convert", json={"path": str(harness.src), "voice": "dora"})
    assert response.status_code == 200, response.text
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    result = job.result
    assert Path(result["output"]).parent == config.OUTPUT_DIR / "troca-de-voz"
    assert result["voice"] == "dora" and result["blocks"] == 2 and result["excerpt"] is False
    assert client.get(result["audio_url"]).content == b"corrigido"  # o arquivo que o ffmpeg falso gravou
    assert result["original_url"].startswith("/api/file?") and job.progress["percent"] == 100


def test_convert_route_marks_excerpts(client, harness: ServiceHarness):
    response = client.post(
        "/api/speech/convert", json={"path": str(harness.src), "voice": "alex", "start": 2, "end": 22}
    )
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    assert job.result["excerpt"] is True and job.result["seconds"] == 20.0
    assert harness.isolation.calls == [(2.0, 22.0)]


def test_convert_route_validates_before_starting_a_job(client, harness: ServiceHarness, tmp_path: Path):
    before = len(server.jobs.list())
    assert (
        client.post(
            "/api/speech/convert", json={"path": str(tmp_path / "nada.mp4"), "voice": "dora"}
        ).status_code
        == 404
    )
    unknown = client.post("/api/speech/convert", json={"path": str(harness.src), "voice": "fantasma"})
    assert unknown.status_code == 404 and "fantasma" in unknown.json()["detail"]
    backwards = client.post(
        "/api/speech/convert", json={"path": str(harness.src), "voice": "dora", "start": 9, "end": 3}
    )
    assert backwards.status_code == 400
    assert client.post("/api/speech/convert", json={"path": str(harness.src)}).status_code == 422
    assert len(server.jobs.list()) == before
