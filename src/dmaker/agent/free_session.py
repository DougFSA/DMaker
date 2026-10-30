"""Conversa livre: o modelo local como assistente comum, sem ferramentas e sem triagem de kit.

É o segundo modo de uma conversa do agente. "Operar o DMaker" (`AgentSession`) escolhe um kit de ferramentas a cada
pedido; aqui o modelo só conversa, com o mesmo laço (fluxo, Parar, aparo do histórico, conversa salva), mas sem nada
que execute algo no computador. Por isso não há `ToolGate`: não existe ferramenta para barrar.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .llm import ChatModel
from .loop import AgentLoop, TurnControl
from .session import abort_chat
from .tools import ToolSpec

FREE_SYSTEM_PROMPT = """Você é um assistente de conversa que roda no computador da pessoa, sem internet.

- Responda sempre em português do Brasil, de forma clara e direta, sem travessão.
- Se não souber algo, diga que não sabe em vez de inventar.
- Nesta conversa você não tem ferramentas: não finja abrir arquivos nem executar ações. Trabalhe só com o que a
  pessoa escreveu aqui.
"""

NO_TOOLS_ANSWER = "Esta conversa não tem ferramentas. Responda só com o que a pessoa escreveu."


class NoTools:
    """O `ToolHost` vazio: o modelo não recebe ferramenta nenhuma, e se pedir uma ouve que não existe."""

    def specs(self) -> list[ToolSpec]:
        return []

    def call(self, name: str, arguments: dict) -> str:
        return NO_TOOLS_ANSWER


@dataclass
class FreeSession:
    """Uma conversa livre: o mesmo contrato de `ConversationSession`, sobre um laço sem ferramentas."""

    chat: ChatModel
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    system: str = FREE_SYSTEM_PROMPT
    current_kits: tuple[str, ...] = field(default=(), init=False)  # nunca há kit: o contrato pede o campo
    _loop: AgentLoop = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._loop = AgentLoop(model=self.chat, tools=NoTools(), system=self.system, on_event=self.on_event)

    def ask(self, message: str, control: TurnControl | None = None) -> str:
        return self._loop.ask(message, "", control)

    @property
    def interrupted(self) -> bool:
        return self._loop.interrupted

    @property
    def history(self) -> list[dict[str, Any]]:
        return self._loop.history

    def load_history(self, messages: Sequence[dict[str, Any]], kits: Sequence[str] = ()) -> None:
        self._loop.load_history(copy.deepcopy(list(messages)))

    def abort(self) -> None:
        abort_chat(self.chat)

    def reset(self) -> None:
        self._loop.reset()
