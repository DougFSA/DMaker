"""Agente local: liga um modelo do Ollama às ferramentas MCP do DMaker num loop de conversa no terminal.

Pensado para tarefas mecânicas (criar projeto por template, renderizar, ler QA, corrigir legendas,
exportar) com um modelo pequeno rodando na máquina do usuário, sem depender de nuvem. Cortes, ritmo e
decisões de edição continuam sendo trabalho de um modelo maior (ou de uma pessoa).
"""

from __future__ import annotations

from .llm import DEFAULT_OLLAMA_URL, OLLAMA_URL_ENV, ChatModel, OllamaChat, Reply, ToolCall
from .loop import AgentLoop
from .prompt import system_prompt
from .tools import AGENT_TOOLS, McpToolHost, ToolHost, ToolSpec, to_ollama_tools, truncate_result

__all__ = [
    "AGENT_TOOLS",
    "DEFAULT_OLLAMA_URL",
    "OLLAMA_URL_ENV",
    "AgentLoop",
    "ChatModel",
    "McpToolHost",
    "OllamaChat",
    "Reply",
    "ToolCall",
    "ToolHost",
    "ToolSpec",
    "system_prompt",
    "to_ollama_tools",
    "truncate_result",
]
