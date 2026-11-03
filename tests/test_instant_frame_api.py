"""As rotas do quadro de um instante: pedir, acompanhar pelo GET, servir o PNG, o cache, o erro e o pedido superado.
O ffmpeg e o probe são falsos; o resto é o servidor de verdade."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.instant_frame_tasks import InstantFrameTasks
from dmaker.ui import server
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.library import VoiceLibrary

from .conftest import fake_ffmpeg_output
from .test_pipeline_unit import fake_prober

PROJECT = "ui-quadro"
SPEC = {
    "output": {"preset": "instagram/reels"},
    "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 6}],
    "overlays": [{"type": "text", "text": "Gancho", "role": "hook", "start": 0, "end": 6}],
    "audio": {"normalize": "off"},
}


class GatedRunner(RecordingRunner):
    """O primeiro comando espera alguém abrir o portão: dá tempo de um pedido novo chegar no meio do trabalho."""

    def __init__(self, gate: threading.Event | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.gate = gate
        self.waiting = threading.Event()

    def run(self, command):
        if self.gate is not None and not self.waiting.is_set():
            self.waiting.set()
            assert self.gate.wait(10), "o teste esqueceu de abrir o portão"
        return super().run(command)


@pytest.fixture
def api(tmp_path, monkeypatch):
    runner = GatedRunner(on_run=fake_ffmpeg_output)
    services = VoiceServices(library=VoiceLibrary(tmp_path / "voices"), runner=runner, prober=fake_prober)
    server.app.dependency_overrides[get_voice_services] = lambda: services
    monkeypatch.setattr(server, "instant_frame_tasks", InstantFrameTasks())
    with TestClient(server.app) as client:
        assert client.put(f"/api/projects/{PROJECT}", json=SPEC).status_code == 200
        (config.PROJECTS_DIR / PROJECT / "take.mp4").write_bytes(b"x")
        yield client, runner
    server.app.dependency_overrides.pop(get_voice_services, None)


def ask(client, **body) -> dict:
    response = client.post(f"/api/projects/{PROJECT}/frame", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def poll(client, key: str, timeout: float = 10.0, *, name: str = PROJECT) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/api/projects/{name}/frame/{key}").json()
        if body["status"] != "pending":
            return body
        time.sleep(0.02)
    raise AssertionError("o quadro não terminou")


def test_a_frame_is_made_in_the_background_served_as_an_image_and_the_second_request_is_instant(api):
    client, runner = api
    asked = ask(client, t=1.0)
    assert (
        asked["status"] in ("pending", "ready")
        and len(asked["key"]) == 16
        and asked["t"] == pytest.approx(1.0)
    )

    done = poll(client, asked["key"])
    assert done["status"] == "ready" and done["notes"] == [] and "error" not in done
    assert done["url"].startswith("/api/file?path=") and done["url"].endswith(".png")
    assert done["t"] == pytest.approx(1.0)
    assert client.get(done["url"]).status_code == 200  # o `<img>` do front lê direto

    commands = len(runner.commands)
    again = ask(client, t=1.0)
    assert again["status"] == "ready" and again["key"] == asked["key"] and again["url"] == done["url"]
    assert len(runner.commands) == commands  # nada foi refeito


def test_the_instant_is_rounded_to_the_frame_and_the_same_frame_has_the_same_key(api):
    client, _ = api
    first, same, next_frame = ask(client, t=1.0), ask(client, t=1.01), ask(client, t=1.04)
    assert same["key"] == first["key"] and next_frame["key"] != first["key"]
    assert first["t"] == pytest.approx(1.0) and next_frame["t"] == pytest.approx(31 / 30)


def test_the_spec_in_the_body_is_the_one_drawn_and_a_new_edit_is_a_new_key(api):
    client, _ = api
    first = ask(client, t=1.0, spec=SPEC)
    edited = {**SPEC, "overlays": [{"type": "text", "text": "Outro texto", "role": "hook"}]}
    second = ask(client, t=1.0, spec=edited)
    assert first["key"] != second["key"]
    assert poll(client, second["key"])["status"] == "ready"


def test_a_missing_file_is_an_error_state_with_the_message(api):
    client, _ = api
    (config.PROJECTS_DIR / PROJECT / "take.mp4").unlink()
    asked = ask(client, t=1.0)
    done = poll(client, asked["key"])
    assert done["status"] == "error" and "take.mp4" in done["error"] and "url" not in done


def test_a_newer_request_supersedes_the_one_in_progress(api):
    client, runner = api
    runner.gate = threading.Event()
    old = ask(client, t=1.0)
    assert runner.waiting.wait(10)  # o trabalho do primeiro está no meio do primeiro comando
    new = ask(client, t=2.0)
    assert client.get(f"/api/projects/{PROJECT}/frame/{old['key']}").json()["status"] == "superseded"

    runner.gate.set()
    assert poll(client, new["key"])["status"] == "ready"
    assert client.get(f"/api/projects/{PROJECT}/frame/{old['key']}").json()["status"] == "superseded"


def test_a_pending_frame_reports_the_step_and_the_progress(api):
    client, runner = api
    runner.gate = threading.Event()
    asked = ask(client, t=1.0)
    assert asked["status"] == "pending" and "label" in asked and asked["percent"] == 0
    runner.gate.set()
    assert poll(client, asked["key"])["status"] == "ready"


def test_the_errors_of_the_routes(api):
    client, _ = api
    assert client.post("/api/projects/nao-existe/frame", json={"t": 1.0}).status_code == 404
    assert client.post(f"/api/projects/{PROJECT}/frame", json={"t": -1.0}).status_code == 422
    assert client.post(f"/api/projects/{PROJECT}/frame", json={}).status_code == 422
    invalid = client.post(f"/api/projects/{PROJECT}/frame", json={"t": 1.0, "spec": {"timeline": []}})
    assert invalid.status_code == 400  # a spec do corpo não é válida (como na linha do tempo)
    unknown_preset = client.post(
        f"/api/projects/{PROJECT}/frame", json={"t": 1.0, "spec": {**SPEC, "output": {"preset": "x/y"}}}
    )
    assert unknown_preset.status_code == 422
    assert (
        client.get(f"/api/projects/{PROJECT}/frame/{'a' * 16}").status_code == 404
    )  # chave que ninguém pediu
    assert client.get(f"/api/projects/{PROJECT}/frame/nao-e-uma-chave").status_code == 404
    assert client.get(f"/api/projects/{PROJECT}/frame/..%2F..%2Fx").status_code == 404
