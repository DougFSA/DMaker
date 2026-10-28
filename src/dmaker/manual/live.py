"""Os dados vivos do código que o manual descreve: a árvore da CLI, as ferramentas MCP e o esquema da spec.

Fica separado de `build.py` porque importar a CLI e o servidor MCP custa caro e porque o teste troca estes dados
por falsos (um comando inventado, por exemplo) para provar que o manual reprova quando o código muda.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .build import BuildInputs
from .field_notes import FIELD_NOTES
from .reference_mcp import ToolDoc, tool_docs


def cli_root() -> Any:
    """A árvore de comandos do Typer, no formato que o gerador de referência lê."""
    import typer

    from ..cli import app

    return typer.main.get_command(app)


def mcp_tools() -> tuple[ToolDoc, ...]:
    from .. import mcp_server

    return tuple(tool_docs(asyncio.run(mcp_server.server.list_tools())))


def spec_schema() -> dict[str, Any]:
    from ..domain.spec import Project

    return Project.model_json_schema()


def agent_tools() -> tuple[str, ...]:
    from ..agent.tools import AGENT_TOOLS

    return tuple(AGENT_TOOLS)


def build_inputs() -> BuildInputs:
    return BuildInputs(
        cli_root=cli_root(),
        tools=mcp_tools(),
        spec_schema=spec_schema(),
        agent_tools=agent_tools(),
        field_notes=FIELD_NOTES,
    )
