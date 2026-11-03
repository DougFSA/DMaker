"""Os analisadores de áudio pelos três adaptadores: ferramenta MCP, linha de comando e rota da interface.

Cada um é fino sobre o mesmo serviço (`pipeline/audio_analysis.py`), então aqui se prova a fiação: o catálogo é o mesmo nos
três, o pedido recusado volta com o motivo, e o que marca grava o grupo certo na spec."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dmaker import config
from dmaker.analysis import ANALYZER_CLASSES, analyzer_catalog
from dmaker.cli import app
from dmaker.domain.spec import Project
from dmaker.media.wavio import write_wav_channels
from dmaker.pipeline.projects import load_project
from dmaker.ui import server

from .conftest import requires_ffmpeg
from .test_mcp import _session, _text

runner = CliRunner()
RATE = 48000


def tone(hz: float, seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return amp * np.sin(2 * np.pi * hz * t)


def voice_with_clipping() -> np.ndarray:
    samples = tone(220.0, 3.0, 0.4)
    samples[int(1.0 * RATE) : int(1.001 * RATE)] = 1.0
    return samples


def write_project(folder: Path, name: str = "analise-cli") -> Path:
    write_wav_channels(folder / "voz.wav", voice_with_clipping().reshape(-1, 1).astype(np.float32), RATE)
    project = Project.model_validate(
        {
            "name": name,
            "timeline": [{"type": "card", "title": "Análise", "duration": 4.0}],
            "audio": {"voiceover": [{"src": "voz.wav", "start": 0.5}], "normalize": "off"},
        }
    )
    return project.save(folder / "spec.json")


# ---------- MCP ----------


def test_the_mcp_lists_the_analyzers_and_refuses_a_bad_request_with_the_reason():
    async def go(session):
        tools = await session.list_tools()
        catalog = await session.call_tool("audio_analyzers", {})
        only = await session.call_tool("audio_analyzers", {"type": "beats"})
        unknown = await session.call_tool("audio_analyzers", {"type": "wavelet"})
        await session.call_tool(
            "save_project",
            {
                "name": "mcp-analise-teste",
                "spec": {"timeline": [{"type": "card", "title": "x", "duration": 1.0}]},
            },
        )
        no_output = await session.call_tool("audio_analyze", {"name": "mcp-analise-teste", "analyzer": "rms"})
        bad_target = await session.call_tool(
            "audio_analyze", {"name": "mcp-analise-teste", "analyzer": "rms", "target": "audio.music"}
        )
        bad_param = await session.call_tool(
            "audio_analyze",
            {
                "name": "mcp-analise-teste",
                "analyzer": "clipping",
                "target": "output",
                "params": {"start_threshold": 0},
            },
        )
        beat_cut = await session.call_tool("cut_on_beat", {"name": "mcp-analise-teste"})
        return (
            {t.name for t in tools.tools},
            _text(catalog),
            _text(only),
            unknown,
            no_output,
            bad_target,
            bad_param,
            beat_cut,
        )

    tools, catalog, only, unknown, no_output, bad_target, bad_param, beat_cut = asyncio.run(_session(go))
    assert {"audio_analyzers", "audio_analyze", "cut_on_beat"} <= tools
    assert json.loads(catalog) == analyzer_catalog()  # o mesmo catálogo da CLI e da interface
    assert [a["type"] for a in json.loads(only)["analyzers"]] == ["beats"]
    assert unknown.is_error and "Analisador desconhecido" in _text(unknown)
    assert no_output.is_error and "não tem saída final renderizada" in _text(no_output)
    assert bad_target.is_error and "não tem música" in _text(bad_target)
    assert bad_param.is_error and "start_threshold" in _text(bad_param)
    assert beat_cut.is_error and "música" in _text(beat_cut)
    folder = config.PROJECTS_DIR / "mcp-analise-teste"
    (folder / "spec.json").unlink()
    folder.rmdir()


@requires_ffmpeg
def test_the_mcp_tool_analyses_marks_and_exports(tmp_path):
    from dmaker import mcp_server

    spec = write_project(tmp_path)
    result = mcp_server.audio_analyze(
        str(spec), "clipping", target="audio.voiceover.0", mark=True, out=str(tmp_path / "r.json")
    )
    assert result["regions"][0]["start"] == pytest.approx(1.0, abs=0.001)
    assert result["markers"] == {"group": "clipping", "written": 1, "warnings": []}
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["analyzer"] == "clipping"
    assert load_project(spec).markers[0].begin == pytest.approx(1.5, abs=0.002)  # a voz começa em 0,5 s
    spectrum = mcp_server.audio_analyze(
        str(spec), "spectrum", target="audio.voiceover.0", params={"size": 2048}
    )
    assert len(spectrum["curve"]["frequencies"]) == 512 and spectrum["peak_hz"] == pytest.approx(
        220.0, abs=3.0
    )


# ---------- CLI ----------


def test_the_cli_catalog_lists_every_analyzer_and_matches_the_json():
    result = runner.invoke(app, ["audio", "analyze", "catalog"], terminal_width=240)
    assert result.exit_code == 0, result.output
    for name in ANALYZER_CLASSES:
        assert name in result.output
    assert "Find Clipping" in result.output and "Beat Finder" in result.output
    as_json = runner.invoke(app, ["audio", "analyze", "catalog", "--json"])
    assert json.loads(as_json.output) == analyzer_catalog()
    one = runner.invoke(app, ["audio", "analyze", "catalog", "rms", "--json"])
    assert [a["type"] for a in json.loads(one.output)["analyzers"]] == ["rms"]
    unknown = runner.invoke(app, ["audio", "analyze", "catalog", "wavelet"])
    assert unknown.exit_code == 1 and "Analisador desconhecido" in unknown.output


@requires_ffmpeg
def test_the_cli_runs_an_analyzer_prints_the_summary_and_writes_the_markers(tmp_path):
    spec = write_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "audio",
            "analyze",
            "run",
            str(spec),
            "clipping",
            "--target",
            "audio.voiceover.0",
            "--mark",
            "--group",
            "estouro",
        ],
        terminal_width=200,
    )
    assert result.exit_code == 0, result.output
    assert "1 trecho(s) estourado(s)" in result.output and "grupo 'estouro'" in result.output
    assert [m.group for m in load_project(spec).markers] == ["estouro"]
    as_json = runner.invoke(
        app,
        [
            "audio",
            "analyze",
            "run",
            str(spec),
            "rms",
            "--target",
            "audio.voiceover.0",
            "-p",
            "window=1",
            "--json",
        ],
    )
    data = json.loads(as_json.output)
    assert (
        data["analyzer"] == "rms" and len(data["windows"]) == 3 and data["source"].startswith("Voz gravada 1")
    )
    csv = tmp_path / "janelas.csv"
    exported = runner.invoke(
        app,
        [
            "audio",
            "analyze",
            "run",
            str(spec),
            "rms",
            "--target",
            "audio.voiceover.0",
            "-p",
            "window=1",
            "--out",
            str(csv),
        ],
    )
    assert exported.exit_code == 0 and csv.read_text(encoding="utf-8").startswith("tempo_s,rms_db")


def test_the_cli_explains_a_refused_request_without_a_traceback(tmp_path):
    spec = write_project(tmp_path)
    for args, message in (
        (["clipping", "--target", "audio.music"], "não tem música"),
        (["clipping", "--target", "audio.voiceover.0", "--start", "abc"], "Instante inválido"),
        (["clipping", "--target", "audio.voiceover.0", "-p", "start_threshold=0"], "start_threshold"),
        (["wavelet"], "Analisador desconhecido"),
    ):
        result = runner.invoke(app, ["audio", "analyze", "run", str(spec), *args], terminal_width=200)
        assert result.exit_code == 1 and message in result.output, (args, result.output)
        assert "Traceback" not in result.output
    refused = runner.invoke(app, ["audio", "analyze", "cut-on-beat", str(spec)])
    assert refused.exit_code == 1 and "música" in refused.output


# ---------- a rota da interface ----------


def test_the_route_serves_the_catalog_and_the_spectrum_curve(tmp_path):
    client = TestClient(server.app)
    assert client.get("/api/audio-analyzers").json() == analyzer_catalog()
    assert client.get("/api/audio-analyzers", params={"type": "wavelet"}).status_code == 404
    folder = config.PROJECTS_DIR / "analise-rota"
    folder.mkdir(parents=True)
    write_project(folder, "analise-rota")
    missing = client.post("/api/projects/nao-existe/audio-analysis", json={"analyzer": "spectrum"})
    assert missing.status_code == 404
    refused = client.post(
        "/api/projects/analise-rota/audio-analysis", json={"analyzer": "spectrum", "target": "audio.music"}
    )
    assert refused.status_code == 400 and "não tem música" in refused.json()["detail"]


@requires_ffmpeg
def test_the_route_returns_a_curve_with_the_peak_the_note_and_never_marks(tmp_path):
    folder = config.PROJECTS_DIR / "analise-rota"
    folder.mkdir(parents=True)
    write_wav_channels(folder / "tom.wav", tone(440.0, 2.0, 0.5).reshape(-1, 1).astype(np.float32), RATE)
    Project.model_validate(
        {
            "name": "analise-rota",
            "timeline": [{"type": "card", "title": "x", "duration": 3.0}],
            "audio": {"voiceover": [{"src": "tom.wav"}], "normalize": "off"},
        }
    ).save(folder / "spec.json")
    client = TestClient(server.app)
    response = client.post(
        "/api/projects/analise-rota/audio-analysis",
        json={"analyzer": "spectrum", "target": "audio.voiceover.0", "params": {"size": 4096}, "points": 256},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["peak_hz"] == pytest.approx(440.0, abs=2.0) and data["peak_note"].startswith("Lá4")
    assert len(data["curve"]["frequencies"]) == 256 and data["curve"]["points_total"] == 2049
    assert data["source"].startswith("Voz gravada 1") and "markers" not in data
    marking = client.post(
        "/api/projects/analise-rota/audio-analysis", json={"analyzer": "beats", "target": "audio.voiceover.0"}
    )
    assert marking.status_code == 200 and "markers" not in marking.json()  # a rota só lê
    assert load_project("analise-rota").markers == []
