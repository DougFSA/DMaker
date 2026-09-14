"""Loop de conversa do agente: liga um `ChatModel` (Ollama) às ferramentas do DMaker (`ToolHost`).

A cada passo o modelo vê o histórico inteiro e decide entre responder ou chamar ferramentas; erro de
ferramenta vira texto de volta para o modelo (nunca uma exceção que derrubaria a conversa), para ele
tentar se recuperar sozinho, como pediria qualquer IA operando por function calling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .llm import ChatModel
from .tools import ToolHost, to_ollama_tools, truncate_result

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
    _messages: list[dict[str, Any]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._messages = [{"role": "system", "content": self.system}]

    def reset(self) -> None:
        """Limpa o histórico de conversa, voltando só à mensagem de sistema."""
        self._messages = [{"role": "system", "content": self.system}]

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _run_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        self._emit("tool_call", {"name": name, "arguments": arguments})
        try:
            result = self.tools.call(name, arguments)
        except Exception as exc:  # noqa: BLE001 - erro de ferramenta nunca deve derrubar o loop
            result = f"erro: {exc}"
        result = truncate_result(result, DEFAULT_TRUNCATE_LIMIT)
        self._emit("tool_result", {"name": name, "result": result})
        return result

    def ask(self, user_message: str) -> str:
        """Manda uma mensagem do usuário, roda o loop de ferramentas e devolve a resposta final."""
        self._messages.append({"role": "user", "content": user_message})
        tool_specs = to_ollama_tools(self.tools.specs())

        for _ in range(self.max_steps):
            reply = self.model.chat(self._messages, tool_specs)
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
