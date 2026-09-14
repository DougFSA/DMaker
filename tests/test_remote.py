"""Ponte com a interface gráfica (pipeline/remote.py): UIClient contra um servidor real (subprocesso
não é necessário, sobe a própria app FastAPI numa porta efêmera) e RenderDispatcher com um cliente
falso, para testar a tradução de eventos sem precisar de HTTP nem de processo nenhum."""

from __future__ import annotations

import threading
import time

import pytest
import uvicorn

from dmaker.pipeline.jobs import JobManager
from dmaker.pipeline.remote import RenderDispatcher, UIClient
from dmaker.ui import server as ui_server


class _NoSignalServer(uvicorn.Server):
    """Evita o uvicorn tentar instalar handlers de sinal fora da thread principal (erro em teste)."""

    def install_signal_handlers(self) -> None:
        pass


@pytest.fixture
def live_server():
    cfg = uvicorn.Config(ui_server.app, host="127.0.0.1", port=0, log_level="error")
    srv = _NoSignalServer(cfg)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    assert srv.started, "servidor de teste não subiu a tempo"
    port = srv.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.should_exit = True
        thread.join(timeout=5)


# ---------- UIClient contra o servidor de verdade ----------


def test_is_alive_true_when_up_and_false_when_not(live_server):
    assert UIClient(live_server).is_alive() is True
    assert UIClient("http://127.0.0.1:1", timeout=1.0).is_alive() is False


def test_job_and_events_roundtrip(live_server):
    def work(job):
        job.log("etapa 1")
        sink = job.sink()
        sink.start("montagem final", 10.0)
        sink.update(5.0)
        sink.finish()
        return {"ok": True}

    job = ui_server.jobs.start("teste remoto", work)
    ui_server.jobs.wait(job, 5)

    client = UIClient(live_server)
    kinds = [evt["kind"] for evt in client.events(job.id)]
    assert kinds[0] == "start" and "log" in kinds and "progress" in kinds and kinds[-1] == "end"

    snapshot = client.job(job.id)
    assert snapshot["status"] == "done" and snapshot["result"] == {"ok": True}
    assert any(j["job_id"] == job.id for j in client.jobs())


def test_render_posts_focus_true_even_when_not_asked(live_server):
    client = UIClient(live_server)
    started = client.render("projeto-que-nao-existe", {"preview": True})
    job_id = started["job_id"]
    job = ui_server.jobs.get(job_id)
    assert job is not None and job.meta["focus"] is True and job.meta["project"] == "projeto-que-nao-existe"
    ui_server.jobs.wait(job, 5)
    assert job.status == "error"  # projeto não existe; só confere que o job foi mesmo disparado


def test_export_posts_presets(live_server):
    client = UIClient(live_server)
    started = client.export("projeto-que-nao-existe", ["instagram/reels"])
    job = ui_server.jobs.get(started["job_id"])
    assert job is not None and "instagram/reels" in job.description


def test_clients_active_reflects_ping(live_server):
    client = UIClient(live_server)
    assert client.clients_active() in (True, False)  # não derruba, seja qual for o estado anterior
    ui_server._last_client_ping = time.time()
    assert client.clients_active() is True
    ui_server._last_client_ping = 0.0
    assert client.clients_active() is False


# ---------- RenderDispatcher com cliente e dependências falsas ----------


class FakeClient:
    def __init__(self, alive_after_launch=True):
        self.base_url = "http://fake"
        self._alive = False
        self._alive_after_launch = alive_after_launch
        self._active_clients = False
        self.events_by_job: dict[str, list[dict]] = {}
        self.render_calls: list[tuple[str, dict]] = []
        self.export_calls: list[tuple[str, list[str]]] = []
        self._next_job_id = 1

    def is_alive(self) -> bool:
        return self._alive

    def launch(self) -> None:
        if self._alive_after_launch:
            self._alive = True

    def render(self, name, options):
        self.render_calls.append((name, dict(options)))
        job_id = f"job{self._next_job_id}"
        self._next_job_id += 1
        return {"job_id": job_id}

    def export(self, name, presets):
        self.export_calls.append((name, list(presets)))
        job_id = f"job{self._next_job_id}"
        self._next_job_id += 1
        return {"job_id": job_id}

    def job(self, job_id):
        return {"job_id": job_id, "status": "done", "result": {"output": f"{job_id}.mp4"}}

    def clients_active(self) -> bool:
        return self._active_clients

    def events(self, job_id):
        yield from self.events_by_job.get(job_id, [])


class FakeSink:
    def __init__(self):
        self.calls: list[tuple] = []

    def start(self, label, total):
        self.calls.append(("start", label, total))

    def update(self, done):
        self.calls.append(("update", done))

    def finish(self):
        self.calls.append(("finish",))


def _dispatcher(client, **kwargs):
    logs: list[str] = []
    dispatcher = RenderDispatcher(
        client=client,
        launcher=kwargs.pop("launcher", client.launch),
        opener=kwargs.pop("opener", lambda url: logs.append(f"open:{url}")),
        log=logs.append,
    )
    return dispatcher, logs


def test_ensure_ui_launches_only_when_dead():
    client = FakeClient()
    dispatcher, _logs = _dispatcher(client)
    launched = []
    dispatcher.launcher = lambda: (launched.append(1), client.launch())

    assert dispatcher.ensure_ui() is True
    assert launched == [1]

    # já está viva: a segunda chamada não lança de novo
    assert dispatcher.ensure_ui() is True
    assert launched == [1]


def test_ensure_ui_raises_when_launch_does_not_bring_it_up():
    client = FakeClient(alive_after_launch=False)
    dispatcher, _logs = _dispatcher(client)
    with pytest.raises(RuntimeError):
        dispatcher.ensure_ui()


def test_open_browser_only_when_just_launched_or_no_clients():
    client = FakeClient()
    dispatcher, logs = _dispatcher(client)

    dispatcher.ensure_ui()  # acabou de lançar
    dispatcher.open_browser_if_needed("proj", "job1")
    assert any("open:" in line for line in logs)

    logs.clear()
    client._active_clients = True  # já tem gente olhando; não deveria abrir outra aba
    dispatcher.open_browser_if_needed("proj", "job2")
    assert not any(line.startswith("open:") for line in logs)

    client._active_clients = False  # ninguém olhando: abre de novo
    dispatcher.open_browser_if_needed("proj", "job3")
    assert any("open:" in line for line in logs)


def test_render_translates_progress_and_log_events():
    client = FakeClient()
    dispatcher, logs = _dispatcher(client)
    dispatcher.ensure_ui()

    job_id = "job1"
    client.events_by_job[job_id] = [
        {"kind": "start", "description": "render x"},
        {"kind": "log", "message": "trechos: 1 (1 a gerar, 0 em cache)"},
        {"kind": "progress", "label": "trecho 1/1", "total": 10.0, "done": 5.0, "percent": 50},
        {"kind": "progress", "label": "trecho 1/1", "total": 10.0, "done": 10.0, "percent": 100},
        {"kind": "progress", "label": "montagem final", "total": 20.0, "done": 20.0, "percent": 100},
        {"kind": "end", "status": "done"},
    ]
    client.render_calls.clear()

    def fake_render(name, options):
        client.render_calls.append((name, dict(options)))
        return {"job_id": job_id}

    client.render = fake_render
    sink = FakeSink()
    result = dispatcher.render("meu-projeto", {"preview": True}, sink, logs.append)

    assert result == {"job_id": job_id, "status": "done", "result": {"output": "job1.mp4"}}
    assert client.render_calls == [("meu-projeto", {"preview": True})]
    assert sink.calls == [
        ("start", "trecho 1/1", 10.0),
        ("update", 5.0),
        ("update", 10.0),
        ("finish",),
        ("start", "montagem final", 20.0),
        ("update", 20.0),
        ("finish",),
    ]
    assert any("render x" in line for line in logs)
    assert any("trechos: 1" in line for line in logs)


def test_render_raises_runtime_error_when_job_fails():
    client = FakeClient()
    dispatcher, logs = _dispatcher(client)
    dispatcher.ensure_ui()
    job_id = "job1"
    client.events_by_job[job_id] = [
        {"kind": "start", "description": "render x"},
        {"kind": "end", "status": "error", "error": "ffmpeg explodiu"},
    ]
    client.render = lambda name, options: {"job_id": job_id}

    with pytest.raises(RuntimeError, match="ffmpeg explodiu"):
        dispatcher.render("meu-projeto", {}, FakeSink(), logs.append)


def test_export_dispatches_through_client_export():
    client = FakeClient()
    dispatcher, logs = _dispatcher(client)
    dispatcher.ensure_ui()
    job_id = "job1"
    client.events_by_job[job_id] = [{"kind": "end", "status": "done"}]
    client.export = lambda name, presets: (
        client.export_calls.append((name, list(presets))),
        {"job_id": job_id},
    )[1]

    result = dispatcher.export("meu-projeto", ["instagram/reels", "youtube/shorts"], FakeSink(), logs.append)

    assert result["status"] == "done"
    assert client.export_calls == [("meu-projeto", ["instagram/reels", "youtube/shorts"])]


def test_job_manager_start_accepts_optional_meta():
    manager = JobManager()
    job = manager.wait(manager.start("sem meta", lambda job: None), timeout=5)
    assert job.snapshot()["focus"] is False and job.snapshot()["project"] is None

    job2 = manager.wait(
        manager.start("com meta", lambda job: None, meta={"focus": True, "project": "x"}), timeout=5
    )
    assert job2.snapshot()["focus"] is True and job2.snapshot()["project"] == "x"
