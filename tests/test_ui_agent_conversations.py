"""Rotas de conversas salvas: criar, listar, abrir, renomear, apagar, continuar depois de reiniciar, fluxo e Parar."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.agent import AgentSession
from dmaker.agent.catalog import LoadedModel
from dmaker.agent.conversations import ConversationInUseError, DiskConversationStore
from dmaker.agent.free_session import FreeSession
from dmaker.agent.llm import ToolCall
from dmaker.agent.loop import INTERRUPTED_MARK
from dmaker.agent.memory import GIB
from dmaker.agent.settings import AgentSettings
from dmaker.pipeline.jobs import JobManager
from dmaker.ui.agent_routes import build_agent_router

from .test_agent_loop_stream import FlowChat, Host, Turn, words
from .test_ui_agent import OSS, QWEN, FakeCatalog, FakeMemory, kinds, wait_for

INSTALLED = {"modelo-x", "gpt-oss:20b", "qwen3:30b-a3b"}


class ConfiguredChat(FlowChat):
    """O motor em fluxo com os campos que `configure_chat` ajusta, anotando o que valia em cada chamada."""

    def __init__(self, *turns: Turn):
        super().__init__(*turns)
        self.model = ""
        self.think = None
        self.num_ctx = 0
        self.temperature = None
        self.seed = None
        self.options_seen: list[tuple] = []

    def stream(self, messages, tools, on_delta, should_stop=None):
        self.options_seen.append((self.model, self.think, self.num_ctx, self.temperature, self.seed))
        return super().stream(messages, tools, on_delta, should_stop)


class FlowEnv:
    """O que as rotas recebem por injeção: um motor em fluxo compartilhado, o host falso e a saúde do servidor."""

    def __init__(self, *turns: Turn, reachable: bool = True):
        self.chat = ConfiguredChat(*turns)
        self.host = Host()
        self.reachable = reachable
        self.operate_settings: list[AgentSettings] = []

    def session(self, relay, settings):
        self.operate_settings.append(settings)
        return AgentSession(
            chat=self.chat,
            host_factory=lambda names: self.host,
            available={"render_project", "presets", "probe_media", "job_status", "search_manual"},
            policy=relay,
            on_event=relay.emit,
            manual_loader=lambda name: "manual",
        )

    def free_session(self, relay, settings):
        return FreeSession(chat=self.chat, on_event=relay.emit)

    def health(self, settings):
        return {
            "reachable": self.reachable,
            "model_installed": self.reachable and settings.model in INSTALLED,
        }


@pytest.fixture
def make_app():
    def make(env: FlowEnv, catalog=None, loader=lambda: AgentSettings(model="modelo-x")):
        manager = JobManager()
        app = FastAPI()
        app.include_router(
            build_agent_router(
                manager,
                env.session,
                env.health,
                loader,
                catalog_factory=lambda settings: catalog or FakeCatalog([OSS, QWEN]),
                memory_probe=FakeMemory(None),
                free_session_factory=env.free_session,
            )
        )
        return TestClient(app), manager

    return make


def ask(client, message, **extra):
    response = client.post("/api/agent/messages", json={"message": message, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def finish(manager, started):
    return wait_for(manager.get(started["job_id"]))


def saved(conversation_id: str) -> dict:
    return json.loads((config.CONVERSATIONS_DIR / f"{conversation_id}.json").read_text(encoding="utf-8"))


def wait_until(condition, timeout=10.0):
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.01)
    assert condition(), "a condição não chegou a valer"


# ---------- criar, listar, abrir, renomear e apagar ----------


def test_a_conversation_is_created_listed_opened_renamed_and_deleted(make_app):
    client, _ = make_app(FlowEnv())

    created = client.post("/api/agent/conversations", json={"mode": "free"}).json()
    listed = client.get("/api/agent/conversations").json()["conversations"]

    assert created["mode"] == "free" and created["title"] == "Nova conversa" and created["transcript"] == []
    assert (
        created["mode_locked"] is False
        and created["running_job_id"] is None
        and created["model"] == "modelo-x"
    )
    assert [(c["id"], c["messages"], c["running"]) for c in listed] == [(created["id"], 0, False)]
    assert saved(created["id"])["mode"] == "free"  # já está em disco, antes de qualquer mensagem

    renamed = client.patch(
        f"/api/agent/conversations/{created['id']}", json={"title": "  Minha conversa  "}
    ).json()
    opened = client.get(f"/api/agent/conversations/{created['id']}").json()

    assert renamed["title"] == opened["title"] == "Minha conversa"
    assert client.get("/api/agent/conversations").json()["conversations"][0]["title"] == "Minha conversa"
    assert client.delete(f"/api/agent/conversations/{created['id']}").json() == {"deleted": created["id"]}
    assert not (config.CONVERSATIONS_DIR / f"{created['id']}.json").exists()
    assert client.get(f"/api/agent/conversations/{created['id']}").status_code == 404
    assert client.delete(f"/api/agent/conversations/{created['id']}").status_code == 404
    assert client.get("/api/agent/conversations").json() == {"conversations": []}


def test_an_empty_or_blank_title_is_refused(make_app):
    client, _ = make_app(FlowEnv())
    created = client.post("/api/agent/conversations", json={}).json()

    assert client.patch(f"/api/agent/conversations/{created['id']}", json={"title": ""}).status_code == 422
    assert client.patch(f"/api/agent/conversations/{created['id']}", json={"title": "   "}).status_code == 422
    assert (
        client.patch(f"/api/agent/conversations/{created['id']}", json={"title": "x" * 200}).status_code
        == 422
    )
    assert client.patch("/api/agent/conversations/nada", json={"title": "a"}).status_code == 404


def test_the_list_puts_the_most_recent_conversation_first(make_app):
    env = FlowEnv(Turn(chunks=words("a")), Turn(chunks=words("b")))
    client, manager = make_app(env)
    older = ask(client, "corta o vídeo do projeto um")
    finish(manager, older)
    newer = ask(client, "corta o vídeo do projeto dois")
    finish(manager, newer)

    listed = client.get("/api/agent/conversations").json()["conversations"]

    assert [c["id"] for c in listed] == [newer["conversation_id"], older["conversation_id"]]
    assert listed[0]["title"] == "corta o vídeo do projeto dois" and listed[0]["messages"] == 1


def test_a_path_like_id_never_reaches_the_disk(make_app):
    client, _ = make_app(FlowEnv())
    victim = config.CONVERSATIONS_DIR.parent / "importante"
    victim.mkdir(parents=True)
    (victim / "a.txt").write_text("fica", encoding="utf-8")

    assert client.delete("/api/agent/conversations/..%2Fimportante").status_code in (404, 405)
    assert client.get("/api/agent/conversations/..").status_code in (404, 405)
    assert (victim / "a.txt").exists()


# ---------- mensagens: criação, título, transcrição salva ----------


def test_a_message_without_an_id_creates_the_conversation_with_the_title_and_saves_the_transcript(make_app):
    env = FlowEnv(Turn(chunks=[("thinking", "Vou olhar. "), ("answer", "Os formatos são Reels.")]))
    client, manager = make_app(env)

    started = ask(client, "Quais formatos existem para reel? Me diga os presets")
    job = finish(manager, started)

    assert job.status == "done" and job.result["answer"] == "Os formatos são Reels."
    file = saved(started["conversation_id"])
    assert file["title"] == "Quais formatos existem para reel? Me diga os presets"
    assert file["mode"] == "operate" and file["model"] == "modelo-x" and file["kits"] == ["editing"]
    assert [m["role"] for m in file["history"]] == ["user", "assistant"]
    assert [(e["kind"], e.get("text")) for e in file["transcript"] if e["kind"] != "kits"] == [
        ("user", "Quais formatos existem para reel? Me diga os presets"),
        ("thinking", "Vou olhar."),
        ("answer", "Os formatos são Reels."),
    ]
    detail = client.get(f"/api/agent/conversations/{started['conversation_id']}").json()
    assert detail["mode_locked"] is True and detail["kits"] == ["editing"] and detail["messages"] == 1


def test_the_transcript_keeps_the_tool_steps_and_the_confirmations_with_their_answers(make_app):
    env = FlowEnv(
        Turn(tool_calls=[ToolCall("presets", {})]),
        Turn(tool_calls=[ToolCall("render_project", {"name_or_path": "meu-video"})]),
        Turn(chunks=words("Renderizei.")),
    )
    client, manager = make_app(env)
    started = ask(client, "lista os presets e renderiza o projeto meu-video")
    job = manager.get(started["job_id"])
    wait_until(lambda: "confirmation_request" in kinds(job))
    request = next(e for e in job.events if e["kind"] == "confirmation_request")
    assert job.status == "running"

    client.post(
        f"/api/agent/confirmations/{request['id']}",
        params={"conversation_id": started["conversation_id"]},
        json={"approve": True},
    )
    wait_for(job)

    transcript = saved(started["conversation_id"])["transcript"]
    steps = [(e["name"], e["state"]) for e in transcript if e["kind"] == "tool"]
    confirmation = next(e for e in transcript if e["kind"] == "confirmation")
    assert steps == [("presets", "done"), ("render_project", "done")]
    assert confirmation["state"] == "approved" and confirmation["tool"] == "render_project"
    assert "Posso" in confirmation["question"] and confirmation["confirmation_id"] == request["id"]
    assert transcript[-1]["kind"] == "answer"


# ---------- fluxo ao vivo ----------


def test_the_events_carry_the_stages_and_the_pieces_grouped_and_the_final_answer(make_app):
    env = FlowEnv(Turn(chunks=[("thinking", "Hmm. ")] + words(*[f"p{i} " for i in range(300)])))
    client, manager = make_app(env, catalog=FakeCatalog([OSS], loaded=[LoadedModel("modelo-x", GIB, 0)]))

    job = finish(manager, ask(client, "corta o vídeo do projeto x"))

    deltas = [e["text"] for e in job.events if e["kind"] == "answer_delta"]
    statuses = [e["stage"] for e in job.events if e["kind"] == "status"]
    assert (
        "".join(deltas) == "".join(f"p{i} " for i in range(300)) and len(deltas) <= 4
    )  # 300 trechos, poucos eventos
    assert statuses == ["reading", "thinking", "writing"]
    final = next(e for e in job.events if e["kind"] == "answer")
    assert final["text"] == "".join(deltas)
    assert kinds(job)[0] == "start" and kinds(job)[-1] == "end"


def test_a_model_that_is_not_in_memory_starts_as_loading(make_app):
    client, manager = make_app(FlowEnv(Turn(chunks=words("oi"))), catalog=FakeCatalog([OSS], loaded=[]))

    job = finish(manager, ask(client, "corta o vídeo do projeto x"))

    assert [e["stage"] for e in job.events if e["kind"] == "status"] == ["loading_model", "writing"]


def test_a_model_loaded_with_another_context_is_reloaded_by_ollama_so_it_counts_as_cold(make_app):
    loaded = [LoadedModel("modelo-x", GIB, 0, context_length=4096)]
    client, manager = make_app(FlowEnv(Turn(chunks=words("oi"))), catalog=FakeCatalog([OSS], loaded=loaded))

    job = finish(manager, ask(client, "corta o vídeo do projeto x", options={"num_ctx": 8192}))

    assert [e["stage"] for e in job.events if e["kind"] == "status"] == ["loading_model", "writing"]


def test_a_model_loaded_with_the_same_context_is_warm(make_app):
    loaded = [LoadedModel("modelo-x", GIB, 0, context_length=8192)]
    client, manager = make_app(FlowEnv(Turn(chunks=words("oi"))), catalog=FakeCatalog([OSS], loaded=loaded))

    job = finish(manager, ask(client, "corta o vídeo do projeto x", options={"num_ctx": 8192}))

    assert [e["stage"] for e in job.events if e["kind"] == "status"] == ["reading", "writing"]


def test_a_failing_status_lookup_is_not_taken_for_a_cold_model(make_app):
    from dmaker.agent.catalog import CatalogError

    client, manager = make_app(
        FlowEnv(Turn(chunks=words("oi"))), catalog=FakeCatalog([OSS], failure=CatalogError("sem /api/ps"))
    )

    job = finish(manager, ask(client, "corta o vídeo do projeto x"))

    assert [e["stage"] for e in job.events if e["kind"] == "status"] == ["reading", "writing"]


def test_an_engine_that_cannot_unload_never_claims_the_model_is_loading(make_app):
    client, manager = make_app(
        FlowEnv(Turn(chunks=words("oi"))), catalog=FakeCatalog([OSS], loaded=[], can_unload=False)
    )

    job = finish(manager, ask(client, "corta o vídeo do projeto x"))

    assert [e["stage"] for e in job.events if e["kind"] == "status"] == ["reading", "writing"]


# ---------- modelo, esforço e opções da conversa ----------


def test_the_model_effort_and_options_of_the_message_are_saved_and_reach_the_next_call(make_app):
    env = FlowEnv(Turn(chunks=words("a")), Turn(chunks=words("b")))
    client, manager = make_app(env)

    first = ask(
        client,
        "corta o vídeo do projeto x",
        model="gpt-oss:20b",
        effort="high",
        options={"num_ctx": 8192, "temperature": 0.2, "seed": 7},
    )
    finish(manager, first)
    second = ask(client, "e agora?", conversation_id=first["conversation_id"], effort="low")
    finish(manager, second)

    assert env.chat.options_seen == [
        ("gpt-oss:20b", "high", 8192, 0.2, 7),
        ("gpt-oss:20b", "low", 8192, 0.2, 7),  # o esforço mudou; o resto da conversa ficou
    ]
    file = saved(first["conversation_id"])
    assert (file["model"], file["effort"], file["options"]) == (
        "gpt-oss:20b",
        "low",
        {"num_ctx": 8192, "temperature": 0.2, "seed": 7},
    )
    assert env.operate_settings[0].model == "gpt-oss:20b"  # a sessão já nasce com a escolha da conversa


def test_a_switch_effort_becomes_a_boolean_for_the_models_that_only_turn_it_on_or_off(make_app):
    env = FlowEnv(Turn(chunks=words("a")))
    client, manager = make_app(env)

    finish(manager, ask(client, "corta o vídeo do projeto x", model="qwen3:30b-a3b", effort="off"))

    assert env.chat.options_seen[0][:2] == ("qwen3:30b-a3b", False)


def test_a_conversation_without_choices_uses_the_environment_settings(make_app):
    env = FlowEnv(Turn(chunks=words("a")))
    client, manager = make_app(
        env, loader=lambda: AgentSettings(model="modelo-x", num_ctx=2048, think="medium")
    )

    finish(manager, ask(client, "corta o vídeo do projeto x"))

    assert env.chat.options_seen == [("modelo-x", "medium", 2048, None, None)]


def test_an_effort_the_model_does_not_have_is_a_422_that_names_the_options(make_app):
    client, _ = make_app(FlowEnv())
    created = client.post("/api/agent/conversations", json={"model": "gpt-oss:20b"}).json()

    wrong = client.patch(f"/api/agent/conversations/{created['id']}", json={"effort": "on"})
    fine = client.patch(f"/api/agent/conversations/{created['id']}", json={"effort": "high"})

    assert wrong.status_code == 422 and "Baixo, Médio, Alto" in wrong.json()["detail"]
    assert fine.json()["effort"] == "high"


def test_a_model_without_effort_levels_refuses_any_effort(make_app):
    client, _ = make_app(FlowEnv(), catalog=FakeCatalog([OSS, replace(QWEN, effort_levels=())]))
    created = client.post("/api/agent/conversations", json={"model": "qwen3:30b-a3b"}).json()

    response = client.patch(f"/api/agent/conversations/{created['id']}", json={"effort": "on"})

    assert response.status_code == 422 and "não tem escolha de esforço" in response.json()["detail"]


def test_switching_the_model_drops_an_effort_the_new_model_does_not_have(make_app):
    client, _ = make_app(FlowEnv())
    created = client.post("/api/agent/conversations", json={"model": "gpt-oss:20b", "effort": "high"}).json()

    switched = client.patch(
        f"/api/agent/conversations/{created['id']}", json={"model": "qwen3:30b-a3b"}
    ).json()
    then = client.patch(f"/api/agent/conversations/{created['id']}", json={"effort": "off"}).json()

    assert (switched["model"], switched["effort"]) == ("qwen3:30b-a3b", None)  # "high" não existe no qwen
    assert then["effort"] == "off"
    assert saved(created["id"])["model"] == "qwen3:30b-a3b"


def test_effort_null_goes_back_to_the_models_default(make_app):
    client, _ = make_app(FlowEnv())
    created = client.post("/api/agent/conversations", json={"model": "gpt-oss:20b", "effort": "low"}).json()

    cleared = client.patch(f"/api/agent/conversations/{created['id']}", json={"effort": None}).json()
    untouched = client.patch(f"/api/agent/conversations/{created['id']}", json={"title": "x"}).json()

    assert cleared["effort"] is None and untouched["effort"] is None


def test_the_context_cannot_pass_the_models_maximum(make_app):
    client, _ = make_app(FlowEnv())
    created = client.post("/api/agent/conversations", json={"model": "gpt-oss:20b"}).json()

    too_big = client.patch(f"/api/agent/conversations/{created['id']}", json={"options": {"num_ctx": 999999}})
    fine = client.patch(
        f"/api/agent/conversations/{created['id']}", json={"options": {"num_ctx": 4096, "seed": 3}}
    )
    reset = client.patch(f"/api/agent/conversations/{created['id']}", json={"options": None})

    assert too_big.status_code == 422 and "131072" in too_big.json()["detail"]
    assert fine.json()["options"] == {"num_ctx": 4096, "temperature": None, "seed": 3}
    assert reset.json()["options"] == {"num_ctx": None, "temperature": None, "seed": None}
    assert (
        client.patch(
            f"/api/agent/conversations/{created['id']}", json={"options": {"temperature": 3}}
        ).status_code
        == 422
    )


def test_choosing_a_model_the_server_does_not_have_is_a_422_and_a_message_with_it_is_a_503(make_app):
    client, _ = make_app(FlowEnv())

    created = client.post("/api/agent/conversations", json={"model": "nao-instalado"})
    message = client.post("/api/agent/messages", json={"message": "oi", "model": "nao-instalado"})

    assert created.status_code == 422 and "nao-instalado" in created.json()["detail"]
    assert message.status_code == 503 and "'nao-instalado' não está instalado" in message.json()["detail"]
    assert client.get("/api/agent/conversations").json() == {
        "conversations": []
    }  # nada ficou criado pela metade


def test_the_installed_check_is_about_the_conversations_model_not_the_environments(make_app):
    env = FlowEnv(Turn(chunks=words("a")))
    client, manager = make_app(env, loader=lambda: AgentSettings(model="nao-instalado"))

    # o ambiente aponta para um modelo que não existe, mas a conversa escolhe um que existe
    started = ask(client, "corta o vídeo do projeto x", model="gpt-oss:20b")
    finish(manager, started)
    refused = client.post("/api/agent/messages", json={"message": "oi"})

    assert refused.status_code == 503 and "'nao-instalado'" in refused.json()["detail"]
    assert saved(started["conversation_id"])["model"] == "gpt-oss:20b"


def test_creating_a_conversation_works_while_the_model_server_is_down(make_app):
    client, _ = make_app(FlowEnv(reachable=False))

    created = client.post("/api/agent/conversations", json={"model": "gpt-oss:20b"})
    message = client.post(
        "/api/agent/messages", json={"message": "oi", "conversation_id": created.json()["id"]}
    )

    assert created.status_code == 200
    assert message.status_code == 503 and "não está respondendo" in message.json()["detail"]


def test_unload_looks_at_the_model_of_the_conversation_that_is_answering(make_app):
    env = FlowEnv(Turn(chunks=words("parcial"), hang_after=1))
    catalog = FakeCatalog([OSS], loaded=[LoadedModel("gpt-oss:20b", GIB, 0)])
    client, manager = make_app(env, catalog=catalog)
    started = ask(client, "corta o vídeo do projeto x", model="gpt-oss:20b")
    assert env.chat.waiting.wait(timeout=5)

    busy = client.post("/api/agent/unload", json={"model": "gpt-oss:20b"})
    other = client.post("/api/agent/unload", json={"model": "modelo-x"})
    client.post(f"/api/agent/conversations/{started['conversation_id']}/stop")
    finish(manager, started)
    after = client.post("/api/agent/unload", json={"model": "gpt-oss:20b"})

    assert busy.status_code == 409 and other.status_code == 200
    assert after.json() == {"model": "gpt-oss:20b", "unloaded": True}


# ---------- Parar ----------


def test_stopping_during_the_flow_returns_quickly_keeps_the_partial_text_and_the_next_message_works(make_app):
    env = FlowEnv(Turn(chunks=words("Os formatos ", "são"), hang_after=2), Turn(chunks=words("Retomei.")))
    client, manager = make_app(env)
    started = ask(client, "corta o vídeo do projeto x")
    job = manager.get(started["job_id"])
    assert env.chat.waiting.wait(timeout=5)

    began = time.monotonic()
    response = client.post(f"/api/agent/conversations/{started['conversation_id']}/stop")
    wait_for(job, timeout=5)
    took = time.monotonic() - began

    assert response.json() == {"stopping": True, "job_id": started["job_id"]}
    assert took < 2 and env.chat.aborts == 1
    assert job.status == "cancelled" and job.result["interrupted"] is True
    assert job.result["answer"] == "Os formatos são"
    end = job.events[-1]
    assert end["kind"] == "end" and end["status"] == "cancelled"
    file = saved(started["conversation_id"])
    assert file["history"][-1] == {"role": "assistant", "content": f"Os formatos são\n\n{INTERRUPTED_MARK}"}
    answer = [e for e in file["transcript"] if e["kind"] == "answer"][-1]
    assert answer == {"kind": "answer", "id": answer["id"], "text": "Os formatos são", "interrupted": True}

    again = ask(client, "e agora?", conversation_id=started["conversation_id"])
    assert finish(manager, again).status == "done"
    sent = env.chat.requests[-1][0]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]


def test_stopping_before_the_first_piece_works_while_the_model_is_still_reading_the_request(make_app):
    env = FlowEnv(Turn(chunks=words("nunca"), hang_after=0))
    client, manager = make_app(env)
    started = ask(client, "corta o vídeo do projeto x")
    job = manager.get(started["job_id"])
    assert env.chat.waiting.wait(timeout=5)
    assert [e["stage"] for e in job.events if e["kind"] == "status"][-1] in ("reading", "loading_model")

    began = time.monotonic()
    assert manager.cancel(started["job_id"]) is job  # é o que POST /api/jobs/{id}/cancel faz
    wait_for(job, timeout=5)

    assert time.monotonic() - began < 2 and job.status == "cancelled"
    transcript = saved(started["conversation_id"])["transcript"]
    assert [(e["kind"], e.get("code")) for e in transcript if e["kind"] == "notice"] == [
        ("notice", "interrupted")
    ]
    assert saved(started["conversation_id"])["history"][-1]["content"] == INTERRUPTED_MARK


def test_stopping_while_a_confirmation_waits_answers_no_and_the_tool_never_runs(make_app):
    env = FlowEnv(
        Turn(tool_calls=[ToolCall("render_project", {"name_or_path": "meu-video"})]),
        Turn(chunks=words("Ok.")),
    )
    client, manager = make_app(env)
    started = ask(client, "renderiza o vídeo final do projeto meu-video")
    job = manager.get(started["job_id"])
    wait_until(lambda: "confirmation_request" in kinds(job))

    began = time.monotonic()
    client.post(f"/api/agent/conversations/{started['conversation_id']}/stop")
    wait_for(job, timeout=5)

    answered = next(e for e in job.events if e["kind"] == "confirmation_answered")
    assert answered["approved"] is False and time.monotonic() - began < 2
    assert env.host.calls == [] and job.status == "cancelled"
    transcript = saved(started["conversation_id"])["transcript"]
    confirmation = next(e for e in transcript if e["kind"] == "confirmation")
    assert confirmation["state"] == "refused"
    assert next(e for e in transcript if e["kind"] == "tool")["state"] == "blocked"

    again = ask(client, "e agora?", conversation_id=started["conversation_id"])
    assert finish(manager, again).status == "done"  # a conversa continua utilizável


def test_stopping_a_conversation_that_is_not_answering_is_a_409_and_an_unknown_one_a_404(make_app):
    env = FlowEnv(Turn(chunks=words("a")))
    client, manager = make_app(env)
    done = ask(client, "corta o vídeo do projeto x")
    finish(manager, done)

    idle = client.post(f"/api/agent/conversations/{done['conversation_id']}/stop")
    nowhere = client.post("/api/agent/conversations/nada/stop")

    assert idle.status_code == 409 and "Não há resposta em andamento" in idle.json()["detail"]
    assert nowhere.status_code == 404


def test_the_turn_job_declares_itself_cancellable(make_app):
    env = FlowEnv(Turn(chunks=words("a")))
    client, manager = make_app(env)

    started = ask(client, "corta o vídeo do projeto x")
    finish(manager, started)

    assert manager.get(started["job_id"]).cancellable is True
    assert manager.get(started["job_id"]).meta["conversation"] == started["conversation_id"]


# ---------- conflitos ----------


def test_a_busy_conversation_refuses_a_second_message_a_delete_and_a_model_switch(make_app):
    env = FlowEnv(Turn(chunks=words("a"), hang_after=1))
    client, manager = make_app(env)
    started = ask(client, "corta o vídeo do projeto x")
    cid = started["conversation_id"]
    assert env.chat.waiting.wait(timeout=5)

    second = client.post("/api/agent/messages", json={"message": "de novo", "conversation_id": cid})
    delete = client.delete(f"/api/agent/conversations/{cid}")
    switch = client.patch(f"/api/agent/conversations/{cid}", json={"model": "gpt-oss:20b"})
    rename = client.patch(f"/api/agent/conversations/{cid}", json={"title": "Pode renomear"})
    listed = client.get("/api/agent/conversations").json()["conversations"][0]
    detail = client.get(f"/api/agent/conversations/{cid}").json()
    client.post(f"/api/agent/conversations/{cid}/stop")
    finish(manager, started)

    assert second.status_code == 409 and "ainda está respondendo" in second.json()["detail"]
    assert delete.status_code == 409 and "Pare a resposta" in delete.json()["detail"]
    assert switch.status_code == 409 and "trocar o modelo" in switch.json()["detail"]
    assert rename.status_code == 200
    assert listed["running"] is True and detail["running_job_id"] == started["job_id"]
    assert client.delete(f"/api/agent/conversations/{cid}").status_code == 200  # parou: agora apaga


def test_an_unknown_conversation_id_is_a_404_instead_of_a_silent_new_conversation(make_app):
    client, _ = make_app(FlowEnv())

    response = client.post("/api/agent/messages", json={"message": "oi", "conversation_id": "inexistente"})

    assert response.status_code == 404 and "Conversa desconhecida" in response.json()["detail"]
    assert client.get("/api/agent/conversations").json() == {"conversations": []}


def test_a_file_in_use_makes_the_delete_a_409_with_the_explanation(make_app, monkeypatch):
    client, _ = make_app(FlowEnv())
    created = client.post("/api/agent/conversations", json={}).json()

    def locked(self, conversation_id):
        raise ConversationInUseError("Não consegui apagar a conversa porque o arquivo 'v.mp4' está aberto.")

    with monkeypatch.context() as patched:
        patched.setattr(DiskConversationStore, "delete", locked)
        response = client.delete(f"/api/agent/conversations/{created['id']}")

    assert response.status_code == 409 and "'v.mp4' está aberto" in response.json()["detail"]
    assert client.get(f"/api/agent/conversations/{created['id']}").status_code == 200


# ---------- reiniciar o DMaker ----------


def test_after_a_restart_the_conversation_remembers_the_context(make_app):
    first_env = FlowEnv(Turn(chunks=words("Primeira resposta.")), Turn(chunks=words("Segunda resposta.")))
    client, manager = make_app(first_env)
    one = ask(client, "corta o vídeo do projeto viagem")
    finish(manager, one)
    two = ask(client, "e o que mais?", conversation_id=one["conversation_id"])
    finish(manager, two)

    # um DMaker novo: roteador novo, memória vazia, só o disco em comum
    second_env = FlowEnv(Turn(chunks=words("Terceira resposta.")))
    client2, manager2 = make_app(second_env)
    reopened = client2.get(f"/api/agent/conversations/{one['conversation_id']}").json()
    three = ask(client2, "e a terceira?", conversation_id=one["conversation_id"])
    finish(manager2, three)

    assert reopened["title"] == "corta o vídeo do projeto viagem" and reopened["kits"] == ["editing"]
    assert [e["text"] for e in reopened["transcript"] if e["kind"] in ("user", "answer")] == [
        "corta o vídeo do projeto viagem",
        "Primeira resposta.",
        "e o que mais?",
        "Segunda resposta.",
    ]
    sent = second_env.chat.requests[0][0]
    assert [(m["role"], m["content"]) for m in sent[1:]] == [
        ("user", "corta o vídeo do projeto viagem"),
        ("assistant", "Primeira resposta."),
        ("user", "e o que mais?"),
        ("assistant", "Segunda resposta."),
        ("user", "e a terceira?"),
    ]
    assert "manual" in sent[0]["content"]  # o kit de edição voltou, com o prompt dele
    assert [s.model for s in second_env.operate_settings] == ["modelo-x"]
    file = saved(one["conversation_id"])
    assert len([m for m in file["history"] if m["role"] == "user"]) == 3


def test_a_confirmation_that_was_pending_when_the_dmaker_closed_comes_back_as_not_confirmed(make_app):
    env = FlowEnv(Turn(tool_calls=[ToolCall("render_project", {"name_or_path": "meu-video"})]))
    client, manager = make_app(env)
    started = ask(client, "renderiza o vídeo final do projeto meu-video")
    job = manager.get(started["job_id"])
    wait_until(lambda: "confirmation_request" in kinds(job))
    request = next(e for e in job.events if e["kind"] == "confirmation_request")

    # o processo "morre" aqui: o que existe é o que já foi para o disco
    client2, _ = make_app(FlowEnv())
    reopened = client2.get(f"/api/agent/conversations/{started['conversation_id']}").json()

    confirmation = next(e for e in reopened["transcript"] if e["kind"] == "confirmation")
    assert confirmation["state"] == "unconfirmed" and "Posso" in confirmation["question"]
    assert (
        reopened["transcript"][-1]["kind"] == "notice" and reopened["transcript"][-1]["code"] == "unfinished"
    )
    assert reopened["running_job_id"] is None
    assert (
        client2.post(
            f"/api/agent/confirmations/{request['id']}",
            params={"conversation_id": started["conversation_id"]},
            json={"approve": True},
        ).status_code
        == 404
    )  # o botão morreu junto com o processo: não há o que responder

    client.post(
        f"/api/agent/confirmations/{request['id']}",
        params={"conversation_id": started["conversation_id"]},
        json={"approve": False},
    )
    wait_for(job)  # solta a thread do "processo antigo"


def test_a_history_cut_in_the_middle_of_a_tool_call_is_repaired_before_the_model_reads_it(make_app):
    store = DiskConversationStore()
    from dmaker.agent.conversations import new_record

    cut = new_record("corte00001", "operate", "modelo-x")
    cut.kits = ["editing"]
    cut.history = [
        {"role": "user", "content": "renderiza o projeto x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "render_project", "arguments": {}}}],
        },
    ]
    cut.transcript = [{"kind": "user", "id": "e1", "text": "renderiza o projeto x", "at": "x"}]
    store.save(cut)
    env = FlowEnv(Turn(chunks=words("Vi que parou.")))
    client, manager = make_app(env)

    finish(manager, ask(client, "e agora?", conversation_id="corte00001"))

    sent = env.chat.requests[0][0]
    assert [m["role"] for m in sent[1:]] == ["user", "assistant", "tool", "user"]
    assert sent[3]["tool_name"] == "render_project" and "não terminou" in sent[3]["content"]


def test_a_corrupt_conversation_file_is_a_clear_500_and_does_not_break_the_list(make_app):
    client, _ = make_app(FlowEnv())
    good = client.post("/api/agent/conversations", json={}).json()
    (config.CONVERSATIONS_DIR / "quebrada.json").write_text("{ não é json", encoding="utf-8")

    opened = client.get("/api/agent/conversations/quebrada")
    listed = client.get("/api/agent/conversations").json()["conversations"]

    assert (
        opened.status_code == 500
        and "quebrada" in opened.json()["detail"]
        and "ilegível" in opened.json()["detail"]
    )
    assert [c["id"] for c in listed] == [good["id"]]


# ---------- conversa livre ----------


def test_a_free_conversation_answers_without_any_tool_or_triage(make_app):
    env = FlowEnv(Turn(chunks=words("Bom dia!")))
    client, manager = make_app(env)
    created = client.post("/api/agent/conversations", json={"mode": "free"}).json()

    job = finish(manager, ask(client, "bom dia", conversation_id=created["id"]))

    messages, tools = env.chat.requests[0]
    assert job.result["answer"] == "Bom dia!" and tools == []
    assert "assistente de conversa" in messages[0]["content"]
    assert "triage" not in kinds(job) and env.operate_settings == []
    assert saved(created["id"])["mode"] == "free" and saved(created["id"])["kits"] == []


def test_a_message_without_an_id_can_pick_the_free_mode(make_app):
    env = FlowEnv(Turn(chunks=words("Oi!")))
    client, manager = make_app(env)

    started = ask(client, "bom dia", mode="free")
    finish(manager, started)

    assert saved(started["conversation_id"])["mode"] == "free" and env.operate_settings == []


def test_the_mode_is_locked_after_the_first_message_but_can_change_before_it(make_app):
    env = FlowEnv(Turn(chunks=words("Oi!")), Turn(chunks=words("Oi de novo!")))
    client, manager = make_app(env)
    created = client.post("/api/agent/conversations", json={"mode": "operate"}).json()

    switched = client.patch(f"/api/agent/conversations/{created['id']}", json={"mode": "free"})
    finish(manager, ask(client, "bom dia", conversation_id=created["id"]))
    locked = client.patch(f"/api/agent/conversations/{created['id']}", json={"mode": "operate"})
    through_message = client.post(
        "/api/agent/messages", json={"message": "oi", "conversation_id": created["id"], "mode": "operate"}
    )
    same = ask(client, "outra", conversation_id=created["id"], mode="free")
    finish(manager, same)

    assert switched.json()["mode"] == "free" and switched.json()["mode_locked"] is False
    assert locked.status_code == 409 and "não muda depois da primeira mensagem" in locked.json()["detail"]
    assert through_message.status_code == 409
    assert saved(created["id"])["mode"] == "free"


# ---------- aparo ----------


def test_a_long_saved_conversation_is_trimmed_and_the_screen_keeps_everything(make_app):
    from dmaker.agent.conversations import new_record

    store = DiskConversationStore()
    long_one = new_record("longa00001", "operate", "modelo-x")
    long_one.kits = ["editing"]
    for index in range(8):
        long_one.history += [
            {"role": "user", "content": f"pergunta {index} " + "x" * 3000},
            {"role": "assistant", "content": f"resposta {index} " + "y" * 3000},
        ]
        long_one.transcript += [
            {"kind": "user", "id": f"e{2 * index + 1}", "text": f"pergunta {index}", "at": "x"},
            {"kind": "answer", "id": f"e{2 * index + 2}", "text": f"resposta {index}", "interrupted": False},
        ]
    store.save(long_one)
    env = FlowEnv(Turn(chunks=words("ok")))
    client, manager = make_app(env)

    job = finish(manager, ask(client, "e agora?", conversation_id="longa00001", options={"num_ctx": 4096}))

    trimmed = next(e for e in job.events if e["kind"] == "history_trimmed")
    assert trimmed["turns"] >= 6 and "saíram da memória do modelo" in trimmed["text"]
    sent = env.chat.requests[0][0]
    assert len(sent) < 17
    file = saved("longa00001")
    assert len(file["history"]) < 17  # o que o modelo lê foi aparado...
    assert [e["text"] for e in file["transcript"] if e["kind"] == "user"][:2] == [
        "pergunta 0",
        "pergunta 1",
    ]  # ...a tela não
    assert any(e["kind"] == "notice" and e["code"] == "history_trimmed" for e in file["transcript"])


# ---------- falhas ----------


def test_a_model_error_ends_the_job_with_an_error_and_a_notice_and_the_conversation_survives(make_app):
    class Broken(ConfiguredChat):
        def stream(self, messages, tools, on_delta, should_stop=None):
            if not self.requests:
                self.requests.append((messages, tools))
                raise RuntimeError("A conexão com o modelo terminou antes do fim da resposta.")
            return super().stream(messages, tools, on_delta, should_stop)

    env = FlowEnv()
    env.chat = Broken(Turn(chunks=words("Voltei.")))
    client, manager = make_app(env)

    started = ask(client, "corta o vídeo do projeto x")
    job = finish(manager, started)
    transcript = saved(started["conversation_id"])["transcript"]

    assert job.status == "error"
    notice = [e for e in transcript if e["kind"] == "notice"][-1]
    assert notice["level"] == "error" and "terminou antes do fim" in notice["text"]
    again = ask(client, "tenta de novo", conversation_id=started["conversation_id"])
    assert finish(manager, again).status == "done"


def test_a_disk_that_refuses_to_save_does_not_break_the_turn_and_warns_once(make_app, monkeypatch):
    env = FlowEnv(Turn(chunks=words("Mesmo assim respondi.")))
    client, manager = make_app(env)
    created = client.post("/api/agent/conversations", json={}).json()

    def refuse(self, record):
        raise OSError("disco cheio")

    with monkeypatch.context() as patched:
        patched.setattr(DiskConversationStore, "save", refuse)
        job = finish(manager, ask(client, "corta o vídeo do projeto x", conversation_id=created["id"]))
        detail = client.get(f"/api/agent/conversations/{created['id']}").json()

    assert job.status == "done" and job.result["answer"] == "Mesmo assim respondi."
    warnings = [e for e in detail["transcript"] if e["kind"] == "notice" and e["code"] == "save_failed"]
    assert len(warnings) == 1 and "disco cheio" in warnings[0]["text"]


def test_the_real_ui_app_exposes_the_conversation_routes():
    from dmaker.ui import server

    with TestClient(server.app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert {
        "/api/agent/conversations",
        "/api/agent/conversations/{conversation_id}",
        "/api/agent/conversations/{conversation_id}/stop",
    } <= set(paths)
    assert {"get", "post"} <= set(paths["/api/agent/conversations"])
    assert {"get", "patch", "delete"} <= set(paths["/api/agent/conversations/{conversation_id}"])
