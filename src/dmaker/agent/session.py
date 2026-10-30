"""Sessão do agente: triagem do pedido, kit de ferramentas, prompt e loop num só objeto.

A CLI (`dmaker agent`), a interface (painel de conversa) e a bateria de avaliação usam a mesma sessão; só mudam
o motor de conversa, a política de confirmação e quem escuta os eventos. A cada mensagem a triagem escolhe o
kit e o loop troca de prompt e de ferramentas, sem perder a conversa.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .extraction import extract_facts, render_facts
from .kits import FREE_HTML_TOOLS, KITS, Kit, kit_by_name, tools_for_kits
from .llm import ChatModel, StreamingChat
from .loop import AgentLoop, TurnControl
from .prompt import ManualLoader, system_prompt
from .safety import ConfirmationPolicy, DenyAll, ToolGate
from .tools import McpToolHost, ToolHost
from .transport import ShouldStop
from .triage import Triage, triage

HostFactory = Callable[[list[str]], ToolHost]


def default_host_factory(argument_defaults: dict[str, Any] | None = None) -> HostFactory:
    """O host padrão: o servidor MCP em processo, só com as ferramentas do kit."""

    def make(tool_names: list[str]) -> ToolHost:
        return McpToolHost(allowed=tool_names, argument_defaults=argument_defaults)

    return make


def server_tool_names() -> set[str]:
    """As ferramentas que o servidor MCP expõe de fato (os kits podem citar nomes que ainda não existem)."""
    import asyncio

    from .. import mcp_server

    return {tool.name for tool in asyncio.run(mcp_server.server.list_tools())}


class ConversationSession(Protocol):
    """O que uma conversa salva precisa de qualquer sessão: perguntar, parar e guardar/retomar o histórico.

    `AgentSession` (operar o DMaker, com ferramentas) e `FreeSession` (conversa livre, sem ferramentas) a cumprem; a
    interface só conhece este contrato, então o modo da conversa não espalha `if` pelas rotas.
    """

    chat: ChatModel
    current_kits: tuple[str, ...]

    def ask(self, message: str, control: TurnControl | None = None) -> str: ...

    @property
    def interrupted(self) -> bool: ...

    @property
    def history(self) -> list[dict[str, Any]]: ...

    def load_history(self, messages: Sequence[dict[str, Any]], kits: Sequence[str] = ()) -> None: ...

    def abort(self) -> None: ...

    def reset(self) -> None: ...


def abort_chat(chat: ChatModel) -> None:
    """Fecha a conexão da resposta em curso, se o motor sabe fazer isso (quem pede Parar marcou o sinal antes)."""
    if isinstance(chat, StreamingChat):
        chat.abort()


@dataclass
class AgentSession:
    """Uma conversa com o agente. `available` é o que o servidor expõe; `kits` e `manual_loader` entram por injeção."""

    chat: ChatModel
    host_factory: HostFactory
    available: Collection[str]
    policy: ConfirmationPolicy = field(default_factory=DenyAll)
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    kits: Sequence[Kit] = KITS
    manual_loader: ManualLoader | None = None
    free_html: bool = False
    project_exists: Callable[[str], bool] | None = None
    known_projects: Callable[[], Sequence[str]] | None = (
        None  # os projetos que existem, para achar o nome no pedido
    )
    max_steps: int = 25
    current_kits: tuple[str, ...] = field(default=(), init=False)
    _loop: AgentLoop | None = field(default=None, init=False, repr=False)

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def tool_names(self, kit_names: Sequence[str]) -> list[str]:
        """As ferramentas dos kits escolhidos que o servidor tem (e, sem a configuração, sem o HTML livre)."""
        chosen = [kit_by_name(name) for name in kit_names]
        names = tools_for_kits(chosen, self.available)
        return names if self.free_html else [name for name in names if name not in FREE_HTML_TOOLS]

    def _build_loop(self, kit_names: Sequence[str]) -> AgentLoop:
        host = self.host_factory(self.tool_names(kit_names))
        gate_arguments: dict[str, Any] = {"schemas": {}, "policy": self.policy}
        if self.project_exists is not None:
            gate_arguments["project_exists"] = self.project_exists
        return AgentLoop(
            model=self.chat,
            tools=host,
            system=system_prompt(kit_names, self.manual_loader),
            on_event=self.on_event,
            max_steps=self.max_steps,
            gate=ToolGate(**gate_arguments),
        )

    def choose(self, message: str, should_stop: ShouldStop | None = None) -> Triage:
        """Escolhe o kit do pedido; uma resposta curta ("sim", "pode") continua no kit anterior."""
        result = triage(
            message, self.chat, previous=self.current_kits, kits=self.kits, should_stop=should_stop
        )
        self._emit("triage", {"kits": list(result.kits), "method": result.method})
        return result

    def ask(self, message: str, control: TurnControl | None = None) -> str:
        """Responde a uma mensagem: triagem, troca de kit se for o caso e o loop de ferramentas."""
        chosen = self.choose(message, control.should_stop if control else None).kits
        if self._loop is None:
            self._loop = self._build_loop(chosen)
        elif chosen != self.current_kits:
            rebuilt = self._build_loop(chosen)
            self._loop.configure(rebuilt.system, rebuilt.tools)
        self.current_kits = tuple(chosen)
        facts = render_facts(extract_facts(message, self._project_names()))
        if facts:
            self._emit("facts", {"text": facts})
        return self._loop.ask(message, facts, control)

    def _project_names(self) -> Sequence[str]:
        if self.known_projects is not None:
            return self.known_projects()
        from ..pipeline.recipes import project_names

        return project_names()

    @property
    def steps_taken(self) -> int:
        return self._loop.steps_taken if self._loop else 0

    @property
    def interrupted(self) -> bool:
        """O último pedido terminou porque a pessoa mandou parar."""
        return self._loop.interrupted if self._loop else False

    @property
    def history(self) -> list[dict[str, Any]]:
        """A conversa que o modelo lê, sem o prompt de sistema, para guardar em disco."""
        return self._loop.history if self._loop else []

    def load_history(self, messages: Sequence[dict[str, Any]], kits: Sequence[str] = ()) -> None:
        """Retoma uma conversa guardada: o kit em uso volta, e com ele o prompt e as ferramentas daquele ponto."""
        if not messages or not kits:
            return
        self._loop = self._build_loop(kits)
        self._loop.load_history(copy.deepcopy(list(messages)))
        self.current_kits = tuple(kits)

    def abort(self) -> None:
        """Fecha a conexão da resposta em curso, para o Parar valer mesmo antes do primeiro trecho."""
        abort_chat(self.chat)

    def reset(self) -> None:
        """Esquece a conversa e o kit atual."""
        if self._loop is not None:
            self._loop.reset()
        self.current_kits = ()
        self._loop = None
