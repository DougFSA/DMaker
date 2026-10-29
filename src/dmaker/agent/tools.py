"""Ponte entre o `AgentLoop` e as ferramentas do servidor MCP do DMaker.

`McpToolHost` chama `mcp_server.server` direto em processo (sem stdio): mesmas ferramentas que qualquer
outra IA usa, só que as do kit que a triagem escolheu (`kits.py`), para caber num modelo pequeno. Nada de
lógica de edição aqui: o agente nunca contorna o servidor.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .. import config
from .kits import all_kit_tool_names

# Tudo o que algum kit pode oferecer ao agente local; cada pedido vê só as ferramentas do seu kit.
AGENT_TOOLS: list[str] = list(all_kit_tool_names())

# Ferramentas longas devolvem um `job_id` e pedem consulta com `job_status`: para um modelo de CPU cada consulta é
# uma volta de minutos. Por isso o agente espera a ferramenta terminar (até este limite) em vez de sondar.
DEFAULT_WAIT_SECONDS = 1800.0
PROGRESS_INTERVAL = 1.0


def agent_images_dir() -> Path:
    """Onde ficam as imagens que uma ferramenta devolveu (o agente só aponta o caminho).

    Lida a cada uso, porque a pasta de jobs pode ser trocada depois da importação (testes, DMAKER_DATA_DIR).
    """
    return config.JOBS_DIR / "agent"


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
    folder = agent_images_dir()
    folder.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(block.data)
    ext = "png" if "png" in (block.mime_type or "") else "jpg"
    path = folder / f"{uuid.uuid4().hex}.{ext}"
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
    """Chama as ferramentas do servidor MCP direto em processo (sem subir um processo `dmaker mcp`).

    `argument_defaults` completa, nas ferramentas que têm o argumento no esquema, o que o modelo não disse
    (`wait_seconds`, para esperar o fim da tarefa; `show_ui=False` quando o agente roda dentro da própria
    interface). O que o modelo pediu explicitamente nunca é trocado.
    """

    def __init__(
        self,
        server: Any = None,
        allowed: list[str] | None = None,
        argument_defaults: Mapping[str, Any] | None = None,
    ):
        if server is None:
            from .. import mcp_server

            server = mcp_server.server
        self._server = server
        self._allowed = list(AGENT_TOOLS) if allowed is None else list(allowed)
        self._defaults = (
            {"wait_seconds": DEFAULT_WAIT_SECONDS} if argument_defaults is None else dict(argument_defaults)
        )
        self._schemas: dict[str, dict] = {}

    def specs(self) -> list[ToolSpec]:
        tools = asyncio.run(self._server.list_tools())
        by_name = {tool.name: tool for tool in tools}
        specs = []
        for name in self._allowed:
            tool = by_name.get(name)
            if tool is None:
                continue  # ferramenta liberada para o agente mas não registrada neste servidor (teste)
            self._schemas[name] = tool.input_schema
            specs.append(
                ToolSpec(name=tool.name, description=tool.description or "", parameters=tool.input_schema)
            )
        return specs

    def _with_defaults(self, name: str, arguments: dict) -> dict:
        if not self._schemas:
            self.specs()
        properties = (self._schemas.get(name) or {}).get("properties") or {}
        filled = dict(arguments)
        for key, value in self._defaults.items():
            if key in properties and key not in filled:
                filled[key] = value
        return filled

    def call(self, name: str, arguments: dict) -> str:
        if name not in self._allowed:
            return f"erro: ferramenta '{name}' não está disponível para o agente"
        try:
            result = asyncio.run(self._server.call_tool(name, self._with_defaults(name, arguments)))
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira texto para o modelo se recuperar
            return f"erro: {_format_tool_error(exc)}"
        return _stringify_result(result)


class ProgressReportingHost:
    """Acompanha uma ferramenta longa: enquanto `inner.call` roda, uma segunda thread avisa o andamento.

    `poll` devolve o que está rodando agora (os jobs do servidor MCP); só o que muda vira aviso, para a interface
    mostrar a barra andando sem inundar o canal. A chamada em si continua síncrona e devolve o mesmo resultado.
    """

    def __init__(
        self,
        inner: ToolHost,
        on_progress: Callable[[str, dict], None],
        poll: Callable[[], list[dict]],
        interval: float = PROGRESS_INTERVAL,
    ) -> None:
        self._inner = inner
        self._on_progress = on_progress
        self._poll = poll
        self._interval = interval

    def specs(self) -> list[ToolSpec]:
        return self._inner.specs()

    def call(self, name: str, arguments: dict) -> str:
        stop = threading.Event()
        watcher = threading.Thread(target=self._watch, args=(name, stop), daemon=True, name="dmaker-progress")
        watcher.start()
        try:
            return self._inner.call(name, arguments)
        finally:
            stop.set()
            watcher.join(timeout=self._interval * 2 + 1)

    def _watch(self, name: str, stop: threading.Event) -> None:
        last: dict[str, tuple] = {}
        while not stop.is_set():
            for snapshot in self._poll():
                key = snapshot.get("job_id", "")
                state = (snapshot.get("status"), json.dumps(snapshot.get("progress") or {}, sort_keys=True))
                if last.get(key) != state:
                    last[key] = state
                    self._on_progress(name, snapshot)
            stop.wait(self._interval)
