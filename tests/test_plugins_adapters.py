"""Os plugins pelos três adaptadores (CLI, ferramenta MCP e rotas da interface) e o `dmaker doctor` e o `dmaker setup --plugins`,
sobre um serviço de plugins com varredura falsa."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from typer.testing import CliRunner

from dmaker import config, mcp_server, setup_tools
from dmaker.cli import _doctor_plugins, app
from dmaker.filtergraph.plugins import lv2_help_graph
from dmaker.media.plugin_scan import PluginRoot
from dmaker.pipeline import plugins as plugins_module
from dmaker.pipeline.plugins import PluginService
from dmaker.ui import server

from .test_plugins_unit import LV2_HELP, FakeProbe, make_lv2_bundle

runner = CliRunner()
URI = "urn:dmaker:test:echo"


@pytest.fixture
def service(tmp_path, monkeypatch) -> PluginService:
    """O serviço do processo trocado por um que varre um pacote de mentira com o ffmpeg de mentira."""
    make_lv2_bundle(tmp_path / "lv2")
    probe = FakeProbe({lv2_help_graph(URI): LV2_HELP})
    fake = PluginService(probe, lambda: [PluginRoot("lv2", tmp_path / "lv2")], lambda name: Path("ffmpeg"))
    monkeypatch.setattr(plugins_module, "_default", fake)
    return fake


def plugin_id_of(service: PluginService) -> str:
    return service.plugins()[0].id


# ---------- CLI ----------


def test_cli_scan_and_list_show_the_plugin_the_hosts_and_where_to_put_plugins(service):
    for command in (["audio", "plugins", "scan"], ["audio", "plugins", "list"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
        assert "DMaker Eco" in result.output and "habilitado" in result.output
        assert "ffmpeg do LV2" in result.output and "ffmpeg do LADSPA" in result.output
        assert "dmaker audio plugins scan" in result.output.replace("\n", " ")


def test_cli_json_is_the_same_payload_the_mcp_tool_and_the_route_give(service):
    payload = json.loads(runner.invoke(app, ["audio", "plugins", "list", "--json"]).output)
    assert [p["ref"] for p in payload["plugins"]] == [URI]
    assert [c["name"] for c in payload["plugins"][0]["controls"]] == ["delay_ms", "feedback", "mix"]
    assert payload == mcp_server.audio_plugins("list")
    with TestClient(server.app) as client:
        assert client.get("/api/audio-plugins").json() == payload


def test_cli_show_prints_the_spec_reference_and_every_control_with_range_and_default(service):
    result = runner.invoke(app, ["audio", "plugins", "show", URI])
    assert result.exit_code == 0, result.output
    assert "format='lv2'" in result.output and URI in result.output
    assert "delay_ms" in result.output and "Realimentacao" in result.output and "0.95" in result.output


def test_cli_disable_and_enable_by_id_are_kept_in_plugins_json(service):
    identifier = plugin_id_of(service)
    off = runner.invoke(app, ["audio", "plugins", "disable", identifier])
    assert off.exit_code == 0 and "desabilitado" in off.output
    assert json.loads(config.PLUGINS_FILE.read_text(encoding="utf-8")) == {"disabled": [f"lv2:{URI}"]}
    on = runner.invoke(app, ["audio", "plugins", "enable", identifier, "--json"])
    assert json.loads(on.output)["plugins"][0]["enabled"] is True


def test_cli_asking_for_an_unknown_plugin_fails_with_the_reason(service):
    result = runner.invoke(app, ["audio", "plugins", "show", "nada"])
    assert result.exit_code == 1 and "não encontrado" in result.output


# ---------- MCP ----------


def test_mcp_tool_lists_scans_shows_and_toggles_and_refuses_what_it_does_not_know(service):
    assert mcp_server.audio_plugins()["plugins"][0]["ref"] == URI
    assert mcp_server.audio_plugins("scan")["plugins"][0]["name"] == "DMaker Eco"
    identifier = plugin_id_of(service)
    assert mcp_server.audio_plugins("disable", identifier)["plugins"][0]["enabled"] is False
    assert mcp_server.audio_plugins("enable", URI)["plugins"][0]["enabled"] is True
    assert mcp_server.audio_plugins("show", URI)["plugins"][0]["id"] == identifier
    with pytest.raises(ToolError, match="pede o plugin"):
        mcp_server.audio_plugins("show")
    with pytest.raises(ToolError, match="não encontrado"):
        mcp_server.audio_plugins("show", "nada")
    with pytest.raises(ToolError, match="ação desconhecida"):
        mcp_server.audio_plugins("apagar")


def test_the_mcp_tool_is_out_of_the_small_model_kits_with_the_reason():
    from dmaker.agent.kits import EXCLUDED_TOOLS

    assert "audio_plugins" in EXCLUDED_TOOLS and "teto de 25" in EXCLUDED_TOOLS["audio_plugins"]


# ---------- rotas ----------


def test_the_routes_list_scan_show_and_toggle(service):
    with TestClient(server.app) as client:
        scanned = client.post("/api/audio-plugins/scan").json()
        identifier = scanned["plugins"][0]["id"]
        assert client.get(f"/api/audio-plugins/{identifier}").json()["plugins"][0]["ref"] == URI
        off = client.post(f"/api/audio-plugins/{identifier}/disable").json()
        assert off["plugins"][0]["enabled"] is False
        assert client.get("/api/audio-plugins").json()["plugins"][0]["enabled"] is False
        on = client.post(f"/api/audio-plugins/{identifier}/enable").json()
        assert on["plugins"][0]["enabled"] is True
        missing = client.get("/api/audio-plugins/nada")
        assert missing.status_code == 404 and "não encontrado" in missing.json()["detail"]
        assert client.post("/api/audio-plugins/nada/disable").status_code == 404


def test_the_catalog_of_effects_tells_the_interface_to_build_the_plugin_fields_from_the_plugin_list():
    with TestClient(server.app) as client:
        effects = {e["type"]: e for e in client.get("/api/audio-effects").json()["effects"]}
    assert [p["kind"] for p in effects["plugin"]["parameters"]] == [
        "plugin_format",
        "plugin",
        "plugin_params",
    ]


# ---------- doctor e setup ----------


def test_doctor_tells_which_ffmpeg_hosts_each_format_and_which_command_installs_the_missing_one(
    service, capsys, monkeypatch
):
    monkeypatch.setattr(
        service, "_ffmpeg_for", lambda name: Path("C:/ff/ffmpeg.exe") if name == "ladspa" else None
    )
    _doctor_plugins()
    out = capsys.readouterr().out.replace("\n", "")  # o Rich quebra o caminho comprido na largura do terminal
    assert "plugins LADSPA: disponível" in out and "ffmpeg.exe" in out
    assert "plugins LV2: indisponível (rode dmaker setup --plugins)" in out
    assert str(config.PLUGINS_DIR) in out


def test_setup_with_plugins_installs_only_the_lv2_ffmpeg(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        setup_tools, "install_lv2_ffmpeg", lambda force=False: calls.append(f"lv2 force={force}")
    )
    monkeypatch.setattr(
        setup_tools, "install_ffmpeg", lambda force=False: pytest.fail("não devia trocar o ffmpeg principal")
    )
    monkeypatch.setattr(
        setup_tools, "install_fonts", lambda force=False: pytest.fail("não devia baixar as fontes")
    )
    assert runner.invoke(app, ["setup", "--plugins"]).exit_code == 0
    assert runner.invoke(app, ["setup", "--plugins", "--force"]).exit_code == 0
    assert calls == ["lv2 force=False", "lv2 force=True"]


def test_setup_with_plugins_fails_with_the_reason_when_the_install_fails(monkeypatch):
    def broken(force=False):
        raise RuntimeError("o SHA-256 não confere")

    monkeypatch.setattr(setup_tools, "install_lv2_ffmpeg", broken)
    result = runner.invoke(app, ["setup", "--plugins"])
    assert result.exit_code == 1 and "SHA-256" in result.output
