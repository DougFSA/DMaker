"""Rotas /api/voices/queue: entrar por texto ou arquivo, controlar a fila, baixar os arquivos e acompanhar por SSE."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.pipeline.voice_queue import QueueOptions, VoiceQueue
from dmaker.pipeline.voice_queue_service import VoiceQueueService
from dmaker.ui import server
from dmaker.ui.queue_routes import build_queue_router, get_queue_service, queue_event_stream
from dmaker.voice.library import VoiceLibrary

MANUSCRIPT = (
    "# Primeiro\nTexto do primeiro capitulo.\n\n# Segundo\nTexto do segundo capitulo.\n\n# Terceiro\nFim."
)


@pytest.fixture
def service(tmp_path, monkeypatch) -> VoiceQueueService:
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    return VoiceQueueService(
        VoiceQueue(tmp_path / "cache" / "voice_queue.json"), VoiceLibrary(tmp_path / "voices")
    )


@pytest.fixture
def client(service):
    server.app.dependency_overrides[get_queue_service] = lambda: service
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.pop(get_queue_service, None)


def enqueue_text(client: TestClient, **body) -> dict:
    response = client.post("/api/voices/queue", json={"text": "Um texto para a fila.", **body})
    assert response.status_code == 200, response.text
    return response.json()


def upload(client: TestClient, content: str | bytes, filename: str = "roteiro.md", **form):
    data = content.encode() if isinstance(content, str) else content
    return client.post("/api/voices/queue/upload", files={"file": (filename, data)}, data=form)


# ---------- entrada ----------


def test_text_goes_to_the_queue_and_comes_back_in_the_view(client):
    body = enqueue_text(client, title="Meu audiobook", voice="dora", draft=True, format="mp3", speed=1.1)

    (item,) = body["items"]
    assert body["id"] == item["id"] and item["title"] == "Meu audiobook"
    assert item["state"] == "pending" and item["state_label"] == "Pendente"
    assert item["options"] == {
        "voice": "dora",
        "language": None,
        "speed": 1.1,
        "brand": None,
        "draft": True,
        "format": "mp3",
    }
    assert body["worker"] is False  # nenhum worker foi ligado: só o `dmaker ui` de verdade liga
    assert client.get("/api/voices/queue").json()["items"][0]["id"] == item["id"]


def test_uploaded_markdown_with_three_chapters_enters_the_queue_with_three_chapters(client):
    response = upload(client, MANUSCRIPT, "curso.md", voice="dora", title="Curso curto")

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["chapters_total"] == 3 and item["title"] == "Curso curto"
    assert item["source"] == {"kind": "file", "name": "curso.md"}
    assert item["output_dir"].endswith("curso-curto")


def test_bad_requests_get_a_clear_400(client):
    assert (
        client.post("/api/voices/queue", json={"text": "   "}).json()["detail"]
        == "Escreva o texto da narração."
    )
    unknown = client.post("/api/voices/queue", json={"text": "Texto.", "voice": "fantasma"})
    assert unknown.status_code == 400 and "fantasma" in unknown.json()["detail"]
    pdf = upload(client, b"x", "livro.pdf")
    assert pdf.status_code == 400 and "não suportado" in pdf.json()["detail"]
    assert client.post("/api/voices/queue", json={"text": "Texto.", "speed": 5}).status_code == 422
    assert client.post("/api/voices/queue", json={"text": "Texto.", "format": "ogg"}).status_code == 422
    assert client.get("/api/voices/queue").json()["items"] == []


# ---------- controle ----------


def test_pause_resume_cancel_retry_and_remove(client):
    item_id = enqueue_text(client)["id"]
    base = f"/api/voices/queue/{item_id}"

    assert client.post(f"{base}/pause").json()["items"][0]["state"] == "paused"
    assert client.post(f"{base}/resume").json()["items"][0]["state"] == "pending"
    assert client.post(f"{base}/cancel").json()["items"][0]["state"] == "cancelled"
    assert client.post(f"{base}/retry").json()["items"][0]["state"] == "pending"
    client.post(f"{base}/cancel")
    assert client.delete(base).json()["items"] == []


def test_invalid_transitions_and_unknown_items_are_reported(client):
    item_id = enqueue_text(client)["id"]
    client.post(f"/api/voices/queue/{item_id}/cancel")

    again = client.post(f"/api/voices/queue/{item_id}/cancel")
    assert again.status_code == 400 and "cancelado não pode ir para cancelado" in again.json()["detail"]
    assert client.post("/api/voices/queue/naoexiste/pause").status_code == 404
    assert client.delete("/api/voices/queue/naoexiste").status_code == 404
    assert client.get("/api/voices/queue/naoexiste/files/a.wav").status_code == 404


def test_running_item_cannot_be_removed_and_cancelling_it_frees_the_worker(client, service):
    item_id = enqueue_text(client)["id"]
    service.queue.claim_next()

    assert client.delete(f"/api/voices/queue/{item_id}").status_code == 400
    assert client.post(f"/api/voices/queue/{item_id}/pause").json()["items"][0]["state"] == "paused"
    assert service.queue.update_progress(item_id, utterance=2) is False  # o worker percebe e larga o item


def test_move_reorders_the_waiting_items(client):
    first = enqueue_text(client, title="A")["id"]
    second = enqueue_text(client, title="B")["id"]

    moved = client.post(f"/api/voices/queue/{second}/move", json={"direction": -1}).json()

    assert [i["title"] for i in moved["items"]] == ["B", "A"]
    assert moved["items"][1]["id"] == first
    assert client.post(f"/api/voices/queue/{second}/move", json={"direction": 2}).status_code == 422


def test_clear_finished_removes_done_and_cancelled(client, service):
    done, cancelled, waiting = (enqueue_text(client, title=t)["id"] for t in ("A", "B", "C"))
    service.queue.claim_next()
    service.queue.finish(done, ["a.wav"], 1.0)
    client.post(f"/api/voices/queue/{cancelled}/cancel")

    body = client.post("/api/voices/queue/clear-finished").json()

    assert body["removed"] == 2 and [i["id"] for i in body["items"]] == [waiting]


def test_queue_routes_do_not_collide_with_the_voice_routes(client):
    # DELETE /api/voices/{voice_id} continua sendo a remoção de voz; a fila usa o caminho mais fundo
    assert client.delete("/api/voices/fantasma").status_code == 404
    assert client.get("/api/voices/design-options").status_code == 200
    assert client.get("/api/voices/queue").status_code == 200


# ---------- arquivos prontos ----------


def make_done_item(client, service, tmp_path) -> tuple[str, Path]:
    item_id = enqueue_text(client, title="Pronto")["id"]
    item = service.queue.claim_next()
    folder = Path(item.output_dir)
    folder.mkdir(parents=True)
    (folder / "pronto-completo.wav").write_bytes(b"RIFFdados")
    (folder / "pronto-completo.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nOi\n", encoding="utf-8")
    (tmp_path / "segredo.txt").write_text("fora da pasta", encoding="utf-8")
    service.queue.finish(item_id, ["pronto-completo.wav", "pronto-completo.srt"], 1.0)
    return item_id, folder


def test_ready_files_are_served_from_the_item_folder_only(client, service, tmp_path):
    item_id, _ = make_done_item(client, service, tmp_path)

    audio = client.get(f"/api/voices/queue/{item_id}/files/pronto-completo.wav")
    assert audio.status_code == 200 and audio.content == b"RIFFdados"
    assert "attachment" not in audio.headers.get("content-disposition", "")
    download = client.get(f"/api/voices/queue/{item_id}/files/pronto-completo.srt?download=true")
    assert "attachment" in download.headers["content-disposition"] and "Oi" in download.text

    view = client.get("/api/voices/queue").json()["items"][0]
    assert [(f["name"], f["audio"]) for f in view["files"]] == [
        ("pronto-completo.wav", True),
        ("pronto-completo.srt", False),
    ]
    assert client.get(view["files"][0]["url"]).status_code == 200


def test_files_outside_the_item_outputs_are_never_served(client, service, tmp_path):
    item_id, folder = make_done_item(client, service, tmp_path)
    (folder / "nao-listado.wav").write_bytes(b"x")

    assert client.get(f"/api/voices/queue/{item_id}/files/nao-listado.wav").status_code == 404
    assert client.get(f"/api/voices/queue/{item_id}/files/..%2Fsegredo.txt").status_code == 404
    assert client.get(f"/api/voices/queue/{item_id}/files/%2E%2E%2F%2E%2E%2Fsegredo.txt").status_code == 404
    (folder / "pronto-completo.wav").unlink()
    assert client.get(f"/api/voices/queue/{item_id}/files/pronto-completo.wav").status_code == 404


# ---------- andamento por SSE ----------


def frames(stream, count: int) -> list[str]:
    return [next(stream) for _ in range(count)]


def test_event_stream_sends_the_queue_when_it_changes_and_a_keepalive_while_it_does_not(service):
    service.add_text("Um texto para a fila.", QueueOptions())
    stream = queue_event_stream(service, interval=5.0, keepalive=15.0, sleep=lambda _s: None)

    first = next(stream)
    assert first.startswith("data: ") and first.endswith("\n\n")
    assert json.loads(first[6:])["items"][0]["state"] == "pending"

    # sem mudança: 5 s, 10 s e, aos 15 s, o comentário de vida que mantém a conexão aberta
    assert frames(stream, 1) == [": keep-alive\n\n"]

    item = service.queue.claim_next()
    service.queue.update_progress(item.id, chapter=1, utterance=2, utterances=9, utterances_done=1)
    changed = next(stream)
    assert changed.startswith("data: ") and json.loads(changed[6:])["items"][0]["utterance"] == 2


def test_event_stream_sends_again_when_only_the_worker_flag_changes(service):
    service.add_text("Um texto para a fila.", QueueOptions())
    worker = {"on": False}
    stream = queue_event_stream(
        service, sleep=lambda _s: None, snapshot=lambda: {**service.view(), "worker": worker["on"]}
    )

    assert json.loads(next(stream)[6:])["worker"] is False
    worker["on"] = True
    assert json.loads(next(stream)[6:])["worker"] is True


def test_events_route_frames_say_whether_a_worker_is_running(service, monkeypatch):
    """A tela só mostra "nenhum executor ativo" se o fluxo diz isso; sem o campo, o aviso piscaria entre itens."""
    import asyncio

    from dmaker.ui import queue_routes

    route = next(r for r in build_queue_router().routes if r.path == "/api/voices/queue/events")

    def first_frame() -> dict:
        body = route.endpoint(service).body_iterator
        return json.loads(asyncio.run(anext(body))[6:])

    assert first_frame()["worker"] is False

    class RunningWorker:
        running = True

    monkeypatch.setattr(queue_routes.runtime, "worker", RunningWorker())
    assert first_frame()["worker"] is True


def test_events_route_answers_as_an_event_stream_without_caching(service):
    # ler a rota pelo TestClient travaria (o fluxo não termina); aqui se chama o endpoint e se confere a resposta
    route = next(r for r in build_queue_router().routes if r.path == "/api/voices/queue/events")
    response = route.endpoint(service)
    assert "GET" in route.methods
    assert response.media_type == "text/event-stream" and response.headers["cache-control"] == "no-cache"


# ---------- worker da interface e trava de síntese ----------


def test_importing_the_server_never_starts_a_worker():
    from dmaker.ui.queue_routes import runtime

    assert runtime.worker is None and runtime.worker_running is False


def test_runtime_builds_the_worker_with_the_synthesis_lock_and_wakes_it_on_new_items(monkeypatch, service):
    from dmaker.ui import queue_routes
    from dmaker.ui.voice_routes import hold_synthesis

    calls: list[str] = []

    class FakeWorker:
        running = False

        def start(self):
            calls.append("start")
            self.running = True

        def wake(self):
            calls.append("wake")

    built: dict = {}

    def fake_build(queue, guard=None, log=None):
        built["guard"] = guard
        return FakeWorker()

    monkeypatch.setattr(queue_routes, "build_worker", fake_build)
    runtime = queue_routes.QueueRuntime()
    monkeypatch.setattr(runtime, "_service", service)
    service.on_change = runtime.wake

    runtime.wake()  # sem worker ainda: não quebra
    runtime.start_worker()
    service.add_text("Um texto.", QueueOptions())

    assert built["guard"] is hold_synthesis  # a fila disputa a mesma trava das sínteses avulsas
    assert calls == ["start", "wake"] and runtime.worker_running is True


def test_synthesis_lock_makes_the_queue_wait_for_a_standalone_job_and_says_so():
    import threading

    from dmaker.ui.voice_routes import hold_synthesis

    notes: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def standalone():
        with hold_synthesis(notes.append):
            entered.set()
            release.wait(5)

    holder = threading.Thread(target=standalone)
    holder.start()
    assert entered.wait(5)
    got_it = threading.Event()

    def queued():
        with hold_synthesis(notes.append):
            got_it.set()

    waiter = threading.Thread(target=queued)
    waiter.start()
    assert not got_it.wait(0.2)  # a fila espera a síntese avulsa terminar
    assert notes == ["Aguardando outro trabalho de voz terminar"]
    release.set()
    assert got_it.wait(5)
    holder.join(), waiter.join()
