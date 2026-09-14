"""Cliente de chat para um modelo local do Ollama, com function calling (`POST /api/chat`).

Só stdlib (`urllib`), no padrão de `pipeline/remote.py`: nada de dependência nova para falar com um
servidor HTTP local. `opener` é injetável para testar sem um Ollama de verdade no ar.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

OLLAMA_URL_ENV = "DMAKER_OLLAMA_URL"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

# Verificações de saúde (is_alive/has_model) não devem prender o chamador; um Ollama fora do ar costuma
# recusar a conexão na hora, não travar.
HEALTH_CHECK_TIMEOUT = 5.0


def ollama_url() -> str:
    """Endereço do Ollama: `DMAKER_OLLAMA_URL` se definida, senão o padrão local."""
    return os.environ.get(OLLAMA_URL_ENV, DEFAULT_OLLAMA_URL)


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: str | None = None


class ChatModel(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> Reply: ...


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """`arguments` de uma tool_call pode vir como dict (formato usual) ou como string JSON."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_tool_calls(raw: list[dict] | None) -> list[ToolCall]:
    calls = []
    for item in raw or []:
        function = item.get("function", {})
        calls.append(
            ToolCall(name=function.get("name", ""), arguments=_parse_arguments(function.get("arguments")))
        )
    return calls


def _normalize_model_name(name: str) -> str:
    """Ignora só a tag ":latest": "gpt-oss" e "gpt-oss:latest" contam como o mesmo modelo."""
    return name[: -len(":latest")] if name.endswith(":latest") else name


@dataclass
class OllamaChat:
    """Fala com `POST /api/chat` de um servidor Ollama local, sem streaming."""

    model: str
    base_url: str = DEFAULT_OLLAMA_URL
    num_ctx: int = 16384
    timeout: float = 600.0
    opener: Callable[..., Any] = urllib.request.urlopen

    def _request(self, method: str, path: str, body: dict | None, timeout: float) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}", data=data, method=method, headers=headers
        )
        with self.opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        """Uma volta de conversa: `stream: false`, resposta inteira de uma vez."""
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"num_ctx": self.num_ctx},
        }
        data = self._request("POST", "/api/chat", body, self.timeout)
        message = data.get("message") or {}
        return Reply(
            content=message.get("content") or "",
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            thinking=message.get("thinking") or None,
        )

    def is_alive(self) -> bool:
        """Verificação rápida e barata; um Ollama fora do ar não deve travar quem chamou."""
        try:
            self._request("GET", "/api/tags", None, HEALTH_CHECK_TIMEOUT)
            return True
        except (OSError, ValueError):
            return False

    def has_model(self) -> bool:
        """Confere se `model` está instalado (`GET /api/tags`); aceita nome com ou sem tag ":latest"."""
        try:
            data = self._request("GET", "/api/tags", None, HEALTH_CHECK_TIMEOUT)
        except (OSError, ValueError):
            return False
        wanted = _normalize_model_name(self.model)
        installed = data.get("models") or []
        return any(_normalize_model_name(m.get("name", "")) == wanted for m in installed)
