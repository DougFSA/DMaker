"""Loop de conversa do agente: liga um `ChatModel` (Ollama ou compatível com a OpenAI) às ferramentas do DMaker.

A cada passo o modelo vê o histórico inteiro e decide entre responder ou chamar ferramentas; erro de
ferramenta vira texto de volta para o modelo (nunca uma exceção que derrubaria a conversa), para ele
tentar se recuperar sozinho, como pediria qualquer IA operando por function calling. Antes de executar, o
`ToolGate` (se houver) confere os argumentos, os caminhos e a confirmação do usuário.

Quando o motor sabe responder em fluxo (`StreamingChat`), o laço o usa: a tela recebe a resposta e o raciocínio
chegando (`answer_delta`, `thinking_delta`, agrupados) e a etapa em que o agente está (`status`), e a pessoa pode parar
no meio (`TurnControl.should_stop`). Parar guarda o que já tinha chegado, marcado como interrompido, e nenhuma
ferramenta roda depois do pedido. Um motor só com `chat` segue como antes, sem nenhum evento novo.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .flow import DELTA_EVENTS, TOOL_STAGE, DeltaBatcher, stage_label
from .history import (
    DEFAULT_CHARS_PER_TOKEN,
    calibrated_chars_per_token,
    image_count,
    request_chars,
    trim_history,
)
from .llm import ChatModel, Reply, StreamingChat
from .safety import PendingCall, ToolGate, is_affirmative
from .tools import ToolHost, ToolSpec, to_ollama_tools, truncate_result
from .transport import DeltaKind, ShouldStop

DEFAULT_MAX_STEPS = 25
DEFAULT_TRUNCATE_LIMIT = 6000
GIVE_UP_WARNING = (
    "Desisti depois de várias etapas sem chegar a uma resposta final. Tente de novo com um pedido mais "
    "simples ou específico."
)
# O que o modelo lê no lugar da resposta que a pessoa cortou: ele entende que a fala anterior ficou pela metade.
INTERRUPTED_MARK = "[Resposta interrompida pelo usuário.]"
STOPPED_TOOL_RESULT = "Interrompido pelo usuário antes de executar esta ferramenta."


@dataclass(frozen=True)
class TurnControl:
    """O que quem chama controla num turno: parar, o contexto em que o histórico precisa caber e se o modelo estava frio."""

    should_stop: ShouldStop | None = None
    num_ctx: int | None = None  # None: sem aparo (a CLI, a bateria)
    model_cold: bool = False  # o modelo não estava na memória: a primeira espera é o carregamento dele


def trimmed_notice(turns: int) -> str:
    """O aviso da tela quando o aparo tirou turnos do que o modelo lê (eles continuam na transcrição)."""
    what = "A troca mais antiga saiu" if turns == 1 else f"As {turns} trocas mais antigas saíram"
    return f"{what} da memória do modelo para a conversa caber no contexto. Elas continuam na tela."


@dataclass
class AgentLoop:
    model: ChatModel
    tools: ToolHost
    system: str
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    max_steps: int = DEFAULT_MAX_STEPS
    gate: ToolGate | None = None
    steps_taken: int = field(default=0, init=False)  # voltas ao modelo no último pedido (a bateria mede)
    interrupted: bool = field(
        default=False, init=False
    )  # o último pedido terminou porque a pessoa mandou parar
    _messages: list[dict[str, Any]] = field(init=False, repr=False)
    _chars_per_token: float = field(default=DEFAULT_CHARS_PER_TOKEN, init=False, repr=False)
    _tools_chars: int = field(
        default=0, init=False, repr=False
    )  # as definições de ferramenta também ocupam contexto
    _stage: tuple[str, str] | None = field(default=None, init=False, repr=False)
    _streaming: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._messages = [{"role": "system", "content": self.system}]

    def reset(self) -> None:
        """Limpa o histórico de conversa, voltando só à mensagem de sistema."""
        self._messages = [{"role": "system", "content": self.system}]

    @property
    def history(self) -> list[dict[str, Any]]:
        """A conversa que o modelo lê, sem o prompt de sistema: é o que se guarda para continuar depois."""
        return copy.deepcopy(self._messages[1:])

    def load_history(self, messages: Sequence[dict[str, Any]]) -> None:
        """Retoma uma conversa guardada. Os caminhos que ela já citou voltam a contar como conhecidos, como antes de fechar."""
        self._messages = [{"role": "system", "content": self.system}, *copy.deepcopy(list(messages))]
        if self.gate is not None:
            for message in messages:
                if message.get("role") in ("user", "tool"):
                    self.gate.known_paths.remember(str(message.get("content") or ""))

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

    def _set_stage(self, stage: str, tool: str = "") -> None:
        """Diz à tela em que etapa o agente está; só em fluxo, e só quando a etapa muda."""
        if not self._streaming or self._stage == (stage, tool):
            return
        self._stage = (stage, tool)
        data: dict[str, Any] = {"stage": stage, "label": stage_label(stage, tool)}
        if tool:
            data["tool"] = tool
        self._emit("status", data)

    def _skip_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        """Uma chamada que a pessoa interrompeu antes de rodar: fica registrada como barrada, e o modelo sabe por quê."""
        self._emit("tool_call", {"name": name, "arguments": arguments})
        self._emit("tool_blocked", {"name": name, "reason": STOPPED_TOOL_RESULT})
        return STOPPED_TOOL_RESULT

    def _run_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        self._set_stage(TOOL_STAGE, name)
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

    def _trim(self, num_ctx: int | None) -> None:
        """Tira os turnos mais antigos se o pedido não cabe no contexto, e avisa a tela."""
        if num_ctx is None:
            return
        result = trim_history(self._messages, num_ctx, self._tools_chars, self._chars_per_token)
        if result.removed_turns:
            self._messages = result.messages
            self._emit(
                "history_trimmed",
                {"turns": result.removed_turns, "text": trimmed_notice(result.removed_turns)},
            )

    def _learn_density(self, sent_chars: int, images: int, reply: Reply) -> None:
        """Calibra a estimativa de tokens pelo que o servidor contou na resposta (ver `calibrated_chars_per_token`)."""
        if not reply.interrupted and reply.prompt_tokens:
            self._chars_per_token = calibrated_chars_per_token(sent_chars, reply.prompt_tokens, images)

    def _call_model(self, tool_specs: list[dict], stage: str, should_stop: ShouldStop | None) -> Reply:
        """Uma volta ao modelo: em fluxo, quando o motor sabe, contando à tela o que chega; senão o `chat` inteiro."""
        sent_chars = request_chars(self._messages, self._tools_chars)
        images = image_count(self._messages)
        if not isinstance(self.model, StreamingChat):
            reply = self.model.chat(self._messages, tool_specs)
            self._learn_density(sent_chars, images, reply)
            return reply

        def announce(kind: DeltaKind, text: str) -> None:
            self._emit(DELTA_EVENTS[kind], {"text": text})

        batcher = DeltaBatcher(announce)

        def on_delta(kind: DeltaKind, text: str) -> None:
            self._set_stage("thinking" if kind == "thinking" else "writing")
            batcher.add(kind, text)

        self._stage = None
        self._set_stage(stage)
        try:
            reply = self.model.stream(self._messages, tool_specs, on_delta, should_stop)
        finally:
            batcher.flush()  # o que ficou guardado sai antes de qualquer evento seguinte (resposta, ferramenta)
        self._learn_density(sent_chars, images, reply)
        return reply

    def _interrupted_answer(self, partial: str) -> str:
        """Fecha o turno que a pessoa parou: o que chegou fica no histórico e na tela, marcado como interrompido."""
        self.interrupted = True
        text = partial.rstrip()
        content = f"{text}\n\n{INTERRUPTED_MARK}" if text else INTERRUPTED_MARK
        self._messages.append({"role": "assistant", "content": content})
        self._emit("answer", {"text": partial, "interrupted": True})
        return partial

    def ask(self, user_message: str, facts: str = "", control: TurnControl | None = None) -> str:
        """Manda uma mensagem do usuário, roda o loop de ferramentas e devolve a resposta final.

        `facts` é o bloco "o que o pedido já diz": vai junto da mensagem para o modelo, mas a conferência do "sim" de
        uma confirmação pendente olha só o que a pessoa escreveu. `control` traz o Parar, o contexto para o aparo do
        histórico e se o modelo estava frio; sem ele o pedido corre como sempre correu.
        """
        control = control or TurnControl()
        stopped = control.should_stop or (lambda: False)
        sent = f"{user_message}\n\n{facts}" if facts else user_message
        self._messages.append({"role": "user", "content": sent})
        if self.gate is not None:
            self.gate.known_paths.remember(sent)  # um caminho que a pessoa escreveu não é inventado
        specs = self.tools.specs()
        self._refresh_gate(specs)
        tool_specs = to_ollama_tools(specs)
        self.steps_taken = 0
        self.interrupted = False
        self._streaming = isinstance(self.model, StreamingChat)
        self._tools_chars = len(json.dumps(tool_specs, ensure_ascii=False)) if tool_specs else 0
        self._trim(control.num_ctx)
        # Qualquer mensagem descarta a pendência; só um "sim" claro a executa, e executa a chamada confirmada.
        pending = self.gate.pending if self.gate is not None else None
        if self.gate is not None:
            self.gate.pending = None
        if pending is not None and is_affirmative(user_message):
            self._run_confirmed(pending)

        stage = "loading_model" if control.model_cold else "reading"
        for _ in range(self.max_steps):
            if stopped():
                return self._interrupted_answer("")
            started = time.monotonic()
            reply = self._call_model(tool_specs, stage, control.should_stop)
            stage = "reading"  # depois da primeira volta o modelo já está na memória: só relê o histórico
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
            if reply.interrupted:
                return self._interrupted_answer(reply.content)

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
                # cada chamada pedida ganha o seu resultado, mesmo a que não rodou: o par nunca se separa
                if stopped():
                    result = self._skip_tool_call(call.name, call.arguments)
                else:
                    result = self._run_tool_call(call.name, call.arguments)
                self._messages.append({"role": "tool", "tool_name": call.name, "content": result})

        self._messages.append({"role": "assistant", "content": GIVE_UP_WARNING})
        self._emit("answer", {"text": GIVE_UP_WARNING})
        return GIVE_UP_WARNING
