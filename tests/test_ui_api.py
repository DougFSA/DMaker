"""API da interface: projetos, validação, legendas, navegação de arquivos, jobs com SSE."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.ui import server

from .conftest import requires_ffmpeg

PROJECT = "ui-teste"
SPEC = {
    "output": {"preset": "instagram/stories"},
    "brand": "medlycare",
    "timeline": [{"type": "card", "title": "Interface", "duration": 1.0, "motion": "none"}],
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


def test_state_and_schema(client):
    state = client.get("/api/state").json()
    assert state["version"] and any(p["id"] == "instagram/reels" for p in state["presets"])
    assert any(b["key"] == "medlycare" for b in state["brands"])
    assert "timeline" in client.get("/api/schema").json()["properties"]


def test_project_roundtrip_and_validation(client):
    assert client.put(f"/api/projects/{PROJECT}", json=SPEC).json()["ok"]
    got = client.get(f"/api/projects/{PROJECT}").json()
    assert got["spec"]["timeline"][0]["title"] == "Interface" and got["outputs"] == []
    summary = client.post(f"/api/projects/{PROJECT}/validate").json()
    assert summary["total_s"] == 1.0 and summary["preset"] == "instagram/stories"
    assert any(p["name"] == PROJECT for p in client.get("/api/projects").json())

    bad = dict(SPEC, timeline=[{"type": "clip", "src": "x.mp4", "start": 5, "end": 2}])
    resp = client.put(f"/api/projects/{PROJECT}", json=bad)
    assert resp.status_code == 422 and "end" in json.dumps(resp.json())
    assert client.get("/api/projects/nao-existe").status_code == 404


def test_list_templates_endpoint(client):
    templates = client.get("/api/templates").json()
    assert len(templates) >= 4
    names = {t["name"] for t in templates}
    assert "stories-medlycare" in names
    stories = next(t for t in templates if t["name"] == "stories-medlycare")
    assert stories["params"]["print"]["required"] is True
    assert stories["params"]["titulo"]["required"] is False


def test_create_project_from_template_endpoint(client):
    name = "ui-teste-template"
    resp = client.post(
        "/api/projects",
        json={"name": name, "template": "stories-medlycare", "params": {"print": "D:/fake/print.png"}},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == name
    assert data["spec"]["timeline"][0]["src"] == "D:/fake/print.png"
    assert data["spec"]["overlays"][0]["text"] == "Chegou sem hora marcada?"  # default de "titulo"

    folder = config.PROJECTS_DIR / name
    for f in folder.glob("*"):
        f.unlink()
    folder.rmdir()


def test_create_project_from_template_missing_required_param_returns_400(client):
    resp = client.post(
        "/api/projects",
        json={"name": "ui-teste-template-erro", "template": "stories-medlycare", "params": {}},
    )
    assert resp.status_code == 400
    assert "print" in resp.json()["detail"]
    assert not (config.PROJECTS_DIR / "ui-teste-template-erro").exists()


def test_captions_read_and_update(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    store = config.PROJECTS_DIR / PROJECT / "captions.auto.json"
    store.write_text(
        json.dumps(
            {"language": "pt", "hash": "abc", "cues": [{"start": 0, "end": 1, "text": "ola", "words": []}]}
        ),
        encoding="utf-8",
    )
    assert client.get(f"/api/projects/{PROJECT}/captions").json()["cues"][0]["text"] == "ola"
    resp = client.put(
        f"/api/projects/{PROJECT}/captions",
        json={"cues": [{"start": 0, "end": 1, "text": "olá, tudo bem", "words": []}]},
    )
    assert resp.json()["cues"] == 1
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["cues"][0]["text"] == "olá, tudo bem" and saved["hash"] == "abc"
    assert "olá, tudo bem" in store.with_suffix(".srt").read_text(encoding="utf-8")


def test_timeline_view_endpoint(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    view = client.post(f"/api/projects/{PROJECT}/timeline", json={}).json()
    v1 = next(t for t in view["tracks"] if t["id"] == "V1")
    assert v1["items"][0]["kind"] == "card"

    view_from_body = client.post(f"/api/projects/{PROJECT}/timeline", json={"spec": SPEC}).json()
    assert view_from_body["total"] == view["total"] == 1.0

    bad = dict(SPEC, timeline=[{"type": "clip", "src": "x.mp4", "start": 5, "end": 2}])
    resp = client.post(f"/api/projects/{PROJECT}/timeline", json={"spec": bad})
    assert resp.status_code == 400


def test_edit_split_card_endpoint(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    resp = client.post(
        f"/api/projects/{PROJECT}/edit",
        json={"spec": SPEC, "op": {"type": "split", "index": 0, "at": 0.5}},
    )
    body = resp.json()
    assert len(body["spec"]["timeline"]) == 2
    v1 = next(t for t in body["timeline"]["tracks"] if t["id"] == "V1")
    assert len(v1["items"]) == 2

    bad_op = client.post(
        f"/api/projects/{PROJECT}/edit", json={"spec": SPEC, "op": {"type": "remove", "index": 0}}
    )
    assert bad_op.status_code == 400  # não pode remover o único trecho


def test_theme_endpoint(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    theme = client.get(f"/api/projects/{PROJECT}/theme").json()
    assert theme["colors"]["accent"] and theme["font"] == "Poppins"
    assert theme["no_dash"] is True  # regra da marca MedlyCare
    assert client.get("/api/projects/nao-existe/theme").status_code == 404


def test_card_preview_endpoint(client):
    import hashlib

    params = {"title": "Interface de teste do card-preview", "brand": "medlycare", "width": 200}
    resp = client.get("/api/card-preview", params=params)
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"

    key = "|".join([params["title"], "", "", "True", "", "medlycare", "instagram/reels", "200"])
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    cached = config.CACHE_DIR / "cards" / f"{digest}.png"
    assert cached.is_file()
    mtime_before = cached.stat().st_mtime_ns

    again = client.get("/api/card-preview", params=params)
    assert again.status_code == 200
    assert cached.stat().st_mtime_ns == mtime_before  # mesmos parâmetros -> reaproveita o cache

    assert client.get("/api/card-preview", params={"title": "x", "preset": "nao-existe"}).status_code == 404
    assert client.get("/api/card-preview").status_code == 422  # title é obrigatório


def test_browse_and_file_restrictions(client, tmp_path):
    root = client.get("/api/browse").json()
    assert root["dirs"] and root["parent"] is None
    listing = client.get(
        "/api/browse", params={"path": str(config.ROOT / "assets" / "brands" / "medlycare")}
    ).json()
    assert any(f["name"] == "lockup-horizontal.png" for f in listing["files"])
    ok = client.get(
        "/api/file",
        params={"path": str(config.ROOT / "assets" / "brands" / "medlycare" / "lockup-horizontal.png")},
    )
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    secret = tmp_path / "segredo.txt"
    secret.write_text("x")
    assert (
        client.get("/api/file", params={"path": str(secret)}).status_code == 404
    )  # fora da raiz e não é mídia


def test_job_events_stream(client):
    def work(job):
        job.log("etapa 1")
        sink = job.sink()
        sink.start("trecho 1/1", 2.0)
        sink.update(1.0)
        sink.finish()
        return {"ok": True}

    job = server.jobs.start("teste", work)
    server.jobs.wait(job, 5)
    kinds = []
    with client.stream("GET", f"/api/jobs/{job.id}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                kinds.append(event["kind"])
                if event["kind"] == "end":
                    assert event["status"] == "done" and event["result"] == {"ok": True}
    assert kinds[0] == "start" and "log" in kinds and "progress" in kinds and kinds[-1] == "end"
    assert client.get(f"/api/jobs/{job.id}").json()["progress"]["percent"] == 100
    assert client.get("/api/jobs/zzz").status_code == 404


def test_clients_ping_and_status(client):
    assert client.get("/api/clients").json()["active"] is False
    assert client.post("/api/clients/ping").json()["ok"] is True
    assert client.get("/api/clients").json()["active"] is True


def test_clients_status_expires_with_clock(client, monkeypatch):
    import time as time_module

    client.post("/api/clients/ping")
    assert client.get("/api/clients").json()["active"] is True
    later = time_module.time() + 3600
    monkeypatch.setattr(server.time, "time", lambda: later)
    assert client.get("/api/clients").json()["active"] is False


def test_render_with_focus_appears_in_job_snapshot(client, monkeypatch):
    # dublê sem ffmpeg: só interessa aqui se focus/project chegam ao snapshot do job
    monkeypatch.setattr(server, "_run_render", lambda job, name, req, preset=None: {"ok": True})
    client.put(f"/api/projects/{PROJECT}", json=SPEC)

    job_id = client.post(f"/api/projects/{PROJECT}/render", json={"preview": True, "focus": True}).json()[
        "job_id"
    ]
    server.jobs.wait(server.jobs.get(job_id), 5)
    snapshot = client.get(f"/api/jobs/{job_id}").json()
    assert snapshot["focus"] is True and snapshot["project"] == PROJECT and snapshot["status"] == "done"

    job_id_default = client.post(f"/api/projects/{PROJECT}/render", json={"preview": True}).json()["job_id"]
    server.jobs.wait(server.jobs.get(job_id_default), 5)
    assert client.get(f"/api/jobs/{job_id_default}").json()["focus"] is False


@requires_ffmpeg
def test_render_preview_via_api(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    job_id = client.post(f"/api/projects/{PROJECT}/render", json={"preview": True}).json()["job_id"]
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 120)
    assert job.status == "done", job.error
    assert job.result["duration_s"] == 1.0 and job.result["output_url"].startswith("/api/file?path=")
    video = client.get(job.result["output_url"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    outputs = client.get(f"/api/projects/{PROJECT}").json()["outputs"]
    assert outputs and outputs[0]["kind"] == "preview"
    sheet = client.post(
        "/api/qa/sheet", json={"video": job.result["output"], "cols": 2, "rows": 1, "width": 120}
    ).json()
    assert client.get(sheet["url"]).status_code == 200
    for f in config.OUTPUT_DIR.glob(f"{PROJECT}__*"):
        f.unlink()


def test_qa_endpoint(client):
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    result = client.post(f"/api/projects/{PROJECT}/qa").json()
    assert "Checagens feitas" in result["text"]
    assert result["project"] == PROJECT
    assert client.post("/api/projects/nao-existe/qa").status_code == 404
