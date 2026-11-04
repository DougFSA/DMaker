"""O andamento do projeto e da música pelos três adaptadores: ferramenta MCP, linha de comando e rota da interface.

Cada um é fino sobre o mesmo serviço (`pipeline/tempo_detect.py` e as operações `tempo_set`, `tempo_remove` e
`music_tempo_set` do `edit_project`), então aqui se prova a fiação: o pedido recusado volta com o motivo, e a edição entra no
histórico."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.domain.spec import Project
from dmaker.media.wavio import write_wav_channels
from dmaker.pipeline.edit_history import history_listing
from dmaker.pipeline.projects import load_project
from dmaker.ui import server

from .conftest import requires_ffmpeg

runner = CliRunner()
RATE = 48000


def click_track(bpm: float, seconds: float = 12.0) -> np.ndarray:
    samples = np.zeros(int(seconds * RATE))
    click = np.sin(2 * np.pi * 1000 * np.arange(int(0.005 * RATE)) / RATE) * np.hanning(int(0.005 * RATE))
    for number in range(int(seconds / (60.0 / bpm))):
        start = int(round(number * 60.0 / bpm * RATE))
        samples[start : start + len(click)] += 0.8 * click
    return samples


def write_project(folder: Path, name: str = "ritmo-cli", music: bool = True, **audio) -> Path:
    audio_spec: dict = {"normalize": "off", **audio}
    if music:
        write_wav_channels(folder / "loop.wav", click_track(110.0).reshape(-1, 1).astype(np.float32), RATE)
        audio_spec["music"] = {"src": "loop.wav"}
    project = Project.model_validate(
        {
            "name": name,
            "timeline": [{"type": "card", "title": "Ritmo", "duration": 10.0}],
            "audio": audio_spec,
        }
    )
    return project.save(folder / "spec.json")


# ---------- CLI ----------


def test_the_cli_sets_shows_and_clears_the_project_tempo_in_the_history(tmp_path):
    spec = write_project(tmp_path, music=False)
    shown = runner.invoke(app, ["audio", "tempo", "show", str(spec)], terminal_width=200)
    assert shown.exit_code == 0 and "não tem andamento" in shown.output

    done = runner.invoke(
        app,
        ["audio", "tempo", "set", str(spec), "--bpm", "100", "--time-signature", "3/4"],
        terminal_width=200,
    )
    assert done.exit_code == 0, done.output
    tempo = load_project(spec).audio.tempo
    assert (tempo.bpm, tempo.time_signature, tempo.offset) == (100.0, "3/4", 0.0)
    assert history_listing(spec)["undo"][0]["label"] == "Andamento do projeto"

    summary = json.loads(runner.invoke(app, ["audio", "tempo", "show", str(spec), "--json"]).output)
    assert summary["tempo"]["bar_seconds"] == pytest.approx(1.8) and summary["music"] is None

    grid = json.loads(
        runner.invoke(app, ["audio", "tempo", "grid", str(spec), "--level", "bar", "--json"]).output
    )
    assert [point["at"] for point in grid["points"]] == pytest.approx([0.0, 1.8, 3.6, 5.4, 7.2, 9.0])
    assert [point["number"] for point in grid["points"]] == [1, 2, 3, 4, 5, 6]

    assert runner.invoke(app, ["audio", "tempo", "clear", str(spec)]).exit_code == 0
    assert load_project(spec).audio.tempo is None


def test_the_cli_refuses_a_bad_tempo_and_a_grid_without_tempo_with_the_reason(tmp_path):
    spec = write_project(tmp_path, music=False)
    no_bpm = runner.invoke(
        app, ["audio", "tempo", "set", str(spec), "--time-signature", "3/4"], terminal_width=200
    )
    assert no_bpm.exit_code == 1 and "informe o `bpm`" in no_bpm.output and "Traceback" not in no_bpm.output
    bad = runner.invoke(app, ["audio", "tempo", "set", str(spec), "--bpm", "1000"], terminal_width=200)
    assert bad.exit_code == 1 and "Traceback" not in bad.output
    bare = runner.invoke(app, ["audio", "tempo", "grid", str(spec)], terminal_width=200)
    assert bare.exit_code == 1 and "audio.tempo" in bare.output


def test_the_cli_sets_the_music_tempo_and_the_stretch(tmp_path):
    spec = write_project(tmp_path, tempo={"bpm": 120})
    done = runner.invoke(
        app,
        ["audio", "tempo", "music", str(spec), "--bpm", "100", "--beat-offset", "0.12", "--stretch"],
        terminal_width=200,
    )
    assert done.exit_code == 0, done.output
    music = load_project(spec).audio.music
    assert (music.bpm, music.beat_offset, music.stretch_to_tempo) == (100.0, 0.12, True)
    shown = runner.invoke(app, ["audio", "tempo", "show", str(spec)], terminal_width=200)
    assert "esticada" in shown.output and "100 BPM" in shown.output
    other = tmp_path / "outro"
    other.mkdir()
    refused = runner.invoke(app, ["audio", "tempo", "music", str(write_project(other, "outro")), "--stretch"])
    assert refused.exit_code == 1  # esticar sem o andamento da música


@requires_ffmpeg
def test_the_cli_detects_the_bpm_suggests_first_and_writes_only_with_apply(tmp_path):
    spec = write_project(tmp_path)
    suggestion = runner.invoke(app, ["audio", "tempo", "detect", str(spec), "--json"], terminal_width=200)
    assert suggestion.exit_code == 0, suggestion.output
    data = json.loads(suggestion.output)
    assert data["bpm"] == pytest.approx(110.0, abs=1.0) and data["applied"] is False
    assert load_project(spec).audio.music.bpm is None  # só sugeriu
    applied = runner.invoke(
        app, ["audio", "tempo", "detect", str(spec), "--apply", "--json"], terminal_width=200
    )
    assert applied.exit_code == 0 and json.loads(applied.output)["applied"] is True
    assert load_project(spec).audio.music.bpm == pytest.approx(110.0, abs=1.0)


def test_the_cli_cut_on_beat_with_the_grid_needs_the_tempo(tmp_path):
    spec = write_project(tmp_path, music=False)
    refused = runner.invoke(
        app, ["audio", "analyze", "cut-on-beat", str(spec), "--source", "grid"], terminal_width=200
    )
    assert refused.exit_code == 1 and "Traceback" not in refused.output


# ---------- MCP ----------


def test_the_mcp_tool_shows_the_tempo_lists_the_grid_and_refuses_what_does_not_fit(tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError

    from dmaker import mcp_server

    spec = write_project(tmp_path, tempo={"bpm": 120, "time_signature": "3/4"})
    shown = mcp_server.audio_tempo(str(spec))
    assert shown["tempo"] == {
        "bpm": 120.0,
        "time_signature": "3/4",
        "offset": 0.0,
        "beat_seconds": 0.5,
        "bar_seconds": 1.5,
    }
    assert shown["music"] == {"bpm": None, "beat_offset": 0.0, "stretch_to_tempo": False}
    grid = mcp_server.audio_tempo(str(spec), action="grid", start=0.0, end=3.0)
    assert [point["at"] for point in grid["points"]] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    with pytest.raises(ToolError, match="show, detect ou grid"):
        mcp_server.audio_tempo(str(spec), action="apagar")
    with pytest.raises(ToolError, match="level"):
        mcp_server.audio_tempo(str(spec), action="grid", level="nota")
    (tmp_path / "sem").mkdir()
    bare = write_project(tmp_path / "sem", "sem", music=False)
    with pytest.raises(ToolError, match="audio.tempo"):
        mcp_server.audio_tempo(str(bare), action="grid", start=0.0, end=1.0)


@requires_ffmpeg
def test_the_mcp_tool_detects_and_applies(tmp_path):
    from dmaker import mcp_server

    spec = write_project(tmp_path)
    suggestion = mcp_server.audio_tempo(str(spec), action="detect")
    assert suggestion["bpm"] == pytest.approx(110.0, abs=1.0) and suggestion["applied"] is False
    applied = mcp_server.audio_tempo(str(spec), action="detect", apply=True)
    assert applied["applied"] is True and load_project(spec).audio.music.bpm == pytest.approx(110.0, abs=1.0)


def test_the_edit_project_tool_accepts_the_tempo_operations_and_a_bar_reference(tmp_path):
    from dmaker import mcp_server

    spec = write_project(tmp_path, music=False)
    mcp_server.edit_project(str(spec), {"type": "tempo_set", "bpm": 120})
    mcp_server.edit_project(str(spec), {"type": "split", "index": 0, "at": "bar:2"})
    durations = [segment.duration for segment in load_project(spec).timeline]
    assert durations == [2.0, 8.0]  # o compasso 2 de 4/4 a 120 BPM cai em 2 s


# ---------- a rota da interface ----------


def test_the_route_refuses_a_project_without_music_and_a_missing_project():
    client = TestClient(server.app)
    assert client.post("/api/projects/nao-existe/audio-tempo/detect").status_code == 404
    folder = config.PROJECTS_DIR / "ritmo-rota"
    folder.mkdir(parents=True)
    write_project(folder, "ritmo-rota", music=False)
    refused = client.post("/api/projects/ritmo-rota/audio-tempo/detect")
    assert refused.status_code == 400 and "não tem música" in refused.json()["detail"]


@requires_ffmpeg
def test_the_route_suggests_the_tempo_and_never_writes_it():
    folder = config.PROJECTS_DIR / "ritmo-rota"
    folder.mkdir(parents=True)
    write_project(folder, "ritmo-rota")
    response = TestClient(server.app).post("/api/projects/ritmo-rota/audio-tempo/detect")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["bpm"] == pytest.approx(110.0, abs=1.0) and data["source"] == "loop.wav"
    assert data["applied"] is False and data["alternatives"] == []  # 55 e 220 BPM ficam fora da faixa
    assert load_project("ritmo-rota").audio.music.bpm is None  # a rota só lê


def test_the_new_tool_is_listed_as_excluded_from_the_small_models_kits():
    from dmaker.agent.kits import EXCLUDED_TOOLS

    assert "audio_tempo" in EXCLUDED_TOOLS
