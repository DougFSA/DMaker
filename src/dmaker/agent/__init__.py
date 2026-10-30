"""Agente local: liga um modelo (Ollama ou servidor compatível com a OpenAI) às ferramentas MCP do DMaker.

Pensado para operar o editor por conversa, sem internet: a triagem escolhe um kit de ferramentas pelo pedido,
o modelo vê só o manual curto daquele kit e o `ToolGate` confere argumentos, caminhos e confirmações antes de
qualquer chamada. As ferramentas são as do servidor MCP, as mesmas que o Claude usa.
"""

from __future__ import annotations

from .kits import BASE_TOOLS, EXCLUDED_TOOLS, KITS, Kit, kit_by_name
from .llm import DEFAULT_OLLAMA_URL, OLLAMA_URL_ENV, ChatModel, OllamaChat, Reply, StreamingChat, ToolCall
from .loop import AgentLoop
from .openai_chat import OpenAICompatibleChat
from .prompt import system_prompt
from .safety import ConfirmationPolicy, ConfirmationRequest, ToolGate
from .session import AgentSession
from .settings import AgentSettings, build_catalog, build_chat, load_settings
from .tools import (
    AGENT_TOOLS,
    McpToolHost,
    ProgressReportingHost,
    ToolHost,
    ToolSpec,
    to_ollama_tools,
    truncate_result,
)
from .transport import ChatStreamError
from .triage import Triage, triage

__all__ = [
    "AGENT_TOOLS",
    "BASE_TOOLS",
    "DEFAULT_OLLAMA_URL",
    "EXCLUDED_TOOLS",
    "KITS",
    "OLLAMA_URL_ENV",
    "AgentLoop",
    "AgentSession",
    "AgentSettings",
    "ChatModel",
    "ChatStreamError",
    "ConfirmationPolicy",
    "ConfirmationRequest",
    "Kit",
    "McpToolHost",
    "OllamaChat",
    "OpenAICompatibleChat",
    "ProgressReportingHost",
    "Reply",
    "StreamingChat",
    "ToolCall",
    "ToolGate",
    "ToolHost",
    "ToolSpec",
    "Triage",
    "build_catalog",
    "build_chat",
    "kit_by_name",
    "load_settings",
    "system_prompt",
    "to_ollama_tools",
    "triage",
    "truncate_result",
]
