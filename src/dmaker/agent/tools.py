"""Ponte entre o `AgentLoop` e as ferramentas do servidor MCP do DMaker.

`McpToolHost` chama `mcp_server.server` direto em processo (sem stdio): mesmas ferramentas que qualquer
outra IA usa, só que num subconjunto curado (`AGENT_TOOLS`) para caber num modelo pequeno e sem abrir
espaço para operações que exigem mais julgamento (cortes, multicâmera, picture-in-picture na mão).
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from .. import config

# Subconjunto de ferramentas do servidor MCP liberado para o agente local: tarefas mecânicas só (ver
# CLAUDE.md/skill). Fora daqui: cortes, ritmo, multicâmera, picture-in-picture e edição de marca na mão.
AGENT_TOOLS: list[str] = [
    "list_templates",
    "new_from_template",
    "list_projects",
    "get_project",
    "validate_project",
    "render_project",
    "export_project",
    "qa_report",
    "edit_project",
    "timeline_view",
    "read_captions",
    "fix_captions",
    "probe_media",
    "presets",
    "brands",
    "job_status",
]

# Onde ficam as imagens que uma ferramenta devolveu, para o usuário abrir (o agente só aponta o caminho).
AGENT_IMAGES_DIR = config.JOBS_DIR / "agent"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


class ToolHost(Protocol):
    def specs(self) -> list[ToolSpec]: ...

    def call(self, name: str, arguments: dict) -> str: ...


def to_ollama_tools(specs: list[ToolSpec]) -> list[dict]:
    """Converte specs para o formato de function calling aceito por `tools=` em `/api/chat` do Ollama."""
    return [
        {
            "type": "function",
            "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters},
        }
        for spec in specs
    ]


def truncate_result(text: str, limit: int = 6000) -> str:
    """Corta um resultado de ferramenta longo demais no meio, com aviso, para caber no contexto do modelo."""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    cut = len(text) - limit
    return f"{text[:head]}\n... [cortado, {cut} caracteres] ...\n{text[-tail:]}"


def _format_tool_error(exc: Exception) -> str:
    """Mensagem para o modelo: a causa original (`__cause__`), quando existir, diz mais do que a
    mensagem genérica que `UnexpectedToolError` deixa passar."""
    cause = exc.__cause__
    detail = str(cause) if cause else str(exc)
    return detail or exc.__class__.__name__


def _save_image(block: Any) -> str:
    AGENT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(block.data)
    ext = "png" if "png" in (block.mime_type or "") else "jpg"
    path = AGENT_IMAGES_DIR / f"{uuid.uuid4().hex}.{ext}"
    path.write_bytes(data)
    return f"[imagem: {len(data)} bytes, salva em {path}]"


def _stringify_result(result: Any) -> str:
    """Texto de um `CallToolResult`: `structured_content` (um JSON só, mais confiável que juntar blocos
    de texto fragmentados) mais uma nota por imagem devolvida."""
    image_notes = [_save_image(block) for block in result.content if getattr(block, "type", "") == "image"]
    if result.structured_content is not None:
        payload = result.structured_content
        if isinstance(payload, dict) and set(payload.keys()) == {"result"}:
            payload = payload[
                "result"
            ]  # retorno não-objeto (lista, str...) vem embrulhado em {"result": ...}
        text = json.dumps(payload, ensure_ascii=False)
    else:
        text = "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")
    parts = [p for p in (text, *image_notes) if p]
    text = "\n".join(parts) if parts else "(sem conteúdo)"
    return f"erro: {text}" if result.is_error else text


class McpToolHost:
    """Chama as ferramentas do servidor MCP direto em processo (sem subir um processo `dmaker mcp`)."""

    def __init__(self, server: Any = None, allowed: list[str] | None = None):
        if server is None:
            from .. import mcp_server

            server = mcp_server.server
        self._server = server
        self._allowed = list(AGENT_TOOLS) if allowed is None else list(allowed)

    def specs(self) -> list[ToolSpec]:
        tools = asyncio.run(self._server.list_tools())
        by_name = {tool.name: tool for tool in tools}
        specs = []
        for name in self._allowed:
            tool = by_name.get(name)
            if tool is None:
                continue  # ferramenta liberada para o agente mas não registrada neste servidor (teste)
            specs.append(
                ToolSpec(name=tool.name, description=tool.description or "", parameters=tool.input_schema)
            )
        return specs

    def call(self, name: str, arguments: dict) -> str:
        if name not in self._allowed:
            return f"erro: ferramenta '{name}' não está disponível para o agente"
        try:
            result = asyncio.run(self._server.call_tool(name, arguments))
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira texto para o modelo se recuperar
            return f"erro: {_format_tool_error(exc)}"
        return _stringify_result(result)
