"""Rotas /api/speech da interface: enviar arquivo, isolar voz, listar palavras e corrigir uma fala, como jobs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.isolation import IsolationService
from dmaker.ui import server
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.lexicon_store import LexiconStore
from tests.test_isolation import FakeSeparator, write_wav_output
from tests.test_speech_fix import Harness


@pytest.fixture
def harness(tmp_path: Path, monkeypatch) -> Harness:
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("dmaker.pipeline.narration.VOICE_CACHE_DIR", tmp_path / "voice-cache")
    return Harness(tmp_path / "media")


@pytest.fixture
def client(harness: Harness, tmp_path: Path):
    services = VoiceServices(
        library=harness.library,
        runner=harness.runner,
        transcriber=harness.transcriber,
        synthesizer=harness.synthesizer,
        lexicons=LexiconStore(tmp_path / "assets"),
        isolation=harness.isolation,
        prober=harness.service.prober,
    )
    server.app.dependency_overrides[get_voice_services] = lambda: services
    with TestClient(server.app) as c:
        c.services = services
        yield c
    server.app.dependency_overrides.pop(get_voice_services, None)


def finished(job_id: str):
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 15)
    return job


def post_fix(client: TestClient, harness: Harness, **body):
    payload = {"path": str(harness.src), "find": "João", "text": "Pedro", **body}
    return client.post("/api/speech/fix", json=payload)


# ---------- envio ----------


def test_upload_saves_the_media_under_cache_and_the_same_content_keeps_the_path(client, tmp_path: Path):
    first = client.post(
        "/api/speech/upload", files={"file": ("Minha Entrevista.mp4", b"video-bytes", "video/mp4")}
    )
    assert first.status_code == 200, first.text
    path = Path(first.json()["path"])
    assert path.read_bytes() == b"video-bytes" and path.parent == config.CACHE_DIR / "uploads"
    assert path.name.endswith("-Minha-Entrevista.mp4")
    again = client.post(
        "/api/speech/upload", files={"file": ("Minha Entrevista.mp4", b"video-bytes", "video/mp4")}
    )
    assert again.json()["path"] == first.json()["path"]
    assert list((config.CACHE_DIR / "uploads").glob(".*.part")) == []


def test_upload_rejects_an_empty_file(client):
    empty = client.post("/api/speech/upload", files={"file": ("vazio.wav", b"", "audio/wav")})
    assert empty.status_code == 400 and "vazio" in empty.json()["detail"]


# ---------- isolar voz ----------


def test_isolate_runs_as_a_job_and_returns_playable_stems(client, harness: Harness, tmp_path: Path):
    separator = FakeSeparator()
    client.services.isolation = IsolationService(
        separator, RecordingRunner(on_run=write_wav_output), cache_dir=tmp_path / "stems"
    )
    response = client.post(
        "/api/speech/isolate", json={"path": str(harness.src), "start": 5, "end": 25, "format": "wav"}
    )
    assert response.status_code == 200, response.text
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    result = job.result
    assert Path(result["voice"]).name == "entrevista_5-25s_voz.wav"
    assert Path(result["voice"]).parent == config.OUTPUT_DIR / "isolamento"
    assert client.get(result["voice_url"]).content == b"voz"
    assert client.get(result["background_url"]).content == b"fundo"
    assert job.progress["label"] == "bloco 2 de 2"
    assert len(separator.calls) == 1


def test_isolate_validates_before_starting_a_job(client, harness: Harness, tmp_path: Path):
    before = len(server.jobs.list())
    missing = client.post("/api/speech/isolate", json={"path": str(tmp_path / "nada.mp4")})
    assert missing.status_code == 404 and "não encontrado" in missing.json()["detail"]
    backwards = client.post("/api/speech/isolate", json={"path": str(harness.src), "start": 9, "end": 3})
    assert backwards.status_code == 400
    assert (
        client.post("/api/speech/isolate", json={"path": str(harness.src), "format": "ogg"}).status_code
        == 422
    )
    assert client.post("/api/speech/isolate", json={"path": str(harness.src), "start": -1}).status_code == 422
    assert len(server.jobs.list()) == before


# ---------- palavras ----------


def test_words_job_returns_the_words_with_times(client, harness: Harness):
    response = client.post("/api/speech/words", json={"path": str(harness.src)})
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    words = job.result["words"]
    assert {"start": 21.8, "end": 22.2, "text": "João"} in words
    assert job.result["pause_seconds"] == 0.25
    assert client.post("/api/speech/words", json={"path": "/nada.mp4"}).status_code == 404


# ---------- corrigir fala ----------


def test_fix_job_returns_original_and_corrected_players_and_the_decisions(client, harness: Harness):
    response = post_fix(client, harness)
    assert response.status_code == 200, response.text
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    result = job.result
    assert Path(result["output"]).parent == config.OUTPUT_DIR / "correcao"
    assert Path(result["output"]).name.startswith("entrevista.corrigido-") and result["output"].endswith(
        ".mp4"
    )
    assert client.get(result["audio_url"]).content == b"corrigido"  # o vídeo corrigido toca no <audio>
    assert client.get(result["original_url"]).content == b"video"
    assert result["old_text"] == "João" and result["new_text"] == "Pedro"
    assert result["spoken"] == "de Pedro e Maria." and "mantida" in result["rule"]
    assert result["region"][0] < 21.7 < 22.9 < result["region"][1]
    assert result["squeezed"] is False and result["voice"].startswith("falante-")


def test_fix_job_reports_stage_progress_by_sse(client, harness: Harness):
    job_id = post_fix(client, harness).json()["job_id"]
    finished(job_id)
    labels = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as events:
        for line in events.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["kind"] == "progress":
                    labels.append(event["label"])
    assert labels[0].startswith("Transcrevendo") and any(label.startswith("Sintetizando") for label in labels)


def test_fix_by_time_draft_and_without_expansion(client, harness: Harness):
    body = {"find": None, "start": 21.8, "end": 22.2, "expand": False, "draft": True}
    job = finished(post_fix(client, harness, **body).json()["job_id"])
    assert job.status == "done", job.error
    request = harness.synthesizer.requests[0]
    assert request.text == "Pedro" and request.steps == 8


def test_different_texts_do_not_overwrite_each_others_output(client, harness: Harness):
    outputs = {
        finished(post_fix(client, harness, text=text).json()["job_id"]).result["output"]
        for text in ("Pedro", "Paulo")
    }
    assert len(outputs) == 2


def test_fix_validates_before_starting_a_job(client, harness: Harness, tmp_path: Path):
    before = len(server.jobs.list())
    assert client.post("/api/speech/fix", json={"path": str(harness.src), "text": "x"}).status_code == 400
    both = post_fix(client, harness, start=1, end=2)
    assert both.status_code == 400 and "texto (find) ou por tempo" in both.json()["detail"]
    assert post_fix(client, harness, text="  ").status_code == 400
    assert post_fix(client, harness, voice="fantasma").status_code == 404
    assert post_fix(client, harness, text="x" * 3000).status_code == 422
    missing = client.post("/api/speech/fix", json={"path": str(tmp_path / "n.mp4"), "find": "a", "text": "b"})
    assert missing.status_code == 404
    assert len(server.jobs.list()) == before


def test_fix_failure_is_reported_by_the_job(client, harness: Harness):
    job = finished(post_fix(client, harness, find="Joana").json()["job_id"])
    assert job.status == "error" and "Não achei" in job.error


def test_fix_with_an_unreadable_media_file_is_a_400_before_any_job(client, harness: Harness):
    def broken(path):
        raise RuntimeError("ffprobe falhou")

    client.services.prober = broken
    before = len(server.jobs.list())
    response = post_fix(client, harness)
    assert response.status_code == 400 and "Não consegui ler" in response.json()["detail"]
    assert len(server.jobs.list()) == before
