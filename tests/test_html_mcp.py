"""O servidor MCP de verdade renderiza o quadro de uma composição em HTML (DMK-26), pelo stdio.

Fica num arquivo à parte porque o `asyncio.run` do cliente não roda numa thread em que um Chromium do Playwright já
está aberto (o laço do Playwright fica "rodando" nela), como acontece no módulo `test_html_render.py`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dmaker.media.browser import browser_problem

from .test_html_render import guide_pages
from .test_mcp import _session, _text

PROBLEM = browser_problem()
pytestmark = pytest.mark.skipif(PROBLEM is not None, reason=f"Chromium do Playwright indisponível: {PROBLEM}")


def test_the_mcp_server_renders_a_real_frame_from_inside_its_own_event_loop(tmp_path: Path):
    """O servidor MCP chama as ferramentas de dentro de um laço asyncio, onde o Playwright síncrono se recusa a rodar:
    o quadro tem que sair mesmo assim, pelo stdio, como a IA o pede."""
    source = tmp_path / "numero"
    source.mkdir()
    (source / "index.html").write_text(guide_pages()[0], encoding="utf-8")

    async def go(session):
        return await session.call_tool(
            "render_html_frame",
            {"src": str(source), "at": 2.0, "size": "1080x960", "background": "#202830", "duration": 5},
        )

    result = asyncio.run(_session(go))
    assert not result.is_error, _text(result)
    assert [c.type for c in result.content].count("image") == 1
    info = json.loads(_text(result))
    assert info["warnings"] == [] and info["size"] == "1080x960" and info["at_s"] == 2.0
