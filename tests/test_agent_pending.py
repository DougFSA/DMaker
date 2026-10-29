"""Confirmação por conversa: a chamada fica pendente e só um sim claro a executa, exatamente como foi confirmada."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.agent.llm import Reply, ToolCall
from dmaker.agent.loop import AgentLoop
from dmaker.agent.safety import (
    ConfirmationRequest,
    ConversationalConfirmation,
    PendingCall,
    ToolGate,
    is_affirmative,
)
from dmaker.agent.tools import ToolSpec
from dmaker.pipeline.dubbing import default_project_path

RENDER = {"name_or_path": "meu-video"}


class Script:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools):
        return self.replies.pop(0)


class Host:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def specs(self):
        schema = {
            "type": "object",
            "properties": {"name_or_path": {"type": "string"}, "preview": {"type": "boolean"}},
            "required": ["name_or_path"],
        }
        return [ToolSpec("render_project", "r", schema)]

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return '{"output": "saida.mp4"}'


def make_loop(replies):
    host = Host()
    policy = ConversationalConfirmation()
    events: list[tuple[str, dict]] = []
    loop = AgentLoop(
        model=Script(replies),
        tools=host,
        system="s",
        on_event=lambda kind, data: events.append((kind, data)),
        gate=ToolGate(schemas={}, policy=policy),
    )
    return loop, host, policy, events


def ask_for_the_render(loop):
    """O modelo chama o render final; o gate adia e o modelo faz a pergunta à pessoa."""
    return loop.ask("renderiza o vídeo final do meu-video")


def call_then_question():
    return [Reply("", [ToolCall("render_project", RENDER)]), Reply("Posso gerar o vídeo final?")]


# ---------- a política e o gate ----------


def test_the_conversational_policy_defers_instead_of_answering():
    policy = ConversationalConfirmation()
    gate = ToolGate(schemas={}, policy=policy)

    text = gate.check("render_project", RENDER)

    assert (
        text is not None
        and "Aguardando o sim do usuário" in text
        and "não chame a ferramenta de novo" in text
    )
    assert gate.pending == PendingCall(
        "render_project", RENDER, "Posso gerar o vídeo final (leva alguns minutos)?"
    )
    assert policy.asked == ["render_project"]


def test_a_call_that_needs_no_confirmation_leaves_nothing_pending():
    gate = ToolGate(schemas={}, policy=ConversationalConfirmation())

    assert gate.check("render_project", {"name_or_path": "x", "preview": True}) is None
    assert gate.pending is None


# ---------- o sim, o não, o ambíguo e a pendência descartada ----------


def test_a_clear_yes_runs_the_pending_call_exactly_as_it_was_confirmed():
    loop, host, _, events = make_loop([*call_then_question(), Reply("Pronto, saiu em saida.mp4.")])
    ask_for_the_render(loop)
    assert host.calls == []  # a pergunta foi feita e nada rodou

    answer = loop.ask("Sim, confirmo.")

    assert host.calls == [("render_project", RENDER)]
    assert answer == "Pronto, saiu em saida.mp4."
    confirmed = [data for kind, data in events if kind == "tool_call" and data.get("confirmed")]
    assert confirmed == [{"name": "render_project", "arguments": RENDER, "confirmed": True}]
    roles = [m["role"] for m in loop._messages]
    assert roles[-3:] == ["assistant", "tool", "assistant"]  # a chamada confirmada entra no histórico


def test_a_no_runs_nothing_and_clears_the_pending_call():
    loop, host, _, _ = make_loop([*call_then_question(), Reply("Tudo bem, não renderizo.")])
    ask_for_the_render(loop)

    loop.ask("Não, deixa para depois.")

    assert host.calls == [] and loop.gate.pending is None


@pytest.mark.parametrize(
    "message",
    [
        "Sim, mas troca o preset para shorts",
        "Pode ser, antes mostra a prévia",
        "Talvez",
        "Sim?",
        "Sim, confirmo, e aproveita para exportar também todos os outros projetos que eu tenho aqui na pasta agora",
    ],
)
def test_an_ambiguous_answer_runs_nothing(message):
    loop, host, _, _ = make_loop([*call_then_question(), Reply("Entendi, o que muda?")])
    ask_for_the_render(loop)

    loop.ask(message)

    assert host.calls == [] and loop.gate.pending is None


def test_any_other_message_discards_the_pending_call_so_a_later_yes_runs_nothing():
    loop, host, _, _ = make_loop(
        [*call_then_question(), Reply("Os formatos são Reels e Shorts."), Reply("Não tenho nada pendente.")]
    )
    ask_for_the_render(loop)

    loop.ask("Antes, quais formatos existem?")  # outra pergunta: a pendência cai
    loop.ask("Sim")

    assert host.calls == []


def test_the_confirmed_call_still_stops_at_the_gate_checks_it_already_passed():
    """A pendência só nasce depois de esquema e caminhos conferidos: o sim não abre caminho para argumento errado."""
    loop, host, policy, _ = make_loop(
        [Reply("", [ToolCall("render_project", {"preview": True})]), Reply("Corrijo.")]
    )

    loop.ask("renderiza")

    assert host.calls == [] and loop.gate.pending is None and policy.asked == []


def test_a_confirmation_the_person_answered_is_not_asked_again_in_the_same_call():
    loop, host, policy, _ = make_loop([*call_then_question(), Reply("Pronto.")])
    ask_for_the_render(loop)
    loop.ask("Sim")

    assert policy.asked == ["render_project"] and len(host.calls) == 1


# ---------- refazer uma dublagem que já existe ----------

VIDEO = "C:/v/aula.mp4"
DUB = {"path": VIDEO, "target_language": "en"}


class DubHost(Host):
    def specs(self):
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}, "target_language": {"type": "string"}},
            "required": ["path", "target_language"],
        }
        return [ToolSpec("dub_prepare", "d", schema)]

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return '{"status": "done"}'


def make_dub_loop(replies, project_on_disk: bool):
    """O agente com um disco falso: o vídeo existe e, conforme o caso, a dublagem dele para inglês também."""
    existing = {VIDEO}
    if project_on_disk:
        existing.add(str(default_project_path(Path(VIDEO), "en")))
    host = DubHost()
    loop = AgentLoop(
        model=Script(replies),
        tools=host,
        system="s",
        gate=ToolGate(schemas={}, policy=ConversationalConfirmation(), exists=existing.__contains__),
    )
    return loop, host


def dub_call_then_question():
    return [
        Reply("", [ToolCall("dub_prepare", DUB)]),
        Reply("Já existe uma dublagem deste vídeo. Posso refazê-la por cima?"),
    ]


def test_redoing_an_existing_dubbing_waits_for_the_yes_and_a_clear_yes_runs_the_same_call():
    loop, host = make_dub_loop([*dub_call_then_question(), Reply("Refiz a dublagem.")], project_on_disk=True)
    loop.ask("dubla o vídeo da aula para inglês")

    assert host.calls == []  # a pergunta foi feita e nada foi escrito por cima
    assert loop.gate.pending is not None and "apaga as traduções revisadas" in loop.gate.pending.question

    answer = loop.ask("Sim, pode refazer.")

    assert host.calls == [("dub_prepare", DUB)] and answer == "Refiz a dublagem."


def test_redoing_an_existing_dubbing_with_a_no_keeps_the_revised_translations():
    loop, host = make_dub_loop(
        [*dub_call_then_question(), Reply("Mantive a dublagem.")], project_on_disk=True
    )
    loop.ask("dubla o vídeo da aula para inglês")

    loop.ask("Não, deixa como está.")

    assert host.calls == [] and loop.gate.pending is None


def test_a_dubbing_of_a_new_video_runs_at_once_without_a_question_to_the_person():
    loop, host = make_dub_loop([Reply("", [ToolCall("dub_prepare", DUB)]), Reply("Preparei.")], False)

    loop.ask("dubla o vídeo da aula para inglês")

    assert host.calls == [("dub_prepare", DUB)] and loop.gate.pending is None


# ---------- o que conta como sim ----------


@pytest.mark.parametrize(
    "message",
    [
        "Sim",
        "sim, confirmo",
        "Pode fazer",
        "Claro!",
        "ok",
        "Confirmo.",
        "Sim, confirmo. Use o que já informei e siga em frente.",
    ],
)
def test_clear_yes_answers(message):
    assert is_affirmative(message)


@pytest.mark.parametrize(
    "message",
    [
        "Não",
        "nao quero",
        "Talvez mais tarde",
        "Quais formatos existem?",
        "",
        "Sim, mas só a prévia",
        "Depois eu confirmo",
        "Sim?",
    ],
)
def test_everything_else_is_not_a_yes(message):
    assert not is_affirmative(message)


def test_the_request_object_carries_the_tool_and_the_question():
    request = ConfirmationRequest("render_project", RENDER, "Posso gerar o vídeo final?")

    with pytest.raises(Exception, match="Posso gerar"):
        ConversationalConfirmation().confirm(request)
