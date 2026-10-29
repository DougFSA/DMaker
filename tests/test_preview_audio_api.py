"""Rotas do áudio da prévia: pedir a mixagem, acompanhar pelo GET e tocar o arquivo (com Range, que o `<audio>`
precisa para pular sem baixar tudo). O ffmpeg, o probe e o sintetizador são falsos."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.preview_audio_tasks import PreviewAudioTasks
from dmaker.ui import server
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.lexicon_store import LexiconStore
from dmaker.voice.library import VoiceLibrary

from .conftest import fake_ffmpeg_output
from .test_pipeline_unit import LOUDNORM_JSON
from .test_preview_audio import FakeSynthesizer, graph_of, inputs_of, make_prober, pieces

PROJECT = "ui-audio-previa"
API_SPEC = {
    "output": {"preset": "instagram/stories"},
    "sources": {"cam1": {"src": "cam1.mp4"}, "mesa": {"src": "mesa.wav", "sync": 2.0}},
    "timeline": [{"type": "clip", "source": "cam1", "start": 10, "end": 18, "mute": True}],
    "audio": {"tracks": [{"source": "mesa", "volume": 0.5}], "normalize": "off"},
}


@pytest.fixture
def api(tmp_path, monkeypatch):
    runner = RecordingRunner(on_run=fake_ffmpeg_output, capture_stderr=LOUDNORM_JSON)
    services = VoiceServices(
        library=VoiceLibrary(tmp_path / "voices"),
        runner=runner,
        prober=make_prober,
        synthesizer=FakeSynthesizer(),
        lexicons=LexiconStore(tmp_path / "assets"),
    )
    server.app.dependency_overrides[get_voice_services] = lambda: services
    monkeypatch.setattr(server, "preview_audio_tasks", PreviewAudioTasks())
    with TestClient(server.app) as client:
        assert client.put(f"/api/projects/{PROJECT}", json=API_SPEC).status_code == 200
        folder = config.PROJECTS_DIR / PROJECT
        for name in ("cam1.mp4", "mesa.wav"):
            (folder / name).write_bytes(b"x")
        yield client, runner
    server.app.dependency_overrides.pop(get_voice_services, None)


def poll(client, key: str, timeout: float = 10.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/api/projects/{PROJECT}/preview-audio", params={"key": key}).json()
        if body["state"] != "building":
            return body
        time.sleep(0.02)
    raise AssertionError("a mixagem não terminou")


def test_api_mixes_in_the_background_and_serves_the_file_with_ranges(api):
    client, runner = api
    asked = client.post(f"/api/projects/{PROJECT}/preview-audio", json={})
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert body["state"] in ("building", "ready") and body["key"]

    done = poll(client, body["key"])
    assert (
        done["state"] == "ready"
        and done["url"].startswith("/api/file?path=")
        and done["url"].endswith(".m4a")
    )
    assert done["duration_s"] == pytest.approx(8.0) and done["warnings"] == [] and done["error"] is None
    assert [inputs_of(c) for c in pieces(runner)] == [[("mesa.wav", 8.0)]]  # 10 s da sessão = 8 s na mesa

    served = client.get(done["url"])
    assert served.status_code == 200 and served.headers["accept-ranges"] == "bytes"
    assert client.get(done["url"], headers={"Range": "bytes=1-2"}).status_code == 206

    again = client.post(f"/api/projects/{PROJECT}/preview-audio", json={}).json()
    assert again["state"] == "ready" and again["key"] == body["key"]


def test_api_uses_the_spec_in_the_body_and_a_new_edit_is_a_new_key(api):
    client, runner = api
    first = client.post(f"/api/projects/{PROJECT}/preview-audio", json={"spec": API_SPEC}).json()
    louder = {**API_SPEC, "audio": {**API_SPEC["audio"], "tracks": [{"source": "mesa", "volume": 0.9}]}}
    second = client.post(f"/api/projects/{PROJECT}/preview-audio", json={"spec": louder}).json()
    assert first["key"] != second["key"]
    assert poll(client, first["key"])["state"] == "ready" and poll(client, second["key"])["state"] == "ready"
    assert any("volume=0.900" in graph_of(command) for command in pieces(runner))


def test_api_errors(api):
    client, _ = api
    assert client.post("/api/projects/nao-existe/preview-audio", json={}).status_code == 404
    unknown = client.get(f"/api/projects/{PROJECT}/preview-audio", params={"key": "chave-fantasma"})
    assert unknown.status_code == 404
    invalid = client.post(f"/api/projects/{PROJECT}/preview-audio", json={"spec": {"timeline": []}})
    assert invalid.status_code == 400
