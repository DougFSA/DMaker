"""Cliente de chat para servidores compatíveis com a API da OpenAI (llama.cpp server, LM Studio, vLLM).

É a segunda implementação do protocolo `ChatModel`, ao lado do `OllamaChat`: o agente fala o mesmo idioma de
mensagens e ferramentas, e este adaptador converte para o formato da OpenAI (`POST /v1/chat/completions`,
chamadas de ferramenta com `id` e argumentos em texto JSON). Só `urllib`, no padrão do `OllamaChat`, e
`opener` injetável para testar sem servidor de verdade.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .llm import HEALTH_CHECK_TIMEOUT, Reply, parse_tool_calls

DEFAULT_OPENAI_URL = "http://127.0.0.1:8080"


def to_openai_messages(messages: list[dict]) -> list[dict]:
    """Converte o histórico do agente (formato do Ollama) para o da OpenAI.

    A OpenAI exige um `id` em cada chamada de ferramenta e o mesmo `id` na resposta (`tool_call_id`), e os
    argumentos como texto JSON. O agente não guarda ids, então o pareamento é pela ordem: a n-ésima resposta
    de ferramenta depois de uma mensagem do assistente responde à n-ésima chamada dela.
    """
    converted: list[dict] = []
    pending: list[str] = []
    counter = 0
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            calls = []
            pending = []
            for call in message["tool_calls"]:
                counter += 1
                call_id = f"call_{counter}"
                pending.append(call_id)
                function = call["function"]
                arguments = function.get("arguments", {})
                calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": function["name"],
                            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                        },
                    }
                )
            converted.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
        elif role == "tool":
            call_id = pending.pop(0) if pending else f"call_{counter}"
            converted.append({"role": "tool", "tool_call_id": call_id, "content": message.get("content", "")})
        else:
            converted.append({"role": role, "content": message.get("content", "")})
    return converted


def _text_content(content: Any) -> str:
    """`content` costuma ser texto, mas alguns servidores mandam uma lista de partes `{type, text}`."""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


@dataclass
class OpenAICompatibleChat:
    """Fala com `POST /v1/chat/completions` de um servidor local compatível com a OpenAI, sem streaming."""

    model: str
    base_url: str = DEFAULT_OPENAI_URL
    timeout: float = 1800.0  # um modelo grande em CPU leva minutos só para ler o prompt de sistema
    temperature: float | None = None
    api_key: str | None = None  # servidores locais não pedem; alguns (LM Studio) aceitam qualquer valor
    opener: Callable[..., Any] = urllib.request.urlopen

    def _request(self, method: str, path: str, body: dict | None, timeout: float) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}", data=data, method=method, headers=headers
        )
        with self.opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        """Uma volta de conversa: `stream: false`, resposta inteira de uma vez."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if self.temperature is not None:
            body["temperature"] = self.temperature
        data = self._request("POST", "/v1/chat/completions", body, self.timeout)
        choices = data.get("choices") or [{}]
        message = choices[0].get("message") or {}
        return Reply(
            content=_text_content(message.get("content")),
            tool_calls=parse_tool_calls(message.get("tool_calls")),
            thinking=message.get("reasoning_content") or message.get("reasoning") or None,
        )

    def is_alive(self) -> bool:
        """Verificação rápida e barata; um servidor fora do ar não deve travar quem chamou."""
        try:
            self._request("GET", "/v1/models", None, HEALTH_CHECK_TIMEOUT)
            return True
        except (OSError, ValueError):
            return False

    def has_model(self) -> bool:
        """Confere se `model` aparece em `GET /v1/models`; o llama.cpp server serve um só e aceita qualquer nome."""
        try:
            data = self._request("GET", "/v1/models", None, HEALTH_CHECK_TIMEOUT)
        except (OSError, ValueError):
            return False
        installed = data.get("data") or []
        return any(item.get("id") == self.model for item in installed)

    def served_models(self) -> list[str]:
        """Os modelos que o servidor diz ter carregados (vazio se ele não responde)."""
        try:
            data = self._request("GET", "/v1/models", None, HEALTH_CHECK_TIMEOUT)
        except (OSError, ValueError):
            return []
        return [item.get("id", "") for item in data.get("data") or []]
