"""Rotas /api/dub da interface: preparar, revisar, salvar, traduzir de novo e gerar, tudo como jobs com dublês."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.domain.dub import load_dub_project
from dmaker.ui import server
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.lexicon_store import LexiconStore
from tests.test_dubbing import S1, DubHarness


@pytest.fixture
def dub(tmp_path: Path, monkeypatch) -> DubHarness:
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("dmaker.pipeline.narration.VOICE_CACHE_DIR", tmp_path / "voice-cache")
    return DubHarness(tmp_path / "media")


@pytest.fixture
def client(dub: DubHarness, tmp_path: Path):
    services = VoiceServices(
        library=dub.base.library,
        runner=dub.runner,
        transcriber=dub.base.transcriber,
        synthesizer=dub.synthesizer,
        lexicons=LexiconStore(tmp_path / "assets"),
        isolation=dub.base.isolation,
        prober=dub.base.service.prober,
        translator=dub.translator,
    )
    server.app.dependency_overrides[get_voice_services] = lambda: services
    with TestClient(server.app) as c:
        c.services = services
        yield c
    server.app.dependency_overrides.pop(get_voice_services, None)


def finished(job_id: str):
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 20)
    return job


def prepared(client: TestClient, dub: DubHarness, **body) -> dict:
    response = client.post(
        "/api/dub/prepare",
        json={"path": str(dub.src), "target_language": "en", "source_language": "pt", **body},
    )
    assert response.status_code == 200, response.text
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    return job.result


def dub_folder() -> Path:
    return config.OUTPUT_DIR / "dublagem"


# ---------- preparar ----------


def test_prepare_job_saves_the_project_and_returns_the_segments(client, dub: DubHarness):
    result = prepared(client, dub, glossary=["DMaker"], keep_original_db=-18)
    assert Path(result["project"]) == dub_folder() / "entrevista.en.dub.json"
    assert [s["id"] for s in result["segments"]] == ["s1", "s2", "s3"]
    assert result["segments"][0]["original"] == S1 and result["segments"][0]["text"] == f"EN {S1}"
    assert result["keep_original_db"] == -18 and result["glossary"] == ["DMaker"]
    assert client.get(result["source_url"]).content == b"video"
    assert load_dub_project(Path(result["project"])).translator_model == "tradutor-falso"


def test_prepare_reports_stage_progress_by_sse(client, dub: DubHarness):
    job_id = client.post("/api/dub/prepare", json={"path": str(dub.src), "target_language": "en"}).json()[
        "job_id"
    ]
    finished(job_id)
    labels = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as events:
        for line in events.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["kind"] == "progress":
                    labels.append(event["label"])
    assert labels[0].startswith("Separando") and any(
        label.startswith("Traduzindo a fala") for label in labels
    )


def test_prepare_validates_before_starting_a_job(client, dub: DubHarness, tmp_path: Path):
    before = len(server.jobs.list())
    base = {"path": str(dub.src), "target_language": "en"}
    assert client.post("/api/dub/prepare", json={**base, "path": str(tmp_path / "n.mp4")}).status_code == 404
    same = client.post("/api/dub/prepare", json={**base, "target_language": "pt-BR"})
    assert same.status_code == 400 and "diferente" in same.json()["detail"]
    assert client.post("/api/dub/prepare", json={**base, "voice": "fantasma"}).status_code == 404
    assert client.post("/api/dub/prepare", json={**base, "keep_original_db": 6}).status_code == 422
    assert client.post("/api/dub/prepare", json={**base, "speaker_mode": "coro"}).status_code == 422
    assert client.post("/api/dub/prepare", json={"path": str(dub.src)}).status_code == 422
    assert len(server.jobs.list()) == before


def test_prepare_failure_is_reported_by_the_job(client, dub: DubHarness):
    def broken(*args, **kwargs):
        raise RuntimeError("Não consegui falar com o Ollama em http://x.")

    dub.translator.translate = broken
    response = client.post("/api/dub/prepare", json={"path": str(dub.src), "target_language": "en"})
    job = finished(response.json()["job_id"])
    assert job.status == "error" and "Ollama" in job.error


# ---------- projeto ----------


def test_projects_are_listed_newest_first_and_opened_by_path(client, dub: DubHarness):
    assert client.get("/api/dub/projects").json() == []
    result = prepared(client, dub)
    listed = client.get("/api/dub/projects").json()
    assert listed == [{"path": result["project"], "name": "entrevista.en.dub.json"}]
    opened = client.get("/api/dub/project", params={"path": result["project"]})
    assert opened.status_code == 200 and opened.json()["segments"][2]["id"] == "s3"


def test_update_saves_translations_locks_and_project_options(client, dub: DubHarness):
    result = prepared(client, dub)
    body = {
        "project": result["project"],
        "segments": [
            {"id": "s1", "text": "Hi everyone.", "locked": True},
            {"id": "s2", "text": f"EN {S1}", "locked": False},
        ],
        "keep_original_db": -20,
        "speaker_mode": "single",
        "voice": None,
    }
    response = client.put("/api/dub/project", json=body)
    assert response.status_code == 200, response.text
    saved = load_dub_project(Path(result["project"]))
    assert saved.segment("s1").text == "Hi everyone." and saved.segment("s1").locked
    assert saved.segment("s3").text.startswith("EN ")  # as não enviadas ficam como estão
    assert (saved.keep_original_db, saved.speaker_mode, saved.voice) == (-20.0, "single", None)
    assert response.json()["segments"][0]["text"] == "Hi everyone."


def test_update_rejects_unknown_segments_voices_and_long_texts(client, dub: DubHarness):
    result = prepared(client, dub)
    base = {"project": result["project"], "segments": []}
    unknown = client.put("/api/dub/project", json={**base, "segments": [{"id": "s9", "text": "x"}]})
    assert unknown.status_code == 400 and "s9" in unknown.json()["detail"]
    assert client.put("/api/dub/project", json={**base, "voice": "fantasma"}).status_code == 404
    long = client.put("/api/dub/project", json={**base, "segments": [{"id": "s1", "text": "x" * 3000}]})
    assert long.status_code == 422


def test_only_dub_projects_inside_the_dubbing_folder_can_be_opened(client, dub: DubHarness, tmp_path: Path):
    outside = tmp_path / "fora.dub.json"
    outside.write_text("{}", encoding="utf-8")
    assert client.get("/api/dub/project", params={"path": str(outside)}).status_code == 400
    assert client.get("/api/dub/project", params={"path": str(dub.src)}).status_code == 400
    dub_folder().mkdir(parents=True, exist_ok=True)
    assert (
        client.get("/api/dub/project", params={"path": str(dub_folder() / "x.dub.json")}).status_code == 404
    )
    broken = dub_folder() / "quebrado.dub.json"
    broken.write_text('{"source": "a"}', encoding="utf-8")
    assert client.get("/api/dub/project", params={"path": str(broken)}).status_code == 400
    traversal = str(dub_folder() / ".." / ".." / "fora.dub.json")
    assert client.get("/api/dub/project", params={"path": traversal}).status_code == 400


# ---------- traduzir de novo ----------


def test_retranslate_job_skips_locked_segments(client, dub: DubHarness):
    result = prepared(client, dub)
    client.put(
        "/api/dub/project",
        json={
            "project": result["project"],
            "segments": [{"id": "s2", "text": "Minha tradução.", "locked": True}],
            "speaker_mode": "per_segment",
        },
    )
    dub.translator.replies = {"s1": "Um novo.", "s3": "Três novo."}
    job = finished(client.post("/api/dub/retranslate", json={"project": result["project"]}).json()["job_id"])
    assert job.status == "done", job.error
    assert [s["text"] for s in job.result["segments"]] == ["Um novo.", "Minha tradução.", "Três novo."]
    assert [s.text for s in load_dub_project(Path(result["project"])).segments][1] == "Minha tradução."


# ---------- gerar ----------


def test_render_job_returns_players_downloads_and_the_report(client, dub: DubHarness):
    project = prepared(client, dub)["project"]
    response = client.post("/api/dub/render", json={"project": project})
    assert response.status_code == 200, response.text
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    result = job.result
    assert Path(result["output"]) == dub_folder() / "entrevista.en.mp4"
    assert client.get(result["output_url"]).content == b"corrigido"  # o vídeo dublado toca no <video>
    assert "attachment" in client.get(result["download_url"]).headers.get("content-disposition", "")
    assert client.get(result["original_url"]).content == b"video"
    srt = client.get(result["srt_url"])
    assert srt.status_code == 200 and "EN" in srt.text and "attachment" in srt.headers["content-disposition"]
    assert result["regenerated"] == 3 and result["warnings"] == []
    assert [r["id"] for r in result["report"]] == ["s1", "s2", "s3"]
    assert result["report"][0]["status"] == "advances" and result["report"][0]["cached"] is False
    assert "Síntese das falas" in result["timings"]


def test_render_after_an_edit_regenerates_only_that_segment(client, dub: DubHarness):
    project = prepared(client, dub)["project"]
    finished(client.post("/api/dub/render", json={"project": project}).json()["job_id"])
    client.put(
        "/api/dub/project",
        json={"project": project, "segments": [{"id": "s2", "text": "Pick the right song."}]},
    )
    job = finished(client.post("/api/dub/render", json={"project": project}).json()["job_id"])
    assert job.result["regenerated"] == 1
    assert [r["cached"] for r in job.result["report"]] == [True, False, True]


def test_render_draft_and_progress_by_segment(client, dub: DubHarness):
    project = prepared(client, dub)["project"]
    job_id = client.post("/api/dub/render", json={"project": project, "draft": True}).json()["job_id"]
    finished(job_id)
    assert {r.steps for r in dub.synthesizer.requests} == {8}
    labels = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as events:
        for line in events.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["kind"] == "progress":
                    labels.append(event["label"])
    assert "Sintetizando a fala 2 de 3" in labels


def test_render_reports_warnings_for_speech_that_did_not_fit(client, dub: DubHarness):
    project = prepared(client, dub)["project"]
    long_text = " ".join(["this is much too long to fit"] * 10)
    client.put("/api/dub/project", json={"project": project, "segments": [{"id": "s1", "text": long_text}]})
    job = finished(client.post("/api/dub/render", json={"project": project}).json()["job_id"])
    assert job.status == "done" and job.result["warnings"] and "Fala s1" in job.result["warnings"][0]
    assert job.result["report"][0]["status"] == "overflow"


def test_render_validates_before_starting_a_job(client, dub: DubHarness, tmp_path: Path):
    result = prepared(client, dub)
    path = Path(result["project"])
    before = len(server.jobs.list())
    assert client.post("/api/dub/render", json={"project": str(tmp_path / "x.dub.json")}).status_code == 400
    gone = load_dub_project(path).model_copy(update={"source": str(tmp_path / "sumiu.mp4")})
    path.write_text(gone.model_dump_json(), encoding="utf-8")
    missing = client.post("/api/dub/render", json={"project": str(path)})
    assert missing.status_code == 404 and "origem" in missing.json()["detail"]
    blank = gone.model_copy(
        update={
            "source": str(dub.src),
            "segments": [s.model_copy(update={"text": ""}) for s in gone.segments],
        }
    )
    path.write_text(blank.model_dump_json(), encoding="utf-8")
    assert client.post("/api/dub/render", json={"project": str(path)}).status_code == 400
    assert len(server.jobs.list()) == before


# ---------- arquivos ----------


def test_file_route_only_serves_srt_and_projects_from_the_dubbing_folder(
    client, dub: DubHarness, tmp_path: Path
):
    project = prepared(client, dub)["project"]
    finished(client.post("/api/dub/render", json={"project": project}).json()["job_id"])
    srt = dub_folder() / "entrevista.en.srt"
    assert client.get("/api/dub/file", params={"path": str(srt)}).status_code == 200
    assert client.get("/api/dub/file", params={"path": project}).status_code == 200
    assert (
        client.get("/api/dub/file", params={"path": str(dub_folder() / "entrevista.en.mp4")}).status_code
        == 404
    )
    other = tmp_path / "output" / "x.srt"
    other.write_text("1", encoding="utf-8")
    assert client.get("/api/dub/file", params={"path": str(other)}).status_code == 404
    assert client.get("/api/dub/file", params={"path": str(srt) + ".nada"}).status_code == 404


# ---------- falantes (diarização) ----------


def with_two_people(client, dub: DubHarness):
    from tests.test_dubbing_speakers import TWO_PEOPLE, FakeDiarizer

    client.services.diarizer = FakeDiarizer(TWO_PEOPLE)
    return client.services.diarizer


def test_prepare_job_separates_the_speakers_and_returns_them_with_each_segment(client, dub: DubHarness):
    diarizer = with_two_people(client, dub)
    result = prepared(client, dub, num_speakers=2)
    assert result["speaker_mode"] == "per_speaker" and result["speakers"] == ["Falante 1", "Falante 2"]
    assert [s["speaker"] for s in result["segments"]] == ["Falante 1", "Falante 2", "Falante 1"]
    assert diarizer.calls[0][1] == 2


def test_prepare_validates_the_speaker_count_and_mode(client, dub: DubHarness):
    base = {"path": str(dub.src), "target_language": "en"}
    assert client.post("/api/dub/prepare", json={**base, "num_speakers": 0}).status_code == 422
    assert client.post("/api/dub/prepare", json={**base, "num_speakers": 50}).status_code == 422
    assert client.post("/api/dub/prepare", json={**base, "speaker_mode": "per_speaker"}).status_code == 200


def test_prepare_without_a_diarizer_keeps_the_old_per_segment_default(client, dub: DubHarness):
    result = prepared(client, dub)
    assert result["speaker_mode"] == "per_segment" and result["speakers"] == []


def test_update_swaps_the_speaker_of_one_segment_and_keeps_the_mode(client, dub: DubHarness):
    with_two_people(client, dub)
    result = prepared(client, dub)
    body = {
        "project": result["project"],
        "segments": [{"id": "s3", "text": "EN fixa", "speaker": "Falante 2"}],
    }
    response = client.put("/api/dub/project", json=body)
    assert response.status_code == 200, response.text
    saved = load_dub_project(Path(result["project"]))
    assert [s.speaker for s in saved.segments] == ["Falante 1", "Falante 2", "Falante 2"]
    assert saved.speaker_mode == "per_speaker"  # o corpo não trouxe modo: o do projeto fica
    assert response.json()["segments"][2]["speaker"] == "Falante 2"


def test_update_refuses_a_speaker_the_project_does_not_have(client, dub: DubHarness):
    with_two_people(client, dub)
    result = prepared(client, dub)
    body = {"project": result["project"], "segments": [{"id": "s1", "text": "x", "speaker": "Falante 9"}]}
    response = client.put("/api/dub/project", json=body)
    assert response.status_code == 400 and "Falante 9" in response.json()["detail"]
    assert load_dub_project(Path(result["project"])).segment("s1").speaker == "Falante 1"


def test_render_job_returns_the_speaker_and_voice_of_each_line(client, dub: DubHarness):
    with_two_people(client, dub)
    result = prepared(client, dub)
    job = finished(
        client.post("/api/dub/render", json={"project": result["project"], "draft": True}).json()["job_id"]
    )
    assert job.status == "done", job.error
    report = job.result["report"]
    assert [r["speaker"] for r in report] == ["Falante 1", "Falante 2", "Falante 1"]
    assert report[0]["voice"] == report[2]["voice"] != report[1]["voice"]
