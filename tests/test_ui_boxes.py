"""Rotas do DMK-31 (E1): as caixas das sobreposições, a revisão da spec e a gravação com `If-Match`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.domain.atomic_file import content_revision
from dmaker.media.probe import MediaInfo
from dmaker.ui import server
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.library import VoiceLibrary

PROJECT = "ui-caixas"
SPEC = {
    "output": {"preset": "instagram/reels"},
    "timeline": [{"type": "card", "title": "Interface", "duration": 4.0, "motion": "none"}],
    "overlays": [
        {"type": "text", "text": "Gancho", "role": "hook", "x": 0.5, "y": 0.4, "start": 0, "end": 3},
        {"type": "progress-bar"},
    ],
    "audio": {"normalize": "off"},
}


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c
    folder = config.PROJECTS_DIR / PROJECT
    for f in folder.glob("*"):
        f.unlink()
    if folder.exists():
        folder.rmdir()


def spec_file() -> Path:
    return config.PROJECTS_DIR / PROJECT / "spec.json"


def disk_revision() -> str:
    return content_revision(spec_file().read_bytes())


def edited_from_outside(title: str) -> None:
    """O que o Claude (MCP) ou a CLI fazem: reescrevem o `spec.json` sem passar pela interface."""
    data = json.loads(spec_file().read_text(encoding="utf-8"))
    data["timeline"][0]["title"] = title
    spec_file().write_text(json.dumps(data), encoding="utf-8")


# ---------- revisão ----------


def test_get_returns_the_revision_of_the_file_and_the_revision_route_agrees(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    got = client.get(f"/api/projects/{PROJECT}").json()
    assert got["revision"] == disk_revision()
    assert client.get(f"/api/projects/{PROJECT}/revision").json() == {"revision": got["revision"]}


def test_put_answers_with_the_new_revision_of_what_it_wrote(client):
    first = client.put(f"/api/projects/{PROJECT}", json=SPEC).json()
    assert first["ok"] and first["revision"] == disk_revision()
    changed = dict(SPEC, timeline=[{"type": "card", "title": "Outro", "duration": 4.0, "motion": "none"}])
    second = client.put(f"/api/projects/{PROJECT}", json=changed).json()
    assert second["revision"] == disk_revision() != first["revision"]


def test_the_revision_follows_a_change_made_from_outside(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    before = client.get(f"/api/projects/{PROJECT}/revision").json()["revision"]
    edited_from_outside("Pelo Claude")
    after = client.get(f"/api/projects/{PROJECT}/revision").json()["revision"]
    assert after != before and after == disk_revision()


def test_revision_of_an_unknown_project_is_404(client):
    assert client.get("/api/projects/nao-existe-mesmo/revision").status_code == 404


def test_a_spec_the_schema_refuses_still_comes_with_its_revision(client):
    folder = config.PROJECTS_DIR / PROJECT
    folder.mkdir(parents=True, exist_ok=True)
    spec_file().write_text(json.dumps({"name": PROJECT, "campo_que_nao_existe": 1}), encoding="utf-8")
    resp = client.get(f"/api/projects/{PROJECT}")
    assert resp.status_code == 422
    assert resp.json()["revision"] == disk_revision() and resp.json()["raw_spec"]["campo_que_nao_existe"] == 1


# ---------- gravação com If-Match ----------


def test_put_with_the_current_revision_saves_and_returns_the_next_one(client):
    revision = client.put(f"/api/projects/{PROJECT}", json=SPEC).json()["revision"]
    changed = dict(SPEC, timeline=[{"type": "card", "title": "Meu", "duration": 4.0, "motion": "none"}])
    resp = client.put(f"/api/projects/{PROJECT}", json=changed, headers={"If-Match": revision})
    assert resp.status_code == 200
    assert resp.json()["revision"] == disk_revision() != revision
    assert client.get(f"/api/projects/{PROJECT}").json()["spec"]["timeline"][0]["title"] == "Meu"


def test_put_with_a_stale_revision_is_refused_and_writes_nothing(client):
    stale = client.put(f"/api/projects/{PROJECT}", json=SPEC).json()["revision"]
    edited_from_outside("Pelo Claude")
    on_disk = spec_file().read_bytes()
    mine = dict(SPEC, timeline=[{"type": "card", "title": "Meu", "duration": 4.0, "motion": "none"}])
    resp = client.put(f"/api/projects/{PROJECT}", json=mine, headers={"If-Match": stale})
    assert resp.status_code == 409
    body = resp.json()
    assert body["revision"] == disk_revision() != stale and body["detail"]
    assert spec_file().read_bytes() == on_disk  # nada foi gravado


def test_keeping_mine_after_the_conflict_is_a_put_with_the_revision_the_409_gave(client):
    stale = client.put(f"/api/projects/{PROJECT}", json=SPEC).json()["revision"]
    edited_from_outside("Pelo Claude")
    mine = dict(SPEC, timeline=[{"type": "card", "title": "Meu", "duration": 4.0, "motion": "none"}])
    current = client.put(f"/api/projects/{PROJECT}", json=mine, headers={"If-Match": stale}).json()[
        "revision"
    ]
    assert client.put(f"/api/projects/{PROJECT}", json=mine, headers={"If-Match": current}).status_code == 200
    assert client.get(f"/api/projects/{PROJECT}").json()["spec"]["timeline"][0]["title"] == "Meu"


def test_put_without_the_header_saves_as_before_even_if_the_disk_moved(client):
    """A interface clássica não manda `If-Match` e continua gravando como sempre."""
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    edited_from_outside("Pelo Claude")
    mine = dict(SPEC, timeline=[{"type": "card", "title": "Clássica", "duration": 4.0, "motion": "none"}])
    assert client.put(f"/api/projects/{PROJECT}", json=mine).status_code == 200
    assert client.get(f"/api/projects/{PROJECT}").json()["spec"]["timeline"][0]["title"] == "Clássica"


@pytest.mark.parametrize("wrap", ['"{}"', 'W/"{}"'])
def test_put_accepts_the_revision_as_a_quoted_or_weak_etag(client, wrap):
    revision = client.put(f"/api/projects/{PROJECT}", json=SPEC).json()["revision"]
    resp = client.put(f"/api/projects/{PROJECT}", json=SPEC, headers={"If-Match": wrap.format(revision)})
    assert resp.status_code == 200


def test_put_if_match_for_a_project_that_is_gone_is_a_409_with_no_revision(client):
    resp = client.put("/api/projects/projeto-apagado", json=SPEC, headers={"If-Match": "abc"})
    assert resp.status_code == 409 and resp.json()["revision"] is None
    assert not (config.PROJECTS_DIR / "projeto-apagado").exists()


def test_put_if_match_star_saves_an_existing_project(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    assert client.put(f"/api/projects/{PROJECT}", json=SPEC, headers={"If-Match": "*"}).status_code == 200


def test_an_invalid_spec_is_still_422_before_any_revision_check(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    bad = dict(SPEC, timeline=[{"type": "clip", "src": "x.mp4", "start": 5, "end": 2}])
    assert (
        client.put(f"/api/projects/{PROJECT}", json=bad, headers={"If-Match": "qualquer"}).status_code == 422
    )


# ---------- caixas ----------


@pytest.fixture
def probed(tmp_path):
    """Sonda falsa: toda mídia mede 400x300, e a biblioteca de vozes (que a rota pede) fica em tmp_path."""
    services = VoiceServices(
        library=VoiceLibrary(tmp_path / "voices"),
        prober=lambda path: MediaInfo(path, 5.0, 400, 300, 30.0, True, True, False),
    )
    server.app.dependency_overrides[get_voice_services] = lambda: services
    yield services
    server.app.dependency_overrides.pop(get_voice_services, None)


def test_boxes_of_the_saved_spec(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    body = client.post(f"/api/projects/{PROJECT}/boxes", json={}).json()
    assert (body["width"], body["height"]) == (1080, 1920)
    assert set(body["safe_zone"]) == {"top", "bottom", "left", "right"}
    text, bar = body["boxes"]
    assert (text["index"], text["kind"]) == (0, "text") and text["anchor"] == {"x": 0.5, "y": 0.4}
    assert text["movable"] and text["resize"] == "text_width" and text["wrap"]["width"] == pytest.approx(0.86)
    assert (bar["index"], bar["kind"]) == (1, "progress-bar") and not bar["movable"] and bar["locked_reason"]


def test_boxes_accepts_no_body_at_all(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    assert client.post(f"/api/projects/{PROJECT}/boxes").status_code == 200


def test_boxes_of_the_spec_in_the_body_ignore_the_disk(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    moved = json.loads(json.dumps(SPEC))
    moved["overlays"][0].update(x=0.25, y=0.6)
    body = client.post(f"/api/projects/{PROJECT}/boxes", json={"spec": moved}).json()
    assert body["boxes"][0]["anchor"] == {"x": 0.25, "y": 0.6}
    on_disk = client.post(f"/api/projects/{PROJECT}/boxes", json={}).json()
    assert on_disk["boxes"][0]["anchor"] == {"x": 0.5, "y": 0.4}


def test_boxes_flag_the_sides_that_leave_the_safe_zone(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    low = json.loads(json.dumps(SPEC))
    low["overlays"][0].update(x=0.5, y=0.99)
    box = client.post(f"/api/projects/{PROJECT}/boxes", json={"spec": low}).json()["boxes"][0]
    assert "bottom" in box["outside_safe_zone"]


def test_boxes_use_the_injected_prober_for_image_and_pip(client, probed, tmp_path):
    folder = config.PROJECTS_DIR / PROJECT
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "foto.png").write_bytes(b"x")
    (folder / "cam.mp4").write_bytes(b"x")
    spec = json.loads(json.dumps(SPEC))
    spec["overlays"] = [
        {"type": "image", "src": "foto.png", "x": 0.5, "y": 0.5, "width": 0.4},
        {"type": "video", "src": "cam.mp4", "x": 0.5, "y": 0.2, "width": 0.3},
        {"type": "image", "src": "sumiu.png", "x": 0.5, "y": 0.5},
    ]
    boxes = client.post(f"/api/projects/{PROJECT}/boxes", json={"spec": spec}).json()["boxes"]
    image, pip, missing = boxes
    assert image["width"] == pytest.approx(0.4, abs=0.001) and image["height"] == pytest.approx(
        324 / 1920, abs=0.001
    )
    assert pip["kind"] == "video" and pip["width"] == pytest.approx(0.3, abs=0.001)
    assert missing["left"] is None and not missing["movable"] and "sumiu.png" in missing["locked_reason"]


def test_boxes_errors(client):
    assert client.post("/api/projects/nao-existe-mesmo/boxes", json={}).status_code == 404
    bad = dict(SPEC, timeline=[{"type": "clip", "src": "x.mp4", "start": 5, "end": 2}])
    assert client.post(f"/api/projects/{PROJECT}/boxes", json={"spec": bad}).status_code == 400
    odd = dict(SPEC, output={"preset": "nao/existe"})
    assert client.post(f"/api/projects/{PROJECT}/boxes", json={"spec": odd}).status_code in (400, 422)
