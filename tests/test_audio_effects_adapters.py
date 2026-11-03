"""A cadeia de efeitos pelos três adaptadores: ferramenta MCP, linha de comando e rota da interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.domain.audio_effects import EFFECT_CLASSES
from dmaker.domain.spec import Project
from dmaker.ui import server

from .test_mcp import _session, _text

runner = CliRunner()


def write_spec(folder: Path, **audio) -> Path:
    project = Project.model_validate(
        {
            "name": "cli-efeitos",
            "timeline": [{"type": "card", "title": "Efeitos", "duration": 2.0}],
            "audio": {"normalize": "off", **audio},
        }
    )
    return project.save(folder / "spec.json")


def saved(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- MCP ----------


def test_the_mcp_lists_the_effect_catalog_and_edits_a_chain_over_stdio():
    spec = {
        "output": {"preset": "instagram/stories"},
        "timeline": [{"type": "card", "title": "Efeitos via MCP", "duration": 1.0}],
        "audio": {"normalize": "off"},
    }

    async def go(session):
        tools = await session.list_tools()
        catalog = await session.call_tool("audio_effects", {})
        only = await session.call_tool("audio_effects", {"type": "repeat"})
        unknown = await session.call_tool("audio_effects", {"type": "eco"})
        await session.call_tool("save_project", {"name": "mcp-efeitos-teste", "spec": spec})
        op = {"type": "audio_effect", "action": "add", "target": "audio.master"}
        added = await session.call_tool(
            "edit_project",
            {"name": "mcp-efeitos-teste", "op": {**op, "effect": {"type": "amplify", "gain_db": 3}}},
        )
        refused = await session.call_tool(
            "edit_project", {"name": "mcp-efeitos-teste", "op": {**op, "effect": {"type": "repeat"}}}
        )
        return {t.name for t in tools.tools}, _text(catalog), _text(only), unknown, _text(added), refused

    tools, catalog, only, unknown, added, refused = asyncio.run(_session(go))
    assert "audio_effects" in tools
    data = json.loads(catalog)
    assert [e["type"] for e in data["effects"]] == list(EFFECT_CLASSES)
    assert {"effects", "common", "targets"} <= set(data)
    assert [e["type"] for e in json.loads(only)["effects"]] == ["repeat"]
    assert unknown.is_error and "desconhecido" in _text(unknown)
    assert json.loads(added)["total_s"] == 1.0
    assert refused.is_error and "Repetir muda a duração" in _text(refused)

    spec_path = config.PROJECTS_DIR / "mcp-efeitos-teste" / "spec.json"
    assert saved(spec_path)["audio"]["master_effects"][0]["gain_db"] == 3
    spec_path.unlink()
    spec_path.parent.rmdir()


# ---------- CLI ----------


def test_cli_lists_the_catalog_as_a_table_and_as_json():
    table = runner.invoke(app, ["audio", "effects"])
    assert table.exit_code == 0
    for info in EFFECT_CLASSES.values():
        assert info.label in table.output
    assert "Alvos:" in table.output and "audio.master" in table.output

    one = runner.invoke(app, ["audio", "effects", "normalize", "--json"])
    payload = json.loads(one.output)
    assert [e["type"] for e in payload["effects"]] == ["normalize"]
    assert {p["name"] for p in payload["effects"][0]["parameters"]} == {
        "peak_db",
        "remove_dc",
        "stereo_independent",
    }

    assert runner.invoke(app, ["audio", "effects", "eco"]).exit_code == 1


def test_cli_edits_the_chain_of_an_item_step_by_step(tmp_path):
    spec = write_spec(tmp_path, voiceover=[{"src": "fala.wav"}])
    target = "audio.voiceover.0"

    def call(*args: str):
        result = runner.invoke(app, ["audio", "effect", *args])
        assert result.exit_code == 0, result.output
        return saved(spec)["audio"]["voiceover"][0].get("effects", [])

    assert [e["type"] for e in call("add", str(spec), target, "amplify", "-p", "gain_db=6")] == ["amplify"]
    chain = call("add", str(spec), target, "reverse", "--start", "0.5", "--end", "1.5")
    assert chain[1]["start"] == 0.5 and chain[1]["end"] == 1.5
    chain = call(
        "add", str(spec), target, "normalize", "-p", "peak_db=-3", "-p", "remove_dc=false", "--position", "0"
    )
    assert [e["type"] for e in chain] == ["normalize", "amplify", "reverse"]
    assert chain[0]["peak_db"] == -3 and chain[0]["remove_dc"] is False  # o valor é lido como JSON
    assert [e["type"] for e in call("move", str(spec), target, "0", "2")] == [
        "amplify",
        "reverse",
        "normalize",
    ]
    assert call("disable", str(spec), target, "1")[1]["enabled"] is False
    assert call("enable", str(spec), target, "1")[1]["enabled"] is True
    assert call("set", str(spec), target, "0", "-p", "gain_db=-2")[0]["gain_db"] == -2
    assert [e["type"] for e in call("remove", str(spec), target, "0")] == ["reverse", "normalize"]


def test_cli_edits_the_master_chain_and_reports_a_bad_request_without_a_traceback(tmp_path):
    spec = write_spec(tmp_path)
    assert runner.invoke(app, ["audio", "effect", "add", str(spec), "audio.master", "invert"]).exit_code == 0
    assert saved(spec)["audio"]["master_effects"] == [{"type": "invert", "enabled": True}]

    refused = runner.invoke(app, ["audio", "effect", "add", str(spec), "audio.master", "repeat"])
    message = " ".join(refused.output.split())  # o terminal quebra a linha onde quiser
    assert refused.exit_code == 1 and "o efeito Repetir muda a duração" in message
    assert "Traceback" not in refused.output and "validation error" not in message  # só a regra, sem o ruído
    assert runner.invoke(app, ["audio", "effect", "add", str(spec), "audio.master", "eco"]).exit_code == 1
    assert (
        runner.invoke(
            app, ["audio", "effect", "add", str(spec), "audio.master", "invert", "-p", "mal"]
        ).exit_code
        == 1
    )
    assert runner.invoke(app, ["audio", "effect", "set", str(spec), "audio.master", "0"]).exit_code == 1
    assert saved(spec)["audio"]["master_effects"] == [
        {"type": "invert", "enabled": True}
    ]  # nada foi estragado


def test_the_clean_command_also_clears_the_processed_audio_cache(tmp_path):
    config.AUDIO_FX_DIR.mkdir(parents=True, exist_ok=True)
    (config.AUDIO_FX_DIR / "antigo.wav").write_bytes(b"x")
    result = runner.invoke(app, ["clean"])
    assert result.exit_code == 0
    assert not (config.AUDIO_FX_DIR / "antigo.wav").exists()
    assert config.AUDIO_FX_DIR.exists()  # a pasta volta, vazia


# ---------- interface ----------


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


def test_the_ui_serves_the_same_catalog_the_mcp_does(client):
    from dmaker.domain.audio_effects import catalog_payload

    response = client.get("/api/audio-effects")
    assert response.status_code == 200
    assert response.json() == catalog_payload()
    amplify = next(e for e in response.json()["effects"] if e["type"] == "amplify")
    assert amplify["label"] == "Amplificar" and amplify["audacity_name"] == "Amplify"
    assert [p["name"] for p in amplify["parameters"]] == ["gain_db", "prevent_clipping"]


def test_the_ui_filters_by_type_and_answers_404_for_an_unknown_one(client):
    assert [
        e["type"] for e in client.get("/api/audio-effects", params={"type": "invert"}).json()["effects"]
    ] == ["invert"]
    missing = client.get("/api/audio-effects", params={"type": "eco"})
    assert missing.status_code == 404 and "desconhecido" in missing.json()["detail"]


def test_the_ui_edit_route_applies_the_effect_operation(client):
    project = {
        "output": {"preset": "instagram/stories"},
        "timeline": [{"type": "card", "title": "Efeitos", "duration": 1.0, "motion": "none"}],
        "audio": {"normalize": "off"},
    }
    body = {
        "spec": {"name": "ui-efeitos", **project},
        "op": {
            "type": "audio_effect",
            "action": "add",
            "target": "audio.master",
            "effect": {"type": "reverse"},
        },
    }
    response = client.post("/api/projects/ui-efeitos/edit", json=body)
    assert response.status_code == 200
    assert response.json()["spec"]["audio"]["master_effects"][0]["type"] == "reverse"
    body["op"]["effect"] = {"type": "repeat"}
    refused = client.post("/api/projects/ui-efeitos/edit", json=body)
    assert refused.status_code == 400 and "Repetir muda a duração" in refused.json()["detail"]
