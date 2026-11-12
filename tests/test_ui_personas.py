"""Rotas /api/personas: cadastro, o que cada motor aceita, a confirmação de apagar e a prévia como job."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.persona.library import PersonaLibrary
from dmaker.pipeline import persona_preview
from dmaker.pipeline.persona_preview import preview_project
from dmaker.ui import server
from dmaker.ui.persona_routes import get_persona_library


@pytest.fixture
def library(tmp_path) -> PersonaLibrary:
    return PersonaLibrary(root=tmp_path / "personas", presets_root=tmp_path / "prontas")


@pytest.fixture
def client(library, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "modelos")  # sem o personagem 3D baixado
    server.app.dependency_overrides[get_persona_library] = lambda: library
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.pop(get_persona_library, None)


def test_the_list_carries_the_personas_and_what_each_engine_accepts(client):
    client.post("/api/personas", json={"name": "Ana", "kind": "2d", "appearance": {"hair_style": "bun"}})

    body = client.get("/api/personas").json()

    assert [p["id"] for p in body["personas"]] == ["ana"]
    assert body["personas"][0]["appearance"]["hair_style"] == "bun"
    engines = {e["kind"]: e for e in body["engines"]}
    assert "wave" in engines["2d"]["gestures"] and "wave" in engines["3d"]["gestures"]
    assert "persona3d-mpfb" in engines["3d"]["unavailable"]  # a mensagem do motor, com o comando que baixa


def test_create_edit_and_delete_with_confirmation(client):
    created = client.post("/api/personas", json={"name": "Caio", "kind": "3d"}).json()
    assert created["appearance"]["outfit_color"] == "#3A4A5E"

    edited = client.put("/api/personas/caio", json={"appearance": {"outfit_color": "#aa3322"}}).json()
    assert edited["appearance"]["outfit_color"] == "#AA3322"

    assert client.delete("/api/personas/caio").status_code == 409
    assert client.get("/api/personas/caio").status_code == 200
    assert client.delete("/api/personas/caio?confirm=true").json() == {"removed": "caio"}
    assert client.get("/api/personas/caio").status_code == 404


def test_invalid_appearance_and_unknown_voice_come_back_as_400(client):
    assert (
        client.post(
            "/api/personas", json={"name": "Z", "kind": "2d", "appearance": {"skin": "x"}}
        ).status_code
        == 400
    )
    assert client.post("/api/personas", json={"name": "Z", "kind": "9d"}).status_code == 400


def test_a_3d_preview_without_the_model_is_refused_with_the_engine_message(client):
    client.post("/api/personas", json={"name": "Caio", "kind": "3d"})

    response = client.post("/api/personas/caio/preview", json={"phrase": "Oi"})

    assert (
        response.status_code == 409 and "dmaker models download persona3d-mpfb" in response.json()["detail"]
    )


def test_the_preview_is_a_job_that_renders_one_persona_segment(client, monkeypatch, tmp_path):
    client.post("/api/personas", json={"name": "Ana"})
    video = tmp_path / "previa.mp4"
    video.write_bytes(b"v")
    seen = {}

    class Result:
        output = video
        duration = 2.5
        warnings = ["aviso"]

    def fake_render(persona_id, phrase, **kwargs):
        seen.update(persona=persona_id, phrase=phrase)
        return Result()

    monkeypatch.setattr("dmaker.ui.persona_routes.render_persona_preview", fake_render)

    job_id = client.post("/api/personas/ana/preview", json={"phrase": "Bom dia"}).json()["job_id"]
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 30)

    assert job.status == "done" and seen == {"persona": "ana", "phrase": "Bom dia"}
    assert job.result["duration_s"] == 2.5 and job.result["output_url"].startswith("/api/file?path=")


def test_the_preview_project_is_one_full_screen_persona_segment(tmp_path):
    project = preview_project("ana", "  Olá  ", tmp_path)

    (segment,) = project.timeline
    assert segment.type == "persona" and segment.persona == "ana" and segment.speech.text == "Olá"
    assert project.name == persona_preview.preview_project_name("ana")
    with pytest.raises(ValueError):
        preview_project("ana", "x" * 500, tmp_path)
    assert preview_project("ana", "", tmp_path).timeline[0].speech.text == persona_preview.DEFAULT_PHRASE


def test_use_puts_the_persona_in_a_project_as_a_full_screen_segment_or_a_corner_overlay(
    client, tmp_path, monkeypatch
):
    from dmaker.domain.spec import Project
    from dmaker.pipeline.projects import load_project, save_project

    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projetos")
    client.post("/api/personas", json={"name": "Ana"})
    save_project(
        Project.model_validate(
            {
                "name": "demo",
                "output": {"preset": "instagram/reels"},
                "timeline": [{"type": "card", "title": "Abertura", "duration": 2.0}],
            }
        )
    )

    assert client.post("/api/personas/ana/use", json={"project": "demo", "text": "Oi"}).status_code == 200
    body = {"project": "demo", "text": "Olá", "placement": "overlay", "start": 2.0}
    assert client.post("/api/personas/ana/use", json=body).status_code == 200

    saved = load_project("demo")
    assert saved.timeline[1].type == "persona" and saved.timeline[1].persona == "ana"
    assert saved.overlays[0].start == 2.0 and saved.overlays[0].speech.text == "Olá"
    assert client.post("/api/personas/zzz/use", json={"project": "demo", "text": "x"}).status_code == 404
    assert client.post("/api/personas/ana/use", json={**body, "placement": "x"}).status_code == 400
