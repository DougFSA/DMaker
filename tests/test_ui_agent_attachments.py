"""Anexos da conversa com o agente pela API: enviar, listar, remover, mandar com a mensagem e as recusas."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.agent.catalog import ModelInfo
from dmaker.agent.llm import ToolCall
from dmaker.agent.memory import GIB
from dmaker.agent.settings import AgentSettings
from dmaker.pipeline.jobs import JobManager
from dmaker.ui import agent_attachments
from dmaker.ui.agent_routes import build_agent_router

from .pdf_samples import make_pdf
from .test_agent_loop_stream import Turn, words
from .test_ui_agent import OSS, QWEN, FakeCatalog, FakeMemory, kinds, wait_for
from .test_ui_agent_conversations import FlowEnv, ask, finish, saved, wait_until
from .test_voice_manuscript import make_docx

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
VISION = ModelInfo(
    "gemma3:4b", 3 * GIB, family="gemma3", capabilities=("vision", "tools"), context_length=131072
)
LOOKER = ModelInfo(  # como o gemma3:4b: enxerga, mas não usa ferramentas
    "gemma3:4b", 3 * GIB, family="gemma3", capabilities=("vision",), context_length=131072
)
PLAIN = ModelInfo("modelo-simples:1b", GIB, family="x", capabilities=("tools",), context_length=32768)


class OpenEnv(FlowEnv):
    """Como o `FlowEnv`, mas todo modelo pedido está instalado (os testes de visão usam nomes além dos três de sempre)."""

    def health(self, settings):
        return {"reachable": self.reachable, "model_installed": self.reachable}


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


def new_conversation(client, **body) -> dict:
    response = client.post("/api/agent/conversations", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def attach(client, conversation_id, name, data, content_type="application/octet-stream"):
    return client.post(
        f"/api/agent/conversations/{conversation_id}/attachments",
        files={"file": (name, data, content_type)},
    )


def attach_ok(client, conversation_id, name, data) -> dict:
    response = attach(client, conversation_id, name, data)
    assert response.status_code == 200, response.text
    return response.json()


def send(client, message, conversation_id, attachments, **extra):
    return client.post(
        "/api/agent/messages",
        json={"message": message, "conversation_id": conversation_id, "attachments": attachments, **extra},
    )


def detail(client, conversation_id) -> dict:
    return client.get(f"/api/agent/conversations/{conversation_id}").json()


def user_message(env, index=0, call=0) -> dict:
    """A n-ésima mensagem do usuário que o modelo falso recebeu na chamada `call` (a 0 é a primeira)."""
    return [m for m in env.chat.requests[call][0] if m["role"] == "user"][index]


def word_docx() -> bytes:
    return make_docx(
        [
            ("Relatório de teste", "Heading1", False),
            ("A frase-código desta semana é abacate-azul.", None, False),
        ],
        {"Heading1": "heading 1"},
    )


# ---------- texto ----------


def test_a_docx_is_extracted_kept_in_the_conversation_folder_and_listed_as_pending(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    body = attach_ok(client, conversation["id"], "Relatório.docx", word_docx())

    assert body["kind"] == "text" and body["name"] == "Relatório.docx" and body["size"] == len(word_docx())
    assert body["truncated"] is False and body["chars"] == body["total_chars"] > 20
    assert body["preview"]["excerpt"].startswith("# Relatório de teste")
    assert "path" not in body  # o texto extraído mora na pasta da conversa, sem caminho público
    extracted = config.CONVERSATIONS_DIR / conversation["id"] / f"{body['id']}.txt"
    assert "abacate-azul" in extracted.read_text(encoding="utf-8")
    assert detail(client, conversation["id"])["pending_attachments"] == [body]
    on_disk = saved(conversation["id"])["attachments"]
    assert [(a["id"], a["kind"], a["sent"]) for a in on_disk] == [(body["id"], "text", False)]


def test_the_text_goes_in_a_named_block_before_the_question_and_the_transcript_keeps_only_the_card(make_app):
    env = FlowEnv(
        Turn(chunks=words("editing")), Turn(chunks=words("A frase-código é abacate-azul."))
    )  # 1ª: triagem
    client, manager = make_app(env)
    conversation = new_conversation(client)
    attachment = attach_ok(client, conversation["id"], "Relatório.docx", word_docx())

    started = send(client, "qual é a frase-código?", conversation["id"], [attachment["id"]]).json()
    job = finish(manager, started)

    assert job.status == "done", job.error
    content = user_message(env, call=1)["content"]
    assert "Início do arquivo anexado: Relatório.docx" in content and "abacate-azul" in content
    assert content.index("abacate-azul") < content.index("qual é a frase-código?")
    entry = next(e for e in saved(conversation["id"])["transcript"] if e["kind"] == "user")
    assert entry["text"] == "qual é a frase-código?"
    assert entry["attachments"] == [
        {
            "id": attachment["id"],
            "kind": "text",
            "name": "Relatório.docx",
            "size": attachment["size"],
            "chars": attachment["chars"],
            "total_chars": attachment["total_chars"],
            "truncated": False,
        }
    ]
    assert "abacate" not in json.dumps(entry)  # a transcrição guarda a ficha, nunca o texto extraído
    assert detail(client, conversation["id"])["pending_attachments"] == []


def test_a_message_without_attachments_has_no_attachments_key_in_the_transcript(make_app):
    client, manager = make_app(FlowEnv(Turn(chunks=words("oi"))))

    started = ask(client, "corta o vídeo do projeto x")
    finish(manager, started)

    entry = next(e for e in saved(started["conversation_id"])["transcript"] if e["kind"] == "user")
    assert "attachments" not in entry


def test_a_text_longer_than_the_context_share_is_cut_and_the_model_is_told(make_app):
    env = FlowEnv(Turn(chunks=words("ok")))
    client, manager = make_app(env)
    conversation = new_conversation(client, mode="free", options={"num_ctx": 1024})
    long_text = ("palavra " * 1500).strip().encode()  # 11.999 caracteres para um orçamento de 1.228

    attachment = attach_ok(client, conversation["id"], "livro.txt", long_text)
    finish(manager, send(client, "resuma", conversation["id"], [attachment["id"]]).json())

    assert attachment["truncated"] is True and attachment["total_chars"] == 11999
    assert attachment["chars"] == int(1024 * 0.4 * 3.0)
    content = user_message(env)["content"]
    assert "[O arquivo tem 11.999 caracteres; só os primeiros" in content
    entry = next(e for e in saved(conversation["id"])["transcript"] if e["kind"] == "user")
    assert entry["attachments"][0]["truncated"] is True and entry["attachments"][0]["chars"] <= 1228


def test_the_same_attachment_cannot_go_in_two_messages_and_a_sent_one_cannot_be_removed(make_app):
    env = FlowEnv(Turn(chunks=words("um")), Turn(chunks=words("dois")))
    client, manager = make_app(env)
    conversation = new_conversation(client, mode="free")
    attachment = attach_ok(client, conversation["id"], "nota.txt", b"conteudo da nota")
    finish(manager, send(client, "leia", conversation["id"], [attachment["id"]]).json())

    again = send(client, "leia de novo", conversation["id"], [attachment["id"]])
    removal = client.delete(f"/api/agent/conversations/{conversation['id']}/attachments/{attachment['id']}")

    assert again.status_code == 409 and "já foi enviado" in again.json()["detail"]
    assert removal.status_code == 409 and "já foi enviado" in removal.json()["detail"]
    assert detail(client, conversation["id"])["messages"] == 1  # a recusa não abriu uma mensagem fantasma


def test_a_srt_is_read_as_the_words_that_were_said(make_app):
    env = FlowEnv(Turn(chunks=words("ok")))
    client, manager = make_app(env)
    conversation = new_conversation(client, mode="free")
    srt = b"1\n00:00:01,000 --> 00:00:02,000\nBom dia.\n\n2\n00:00:02,500 --> 00:00:04,000\nVamos come\xc3\xa7ar.\n"

    attachment = attach_ok(client, conversation["id"], "aula.srt", srt)
    finish(manager, send(client, "resuma", conversation["id"], [attachment["id"]]).json())

    content = user_message(env)["content"]
    assert "Bom dia. Vamos começar." in content and "-->" not in content


# ---------- imagem ----------


def test_in_a_free_conversation_the_image_is_kept_in_its_folder_and_served_back_for_the_thumbnail(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client, mode="free")

    body = attach_ok(client, conversation["id"], "foto.png", PNG)

    assert body == {"id": body["id"], "kind": "image", "name": "foto.png", "size": len(PNG)}
    stored = config.CONVERSATIONS_DIR / conversation["id"] / f"{body['id']}-foto.png"
    assert stored.read_bytes() == PNG
    thumb = client.get(f"/api/agent/conversations/{conversation['id']}/attachments/{body['id']}")
    assert thumb.status_code == 200 and thumb.content == PNG
    assert (
        thumb.headers["content-type"] == "image/png" and thumb.headers["x-content-type-options"] == "nosniff"
    )


@pytest.mark.parametrize("mode", ["free", "operate"])
def test_a_file_that_only_wears_the_name_of_an_image_is_refused_and_leaves_nothing_behind(make_app, mode):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client, mode=mode)

    response = attach(client, conversation["id"], "golpe.png", b"<html><script>alert(1)</script></html>")

    assert response.status_code == 422 and "não é uma imagem PNG de verdade" in response.json()["detail"]
    folder = config.CONVERSATIONS_DIR / conversation["id"]
    assert not folder.exists() or list(folder.iterdir()) == []
    uploads = config.CACHE_DIR / "uploads"
    assert not uploads.exists() or list(uploads.iterdir()) == []  # nem o arquivo de trabalho do Operar
    assert detail(client, conversation["id"])["pending_attachments"] == []


def test_the_thumbnail_route_only_serves_images_that_belong_to_that_conversation(make_app):
    client, _ = make_app(FlowEnv())
    mine = new_conversation(client)
    other = new_conversation(client)
    image = attach_ok(client, mine["id"], "foto.png", PNG)
    note = attach_ok(client, mine["id"], "nota.txt", b"texto")

    def get(conversation_id, attachment_id):
        return client.get(f"/api/agent/conversations/{conversation_id}/attachments/{attachment_id}")

    assert get(other["id"], image["id"]).status_code == 404  # o id vale só dentro da conversa
    assert get(mine["id"], note["id"]).status_code == 404  # texto não tem miniatura
    assert get(mine["id"], "inexistente").status_code == 404
    assert get(mine["id"], "..%2F..%2Fx").status_code in (404, 405)
    assert get("nao-existe", image["id"]).status_code == 404


def test_in_a_free_conversation_an_image_for_a_model_without_vision_is_a_422_with_the_models_that_can_see(
    make_app,
):
    env = OpenEnv(Turn(chunks=words("nunca")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, VISION]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client, mode="free")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    response = send(client, "o que é isto?", conversation["id"], [image["id"]])

    body = response.json()
    assert response.status_code == 422
    assert body["suggested_models"] == ["gemma3:4b"] and body["error"] == body["detail"]
    assert "gpt-oss:20b não aceita imagens" in body["detail"] and "gemma3:4b" in body["detail"]
    assert env.chat.requests == [] and detail(client, conversation["id"])["messages"] == 0
    assert [a["id"] for a in detail(client, conversation["id"])["pending_attachments"]] == [image["id"]]


def test_with_no_model_that_sees_installed_the_suggestion_is_empty_and_the_text_says_so(make_app):
    env = OpenEnv()
    client, _ = make_app(
        env, catalog=FakeCatalog([OSS, PLAIN]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client, mode="free")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    response = send(client, "o que é isto?", conversation["id"], [image["id"]])

    assert response.status_code == 422 and response.json()["suggested_models"] == []
    assert "Nenhum modelo instalado aceita imagem" in response.json()["detail"]


def test_the_model_for_this_message_is_the_one_checked_not_the_one_the_conversation_had(make_app):
    env = OpenEnv(Turn(chunks=words("É um pixel.")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, VISION]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client, mode="free")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    started = send(client, "o que é isto?", conversation["id"], [image["id"]], model="gemma3:4b").json()
    job = finish(manager, started)

    assert job.status == "done" and detail(client, conversation["id"])["model"] == "gemma3:4b"


def test_with_a_vision_model_the_image_reaches_it_as_base64_and_the_history_keeps_only_the_reference(
    make_app,
):
    env = OpenEnv(Turn(chunks=words("É um pixel.")), Turn(chunks=words("Azul.")))
    client, manager = make_app(env, catalog=FakeCatalog([OSS, VISION]))
    conversation = new_conversation(client, mode="free", model="gemma3:4b")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    started = send(client, "o que é isto?", conversation["id"], [image["id"]]).json()
    job = finish(manager, started)

    assert job.status == "done"
    encoded = base64.b64encode(PNG).decode()
    assert user_message(env)["images"] == [encoded]
    on_disk = saved(conversation["id"])
    history_user = next(m for m in on_disk["history"] if m["role"] == "user")
    assert history_user["images"] == [f"attachment:{image['id']}"]
    assert encoded not in json.dumps(on_disk)  # nem o base64 nem a imagem entram no JSON da conversa
    entry = next(e for e in on_disk["transcript"] if e["kind"] == "user")
    assert entry["attachments"] == [
        {"id": image["id"], "kind": "image", "name": "foto.png", "size": len(PNG)}
    ]


def test_after_a_restart_the_next_turn_still_sends_the_image_from_the_disk(make_app):
    env = OpenEnv(Turn(chunks=words("É um pixel.")))
    client, manager = make_app(env, catalog=FakeCatalog([OSS, VISION]))
    conversation = new_conversation(client, mode="free", model="gemma3:4b")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    finish(manager, send(client, "o que é isto?", conversation["id"], [image["id"]]).json())

    later = OpenEnv(Turn(chunks=words("Azul.")))
    restarted, manager = make_app(later, catalog=FakeCatalog([OSS, VISION]))
    finish(manager, ask(restarted, "e a cor?", conversation_id=conversation["id"]))

    sent = [m for m in later.chat.requests[0][0] if m["role"] == "user"]
    assert sent[0]["images"] == [
        base64.b64encode(PNG).decode()
    ]  # a imagem do primeiro turno segue no contexto
    assert "images" not in sent[1]


def test_a_motor_that_does_not_report_capabilities_is_never_refused_for_an_image(make_app):
    env = OpenEnv(Turn(chunks=words("Vejo um pixel.")))
    catalog = FakeCatalog([ModelInfo("servidor-local", None)])
    client, manager = make_app(
        env, catalog=catalog, loader=lambda: AgentSettings(engine="openai", model="servidor-local")
    )
    conversation = new_conversation(client, mode="free")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    job = finish(manager, send(client, "o que é isto?", conversation["id"], [image["id"]]).json())

    assert job.status == "done" and user_message(env)["images"] == [base64.b64encode(PNG).decode()]


def test_what_the_server_says_when_it_refuses_the_request_reaches_the_person_in_portuguese(make_app):
    class Refusing:
        def abort(self):
            pass

        def chat(self, messages, tools):
            raise AssertionError("o laço devia usar o fluxo")

        def stream(self, messages, tools, on_delta, should_stop=None):
            raise urllib.error.HTTPError(
                "http://127.0.0.1:8080/v1/chat/completions",
                400,
                "Bad Request",
                {},  # type: ignore[arg-type]
                io.BytesIO(b'{"error": {"message": "image input is not supported by this model"}}'),
            )

    env = OpenEnv()
    env.chat = Refusing()  # type: ignore[assignment]
    client, manager = make_app(
        env,
        catalog=FakeCatalog([ModelInfo("servidor-local", None)]),
        loader=lambda: AgentSettings(engine="openai", model="servidor-local"),
    )
    conversation = new_conversation(client, mode="free")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    job = finish(manager, send(client, "o que é isto?", conversation["id"], [image["id"]]).json())

    notice = next(e for e in saved(conversation["id"])["transcript"] if e["kind"] == "notice")
    assert job.status == "error" and notice["level"] == "error"
    assert (
        "O servidor do modelo recusou o pedido (código 400): image input is not supported" in notice["text"]
    )
    assert "selo de imagem" in notice["text"] and "HTTP Error" not in notice["text"]


# ---------- imagem como arquivo de trabalho (modo Operar) ----------


def uploads_dir() -> Path:
    return config.CACHE_DIR / "uploads"


def test_in_an_operate_conversation_the_image_is_a_work_file_in_the_uploads_cache_like_a_video(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    again = attach_ok(client, conversation["id"], "foto.png", PNG)

    assert image["kind"] == "image" and image["path"].startswith(uploads_dir().as_posix())
    assert Path(image["path"]).read_bytes() == PNG
    assert (
        again["path"] == image["path"] and again["id"] != image["id"]
    )  # o mesmo conteúdo reaproveita o caminho
    folder = config.CONVERSATIONS_DIR / conversation["id"]
    assert not folder.exists() or list(folder.iterdir()) == []  # nada da imagem na pasta da conversa
    on_disk = saved(conversation["id"])["attachments"]
    assert on_disk[0]["path"] == image["path"] and on_disk[0]["file"] is None
    thumb = client.get(f"/api/agent/conversations/{conversation['id']}/attachments/{image['id']}")
    assert thumb.status_code == 200 and thumb.content == PNG
    assert (
        thumb.headers["content-type"] == "image/png" and thumb.headers["x-content-type-options"] == "nosniff"
    )


def test_a_model_that_sees_gets_the_work_image_as_a_path_in_the_text_and_as_base64(make_app):
    env = OpenEnv(Turn(chunks=words("Vou usar a foto.")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, VISION]), loader=lambda: AgentSettings(model="gemma3:4b")
    )
    conversation = new_conversation(client)
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    started = send(client, "cria um projeto com esta foto", conversation["id"], [image["id"]]).json()
    job = finish(manager, started)

    assert job.status == "done"
    message = user_message(env)
    assert message["images"] == [base64.b64encode(PNG).decode()]
    assert "cria um projeto com esta foto" in message["content"]
    assert f"Arquivo anexado: {image['path']}" in message["content"]
    on_disk = saved(conversation["id"])
    entry = next(e for e in on_disk["transcript"] if e["kind"] == "user")
    assert entry["attachments"] == [
        {"id": image["id"], "kind": "image", "name": "foto.png", "size": len(PNG)}
    ]
    history_user = next(m for m in on_disk["history"] if m["role"] == "user")
    assert history_user["images"] == [f"attachment:{image['id']}"]  # o histórico segue só com a referência
    assert base64.b64encode(PNG).decode() not in json.dumps(on_disk)


def test_in_an_operate_conversation_a_model_that_does_not_see_still_gets_the_image_as_a_file(make_app):
    """Não há mais 422: a foto serve ao vídeo mesmo que o modelo não consiga olhá-la."""
    env = OpenEnv(Turn(chunks=words("Usei a foto.")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, VISION]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client)
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    response = send(client, "cria um projeto com esta foto", conversation["id"], [image["id"]])
    job = finish(manager, response.json())

    assert response.status_code == 200 and job.status == "done"
    message = user_message(env)
    assert f"Arquivo anexado: {image['path']}" in message["content"]
    assert "images" not in message  # o gpt-oss não recebe a imagem, só o caminho
    entry = next(e for e in saved(conversation["id"])["transcript"] if e["kind"] == "user")
    assert [a["id"] for a in entry["attachments"]] == [image["id"]]


def test_the_work_image_path_passes_the_gate_but_an_invented_one_and_the_confirmations_stay(make_app):
    """Anexar a foto não afrouxa nada: o caminho dela vale, o que ninguém anexou continua barrado e o render pergunta."""
    invented = "C:/outra-pasta/foto-que-ninguem-anexou.png"
    env = FlowEnv(
        Turn(tool_calls=[ToolCall("probe_media", {"path": "__PATH__"})]),
        Turn(tool_calls=[ToolCall("probe_media", {"path": invented})]),
        Turn(tool_calls=[ToolCall("render_project", {"name_or_path": "teste-foto"})]),
        Turn(chunks=words("Não renderizei.")),
    )
    client, manager = make_app(env)
    conversation = new_conversation(client)
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    env.chat.turns[0].tool_calls = [ToolCall("probe_media", {"path": image["path"]})]

    started = send(
        client, "veja a foto e renderiza o projeto teste-foto", conversation["id"], [image["id"]]
    ).json()
    job = manager.get(started["job_id"])
    wait_until(lambda: "confirmation_request" in kinds(job))
    request = next(e for e in job.events if e["kind"] == "confirmation_request")

    assert env.host.calls == [
        ("probe_media", {"path": image["path"]})
    ]  # a foto anexada passou; a inventada, não
    assert "tool_blocked" in kinds(job) and request["tool"] == "render_project"
    client.post(
        f"/api/agent/confirmations/{request['id']}",
        params={"conversation_id": conversation["id"]},
        json={"approve": False},
    )
    wait_for(job)
    assert env.host.calls == [("probe_media", {"path": image["path"]})]  # o render não rodou sem o sim


def test_an_image_attached_in_a_free_conversation_gets_its_work_copy_when_the_message_goes_to_operate(
    make_app,
):
    """O modo vale no envio: a foto que nasceu na pasta da conversa ganha o arquivo de trabalho na hora."""
    env = OpenEnv(Turn(chunks=words("Usei a foto.")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, VISION]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client, mode="free")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    assert "path" not in image and not uploads_dir().exists()

    started = send(client, "cria um projeto com esta foto", conversation["id"], [image["id"]], mode="operate")
    job = finish(manager, started.json())

    assert started.status_code == 200 and job.status == "done"
    record = saved(conversation["id"])["attachments"][0]
    assert record["file"] is not None and record["path"].startswith(uploads_dir().as_posix())
    assert Path(record["path"]).read_bytes() == PNG
    assert f"Arquivo anexado: {record['path']}" in user_message(env)["content"]
    assert "images" not in user_message(env)  # e o gpt-oss, que não enxerga, só recebe o caminho
    assert (config.CONVERSATIONS_DIR / conversation["id"] / record["file"]).read_bytes() == PNG
    thumb = client.get(f"/api/agent/conversations/{conversation['id']}/attachments/{image['id']}")
    assert thumb.status_code == 200 and thumb.content == PNG


def test_switching_a_free_conversation_to_operate_by_patch_before_the_send_gives_the_image_its_work_copy(
    make_app,
):
    """A troca de modo pela rota PATCH, sem o campo `mode` no envio: vale o modo que a conversa tem na hora de enviar."""
    env = OpenEnv(Turn(chunks=words("Usei a foto.")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, VISION]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client, mode="free")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    assert "path" not in image and not uploads_dir().exists()  # na Conversa livre a foto fica na pasta dela

    changed = client.patch(f"/api/agent/conversations/{conversation['id']}", json={"mode": "operate"})
    assert changed.status_code == 200 and changed.json()["mode"] == "operate"
    pending = detail(client, conversation["id"])["pending_attachments"]
    assert [a["id"] for a in pending] == [image["id"]] and not uploads_dir().exists()  # trocar não grava nada

    started = send(client, "cria um projeto com esta foto", conversation["id"], [image["id"]])
    job = finish(manager, started.json())

    assert started.status_code == 200 and job.status == "done"
    record = saved(conversation["id"])["attachments"][0]
    assert record["file"] is not None and record["path"].startswith(uploads_dir().as_posix())
    assert Path(record["path"]).read_bytes() == PNG
    assert f"Arquivo anexado: {record['path']}" in user_message(env)["content"]
    assert "images" not in user_message(env)  # o gpt-oss não enxerga: só o caminho
    thumb = client.get(f"/api/agent/conversations/{conversation['id']}/attachments/{image['id']}")
    assert thumb.status_code == 200 and thumb.content == PNG


def test_switching_an_operate_conversation_to_free_by_patch_before_the_send_keeps_the_image_for_the_model_only(
    make_app,
):
    """O caminho contrário: a foto nasceu como arquivo de trabalho, e a Conversa livre não tem ferramenta para abri-la."""
    env = OpenEnv(Turn(chunks=words("Um quadrado azul.")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, LOOKER]), loader=lambda: AgentSettings(model="gemma3:4b")
    )
    conversation = new_conversation(client, model="gpt-oss:20b")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    assert image["path"].startswith(uploads_dir().as_posix())

    changed = client.patch(
        f"/api/agent/conversations/{conversation['id']}", json={"mode": "free", "model": "gemma3:4b"}
    )
    assert changed.status_code == 200 and changed.json()["mode"] == "free"

    started = send(client, "descreva a imagem", conversation["id"], [image["id"]])
    job = finish(manager, started.json())

    assert started.status_code == 200 and job.status == "done"
    message = user_message(env)
    assert message["images"] == [base64.b64encode(PNG).decode()]
    assert "Arquivo anexado" not in message["content"]
    assert Path(image["path"]).read_bytes() == PNG  # o arquivo de trabalho segue onde estava


def test_switching_an_operate_conversation_to_a_blind_free_model_by_patch_refuses_the_image_and_changes_nothing(
    make_app,
):
    env = OpenEnv(Turn(chunks=words("nunca")))
    client, _ = make_app(
        env, catalog=FakeCatalog([OSS, LOOKER]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client)
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    assert (
        client.patch(f"/api/agent/conversations/{conversation['id']}", json={"mode": "free"}).status_code
        == 200
    )

    refused = send(client, "o que é isto?", conversation["id"], [image["id"]])

    assert refused.status_code == 422 and refused.json()["suggested_models"] == ["gemma3:4b"]
    after = detail(client, conversation["id"])
    assert after["messages"] == 0 and [a["id"] for a in after["pending_attachments"]] == [image["id"]]
    assert env.chat.requests == []


def test_the_work_copy_of_two_conversations_with_the_same_photo_is_one_file(make_app):
    env = OpenEnv(Turn(chunks=words("ok")), Turn(chunks=words("ok")))
    client, manager = make_app(env, catalog=FakeCatalog([OSS, VISION]))
    paths = []
    for _ in range(2):
        conversation = new_conversation(client, mode="free")
        image = attach_ok(client, conversation["id"], "foto.png", PNG)
        job = finish(
            manager,
            send(
                client, "cria um projeto com esta foto", conversation["id"], [image["id"]], mode="operate"
            ).json(),
        )
        assert job.status == "done"
        paths.append(saved(conversation["id"])["attachments"][0]["path"])

    assert paths[0] == paths[1] and len(list(uploads_dir().iterdir())) == 1


def test_an_operate_image_sent_to_a_free_conversation_goes_only_to_the_model_and_is_refused_if_it_cannot_see(
    make_app,
):
    env = OpenEnv(Turn(chunks=words("É um pixel.")))
    client, manager = make_app(
        env, catalog=FakeCatalog([OSS, VISION]), loader=lambda: AgentSettings(model="gpt-oss:20b")
    )
    conversation = new_conversation(client)
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    refused = send(client, "o que é isto?", conversation["id"], [image["id"]], mode="free")
    after = detail(client, conversation["id"])

    assert refused.status_code == 422 and refused.json()["suggested_models"] == ["gemma3:4b"]
    assert after["mode"] == "operate" and after["messages"] == 0  # nem o modo mudou
    assert [a["id"] for a in after["pending_attachments"]] == [image["id"]]

    sent = send(client, "o que é isto?", conversation["id"], [image["id"]], mode="free", model="gemma3:4b")
    finish(manager, sent.json())
    message = user_message(env)
    assert message["images"] == [
        base64.b64encode(PNG).decode()
    ]  # a imagem de trabalho também chega como imagem
    assert "Arquivo anexado" not in message["content"]  # mas a conversa livre não tem ferramenta para abri-la


def test_a_work_image_that_disappeared_from_the_uploads_cache_asks_to_attach_again(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    for path in uploads_dir().iterdir():
        path.unlink()  # `dmaker clean` limpou o cache

    response = send(client, "usa esta foto", conversation["id"], [image["id"]])

    assert response.status_code == 422 and "não está mais disponível" in response.json()["detail"]
    assert detail(client, conversation["id"])["messages"] == 0
    assert (
        client.get(f"/api/agent/conversations/{conversation['id']}/attachments/{image['id']}").status_code
        == 404
    )


def test_removing_a_work_image_only_forgets_it_and_deleting_the_conversation_leaves_the_file(make_app):
    """Como o vídeo: o arquivo do cache pode estar em uso por um projeto, então apagar a conversa não o leva."""
    env = OpenEnv(Turn(chunks=words("ok")))
    client, manager = make_app(env, catalog=FakeCatalog([OSS, VISION]))
    conversation = new_conversation(client)
    discarded = attach_ok(client, conversation["id"], "descartada.png", PNG + b"\x00")
    used = attach_ok(client, conversation["id"], "usada.png", PNG)

    removed = client.delete(f"/api/agent/conversations/{conversation['id']}/attachments/{discarded['id']}")
    job = finish(
        manager, send(client, "cria um projeto com esta foto", conversation["id"], [used["id"]]).json()
    )
    deleted = client.delete(f"/api/agent/conversations/{conversation['id']}")

    assert job.status == "done" and removed.status_code == 200 and deleted.status_code == 200
    assert Path(discarded["path"]).exists() and Path(used["path"]).read_bytes() == PNG
    assert not (config.CONVERSATIONS_DIR / f"{conversation['id']}.json").exists()


def test_an_image_saved_in_the_conversation_folder_before_this_change_still_opens_and_still_goes_to_the_model(
    make_app,
):
    """Compatibilidade: a conversa Operar antiga guardou a imagem na pasta dela (`file`, sem `path`)."""
    env = OpenEnv(Turn(chunks=words("Vou usar a foto.")))
    client, manager = make_app(env, catalog=FakeCatalog([OSS, VISION]))
    conversation = new_conversation(client, model="gemma3:4b")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    first = finish(
        manager, send(client, "cria um projeto com esta foto", conversation["id"], [image["id"]]).json()
    )
    assert first.status == "done"
    folder = config.CONVERSATIONS_DIR / conversation["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{image['id']}-foto.png").write_bytes(PNG)
    path = config.CONVERSATIONS_DIR / f"{conversation['id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["attachments"][0].update(file=f"{image['id']}-foto.png", path=None)
    path.write_text(json.dumps(data), encoding="utf-8")
    for leftover in uploads_dir().iterdir():
        leftover.unlink()

    later = OpenEnv(Turn(chunks=words("Azul.")))
    restarted, manager = make_app(later, catalog=FakeCatalog([OSS, VISION]))
    second = finish(manager, ask(restarted, "e a cor?", conversation_id=conversation["id"]))

    assert second.status == "done"
    thumb = restarted.get(f"/api/agent/conversations/{conversation['id']}/attachments/{image['id']}")
    assert thumb.status_code == 200 and thumb.content == PNG
    sent = [m for m in later.chat.requests[0][0] if m["role"] == "user"]
    assert sent[0]["images"] == [
        base64.b64encode(PNG).decode()
    ]  # a imagem do primeiro turno segue no contexto


# ---------- vídeo, áudio e planilha ----------


def test_a_video_goes_to_the_uploads_cache_and_enters_the_message_as_its_path(make_app):
    env = FlowEnv(Turn(chunks=words("Vou cortar.")))
    client, manager = make_app(env)
    conversation = new_conversation(client)

    video = attach_ok(client, conversation["id"], "aula.mp4", b"fake-video-bytes")
    again = attach_ok(client, conversation["id"], "aula.mp4", b"fake-video-bytes")
    started = send(client, "corta as pausas deste vídeo", conversation["id"], [video["id"]]).json()
    finish(manager, started)

    assert video["kind"] == "media" and video["path"].startswith((config.CACHE_DIR / "uploads").as_posix())
    assert (
        again["path"] == video["path"] and again["id"] != video["id"]
    )  # o mesmo conteúdo reaproveita o caminho
    content = user_message(env)["content"]
    assert f"Arquivo anexado: {video['path']}" in content
    assert content.index("corta as pausas") < content.index("Arquivo anexado")
    assert not list(
        (config.CONVERSATIONS_DIR / conversation["id"]).glob("*.mp4")
    )  # o vídeo não vai para a conversa


def test_the_attached_video_is_usable_by_a_tool_but_the_confirmations_still_ask(make_app):
    """Anexar não afrouxa nada: o caminho é aceito, e render, apagar e sobrescrever seguem pedindo o sim."""
    env = FlowEnv(
        Turn(tool_calls=[ToolCall("probe_media", {"path": "__PATH__"})]),
        Turn(tool_calls=[ToolCall("render_project", {"name_or_path": "meu-video"})]),
        Turn(chunks=words("Não renderizei.")),
    )
    client, manager = make_app(env)
    conversation = new_conversation(client)
    video = attach_ok(client, conversation["id"], "aula.mp4", b"fake-video-bytes")
    env.chat.turns[0].tool_calls = [ToolCall("probe_media", {"path": video["path"]})]

    started = send(
        client, "veja o vídeo e renderiza o projeto meu-video", conversation["id"], [video["id"]]
    ).json()
    job = manager.get(started["job_id"])
    wait_until(lambda: "confirmation_request" in kinds(job))
    request = next(e for e in job.events if e["kind"] == "confirmation_request")

    assert env.host.calls == [("probe_media", {"path": video["path"]})]  # o caminho anexado passou direto
    assert job.status == "running" and request["tool"] == "render_project"  # e o render esperou o clique
    client.post(
        f"/api/agent/confirmations/{request['id']}",
        params={"conversation_id": conversation["id"]},
        json={"approve": False},
    )
    wait_for(job)
    assert env.host.calls == [("probe_media", {"path": video["path"]})] and "tool_blocked" in kinds(job)


def test_a_csv_is_a_sheet_with_a_preview_and_its_path_goes_to_the_model(make_app):
    env = FlowEnv(Turn(chunks=words("Vou montar o lote.")))
    client, manager = make_app(env)
    conversation = new_conversation(client)
    csv_bytes = b"nome;data\nAna;10/10\nRui;11/10\n"

    sheet = attach_ok(client, conversation["id"], "pedidos.csv", csv_bytes)
    finish(manager, send(client, "monta o lote", conversation["id"], [sheet["id"]]).json())

    assert sheet["kind"] == "sheet" and sheet["path"].endswith("-pedidos.csv")
    assert sheet["preview"] == {
        "columns": ["nome", "data"],
        "rows": [["Ana", "10/10"], ["Rui", "11/10"]],
        "rows_total": 2,
        "columns_total": 2,
    }
    content = user_message(env)["content"]
    assert f"Arquivo anexado: {sheet['path']}" in content and "Colunas: nome; data" in content


def test_a_xlsx_is_read_for_the_preview(make_app):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    workbook.active.append(["nome", "idade"])
    workbook.active.append(["Ana", 31])
    buffer = io.BytesIO()
    workbook.save(buffer)
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    sheet = attach_ok(client, conversation["id"], "pessoas.xlsx", buffer.getvalue())

    assert sheet["kind"] == "sheet" and sheet["preview"]["columns"] == ["nome", "idade"]
    assert sheet["preview"]["rows"] == [["Ana", "31"]]


def test_a_broken_xlsx_is_refused_with_the_reason(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    response = attach(client, conversation["id"], "quebrada.xlsx", b"nao e uma planilha")

    assert (
        response.status_code == 422
        and "Não consegui ler a planilha 'quebrada.xlsx'" in response.json()["detail"]
    )


def test_a_csv_with_no_sheet_shape_is_still_read_as_text(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    attachment = attach_ok(client, conversation["id"], "soltos.csv", b",,\n,,\n")

    assert attachment["kind"] == "text" and attachment["total_chars"] == len(",,\n,,")


def test_a_free_conversation_has_no_tools_so_it_refuses_video_and_reads_a_sheet_only_by_its_preview(make_app):
    env = FlowEnv(Turn(chunks=words("Vejo as colunas.")))
    client, manager = make_app(env)
    free = new_conversation(client, mode="free")

    refused = attach(client, free["id"], "aula.mp4", b"video")
    sheet = attach_ok(client, free["id"], "pedidos.csv", b"nome;data\nAna;10/10\n")
    finish(manager, send(client, "o que tem aqui?", free["id"], [sheet["id"]]).json())

    assert refused.status_code == 422 and "Operar o DMaker" in refused.json()["detail"]
    content = user_message(env)["content"]
    assert "Arquivo anexado:" not in content and "Colunas: nome; data" in content


def test_changing_to_a_free_conversation_after_attaching_a_video_blocks_the_send_without_side_effects(
    make_app,
):
    env = FlowEnv(Turn(chunks=words("nunca")))
    client, _ = make_app(env)
    conversation = new_conversation(client)
    video = attach_ok(client, conversation["id"], "aula.mp4", b"video")

    response = send(client, "oi", conversation["id"], [video["id"]], mode="free")

    assert response.status_code == 422 and "conversa livre" in response.json()["detail"]
    after = detail(client, conversation["id"])
    assert after["mode"] == "operate" and after["messages"] == 0  # nem o modo mudou
    assert [a["id"] for a in after["pending_attachments"]] == [video["id"]] and env.chat.requests == []


# ---------- recusas ----------


def test_a_pdf_is_read_and_the_model_gets_its_code_phrase(make_app):
    pytest.importorskip("pypdf")
    env = FlowEnv(Turn(chunks=words("A frase é ARARA-AZUL-742.")))
    client, manager = make_app(env)
    conversation = new_conversation(client, mode="free")

    pdf = attach_ok(client, conversation["id"], "contrato.pdf", make_pdf("A frase-codigo e ARARA-AZUL-742."))
    finish(manager, send(client, "qual e a frase-codigo?", conversation["id"], [pdf["id"]]).json())

    assert pdf["kind"] == "text" and pdf["total_chars"] == len("A frase-codigo e ARARA-AZUL-742.")
    assert "ARARA-AZUL-742" in user_message(env)["content"]
    assert "contrato.pdf" in user_message(env)["content"]


def test_a_scanned_or_broken_pdf_is_refused_with_the_reason_and_leaves_nothing(make_app):
    pytest.importorskip("pypdf")
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    scan = attach(client, conversation["id"], "scan.pdf", make_pdf(""))
    broken = attach(client, conversation["id"], "quebrado.pdf", b"%PDF-1.4 ...")

    assert scan.status_code == 422 and "não tem texto selecionável" in scan.json()["detail"]
    assert broken.status_code == 422 and "Não consegui abrir o PDF" in broken.json()["detail"]
    assert detail(client, conversation["id"])["pending_attachments"] == []


def test_without_pypdf_the_pdf_is_refused_with_the_install_command(make_app, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pypdf", None)
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    response = attach(client, conversation["id"], "contrato.pdf", make_pdf("x"))

    assert response.status_code == 422 and 'pip install -e ".[agente]"' in response.json()["detail"]


def test_other_formats_are_refused_listing_what_is_accepted(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    response = attach(client, conversation["id"], "programa.exe", b"MZ...")

    assert response.status_code == 422
    assert "Não aceito arquivos .exe" in response.json()["detail"] and ".docx" in response.json()["detail"]


def test_empty_files_and_documents_without_text_are_refused(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    empty = attach(client, conversation["id"], "vazio.txt", b"")
    blank = attach(client, conversation["id"], "branco.txt", b"   \n\n  ")
    broken = attach(client, conversation["id"], "quebrado.docx", b"nao e word")

    assert empty.status_code == 400 and "vazio" in empty.json()["detail"]
    assert blank.status_code == 422 and "não tem texto" in blank.json()["detail"]
    assert broken.status_code == 422 and "Não consegui abrir o .docx" in broken.json()["detail"]


def test_each_kind_has_its_own_size_limit_and_the_refusal_says_which(make_app, monkeypatch):
    monkeypatch.setattr(agent_attachments, "MAX_IMAGE_BYTES", 10)
    monkeypatch.setattr(agent_attachments, "MAX_DOCUMENT_BYTES", 10)
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)

    image = attach(client, conversation["id"], "foto.png", PNG)
    text = attach(client, conversation["id"], "nota.txt", b"x" * 11)
    uploads = config.CACHE_DIR / "uploads"
    assert (
        not uploads.exists() or list(uploads.iterdir()) == []
    )  # a imagem recusada do Operar não deixa arquivo

    assert (
        image.status_code == 413
        and "limite" in image.json()["detail"]
        and "imagens" in image.json()["detail"]
    )
    assert text.status_code == 413 and "documentos de texto" in text.json()["detail"]
    folder = config.CONVERSATIONS_DIR / conversation["id"]
    assert not folder.exists() or list(folder.iterdir()) == []
    assert "4 GB" in agent_attachments.too_big_message("media")  # o vídeo tem o limite do upload de fala


def test_an_attachment_needs_an_existing_conversation(make_app):
    client, _ = make_app(FlowEnv())

    response = attach(client, "nao-existe", "nota.txt", b"texto")

    assert response.status_code == 404 and response.json()["detail"] == "Conversa desconhecida."


def test_the_message_checks_the_ids_it_carries(make_app):
    client, _ = make_app(FlowEnv(Turn(chunks=words("ok"))))
    conversation = new_conversation(client)
    attachment = attach_ok(client, conversation["id"], "nota.txt", b"texto")

    unknown = send(client, "oi", conversation["id"], ["fantasma"])
    no_conversation = client.post(
        "/api/agent/messages", json={"message": "oi", "attachments": [attachment["id"]]}
    )
    too_many = send(client, "oi", conversation["id"], [f"a{i}" for i in range(9)])

    assert (
        unknown.status_code == 422
        and "Anexo desconhecido nesta conversa: fantasma" in unknown.json()["detail"]
    )
    assert no_conversation.status_code == 422 and "conversation_id" in no_conversation.json()["detail"]
    assert too_many.status_code == 422
    assert detail(client, conversation["id"])["messages"] == 0


def test_an_attachment_id_from_another_conversation_is_unknown(make_app):
    client, _ = make_app(FlowEnv())
    mine = new_conversation(client)
    other = new_conversation(client)
    foreign = attach_ok(client, other["id"], "nota.txt", b"texto")

    response = send(client, "oi", mine["id"], [foreign["id"]])

    assert response.status_code == 422 and "Anexo desconhecido" in response.json()["detail"]


def test_a_repeated_id_in_one_message_is_sent_once(make_app):
    env = FlowEnv(Turn(chunks=words("ok")))
    client, manager = make_app(env)
    conversation = new_conversation(client, mode="free")
    attachment = attach_ok(client, conversation["id"], "nota.txt", b"conteudo unico")

    finish(manager, send(client, "leia", conversation["id"], [attachment["id"], attachment["id"]]).json())

    assert user_message(env)["content"].count("conteudo unico") == 1


def test_a_file_that_disappeared_from_the_uploads_cache_asks_to_attach_again(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)
    video = attach_ok(client, conversation["id"], "aula.mp4", b"video")
    for path in (config.CACHE_DIR / "uploads").iterdir():
        path.unlink()  # `dmaker clean` limpou o cache

    response = send(client, "corta", conversation["id"], [video["id"]])

    assert response.status_code == 422 and "não está mais disponível" in response.json()["detail"]
    assert detail(client, conversation["id"])["messages"] == 0


# ---------- remover, guardar e apagar ----------


def test_removing_a_pending_attachment_forgets_it_and_deletes_what_it_kept(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)
    note = attach_ok(client, conversation["id"], "nota.txt", b"texto")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)
    folder = config.CONVERSATIONS_DIR / conversation["id"]

    first = client.delete(f"/api/agent/conversations/{conversation['id']}/attachments/{note['id']}")
    second = client.delete(f"/api/agent/conversations/{conversation['id']}/attachments/{image['id']}")
    third = client.delete(f"/api/agent/conversations/{conversation['id']}/attachments/{image['id']}")

    assert first.json() == {"deleted": note["id"]} and second.status_code == 200
    assert third.status_code == 404
    assert list(folder.iterdir()) == [] and detail(client, conversation["id"])["pending_attachments"] == []
    assert saved(conversation["id"])["attachments"] == []


def test_removing_a_video_only_forgets_it_because_the_cache_file_may_be_shared(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)
    first = attach_ok(client, conversation["id"], "aula.mp4", b"video")
    second = attach_ok(client, conversation["id"], "aula.mp4", b"video")  # mesmo conteúdo, mesmo arquivo

    client.delete(f"/api/agent/conversations/{conversation['id']}/attachments/{first['id']}")

    assert (config.CACHE_DIR / "uploads").joinpath(first["path"].rsplit("/", 1)[-1]).exists()
    assert [a["id"] for a in detail(client, conversation["id"])["pending_attachments"]] == [second["id"]]


def test_pending_attachments_survive_a_restart_and_deleting_the_conversation_takes_its_files(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)
    note = attach_ok(client, conversation["id"], "nota.txt", b"texto da nota")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    restarted, _ = make_app(FlowEnv())
    reopened = detail(restarted, conversation["id"])

    assert [a["id"] for a in reopened["pending_attachments"]] == [note["id"], image["id"]]
    folder = config.CONVERSATIONS_DIR / conversation["id"]
    assert restarted.delete(f"/api/agent/conversations/{conversation['id']}").status_code == 200
    assert not folder.exists() and not (config.CONVERSATIONS_DIR / f"{conversation['id']}.json").exists()


def test_attachments_do_not_count_as_messages_and_do_not_lock_the_mode(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)
    attach_ok(client, conversation["id"], "nota.txt", b"texto")

    changed = client.patch(f"/api/agent/conversations/{conversation['id']}", json={"mode": "free"})

    assert changed.status_code == 200 and changed.json()["mode_locked"] is False
    assert client.get("/api/agent/conversations").json()["conversations"][0]["messages"] == 0


def test_a_conversation_saved_before_attachments_existed_still_opens(make_app):
    client, _ = make_app(FlowEnv())
    conversation = new_conversation(client)
    path = config.CONVERSATIONS_DIR / f"{conversation['id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["attachments"]
    path.write_text(json.dumps(data), encoding="utf-8")

    restarted, _ = make_app(FlowEnv())

    assert detail(restarted, conversation["id"])["pending_attachments"] == []


# ---------- modelo sem ferramentas no modo Operar ----------

NO_TOOLS = (
    "O modelo gemma3:4b não usa ferramentas. Para operar o DMaker, escolha um modelo com ferramentas; "
    "para conversar com ele, use a Conversa livre."
)


def test_a_model_without_tools_cannot_start_an_operate_conversation_but_can_start_a_free_one(make_app):
    env = OpenEnv()
    client, _ = make_app(env, catalog=FakeCatalog([OSS, LOOKER]))

    refused = client.post("/api/agent/conversations", json={"mode": "operate", "model": "gemma3:4b"})
    default_mode = client.post("/api/agent/conversations", json={"model": "gemma3:4b"})
    free = client.post("/api/agent/conversations", json={"mode": "free", "model": "gemma3:4b"})

    assert refused.status_code == 422 and refused.json()["detail"] == NO_TOOLS
    assert default_mode.status_code == 422  # o padrão é operar
    assert free.status_code == 200 and free.json()["model"] == "gemma3:4b"
    assert len(client.get("/api/agent/conversations").json()["conversations"]) == 1  # a recusa não criou nada


def test_the_environment_default_model_counts_too(make_app):
    client, _ = make_app(
        OpenEnv(), catalog=FakeCatalog([OSS, LOOKER]), loader=lambda: AgentSettings(model="gemma3:4b")
    )

    response = client.post("/api/agent/conversations", json={})

    assert response.status_code == 422 and response.json()["detail"] == NO_TOOLS


def test_a_message_that_would_operate_with_a_model_without_tools_is_refused_before_the_server(make_app):
    env = OpenEnv(Turn(chunks=words("Olá!")))
    client, manager = make_app(env, catalog=FakeCatalog([OSS, LOOKER]))

    refused = client.post("/api/agent/messages", json={"message": "corta o vídeo", "model": "gemma3:4b"})
    allowed = client.post(
        "/api/agent/messages", json={"message": "bom dia", "model": "gemma3:4b", "mode": "free"}
    )

    assert refused.status_code == 422 and refused.json()["detail"] == NO_TOOLS
    job = finish(manager, allowed.json())
    assert len(env.chat.requests) == 1  # só a conversa livre chegou ao modelo
    assert allowed.status_code == 200 and job.status == "done"
    assert client.get("/api/agent/conversations").json()["conversations"][0]["mode"] == "free"


def test_changing_an_operate_conversation_to_a_model_without_tools_is_refused_and_changes_nothing(make_app):
    client, _ = make_app(OpenEnv(), catalog=FakeCatalog([OSS, LOOKER]))
    operate = new_conversation(client, model="gpt-oss:20b")
    free = new_conversation(client, mode="free", model="gpt-oss:20b")

    refused = client.patch(f"/api/agent/conversations/{operate['id']}", json={"model": "gemma3:4b"})
    allowed = client.patch(f"/api/agent/conversations/{free['id']}", json={"model": "gemma3:4b"})
    to_operate = client.patch(f"/api/agent/conversations/{free['id']}", json={"mode": "operate"})

    assert refused.status_code == 422 and refused.json()["detail"] == NO_TOOLS
    assert detail(client, operate["id"])["model"] == "gpt-oss:20b"
    assert allowed.status_code == 200 and allowed.json()["model"] == "gemma3:4b"
    assert to_operate.status_code == 422 and detail(client, free["id"])["mode"] == "free"


def test_a_model_whose_capabilities_are_unknown_is_never_refused_for_missing_tools(make_app):
    unknown = ModelInfo("antigo:7b", GIB, capabilities=(), capabilities_known=False)
    client, _ = make_app(OpenEnv(), catalog=FakeCatalog([unknown]))
    openai_client, _ = make_app(
        OpenEnv(),
        catalog=FakeCatalog([LOOKER]),
        loader=lambda: AgentSettings(engine="openai", model="gemma3:4b"),
    )

    assert client.post("/api/agent/conversations", json={"model": "antigo:7b"}).status_code == 200
    assert client.post("/api/agent/conversations", json={"model": "fora-da-lista"}).status_code == 200
    assert openai_client.post("/api/agent/conversations", json={"model": "gemma3:4b"}).status_code == 200


def test_only_the_free_conversation_refuses_an_image_for_a_model_that_cannot_see(make_app):
    """O modo Operar usa a imagem como arquivo; ali o modelo sem visão é atendido, e só a Conversa livre recusa."""
    env = OpenEnv(Turn(chunks=words("Usei a foto.")))
    catalog = FakeCatalog([OSS, LOOKER])
    client, manager = make_app(env, catalog=catalog, loader=lambda: AgentSettings(model="gpt-oss:20b"))
    operate = new_conversation(client)
    free = new_conversation(client, mode="free")
    image = attach_ok(client, operate["id"], "foto.png", PNG)
    same_image = attach_ok(client, free["id"], "foto.png", PNG)

    in_free = send(client, "o que é isto?", free["id"], [same_image["id"]])
    in_operate = send(client, "cria um projeto com esta foto", operate["id"], [image["id"]])
    finish(manager, in_operate.json())

    assert in_free.status_code == 422 and in_free.json()["suggested_models"] == ["gemma3:4b"]
    assert (
        in_operate.status_code == 200 and f"Arquivo anexado: {image['path']}" in user_message(env)["content"]
    )


def test_a_vision_model_without_tools_describes_an_image_in_a_free_conversation(make_app):
    env = OpenEnv(Turn(chunks=words("Um quadrado azul.")))
    client, manager = make_app(env, catalog=FakeCatalog([OSS, LOOKER]))
    conversation = new_conversation(client, mode="free", model="gemma3:4b")
    image = attach_ok(client, conversation["id"], "foto.png", PNG)

    job = finish(manager, send(client, "descreva a imagem", conversation["id"], [image["id"]]).json())

    assert job.status == "done" and user_message(env)["images"] == [base64.b64encode(PNG).decode()]
