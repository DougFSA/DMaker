"""Sessão do agente (triagem, kit, prompt e loop), valores padrão do host MCP e acompanhamento do progresso."""

from __future__ import annotations

import threading

from dmaker.agent.kits import all_kit_tool_names, kit_by_name
from dmaker.agent.llm import Reply, ToolCall
from dmaker.agent.safety import ApproveAll
from dmaker.agent.session import FREE_HTML_TOOLS, AgentSession, server_tool_names
from dmaker.agent.tools import DEFAULT_WAIT_SECONDS, McpToolHost, ProgressReportingHost, ToolSpec


class Script:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[tuple[list[dict], list[dict]]] = []

    def chat(self, messages, tools):
        self.seen.append((list(messages), list(tools)))
        return self.replies.pop(0)


class FakeHost:
    def __init__(self, names):
        self.names = names
        self.calls = []

    def specs(self):
        return [ToolSpec(name, name, {"type": "object"}) for name in self.names]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return "ok"


def make_session(chat, available=None, **kwargs):
    hosts: list[FakeHost] = []

    def factory(names):
        hosts.append(FakeHost(names))
        return hosts[-1]

    everything = available if available is not None else set(all_kit_tool_names())
    session = AgentSession(
        chat=chat,
        host_factory=factory,
        available=everything,
        manual_loader=lambda name: f"MANUAL {name}",
        **kwargs,
    )
    return session, hosts


def test_the_session_gives_the_model_only_the_tools_and_manual_of_the_chosen_kit():
    chat = Script([Reply("pronto")])
    session, hosts = make_session(chat)

    answer = session.ask("Dubla este vídeo para inglês")

    assert answer == "pronto" and session.current_kits == ("dubbing",)
    assert set(hosts[0].names) == {
        "probe_media",
        "job_status",
        "search_manual",
        *kit_by_name("dubbing").tools,
    }
    system = chat.seen[0][0][0]["content"]
    assert "MANUAL agente-dubbing" in system and "MANUAL agente-editing" not in system
    assert {tool["function"]["name"] for tool in chat.seen[0][1]} == set(hosts[0].names)


def test_tools_the_server_does_not_have_are_left_out_of_the_kit():
    session, hosts = make_session(
        Script([Reply("ok")]), available={"probe_media", "edit_project", "job_status"}
    )

    session.ask("Põe um contador de 0 a 95 mg")

    assert set(hosts[0].names) == {"probe_media", "edit_project", "job_status"}


def test_free_html_tools_need_an_explicit_setting():
    available = {"render_html_frame", "add_html_overlay", "add_infographic", "probe_media"}

    off, _ = make_session(Script([]), available=available)
    on, _ = make_session(Script([]), available=available, free_html=True)

    assert not FREE_HTML_TOOLS & set(off.tool_names(["compositions"]))
    assert "add_infographic" in off.tool_names(["compositions"])
    assert FREE_HTML_TOOLS <= set(on.tool_names(["compositions"]))


def test_a_follow_up_keeps_the_kit_and_a_new_request_switches_it_without_losing_the_conversation():
    chat = Script(
        [Reply("", [ToolCall("list_voices", {})]), Reply("vozes listadas"), Reply("sim"), Reply("dublado")]
    )
    events: list[tuple[str, dict]] = []
    session, hosts = make_session(chat, on_event=lambda kind, data: events.append((kind, data)))

    session.ask("Quais vozes eu tenho para a narração?")
    session.ask("sim, pode")
    assert session.current_kits == ("voice",) and len(hosts) == 1
    session.ask("Agora dubla em inglês")

    assert session.current_kits == ("dubbing",) and len(hosts) == 2
    triage_events = [data for kind, data in events if kind == "triage"]
    assert [data["method"] for data in triage_events] == ["keywords", "previous", "keywords"]
    last_messages = chat.seen[-1][0]
    assert "MANUAL agente-dubbing" in last_messages[0]["content"]
    assert any(m["role"] == "tool" for m in last_messages)  # a conversa anterior continua no histórico


def test_a_confirmation_the_user_refuses_stops_the_tool_inside_the_session():
    chat = Script([Reply("", [ToolCall("render_project", {"name_or_path": "x"})]), Reply("não renderizei")])
    session, hosts = make_session(chat)

    session.ask("renderiza o vídeo final do projeto x")

    assert hosts[0].calls == []  # o padrão da sessão é recusar o que pede confirmação


def test_an_approved_confirmation_lets_the_tool_run():
    chat = Script([Reply("", [ToolCall("render_project", {"name_or_path": "x"})]), Reply("pronto")])
    session, hosts = make_session(chat, policy=ApproveAll())

    session.ask("renderiza o vídeo final do projeto x")

    assert hosts[0].calls == [("render_project", {"name_or_path": "x"})]


def test_reset_forgets_the_kit_and_the_history():
    chat = Script([Reply("a"), Reply("b")])
    session, hosts = make_session(chat)
    session.ask("dubla em inglês")

    session.reset()
    session.ask("narra o roteiro")

    assert session.current_kits == ("voice",) and len(hosts) == 2 and session.steps_taken == 1


def test_server_tool_names_lists_what_the_mcp_server_exposes():
    names = server_tool_names()

    assert {"quick_edit", "narrate_into_project", "cut_pauses_and_caption", "build_explainer_video"} <= names


# ---------- host MCP: valores padrão ----------


def test_the_mcp_host_waits_for_long_tools_instead_of_leaving_the_model_to_poll():
    host = McpToolHost(allowed=["render_project", "presets"])

    filled = host._with_defaults("render_project", {"name_or_path": "x"})

    assert filled["wait_seconds"] == DEFAULT_WAIT_SECONDS
    assert "wait_seconds" not in host._with_defaults("presets", {})  # a ferramenta nem tem o argumento


def test_what_the_model_asked_for_is_never_replaced_by_a_default():
    host = McpToolHost(allowed=["render_project"], argument_defaults={"wait_seconds": 99, "show_ui": False})

    filled = host._with_defaults("render_project", {"name_or_path": "x", "wait_seconds": 5})

    assert filled["wait_seconds"] == 5 and filled["show_ui"] is False


# ---------- progresso ao vivo ----------


def test_progress_reporting_emits_only_what_changed_while_the_tool_runs():
    started = threading.Event()
    release = threading.Event()
    states = [
        [{"job_id": "j1", "status": "running", "progress": {"percent": 10}}],
        [{"job_id": "j1", "status": "running", "progress": {"percent": 10}}],
        [{"job_id": "j1", "status": "running", "progress": {"percent": 60}}],
    ]
    polled = {"n": 0}

    def poll():
        index = min(polled["n"], len(states) - 1)
        polled["n"] += 1
        if polled["n"] >= len(states) + 1:
            release.set()
        started.set()
        return states[index]

    class SlowHost:
        def specs(self):
            return []

        def call(self, name, arguments):
            release.wait(timeout=5)
            return "terminou"

    updates: list[tuple[str, dict]] = []
    host = ProgressReportingHost(
        SlowHost(), lambda name, snap: updates.append((name, snap)), poll, interval=0.01
    )

    result = host.call("render_project", {})

    assert result == "terminou" and started.is_set()
    assert [snap["progress"]["percent"] for _, snap in updates] == [10, 60]
    assert all(name == "render_project" for name, _ in updates)
