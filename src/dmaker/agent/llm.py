"""Cliente de chat para um modelo local do Ollama, com function calling (`POST /api/chat`).

Só stdlib (`urllib`), no padrão de `pipeline/remote.py`: nada de dependência nova para falar com um
servidor HTTP local. `opener` é injetável para testar sem um Ollama de verdade no ar. A resposta pode vir inteira
(`chat`) ou em fluxo (`stream`), que deixa a tela mostrar o texto chegando e dá como parar no meio.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

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
    prompt_tokens: int | None = None  # o que o servidor leu do histórico: mede se o kit cabe no contexto
    completion_tokens: int | None = None
    # Parar no meio do fluxo: `content` e `thinking` são o que já tinha chegado, e `tool_calls` vem sempre vazio,
    # para que ninguém execute uma ferramenta depois de a pessoa ter pedido para parar.
    interrupted: bool = False


class ChatModel(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> Reply: ...


@runtime_checkable
class StreamingChat(ChatModel, Protocol):
    """Um motor de conversa que também sabe responder em fluxo e ser interrompido de outro thread.

    `stream` faz o mesmo que `chat` e devolve o mesmo `Reply`, mas chama `on_delta(tipo, texto)` a cada trecho que
    chega (`tipo` é "answer" ou "thinking") e consulta `should_stop()` a cada trecho. `abort()`, chamável de outro
    thread, fecha a conexão aberta: serve para o Parar antes do primeiro trecho. Quem pede Parar marca o seu
    `should_stop` ANTES de chamar `abort()`.
    """

    def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        on_delta: OnDelta,
        should_stop: ShouldStop | None = None,
    ) -> Reply: ...

    def abort(self) -> None: ...


def reply_stoppable(
    chat: ChatModel, messages: list[dict], tools: list[dict], should_stop: ShouldStop | None
) -> Reply:
    """Uma resposta inteira que o Parar consegue interromper: em fluxo, se o motor sabe e alguém pode pedir Parar.

    Sem `should_stop` (a CLI, a bateria) é o `chat` de sempre. Serve às chamadas curtas fora do laço (a triagem), que
    em CPU levam minutos quando o modelo ainda está carregando.
    """
    if should_stop is not None and isinstance(chat, StreamingChat):
        return chat.stream(messages, tools, lambda kind, text: None, should_stop)
    return chat.chat(messages, tools)


class HealthCheckedChat(ChatModel, Protocol):
    """Um motor de conversa que sabe dizer se o servidor está no ar e se o modelo configurado está instalado."""

    def is_alive(self) -> bool: ...

    def has_model(self) -> bool: ...


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


def parse_tool_calls(raw: list[dict] | None) -> list[ToolCall]:
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


def same_model(first: str, second: str) -> bool:
    """Se dois nomes são o mesmo modelo instalado (a tag ":latest" é opcional)."""
    return _normalize_model_name(first) == _normalize_model_name(second)


class _OllamaFlow:
    """Junta as linhas NDJSON de `/api/chat` (`stream: true`) num `Reply`, avisando cada trecho que chega."""

    def __init__(self, on_delta: OnDelta) -> None:
        self._on_delta = on_delta
        self._content: list[str] = []
        self._thinking: list[str] = []
        self._tool_calls: list[ToolCall] = []
        self._prompt_tokens: int | None = None
        self._completion_tokens: int | None = None

    def feed(self, line: str) -> bool:
        """Uma linha do fluxo; devolve `True` na última (`done`)."""
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise ChatStreamError("O modelo mandou uma linha ilegível no meio da resposta.") from exc
        if event.get("error"):
            raise ChatStreamError(f"O modelo respondeu com erro: {event['error']}")
        message = event.get("message") or {}
        if thinking := message.get("thinking"):
            self._thinking.append(thinking)
            self._on_delta("thinking", thinking)
        if content := message.get("content"):
            self._content.append(content)
            self._on_delta("answer", content)
        self._tool_calls.extend(parse_tool_calls(message.get("tool_calls")))
        if event.get("done"):
            self._prompt_tokens = event.get("prompt_eval_count")
            self._completion_tokens = event.get("eval_count")
            return True
        return False

    def reply(self, interrupted: bool) -> Reply:
        return Reply(
            content="".join(self._content),
            tool_calls=[] if interrupted else self._tool_calls,
            thinking="".join(self._thinking) or None,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            interrupted=interrupted,
        )


@dataclass
class OllamaChat:
    """Fala com `POST /api/chat` de um servidor Ollama local, inteiro (`chat`) ou em fluxo (`stream`).

    O objeto é mutável de propósito: o modelo, o esforço (`think`) e as opções (`num_ctx`, `temperature`, `seed`) podem
    mudar entre uma mensagem e outra da mesma conversa. Um cliente atende um fluxo por vez.
    """

    model: str
    base_url: str = DEFAULT_OLLAMA_URL
    num_ctx: int = 16384
    timeout: float = 1800.0  # um modelo de 20b em CPU leva minutos só para ler o prompt de sistema
    keep_alive: str = "60m"  # segura o modelo carregado enquanto uma ferramenta longa (sync, render) roda
    temperature: float | None = (
        None  # None: o padrão do modelo; tarefas que pedem fidelidade (tradução) usam baixa
    )
    seed: int | None = (
        None  # None: sorteado a cada resposta; um número repete a mesma resposta (reprodutível)
    )
    think: bool | str | None = (
        None  # modelos de raciocínio: "low" encurta o pensamento (gpt-oss ignora booleano)
    )
    response_format: str | None = None  # "json" obriga a resposta a ser um JSON válido
    opener: Callable[..., Any] = urllib.request.urlopen
    # None: o padrão, que dá ao Parar o socket desde o `connect`; testes injetam um dublê de fluxo aqui
    stream_opener: Callable[..., Any] | None = None
    _guard: StreamGuard = field(default_factory=StreamGuard, init=False, repr=False, compare=False)

    def _request(self, method: str, path: str, body: dict | None, timeout: float) -> dict:
        return request_json(self.opener, self.base_url, method, path, body, timeout)

    def _chat_body(self, messages: list[dict], tools: list[dict], stream: bool) -> dict[str, Any]:
        """O corpo de `/api/chat`; as imagens, se houver, vão cruas em `images` (base64) dentro da mensagem."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": stream,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx},
        }
        if self.temperature is not None:
            body["options"]["temperature"] = self.temperature
        if self.seed is not None:
            body["options"]["seed"] = self.seed
        if self.think is not None:
            body["think"] = self.think
        if self.response_format is not None:
            body["format"] = self.response_format
        return body

    def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        """Uma volta de conversa: `stream: false`, resposta inteira de uma vez."""
        data = self._request(
            "POST", "/api/chat", self._chat_body(messages, tools, stream=False), self.timeout
        )
        message = data.get("message") or {}
        return Reply(
            content=message.get("content") or "",
            tool_calls=parse_tool_calls(message.get("tool_calls")),
            thinking=message.get("thinking") or None,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        on_delta: OnDelta,
        should_stop: ShouldStop | None = None,
    ) -> Reply:
        """Como `chat`, mas em fluxo (`stream: true`, uma linha JSON por trecho), avisando `on_delta` a cada um.

        O `timeout` passa a valer por leitura, e não pela resposta inteira: o que conta é o tempo sem chegar nada
        (o modelo lendo o pedido, ou carregando), e não o quanto a resposta é longa. Parar (`should_stop` ou
        `abort()`) devolve o que já chegou, com `interrupted=True`, e fecha a conexão: o Ollama para de gerar.
        """
        flow = _OllamaFlow(on_delta)
        request = build_request(
            self.base_url, "POST", "/api/chat", self._chat_body(messages, tools, stream=True)
        )
        opener = self.stream_opener or guarded_opener(self._guard)
        interrupted = read_stream(opener, request, self.timeout, self._guard, flow.feed, should_stop)
        return flow.reply(interrupted)

    def abort(self) -> None:
        """Fecha a conexão do fluxo em curso, de qualquer thread; é o que faz o Parar valer antes do primeiro trecho."""
        self._guard.abort()

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
