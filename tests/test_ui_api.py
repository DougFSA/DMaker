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
