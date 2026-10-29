"""Loop de conversa do agente: liga um `ChatModel` (Ollama ou compatível com a OpenAI) às ferramentas do DMaker.

A cada passo o modelo vê o histórico inteiro e decide entre responder ou chamar ferramentas; erro de
ferramenta vira texto de volta para o modelo (nunca uma exceção que derrubaria a conversa), para ele
tentar se recuperar sozinho, como pediria qualquer IA operando por function calling. Antes de executar, o
`ToolGate` (se houver) confere os argumentos, os caminhos e a confirmação do usuário.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .llm import ChatModel
from .safety import PendingCall, ToolGate, is_affirmative
from .tools import ToolHost, ToolSpec, to_ollama_tools, truncate_result

DEFAULT_MAX_STEPS = 25
DEFAULT_TRUNCATE_LIMIT = 6000
GIVE_UP_WARNING = (
    "Desisti depois de várias etapas sem chegar a uma resposta final. Tente de novo com um pedido mais "
    "simples ou específico."
)


@dataclass
class AgentLoop:
    model: ChatModel
    tools: ToolHost
    system: str
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    max_steps: int = DEFAULT_MAX_STEPS
    gate: ToolGate | None = None
    steps_taken: int = field(default=0, init=False)  # voltas ao modelo no último pedido (a bateria mede)
    _messages: list[dict[str, Any]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._messages = [{"role": "system", "content": self.system}]

    def reset(self) -> None:
        """Limpa o histórico de conversa, voltando só à mensagem de sistema."""
        self._messages = [{"role": "system", "content": self.system}]

    def configure(self, system: str, tools: ToolHost) -> None:
        """Troca o prompt e as ferramentas sem perder a conversa (o pedido seguinte caiu em outro kit)."""
        self.system = system
        self.tools = tools
        self._messages[0] = {"role": "system", "content": system}

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _refresh_gate(self, specs: list[ToolSpec]) -> None:
        """O esquema de cada ferramenta do kit atual: contra ele os argumentos do modelo são conferidos."""
        if self.gate is not None:
            self.gate.schemas = {spec.name: spec.parameters for spec in specs}

    def _run_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        self._emit("tool_call", {"name": name, "arguments": arguments})
        refusal = self.gate.check(name, arguments) if self.gate is not None else None
        if refusal is not None:
            self._emit("tool_blocked", {"name": name, "reason": refusal})
            result = refusal
        else:
            try:
                result = self.tools.call(name, arguments)
            except Exception as exc:  # noqa: BLE001 - erro de ferramenta nunca deve derrubar o loop
                result = f"erro: {exc}"
        result = truncate_result(result, DEFAULT_TRUNCATE_LIMIT)
        if self.gate is not None:
            self.gate.known_paths.remember(result)  # o que uma ferramenta listou pode ser usado depois
        self._emit("tool_result", {"name": name, "result": result})
        return result

    def _run_confirmed(self, pending: PendingCall) -> None:
        """Executa a chamada que a pessoa acabou de confirmar, exatamente como foi pedida, e a põe no histórico."""
        arguments = dict(pending.arguments)
        self._emit("tool_call", {"name": pending.tool, "arguments": arguments, "confirmed": True})
        try:
            result = self.tools.call(pending.tool, arguments)
        except Exception as exc:  # noqa: BLE001 - erro de ferramenta nunca deve derrubar o loop
            result = f"erro: {exc}"
        result = truncate_result(result, DEFAULT_TRUNCATE_LIMIT)
        if self.gate is not None:
            self.gate.known_paths.remember(result)
        self._emit("tool_result", {"name": pending.tool, "result": result})
        self._messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": pending.tool, "arguments": arguments}}],
            }
        )
        self._messages.append({"role": "tool", "tool_name": pending.tool, "content": result})

    def ask(self, user_message: str, facts: str = "") -> str:
        """Manda uma mensagem do usuário, roda o loop de ferramentas e devolve a resposta final.

        `facts` é o bloco "o que o pedido já diz": vai junto da mensagem para o modelo, mas a conferência do "sim" de
        uma confirmação pendente olha só o que a pessoa escreveu.
        """
        sent = f"{user_message}\n\n{facts}" if facts else user_message
        self._messages.append({"role": "user", "content": sent})
        if self.gate is not None:
            self.gate.known_paths.remember(sent)  # um caminho que a pessoa escreveu não é inventado
        specs = self.tools.specs()
        self._refresh_gate(specs)
        tool_specs = to_ollama_tools(specs)
        self.steps_taken = 0
        # Qualquer mensagem descarta a pendência; só um "sim" claro a executa, e executa a chamada confirmada.
        pending = self.gate.pending if self.gate is not None else None
        if self.gate is not None:
            self.gate.pending = None
        if pending is not None and is_affirmative(user_message):
            self._run_confirmed(pending)

        for _ in range(self.max_steps):
            started = time.monotonic()
            reply = self.model.chat(self._messages, tool_specs)
            self.steps_taken += 1
            self._emit(
                "model_reply",
                {
                    "seconds": round(time.monotonic() - started, 2),
                    "tool_calls": len(reply.tool_calls),
                    "prompt_tokens": reply.prompt_tokens,
                    "completion_tokens": reply.completion_tokens,
                },
            )
            if reply.thinking:
                self._emit("thinking", {"text": reply.thinking})

            if not reply.tool_calls:
                self._messages.append({"role": "assistant", "content": reply.content})
                self._emit("answer", {"text": reply.content})
                return reply.content

            self._messages.append(
                {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": [
                        {"function": {"name": call.name, "arguments": call.arguments}}
                        for call in reply.tool_calls
                    ],
                }
            )
            for call in reply.tool_calls:
                result = self._run_tool_call(call.name, call.arguments)
                self._messages.append({"role": "tool", "tool_name": call.name, "content": result})

        self._messages.append({"role": "assistant", "content": GIVE_UP_WARNING})
        self._emit("answer", {"text": GIVE_UP_WARNING})
        return GIVE_UP_WARNING
