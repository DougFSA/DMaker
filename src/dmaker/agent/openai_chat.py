"""Cliente de chat para servidores compatíveis com a API da OpenAI (llama.cpp server, LM Studio, vLLM).

É a segunda implementação do protocolo `ChatModel`, ao lado do `OllamaChat`: o agente fala o mesmo idioma de
mensagens e ferramentas, e este adaptador converte para o formato da OpenAI (`POST /v1/chat/completions`,
chamadas de ferramenta com `id` e argumentos em texto JSON). Só `urllib`, no padrão do `OllamaChat`, e
`opener` injetável para testar sem servidor de verdade. O fluxo é o SSE da OpenAI (`data: {...}` até `data: [DONE]`).
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .llm import HEALTH_CHECK_TIMEOUT, Reply, ToolCall, _parse_arguments, parse_tool_calls
from .transport import (
    ChatStreamError,
    OnDelta,
    ShouldStop,
    StreamGuard,
    build_request,
    guarded_opener,
    read_stream,
    request_json,
)

DEFAULT_OPENAI_URL = "http://127.0.0.1:8080"

# Os primeiros caracteres do base64 de cada formato: a OpenAI quer o tipo no data URI, e o agente guarda só os bytes.
_IMAGE_SIGNATURES = (
    ("iVBOR", "image/png"),
    ("/9j/", "image/jpeg"),
    ("UklGR", "image/webp"),
    ("R0lGOD", "image/gif"),
)


def image_data_uri(encoded: str) -> str:
    """O data URI de uma imagem em base64 puro (como o Ollama a recebe em `images`); o tipo vem da assinatura."""
    if encoded.startswith("data:"):
        return encoded
    mime = next((mime for prefix, mime in _IMAGE_SIGNATURES if encoded.startswith(prefix)), "image/png")
    return f"data:{mime};base64,{encoded}"


def _user_content(message: dict) -> str | list[dict]:
    """O texto da mensagem do usuário; com `images`, vira a lista de partes (`text` e `image_url`) da OpenAI."""
    text = message.get("content", "")
    images = message.get("images") or []
    if not images:
        return text
    parts: list[dict] = [{"type": "text", "text": text}] if text else []
    parts.extend({"type": "image_url", "image_url": {"url": image_data_uri(image)}} for image in images)
    return parts


def to_openai_messages(messages: list[dict]) -> list[dict]:
    """Converte o histórico do agente (formato do Ollama) para o da OpenAI.

    A OpenAI exige um `id` em cada chamada de ferramenta e o mesmo `id` na resposta (`tool_call_id`), e os
    argumentos como texto JSON. O agente não guarda ids, então o pareamento é pela ordem: a n-ésima resposta
    de ferramenta depois de uma mensagem do assistente responde à n-ésima chamada dela. As imagens da mensagem
    do usuário (`images`, base64) viram partes `image_url`.
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
        elif role == "user":
            converted.append({"role": role, "content": _user_content(message)})
        else:
            converted.append({"role": role, "content": message.get("content", "")})
    return converted


def _text_content(content: Any) -> str:
    """`content` costuma ser texto, mas alguns servidores mandam uma lista de partes `{type, text}`."""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


class _OpenAIFlow:
    """Junta os eventos SSE de `/v1/chat/completions` (`stream: true`) num `Reply`, avisando cada trecho que chega."""

    def __init__(self, on_delta: OnDelta) -> None:
        self._on_delta = on_delta
        self._content: list[str] = []
        self._thinking: list[str] = []
        self._calls: dict[
            int, dict[str, str]
        ] = {}  # índice da chamada -> nome e argumentos (chegam em pedaços)
        self._prompt_tokens: int | None = None
        self._completion_tokens: int | None = None
        self.finished = False  # chegou um `finish_reason`: alguns servidores fecham sem mandar o `[DONE]`

    def feed(self, line: str) -> bool:
        """Uma linha SSE; devolve `True` em `data: [DONE]`. Comentários (`: ping`) e outros campos são ignorados."""
        if not line.startswith("data:"):
            return False
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            return True
        try:
            event = json.loads(payload)
        except ValueError as exc:
            raise ChatStreamError("O servidor mandou um evento ilegível no meio da resposta.") from exc
        if event.get("error"):
            error = event["error"]
            detail = error.get("message", error) if isinstance(error, dict) else error
            raise ChatStreamError(f"O modelo respondeu com erro: {detail}")
        usage = event.get("usage") or {}
        if usage:
            self._prompt_tokens = usage.get("prompt_tokens", self._prompt_tokens)
            self._completion_tokens = usage.get("completion_tokens", self._completion_tokens)
        for choice in event.get("choices") or []:
            self._read_choice(choice)
        return False

    def _read_choice(self, choice: dict) -> None:
        delta = choice.get("delta") or {}
        if thinking := delta.get("reasoning_content") or delta.get("reasoning"):
            self._thinking.append(thinking)
            self._on_delta("thinking", thinking)
        if content := _text_content(delta.get("content")):
            self._content.append(content)
            self._on_delta("answer", content)
        for call in delta.get("tool_calls") or []:
            slot = self._calls.setdefault(call.get("index", len(self._calls)), {"name": "", "arguments": ""})
            function = call.get("function") or {}
            slot["name"] += function.get("name") or ""
            slot["arguments"] += function.get("arguments") or ""
        if choice.get("finish_reason"):
            self.finished = True

    def reply(self, interrupted: bool) -> Reply:
        calls = [
            ToolCall(name=slot["name"], arguments=_parse_arguments(slot["arguments"]))
            for _, slot in sorted(self._calls.items())
        ]
        return Reply(
            content="".join(self._content),
            tool_calls=[] if interrupted else calls,
            thinking="".join(self._thinking) or None,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            interrupted=interrupted,
        )


@dataclass
class OpenAICompatibleChat:
    """Fala com `POST /v1/chat/completions` de um servidor local compatível com a OpenAI, inteiro ou em fluxo."""

    model: str
    base_url: str = DEFAULT_OPENAI_URL
    timeout: float = 1800.0  # um modelo grande em CPU leva minutos só para ler o prompt de sistema
    temperature: float | None = None
    seed: int | None = None
    api_key: str | None = None  # servidores locais não pedem; alguns (LM Studio) aceitam qualquer valor
    opener: Callable[..., Any] = urllib.request.urlopen
    # None: o padrão, que dá ao Parar o socket desde o `connect`; testes injetam um dublê de fluxo aqui
    stream_opener: Callable[..., Any] | None = None
    _guard: StreamGuard = field(default_factory=StreamGuard, init=False, repr=False, compare=False)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _request(self, method: str, path: str, body: dict | None, timeout: float) -> dict:
        return request_json(self.opener, self.base_url, method, path, body, timeout, self._headers())

    def _chat_body(self, messages: list[dict], tools: list[dict], stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "stream": stream,
        }
        if stream:
            body["stream_options"] = {"include_usage": True}  # sem isso o fluxo não traz a contagem de tokens
        if tools:
            body["tools"] = tools
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.seed is not None:
            body["seed"] = self.seed
        return body

    def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        """Uma volta de conversa: `stream: false`, resposta inteira de uma vez."""
        data = self._request(
            "POST", "/v1/chat/completions", self._chat_body(messages, tools, stream=False), self.timeout
        )
        choices = data.get("choices") or [{}]
        message = choices[0].get("message") or {}
        return Reply(
            content=_text_content(message.get("content")),
            tool_calls=parse_tool_calls(message.get("tool_calls")),
            thinking=message.get("reasoning_content") or message.get("reasoning") or None,
            prompt_tokens=(data.get("usage") or {}).get("prompt_tokens"),
            completion_tokens=(data.get("usage") or {}).get("completion_tokens"),
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        on_delta: OnDelta,
        should_stop: ShouldStop | None = None,
    ) -> Reply:
        """Como `chat`, mas em fluxo SSE, avisando `on_delta` a cada trecho; mesmo contrato do `OllamaChat.stream`.

        O `timeout` vale por leitura, e não pela resposta inteira. Parar devolve o que já chegou com `interrupted=True`.
        """
        flow = _OpenAIFlow(on_delta)
        request = build_request(
            self.base_url,
            "POST",
            "/v1/chat/completions",
            self._chat_body(messages, tools, stream=True),
            self._headers(),
        )
        opener = self.stream_opener or guarded_opener(self._guard)
        try:
            interrupted = read_stream(opener, request, self.timeout, self._guard, flow.feed, should_stop)
        except ChatStreamError:
            if not flow.finished:
                raise
            interrupted = False  # a conexão fechou sem o [DONE], mas a resposta já tinha terminado
        return flow.reply(interrupted)

    def abort(self) -> None:
        """Fecha a conexão do fluxo em curso, de qualquer thread; é o que faz o Parar valer antes do primeiro trecho."""
        self._guard.abort()

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
