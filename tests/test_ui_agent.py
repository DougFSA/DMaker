"""Rotas /api/agent: a conversa com o agente local como job, com eventos ao vivo e confirmação por botão."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dmaker.agent import AgentSession, ConfirmationRequest
from dmaker.agent.llm import Reply, ToolCall
from dmaker.agent.settings import AgentSettings, SettingsError
from dmaker.agent.tools import ToolSpec
from dmaker.pipeline.jobs import JobManager
from dmaker.ui import agent_routes
from dmaker.ui.agent_routes import TurnRelay, build_agent_router, kit_summaries


class Script:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools):
        return self.replies.pop(0) if self.replies else Reply("(sem mais respostas)")


class Host:
    def __init__(self):
        self.calls = []

    def specs(self):
        return [
            ToolSpec(
                "render_project",
                "r",
                {
                    "type": "object",
                    "properties": {"name_or_path": {"type": "string"}},
                    "required": ["name_or_path"],
                },
            ),
            ToolSpec("presets", "p", {"type": "object", "properties": {}}),
        ]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return "feito"


class Env:
    """Tudo que a rota injeta: o modelo falso, o host falso e o estado de saúde do servidor do modelo."""

    def __init__(self, replies, healthy=True):
        self.replies = replies
        self.host = Host()
        self.healthy = healthy
        self.relays: list[TurnRelay] = []

    def session(self, relay, settings):
        self.relays.append(relay)
        return AgentSession(
            chat=Script(self.replies),
            host_factory=lambda names: self.host,
            available={"render_project", "presets", "probe_media", "job_status", "search_manual"},
            policy=relay,
            on_event=relay.emit,
            manual_loader=lambda name: "manual",
        )

    def health(self, settings):
        return {"reachable": self.healthy, "model_installed": self.healthy}


@pytest.fixture
def make_client():
    def make(env: Env, loader=lambda: AgentSettings(model="modelo-x")):
        manager = JobManager()
        app = FastAPI()
        app.include_router(build_agent_router(manager, env.session, env.health, loader))
        return TestClient(app), manager

    return make


def wait_for(job, timeout=10.0):
    deadline = time.time() + timeout
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.02)
    assert job.status != "running", "o job do agente não terminou"
    return job


def kinds(job) -> list[str]:
    return [event["kind"] for event in job.events]


def test_status_reports_the_engine_the_model_and_the_kits(make_client):
    client, _ = make_client(Env([]))

    body = client.get("/api/agent/status").json()

    assert body["model"] == "modelo-x" and body["engine"] == "ollama" and body["reachable"] is True
    assert {kit["name"] for kit in body["kits"]} >= {"editing", "voice", "dubbing", "batch"}
    assert all(kit["tools"] >= 3 for kit in body["kits"])  # as ferramentas comuns entram em todo kit


def test_status_shows_when_the_model_server_is_down(make_client):
    client, _ = make_client(Env([], healthy=False))

    body = client.get("/api/agent/status").json()

    assert body["reachable"] is False and body["model_installed"] is False


def test_a_bad_environment_setting_is_a_clear_error(make_client):
    def broken():
        raise SettingsError("DMAKER_AGENT_ENGINE deve ser ollama ou openai")

    client, _ = make_client(Env([]), loader=broken)

    response = client.get("/api/agent/status")

    assert response.status_code == 500 and "DMAKER_AGENT_ENGINE" in response.json()["detail"]


def test_a_message_runs_as_a_job_and_the_events_tell_the_story(make_client):
    env = Env([Reply("", [ToolCall("presets", {})]), Reply("Os formatos são Reels e Shorts.")])
    client, manager = make_client(env)

    response = client.post("/api/agent/messages", json={"message": "Quais formatos existem? presets"})

    assert response.status_code == 200
    body = response.json()
    job = wait_for(manager.get(body["job_id"]))
    assert job.status == "done" and job.result["answer"] == "Os formatos são Reels e Shorts."
    assert kinds(job)[0] == "start" and kinds(job)[-1] == "end"
    assert {"triage", "model_reply", "tool_call", "tool_result", "answer"} <= set(kinds(job))
    assert job.meta["kind"] == "agent" and job.meta["conversation"] == body["conversation_id"]
    assert env.host.calls == [("presets", {})]


def test_the_same_conversation_keeps_its_history_across_messages(make_client):
    env = Env([Reply("primeira"), Reply("segunda")])
    client, manager = make_client(env)

    first = client.post("/api/agent/messages", json={"message": "oi"}).json()
    wait_for(manager.get(first["job_id"]))
    second = client.post(
        "/api/agent/messages", json={"message": "e agora?", "conversation_id": first["conversation_id"]}
    ).json()
    wait_for(manager.get(second["job_id"]))

    assert second["conversation_id"] == first["conversation_id"] and len(env.relays) == 1
    other = client.post("/api/agent/messages", json={"message": "outra conversa"}).json()
    assert other["conversation_id"] != first["conversation_id"] and len(env.relays) == 2
    wait_for(manager.get(other["job_id"]))


def test_a_confirmation_becomes_an_event_and_a_button_decides(make_client):
    env = Env([Reply("", [ToolCall("render_project", {"name_or_path": "meu-video"})]), Reply("Renderizei.")])
    client, manager = make_client(env)

    started = client.post(
        "/api/agent/messages", json={"message": "renderiza o vídeo final do projeto meu-video"}
    ).json()
    job = manager.get(started["job_id"])
    deadline = time.time() + 10
    while "confirmation_request" not in kinds(job) and time.time() < deadline:
        time.sleep(0.02)
    request = next(event for event in job.events if event["kind"] == "confirmation_request")

    assert job.status == "running" and env.host.calls == []  # esperando o clique, nada rodou
    assert (
        request["tool"] == "render_project" and request["type"] == "action" and "Posso" in request["question"]
    )
    answer = client.post(
        f"/api/agent/confirmations/{request['id']}",
        params={"conversation_id": started["conversation_id"]},
        json={"approve": True},
    )
    wait_for(job)

    assert answer.json() == {"approved": True}
    assert env.host.calls == [("render_project", {"name_or_path": "meu-video"})]
    assert "confirmation_answered" in kinds(job)


def test_refusing_the_confirmation_keeps_the_tool_from_running(make_client):
    env = Env([Reply("", [ToolCall("render_project", {"name_or_path": "x"})]), Reply("Não renderizei.")])
    client, manager = make_client(env)
    started = client.post("/api/agent/messages", json={"message": "renderiza o projeto x"}).json()
    job = manager.get(started["job_id"])
    while "confirmation_request" not in kinds(job):
        time.sleep(0.02)
    request = next(event for event in job.events if event["kind"] == "confirmation_request")

    client.post(
        f"/api/agent/confirmations/{request['id']}",
        params={"conversation_id": started["conversation_id"]},
        json={"approve": False},
    )
    wait_for(job)

    assert env.host.calls == [] and job.status == "done" and "tool_blocked" in kinds(job)


def test_answering_an_unknown_confirmation_is_a_404(make_client):
    client, _ = make_client(Env([Reply("ok")]))
    started = client.post("/api/agent/messages", json={"message": "oi"}).json()

    response = client.post(
        "/api/agent/confirmations/inexistente",
        params={"conversation_id": started["conversation_id"]},
        json={"approve": True},
    )
    nowhere = client.post(
        "/api/agent/confirmations/x", params={"conversation_id": "nada"}, json={"approve": True}
    )

    assert response.status_code == 404 and "não está mais esperando" in response.json()["detail"]
    assert nowhere.status_code == 404


def test_an_unanswered_confirmation_times_out_as_a_no(make_client):
    env = Env(
        [Reply("", [ToolCall("render_project", {"name_or_path": "x"})]), Reply("Sem resposta, não fiz.")]
    )
    client, manager = make_client(env)

    original = TurnRelay.__init__

    def quick(self, confirmation_timeout=0.05):
        original(self, confirmation_timeout)

    TurnRelay.__init__ = quick  # type: ignore[method-assign]
    try:
        started = client.post("/api/agent/messages", json={"message": "renderiza o projeto x"}).json()
        job = wait_for(manager.get(started["job_id"]))
    finally:
        TurnRelay.__init__ = original  # type: ignore[method-assign]

    assert env.host.calls == [] and job.status == "done"


def test_a_second_message_while_the_agent_is_busy_is_refused(make_client):
    gate = threading.Event()

    class Slow(Script):
        def chat(self, messages, tools):
            gate.wait(timeout=5)
            return Reply("pronto")

    env = Env([])
    env.session = lambda relay, settings: AgentSession(  # type: ignore[method-assign]
        chat=Slow([]),
        host_factory=lambda names: env.host,
        available=set(),
        policy=relay,
        on_event=relay.emit,
        manual_loader=lambda name: "",
    )
    client, manager = make_client(env)
    first = client.post("/api/agent/messages", json={"message": "oi"}).json()

    busy = client.post(
        "/api/agent/messages", json={"message": "de novo", "conversation_id": first["conversation_id"]}
    )
    gate.set()
    wait_for(manager.get(first["job_id"]))

    assert busy.status_code == 409 and "ainda está respondendo" in busy.json()["detail"]


def test_messages_are_refused_with_a_helpful_text_when_the_model_server_is_down(make_client):
    client, _ = make_client(Env([], healthy=False))

    response = client.post("/api/agent/messages", json={"message": "oi"})

    assert response.status_code == 503 and "não está respondendo" in response.json()["detail"]


def test_an_empty_or_huge_message_is_rejected_by_validation(make_client):
    client, _ = make_client(Env([]))

    assert client.post("/api/agent/messages", json={"message": ""}).status_code == 422
    assert client.post("/api/agent/messages", json={"message": "x" * 5000}).status_code == 422


def test_reset_clears_an_idle_conversation_and_refuses_a_busy_or_unknown_one(make_client):
    client, manager = make_client(Env([Reply("ok")]))
    started = client.post("/api/agent/messages", json={"message": "oi"}).json()
    wait_for(manager.get(started["job_id"]))

    assert client.delete(f"/api/agent/conversations/{started['conversation_id']}").json() == {
        "reset": started["conversation_id"]
    }
    assert client.delete("/api/agent/conversations/nada").status_code == 404


def test_tool_progress_reaches_the_job_as_events_and_as_the_job_progress():
    manager = JobManager()
    relay = TurnRelay()

    def work(job):
        relay.attach(job)
        relay.progress(
            "render_project",
            {"job_id": "j", "status": "running", "progress": {"label": "etapa", "percent": 40}},
        )
        return {}

    job = wait_for(manager.start("teste", work))

    progress_events = [event for event in job.events if event["kind"] == "tool_progress"]
    assert progress_events[0]["progress"]["percent"] == 40 and progress_events[0]["name"] == "render_project"
    assert job.progress["percent"] == 40 and job.progress["label"].startswith("render_project")


def test_the_relay_resolves_only_what_is_pending():
    relay = TurnRelay(confirmation_timeout=2)
    outcome: list[bool] = []
    request = ConfirmationRequest("render_project", {}, "Posso renderizar?")

    manager = JobManager()
    job = manager.start("t", lambda job: relay.attach(job) or outcome.append(relay.confirm(request)))
    deadline = time.time() + 5
    while relay.waiting == 0 and time.time() < deadline:
        time.sleep(0.01)

    confirmation_id = next(iter(relay._pending))
    assert relay.resolve(confirmation_id, True) is True
    wait_for(job)
    assert outcome == [True] and relay.resolve(confirmation_id, True) is False


def test_kit_summaries_count_only_the_tools_the_server_has():
    summaries = {
        kit["name"]: kit["tools"] for kit in kit_summaries({"probe_media", "job_status", "search_manual"})
    }

    assert summaries["compositions"] == 3  # só as comuns: os infográficos ainda não existem
    assert agent_routes.AGENT_KIND == "agent"


def test_the_real_ui_app_exposes_the_agent_routes():
    from dmaker.ui import server

    with TestClient(server.app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert {"/api/agent/status", "/api/agent/messages", "/api/agent/confirmations/{confirmation_id}"} <= set(
        paths
    )
