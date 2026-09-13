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
