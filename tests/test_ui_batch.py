"""Rotas /api/batches da interface: validar a planilha, iniciar o lote como job, pausar, retomar e relatar."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.pipeline.batch import BatchService
from dmaker.pipeline.batch_state import BatchStore
from dmaker.ui import server
from dmaker.ui.batch_routes import get_batch_service

from .batch_support import FakeRenderer, fake_prober, make_media, write_sheet


@pytest.fixture
def media(tmp_path: Path) -> Path:
    return make_media(tmp_path)


@pytest.fixture
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture
def service(tmp_path, renderer) -> BatchService:
    return BatchService(store=BatchStore(tmp_path / "lotes"), renderer=renderer, prober=fake_prober)


@pytest.fixture
def client(service):
    server.app.dependency_overrides[get_batch_service] = lambda: service
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.pop(get_batch_service, None)


def body(sheet: Path, **extra) -> dict:
    return {"template": "stories-medlycare", "sheet": str(sheet), "name_column": "titulo", **extra}


def finished(job_id: str):
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 30)
    return job


def test_validate_returns_the_table_the_screen_shows(client, media):
    response = client.post("/api/batches/validate", json=body(write_sheet(media, broken={2: "sumiu.png"})))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 5 and data["valid"] == 4 and data["invalid"] == 1 and data["ok"] is False
    assert data["columns"]["matched"] == {"titulo": "titulo", "texto": "texto", "print": "print"}
    bad = data["rows"][1]
    assert bad["valid"] is False and bad["line"] == 3
    assert bad["issues"][0]["field"] == "print" and "arquivo não encontrado" in bad["issues"][0]["message"]
    assert "linha 3, coluna print" in data["text"]


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"template": "nao-existe"}, "não encontrado"),
        ({"sheet": "sumiu.csv"}, "Planilha não encontrada"),
        ({"name_column": "nome"}, "não existe na planilha"),
    ],
)
def test_validate_answers_input_mistakes_with_a_400_and_the_sentence(client, media, payload, fragment):
    response = client.post("/api/batches/validate", json={**body(write_sheet(media)), **payload})

    assert response.status_code == 400 and fragment in response.json()["detail"]


def test_start_runs_the_whole_lote_as_a_job_and_the_view_reports_it(client, media, renderer):
    response = client.post("/api/batches", json=body(write_sheet(media), name="serie"))

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "serie"
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    assert (
        job.meta["batch"] == "serie" and job.progress["percent"] == 80
    )  # o último vídeo começou com 4 de 5 prontos
    assert job.result["done"] == 5 and job.result["status"] == "finished"

    view = client.get("/api/batches/serie").json()
    assert view["status"] == "finished" and view["summary"].startswith("5 de 5") and view["job_id"] is None
    assert [row["state"] for row in view["rows"]] == ["done"] * 5
    assert (config.OUTPUT_DIR / "serie" / "dica-um.mp4").exists()
    assert "5 de 5 vídeo(s) pronto(s)" in view["text"]
    assert len(renderer.calls) == 5


def test_start_refuses_a_sheet_with_a_bad_row_unless_told_to_skip_it(client, media, renderer):
    sheet = write_sheet(media, broken={4: "sumiu.png"})

    refused = client.post("/api/batches", json=body(sheet))
    assert refused.status_code == 400 and "1 linha(s) com problema" in refused.json()["detail"]
    assert renderer.calls == []

    accepted = client.post("/api/batches", json=body(sheet, skip_invalid=True))
    job = finished(accepted.json()["job_id"])
    assert job.result["done"] == 4 and job.result["skipped"] == 1
    skipped = client.get("/api/batches/semana").json()["rows"][3]
    assert skipped["state"] == "invalid" and skipped["issues"][0]["field"] == "print"


def test_start_with_a_name_in_use_is_a_409(client, media):
    finished(client.post("/api/batches", json=body(write_sheet(media))).json()["job_id"])

    again = client.post("/api/batches", json=body(write_sheet(media)))

    assert again.status_code == 409 and "Já existe o lote" in again.json()["detail"]


def test_pause_stops_after_the_video_in_progress_and_resume_continues(client, media, renderer):
    entered, release = threading.Event(), threading.Event()

    def hold_second(project, rendered_so_far):
        if rendered_so_far == 1:
            entered.set()
            assert release.wait(20)

    renderer.before = hold_second
    job_id = client.post("/api/batches", json=body(write_sheet(media))).json()["job_id"]
    assert entered.wait(20)

    during = client.get("/api/batches/semana").json()
    assert during["status"] == "running" and during["job_id"] == job_id
    assert [row["state"] for row in during["rows"]][:2] == ["done", "running"]
    # só um lote por vez
    assert client.post("/api/batches", json=body(write_sheet(media), name="outro")).status_code == 409
    assert client.post("/api/batches/semana/resume", json={}).status_code == 409

    assert client.post("/api/batches/semana/pause").json()["pause_requested"] is True
    release.set()
    job = finished(job_id)
    assert job.status == "done" and job.result["status"] == "paused" and job.result["done"] == 2

    paused = client.get("/api/batches/semana").json()
    assert paused["status"] == "paused" and paused["waiting"] == 3 and paused["job_id"] is None

    renderer.before = None
    resumed = finished(client.post("/api/batches/semana/resume", json={}).json()["job_id"])
    assert resumed.result["status"] == "finished" and resumed.result["done"] == 5
    assert len(renderer.calls) == 5  # os dois primeiros não foram refeitos


def test_resume_can_pick_videos_and_force_them(client, media, renderer):
    finished(client.post("/api/batches", json=body(write_sheet(media))).json()["job_id"])
    renderer.calls.clear()

    job = finished(
        client.post("/api/batches/semana/resume", json={"rows": [2], "force": True}).json()["job_id"]
    )

    assert job.status == "done" and renderer.calls == ["semana-dica-dois"]


def test_the_list_shows_every_lote(client, media):
    finished(client.post("/api/batches", json=body(write_sheet(media), name="um")).json()["job_id"])

    data = client.get("/api/batches").json()["batches"]

    assert [(item["name"], item["status"], item["rows"]) for item in data] == [("um", "finished", 5)]


def test_unknown_lote_is_a_404_on_every_route(client):
    assert client.get("/api/batches/nada").status_code == 404
    assert client.post("/api/batches/nada/pause").status_code == 404
    assert client.post("/api/batches/nada/resume", json={}).status_code == 404
    assert client.delete("/api/batches/nada").status_code == 404


def test_delete_forgets_the_lote_but_keeps_projects_and_videos(client, media):
    finished(client.post("/api/batches", json=body(write_sheet(media), name="velho")).json()["job_id"])

    assert client.delete("/api/batches/velho").json() == {"removed": "velho"}
    assert client.get("/api/batches/velho").status_code == 404
    assert (config.OUTPUT_DIR / "velho" / "dica-um.mp4").exists()
    assert (config.PROJECTS_DIR / "velho-dica-um" / "spec.json").exists()


def test_the_file_browser_lists_sheets_when_asked_for_them(client, tmp_path):
    folder = tmp_path / "pasta"
    folder.mkdir()
    for name in ("a.csv", "b.xlsx", "c.json", "d.mp4", "e.txt"):
        (folder / name).write_bytes(b"x")

    sheets = client.get("/api/browse", params={"path": str(folder), "kind": "sheet"}).json()["files"]
    media_files = client.get("/api/browse", params={"path": str(folder)}).json()["files"]

    assert sorted(f["name"] for f in sheets) == ["a.csv", "b.xlsx", "c.json", "e.txt"]
    assert [f["name"] for f in media_files] == ["d.mp4"]
