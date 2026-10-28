"""Rotas do corte automático da interface: iniciar o corte (job), a lista no detalhe do projeto e desfazer."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker.media.ffmpeg import RecordingRunner
from dmaker.ui import server
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.library import VoiceLibrary

from .test_autocut_service import FakeTranscriber, fake_prober, writes_the_recording


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    path = tmp_path / "gravacao.mp4"
    path.write_bytes(b"\x00" * 64)
    return path


@pytest.fixture
def client(tmp_path: Path):
    services = VoiceServices(
        library=VoiceLibrary(tmp_path / "vozes"),
        runner=RecordingRunner(on_run=writes_the_recording),
        transcriber=FakeTranscriber(),
        prober=fake_prober,
    )
    server.app.dependency_overrides[get_voice_services] = lambda: services
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.pop(get_voice_services, None)


def finished(job_id: str):
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 30)
    return job


def start(client: TestClient, recording: Path, **body):
    return client.post("/api/autocut", json={"source": str(recording), "name": "corte-ui", **body})


def test_autocut_runs_as_a_job_tied_to_the_project_and_returns_the_cut_list(client, recording):
    response = start(client, recording, intensity="agressiva")
    assert response.status_code == 200, response.text

    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    assert job.snapshot()["project"] == "corte-ui"
    assert job.progress["percent"] == 100
    result = job.result
    assert result["project"] == "corte-ui" and result["report"]["cuts"]
    assert {"filler", "repetition"} <= set(result["report"]["counts"])
    assert result["report"]["duration_after_s"] < result["report"]["duration_before_s"]


def test_the_project_detail_carries_the_cut_list_only_for_projects_made_by_autocut(client, recording):
    assert finished(start(client, recording).json()["job_id"]).status == "done"

    cuts = client.get("/api/projects/corte-ui").json()["cuts"]
    assert cuts["intensity"] == "normal" and cuts["cuts"][0]["reason"] in {"silence", "filler"}

    client.post("/api/projects", json={"name": "avulso", "sources": [], "captions": False})
    assert client.get("/api/projects/avulso").json()["cuts"] is None


def test_undo_returns_the_stretch_to_the_project_and_the_updated_list(client, recording):
    result = finished(start(client, recording).json()["job_id"]).result
    first = result["report"]["cuts"][0]
    clips_before = len(client.get("/api/projects/corte-ui").json()["spec"]["timeline"])

    response = client.post(f"/api/projects/corte-ui/cuts/{first['id']}/undo")

    assert response.status_code == 200, response.text
    assert next(c for c in response.json()["cuts"] if c["id"] == first["id"])["undone"] is True
    detail = client.get("/api/projects/corte-ui").json()
    assert len(detail["spec"]["timeline"]) <= clips_before
    assert detail["cuts"]["duration_after_s"] == pytest.approx(
        result["report"]["duration_after_s"] + first["duration_s"], abs=0.02
    )


def test_undo_errors_come_back_in_portuguese(client, recording):
    result = finished(start(client, recording).json()["job_id"]).result
    cut_id = result["report"]["cuts"][0]["id"]
    assert client.post(f"/api/projects/corte-ui/cuts/{cut_id}/undo").status_code == 200
    again = client.post(f"/api/projects/corte-ui/cuts/{cut_id}/undo")
    assert again.status_code == 400 and "já foi desfeito" in again.json()["detail"]
    assert client.post("/api/projects/corte-ui/cuts/99/undo").status_code == 400
    assert client.post("/api/projects/nao-existe/cuts/1/undo").status_code == 404


def test_a_request_that_cannot_work_is_refused_before_the_job_starts(client, recording, tmp_path):
    missing = client.post("/api/autocut", json={"source": str(tmp_path / "x.mp4"), "name": "n"})
    assert missing.status_code == 404 and "não encontrada" in missing.json()["detail"]
    assert start(client, recording, name="nome/ruim").status_code == 400
    assert start(client, recording, preset="plataforma/inexistente").status_code == 400
    assert start(client, recording, intensity="brutal").status_code == 422
    assert finished(start(client, recording).json()["job_id"]).status == "done"
    taken = start(client, recording)
    assert taken.status_code == 400 and "já existe um projeto" in taken.json()["detail"]
    assert finished(start(client, recording, overwrite=True).json()["job_id"]).status == "done"
