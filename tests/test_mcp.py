"""Servidor MCP: sobe por stdio e conversa com o cliente oficial."""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from dmaker import config


async def _session(fn):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "dmaker.mcp_server"], cwd=str(config.ROOT)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _text(result) -> str:
    return "".join(c.text for c in result.content if getattr(c, "type", "") == "text")


def test_lists_tools_and_prompt():
    async def go(session):
        tools = await session.list_tools()
        prompts = await session.list_prompts()
        resources = await session.list_resources()
        return (
            {t.name for t in tools.tools},
            {p.name for p in prompts.prompts},
            {str(r.uri) for r in resources.resources},
        )

    tools, prompts, resources = asyncio.run(_session(go))
    assert {
        "dmaker_guide",
        "spec_schema",
        "presets",
        "probe_media",
        "save_project",
        "validate_project",
        "render_project",
        "job_status",
        "contact_sheet",
        "frames",
        "fix_captions",
        "edit_project",
        "timeline_view",
    } <= tools
    assert "editar-video" in prompts
    assert "dmaker://guide" in resources and "dmaker://schema" in resources


def test_presets_and_schema_tools():
    async def go(session):
        presets = await session.call_tool("presets", {"platform": "youtube"})
        schema = await session.call_tool("spec_schema", {})
        guide = await session.call_tool("dmaker_guide", {})
        return _text(presets), _text(schema), _text(guide)

    presets, schema, guide = asyncio.run(_session(go))
    assert "youtube/shorts" in presets and "instagram" not in presets
    assert "timeline" in json.loads(schema)["properties"]
    assert "spec" in guide.lower()


def test_save_and_validate_project_via_mcp(tmp_path):
    spec = {
        "output": {"preset": "instagram/stories"},
        "brand": "medlycare",
        "timeline": [{"type": "card", "title": "Teste via MCP", "duration": 2}],
        "audio": {"normalize": "off"},
    }

    async def go(session):
        saved = await session.call_tool("save_project", {"name": "mcp-teste", "spec": spec})
        validated = await session.call_tool("validate_project", {"name_or_path": "mcp-teste"})
        return _text(saved), _text(validated)

    saved, validated = asyncio.run(_session(go))
    assert "mcp-teste" in saved and json.loads(validated)["total_s"] == 2.0
    spec_path = config.PROJECTS_DIR / "mcp-teste" / "spec.json"
    assert spec_path.exists()
    spec_path.unlink()
    spec_path.parent.rmdir()


class _FakeUIClient:
    """Dublê de UIClient: nunca fala HTTP de verdade, só registra o que recebeu."""

    def __init__(self):
        self.base_url = "http://127.0.0.1:9"
        self.rendered = None
        self.exported = None

    def render(self, name, options):
        self.rendered = (name, options)
        return {"job_id": "abc123"}

    def export(self, name, presets):
        self.exported = (name, presets)
        return {"job_id": "abc123"}

    def job(self, job_id):
        return {"job_id": job_id, "status": "done", "result": {"output": "x.mp4"}}


class _FakeDispatcher:
    """Dispatcher que sempre "consegue" abrir a interface, sem subir nenhum processo de verdade."""

    def __init__(self):
        self.client = _FakeUIClient()
        self.opened: list[tuple[str, str]] = []

    def ensure_ui(self):
        return True

    def open_browser_if_needed(self, name, job_id):
        self.opened.append((name, job_id))


class _FailingDispatcher:
    """Simula a interface indisponível: ensure_ui() sempre lança, como o dispatcher de verdade faria
    se `dmaker ui` não conseguisse subir."""

    def ensure_ui(self):
        raise RuntimeError("interface indisponível (teste)")


def test_render_project_show_ui_false_keeps_local_job_behavior():
    # importado direto (não via stdio): o decorator @server.tool devolve a função original, chamável
    # como Python puro, o que evita depender de um subprocesso para testar o roteamento show_ui.
    import dmaker.mcp_server as mcp_server

    result = mcp_server.render_project("projeto-inexistente-xyz", show_ui=False, wait_seconds=5)
    assert "where" not in result
    assert result["status"] == "error" and "não encontrada" in result["error"]


def test_render_project_show_ui_true_falls_back_to_local_when_ui_unavailable(monkeypatch):
    import dmaker.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "_dispatcher", lambda: _FailingDispatcher())
    result = mcp_server.render_project("projeto-inexistente-xyz", show_ui=True, wait_seconds=5)
    assert "where" not in result  # caiu no job local de sempre, igual ao show_ui=False
    assert result["status"] == "error" and "não encontrada" in result["error"]


def test_render_project_show_ui_true_delegates_to_ui_when_available(monkeypatch):
    import dmaker.mcp_server as mcp_server

    fake = _FakeDispatcher()
    monkeypatch.setattr(mcp_server, "_dispatcher", lambda: fake)
    result = mcp_server.render_project("qualquer-projeto", show_ui=True, wait_seconds=5)
    assert result["where"] == "ui" and result["status"] == "done"
    assert result["url"] == "http://127.0.0.1:9/#project=qualquer-projeto&job=abc123"
    assert fake.client.rendered[0] == "qualquer-projeto"
    assert fake.opened == [("qualquer-projeto", "abc123")]


def test_export_project_show_ui_true_delegates_to_ui_when_available(monkeypatch):
    import dmaker.mcp_server as mcp_server

    fake = _FakeDispatcher()
    monkeypatch.setattr(mcp_server, "_dispatcher", lambda: fake)
    result = mcp_server.export_project(
        "qualquer-projeto", ["instagram/reels", "youtube/shorts"], show_ui=True, wait_seconds=5
    )
    assert result["where"] == "ui" and result["status"] == "done"
    assert fake.client.exported == ("qualquer-projeto", ["instagram/reels", "youtube/shorts"])


def test_export_project_show_ui_false_keeps_local_job_behavior():
    import dmaker.mcp_server as mcp_server

    result = mcp_server.export_project("projeto-inexistente-xyz", ["instagram/reels"], show_ui=False)
    assert "where" not in result
    assert result["status"] == "error"


def test_edit_project_and_timeline_view_via_mcp():
    spec = {
        "output": {"preset": "instagram/stories"},
        "timeline": [{"type": "card", "title": "Editar via MCP", "duration": 1.0}],
        "audio": {"normalize": "off"},
    }

    async def go(session):
        await session.call_tool("save_project", {"name": "mcp-edit-teste", "spec": spec})
        view = await session.call_tool("timeline_view", {"name": "mcp-edit-teste"})
        edited = await session.call_tool(
            "edit_project",
            {"name": "mcp-edit-teste", "op": {"type": "split", "index": 0, "at": 0.5}},
        )
        return _text(view), _text(edited)

    view, edited = asyncio.run(_session(go))
    view_data = json.loads(view)
    assert any(t["id"] == "V1" for t in view_data["tracks"])
    assert json.loads(edited)["total_s"] == 1.0  # dividir não muda a duração total

    spec_path = config.PROJECTS_DIR / "mcp-edit-teste" / "spec.json"
    saved = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(saved["timeline"]) == 2
    spec_path.unlink()
    spec_path.parent.rmdir()
