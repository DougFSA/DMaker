"""API da interface: projetos, validação, legendas, navegação de arquivos, jobs com SSE."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.text.captions import Cue
from dmaker.text.transcribe import Transcript
from dmaker.ui import server
from dmaker.ui.layouts import LayoutStore
from dmaker.ui.voice_routes import VoiceServices, get_voice_services
from dmaker.voice.lexicon_store import LexiconStore
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.synth import Speech, VoiceRequest

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


def test_state_includes_build_id_and_running_jobs(client):
    assert client.get("/api/state").json()["build_id"] == server.SERVER_BUILD_ID
    assert client.get("/api/state").json()["running_jobs"] == 0

    gate = threading.Event()
    job = server.jobs.start("bloqueado", lambda job: gate.wait(5))
    try:
        assert client.get("/api/state").json()["running_jobs"] == 1
    finally:
        gate.set()
        server.jobs.wait(job, 5)


def test_shutdown_refuses_while_a_job_is_running(client):
    gate = threading.Event()
    job = server.jobs.start("bloqueado", lambda job: gate.wait(5))
    try:
        resp = client.post("/api/shutdown")
        assert resp.status_code == 409
    finally:
        gate.set()
        server.jobs.wait(job, 5)


def test_clear_finished_jobs_endpoint(client):
    server.jobs.wait(server.jobs.start("j1", lambda job: None), timeout=5)
    server.jobs.wait(server.jobs.start("j2", lambda job: None), timeout=5)
    removed = client.delete("/api/jobs/finished").json()["removed"]
    assert removed >= 2
    assert client.delete("/api/jobs/finished").json()["removed"] == 0


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


def test_get_project_with_invalid_spec_returns_422_with_raw_spec(client):
    """Simula um servidor com código antigo lendo uma spec com um campo que ele não conhece: a
    interface precisa do JSON cru para mostrar na aba JSON em vez de travar ao abrir o projeto."""
    client.put(f"/api/projects/{PROJECT}", json=SPEC)
    spec_path = config.PROJECTS_DIR / PROJECT / "spec.json"
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    raw["campo_que_este_schema_nao_conhece"] = True
    spec_path.write_text(json.dumps(raw), encoding="utf-8")

    resp = client.get(f"/api/projects/{PROJECT}")
    assert resp.status_code == 422
    body = resp.json()
    assert body["raw_spec"] == raw
    assert any("campo_que_este_schema_nao_conhece" in d.get("loc", "") for d in body["detail"])


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


# ---------- estúdio de voz ----------


class FakeTranscriber:
    """Devolve sempre o mesmo texto e guarda as chamadas, no lugar do Whisper."""

    def __init__(self, text: str = "texto transcrito da gravação"):
        self.text = text
        self.calls: list[Path] = []

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        self.calls.append(wav)
        return Transcript([Cue(0.0, 2.0, self.text)])


class FakeSynthesizer:
    """Seno com 0,05 s por caractere, no lugar do OmniVoice (que leva minutos para carregar)."""

    engine_id = "fake-ui"

    def __init__(self):
        self.requests: list[VoiceRequest] = []

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.requests.append(request)
        count = int(len(request.text) * 0.05 * 24000)
        samples = (0.3 * np.sin(2 * np.pi * 440 * np.arange(count) / 24000)).astype(np.float32)
        return Speech(samples, 24000)


def _write_last_argument(command) -> None:
    """Simula o ffmpeg criando o arquivo de saída, que é sempre o último argumento."""
    Path(command.args[-1]).write_bytes(b"audio")


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """Biblioteca, saída e cache de voz em tmp_path, com transcritor, sintetizador e ffmpeg falsos."""
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "voice-cache"
    monkeypatch.setattr(config, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", cache_dir)
    monkeypatch.setattr("dmaker.pipeline.narration.VOICE_CACHE_DIR", cache_dir)
    (tmp_path / "assets" / "brands" / "medlycare").mkdir(parents=True)
    services = VoiceServices(
        library=VoiceLibrary(tmp_path / "voices"),
        runner=RecordingRunner(on_run=_write_last_argument),
        transcriber=FakeTranscriber(),
        synthesizer=FakeSynthesizer(),
        lexicons=LexiconStore(tmp_path / "assets"),
    )
    server.app.dependency_overrides[get_voice_services] = lambda: services
    yield services
    server.app.dependency_overrides.pop(get_voice_services, None)


@pytest.fixture
def voice_client(studio):
    with TestClient(server.app) as c:
        yield c


def _wait_for_job(job_id: str):
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 10)
    return job


def _stored_voices(client, **params):
    """Vozes gravadas em disco: a lista da API também traz as vozes prontas embutidas (kind preset)."""
    return [v for v in client.get("/api/voices", params=params).json() if v["kind"] != "preset"]


def test_list_voices_filters_by_brand(voice_client, studio):
    assert _stored_voices(voice_client) == []
    studio.library.save_design("Da marca", "female", brand="medlycare")
    studio.library.save_design("De outra", "male", brand="outra")
    studio.library.save_design("Livre", "elderly")

    everything = _stored_voices(voice_client)
    assert {v["id"] for v in everything} == {"da-marca", "de-outra", "livre"}
    assert everything[0]["kind"] == "design" and "instruct" in everything[0]

    brand_only = _stored_voices(voice_client, brand="medlycare")
    assert {v["id"] for v in brand_only} == {"da-marca", "livre"}  # as sem marca servem para qualquer uma


def test_design_options_expose_vocabulary_for_the_selects(voice_client):
    options = voice_client.get("/api/voices/design-options").json()
    assert {"value": "female", "label": "feminino"} in options["gender"]
    assert {"value": "child", "label": "criança"} in options["age"]
    assert {"value": "very low pitch", "label": "muito grave"} in options["pitch"]
    assert {"value": "british accent", "label": "britânico"} in options["accent"]
    assert {"value": "pt", "label": "Português"} in options["languages"]


def test_clone_with_upload_converts_reference_and_uses_given_text(voice_client, studio):
    resp = voice_client.post(
        "/api/voices/clone",
        data={"name": "Ana Júlia", "reference_text": "texto dado", "brand": "medlycare", "language": "pt"},
        files={"audio": ("gravacao.webm", b"bytes-do-webm", "audio/webm")},
    )
    assert resp.status_code == 200, resp.text
    voice = resp.json()
    assert voice["id"] == "ana-julia" and voice["kind"] == "clone" and voice["brand"] == "medlycare"
    assert voice["reference_text"] == "texto dado"
    assert studio.transcriber.calls == []  # com o texto informado, o Whisper não é chamado

    command = studio.runner.commands[0]
    assert any(
        arg.endswith("referencia.webm") for arg in command
    )  # o ffmpeg lê o formato gravado no navegador
    assert (studio.library.root / "ana-julia" / "reference.wav").exists()
    assert [v["id"] for v in _stored_voices(voice_client)] == ["ana-julia"]


def test_clone_without_text_transcribes_the_reference(voice_client, studio):
    resp = voice_client.post(
        "/api/voices/clone",
        data={"name": "Sem Texto"},
        files={"audio": ("voz.mp3", b"mp3", "audio/mpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reference_text"] == "texto transcrito da gravação"
    assert len(studio.transcriber.calls) == 1


def test_clone_rejects_empty_upload_and_duplicate_name(voice_client, studio):
    empty = voice_client.post(
        "/api/voices/clone", data={"name": "Vazia"}, files={"audio": ("v.wav", b"", "audio/wav")}
    )
    assert empty.status_code == 400 and "vazio" in empty.json()["detail"]

    form = {"name": "Repetida", "reference_text": "a"}
    first = voice_client.post("/api/voices/clone", data=form, files={"audio": ("v.wav", b"x", "audio/wav")})
    assert first.status_code == 200
    again = voice_client.post("/api/voices/clone", data=form, files={"audio": ("v.wav", b"x", "audio/wav")})
    assert again.status_code == 400 and "Já existe" in again.json()["detail"]


def test_design_voice_from_attributes_and_validation_errors(voice_client):
    resp = voice_client.post(
        "/api/voices/design",
        json={"name": "Locutora", "gender": "feminino", "pitch": "grave", "language": "pt"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["instruct"] == "female, low pitch" and resp.json()["kind"] == "design"

    free = voice_client.post("/api/voices/design", json={"name": "Livre", "instruct": "male, elderly"})
    assert free.json()["instruct"] == "male, elderly"

    invalid = voice_client.post("/api/voices/design", json={"name": "Estranha", "gender": "robô"})
    assert invalid.status_code == 400 and "Gênero inválido" in invalid.json()["detail"]
    empty = voice_client.post("/api/voices/design", json={"name": "Vazia"})
    assert empty.status_code == 400 and "pelo menos um atributo" in empty.json()["detail"]


def test_remove_voice_and_unknown_or_malicious_ids(voice_client, studio):
    studio.library.save_design("Sai logo", "female")
    assert voice_client.delete("/api/voices/sai-logo").json() == {"ok": True}
    assert _stored_voices(voice_client) == []

    assert voice_client.delete("/api/voices/fantasma").status_code == 404
    assert voice_client.delete("/api/voices/..").status_code == 404
    assert voice_client.delete("/api/voices/%2E%2E").status_code == 404


def test_speak_returns_job_with_sse_progress_and_result_path(voice_client, studio):
    studio.library.save_design("Locutora", "female")
    resp = voice_client.post(
        "/api/voices/speak",
        json={"text": "Primeira fala.\n\nSegunda fala.", "voice": "locutora", "speed": 1.1, "seed": 7},
    )
    assert resp.status_code == 200, resp.text
    job = _wait_for_job(resp.json()["job_id"])
    assert job.status == "done", job.error

    result = job.result
    assert Path(result["output"]).exists() and Path(result["output"]).parent == config.OUTPUT_DIR
    assert result["audio_url"].startswith("/api/voices/audio?path=")
    assert len(result["cues"]) == 2 and result["duration_s"] > 0
    request = studio.synthesizer.requests[0]
    assert request.speed == 1.1 and request.seed == 7 and request.voice.id == "locutora"

    labels = []
    with voice_client.stream("GET", f"/api/jobs/{job.id}/events") as events:
        for line in events.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["kind"] == "progress":
                    labels.append(event["label"])
    assert labels == ["fala 1 de 2", "fala 2 de 2"]

    audio = voice_client.get(result["audio_url"])
    assert audio.status_code == 200 and audio.content == b"audio"
    download = voice_client.get(result["audio_url"] + "&download=true")
    assert "attachment" in download.headers["content-disposition"]


def test_speak_validates_text_voice_and_speed_before_starting_a_job(voice_client, studio):
    before = len(server.jobs.list())
    assert voice_client.post("/api/voices/speak", json={"text": "   "}).status_code == 400
    unknown = voice_client.post("/api/voices/speak", json={"text": "Oi", "voice": "fantasma"})
    assert unknown.status_code == 404
    assert voice_client.post("/api/voices/speak", json={"text": "Oi", "speed": 9}).status_code == 422
    assert len(server.jobs.list()) == before


def test_different_voices_do_not_overwrite_each_others_narration_file(voice_client, studio):
    studio.library.save_design("Uma", "female")
    studio.library.save_design("Outra", "male")
    outputs = set()
    for voice in ("uma", "outra"):
        body = {"text": "Mesmo texto.", "voice": voice}
        job_id = voice_client.post("/api/voices/speak", json=body).json()["job_id"]
        outputs.add(_wait_for_job(job_id).result["output"])
    assert len(outputs) == 2


def test_voice_preview_is_a_job_that_speaks_the_sample_text(voice_client, studio):
    studio.library.save_design("Locutora", "female")
    resp = voice_client.post("/api/voices/locutora/preview")
    job = _wait_for_job(resp.json()["job_id"])
    assert job.status == "done", job.error
    assert Path(job.result["output"]).name == "voz-locutora-amostra.wav"
    assert studio.synthesizer.requests[0].text.startswith("Olá, esta é a minha voz")
    assert voice_client.post("/api/voices/fantasma/preview").status_code == 404


def test_speech_job_failure_reports_the_error(voice_client, studio):
    def broken(request):
        raise RuntimeError("modelo indisponível")

    studio.synthesizer.synthesize = broken
    job = _wait_for_job(voice_client.post("/api/voices/speak", json={"text": "Oi."}).json()["job_id"])
    assert job.status == "error" and "modelo indisponível" in job.error


def test_audio_endpoint_refuses_paths_outside_output_and_voice_cache(voice_client, studio, tmp_path):
    inside = config.OUTPUT_DIR / "ok.wav"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"ok")
    cached = config.VOICE_CACHE_DIR / "fala.wav"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cache")
    outside = tmp_path / "fora.wav"
    outside.write_bytes(b"secreto")
    not_audio = config.OUTPUT_DIR / "notas.txt"
    not_audio.write_text("x")

    assert voice_client.get("/api/voices/audio", params={"path": str(inside)}).content == b"ok"
    assert voice_client.get("/api/voices/audio", params={"path": str(cached)}).content == b"cache"
    assert voice_client.get("/api/voices/audio", params={"path": str(outside)}).status_code == 404
    assert voice_client.get("/api/voices/audio", params={"path": str(not_audio)}).status_code == 404
    traversal = config.OUTPUT_DIR / ".." / "fora.wav"
    assert voice_client.get("/api/voices/audio", params={"path": str(traversal)}).status_code == 404
    missing = config.OUTPUT_DIR / "nao-existe.wav"
    assert voice_client.get("/api/voices/audio", params={"path": str(missing)}).status_code == 404


def test_layout_accepts_voice_panel_and_known_tab_only(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "layout_store", LayoutStore(tmp_path / "layouts.json"))
    with TestClient(server.app) as c:
        layout = {"version": 1, "areas": {}, "sizes": {}, "hidden": ["voice"], "tab": "voice"}
        assert c.put("/api/layouts/Voz", json=layout).status_code == 200
        assert c.get("/api/layouts").json()["layouts"]["Voz"]["tab"] == "voice"
        assert c.put("/api/layouts/Ruim", json={**layout, "tab": "sofa"}).status_code == 400


def test_pronunciation_crud_with_brand_scope(voice_client):
    assert voice_client.get("/api/voices/pronunciation").json() == {"brand": None, "entries": []}

    first = voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Meiker"})
    assert first.status_code == 200, first.text
    assert first.json()["entries"] == [
        {"term": "DMaker", "spoken": "Di Meiker", "scope": "global", "language": "pt"}
    ]

    voice_client.post(
        "/api/voices/pronunciation", json={"term": "dmaker", "spoken": "Dimêiker", "brand": "medlycare"}
    )
    voice_client.post("/api/voices/pronunciation", json={"term": "API", "spoken": "êi-pi-ai"})

    global_only = voice_client.get("/api/voices/pronunciation").json()["entries"]
    assert [(e["term"], e["scope"]) for e in global_only] == [("API", "global"), ("DMaker", "global")]
    branded = voice_client.get("/api/voices/pronunciation", params={"brand": "medlycare"}).json()["entries"]
    assert branded == [
        {"term": "API", "spoken": "êi-pi-ai", "scope": "global", "language": "pt"},  # herdado
        {"term": "dmaker", "spoken": "Dimêiker", "scope": "medlycare", "language": "pt"},  # esconde o global
    ]

    removed = voice_client.delete(
        "/api/voices/pronunciation", params={"term": "dmaker", "brand": "medlycare"}
    )
    assert removed.status_code == 200
    assert [e["scope"] for e in removed.json()["entries"]] == ["global", "global"]
    assert voice_client.delete("/api/voices/pronunciation", params={"term": "API"}).json()["entries"] == [
        {"term": "DMaker", "spoken": "Di Meiker", "scope": "global", "language": "pt"}
    ]


def test_pronunciation_validation_errors_are_400(voice_client):
    empty = voice_client.post("/api/voices/pronunciation", json={"term": "  ", "spoken": "x"})
    assert empty.status_code == 400 and "termo" in empty.json()["detail"]
    brand = voice_client.post(
        "/api/voices/pronunciation", json={"term": "A", "spoken": "b", "brand": "nenhuma"}
    )
    assert brand.status_code == 400 and "não encontrada" in brand.json()["detail"]
    unknown = voice_client.delete("/api/voices/pronunciation", params={"term": "fantasma"})
    assert unknown.status_code == 400 and "não está no dicionário" in unknown.json()["detail"]
    assert voice_client.get("/api/voices/pronunciation", params={"brand": "../x"}).status_code == 400
    assert voice_client.post("/api/voices/pronunciation", json={"term": "A"}).status_code == 422


def test_pronunciation_route_does_not_clash_with_voice_removal(voice_client, studio):
    studio.library.save_design("Sai logo", "female")
    voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Meiker"})
    assert voice_client.delete("/api/voices/sai-logo").json() == {"ok": True}
    assert len(voice_client.get("/api/voices/pronunciation").json()["entries"]) == 1


def test_speak_uses_the_lexicon_and_cues_keep_the_written_text(voice_client, studio):
    voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Meiker"})
    voice_client.post(
        "/api/voices/pronunciation", json={"term": "MedlyCare", "spoken": "Médli Quér", "brand": "medlycare"}
    )
    body = {"text": "O DMaker é da MedlyCare.", "brand": "medlycare"}

    job = _wait_for_job(voice_client.post("/api/voices/speak", json=body).json()["job_id"])

    assert job.status == "done", job.error
    assert studio.synthesizer.requests[-1].text == "O Di Meiker é da Médli Quér."
    assert job.result["cues"][0]["text"] == "O DMaker é da MedlyCare."


def test_speak_without_brand_only_uses_the_global_lexicon(voice_client, studio):
    voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Meiker"})
    voice_client.post(
        "/api/voices/pronunciation", json={"term": "MedlyCare", "spoken": "Médli Quér", "brand": "medlycare"}
    )

    body = {"text": "O DMaker é da MedlyCare."}
    _wait_for_job(voice_client.post("/api/voices/speak", json=body).json()["job_id"])

    assert studio.synthesizer.requests[-1].text == "O Di Meiker é da MedlyCare."


def test_changing_the_lexicon_gives_the_narration_a_new_output_file(voice_client, studio):
    body = {"text": "O DMaker edita vídeos."}
    first = _wait_for_job(voice_client.post("/api/voices/speak", json=body).json()["job_id"]).result["output"]
    voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Meiker"})
    second = _wait_for_job(voice_client.post("/api/voices/speak", json=body).json()["job_id"]).result[
        "output"
    ]

    assert first != second  # o navegador não pode reaproveitar o áudio antigo


def test_speak_rejects_an_invalid_brand_before_starting_a_job(voice_client):
    before = len(server.jobs.list())
    resp = voice_client.post("/api/voices/speak", json={"text": "Oi", "brand": "../x"})
    assert resp.status_code == 400 and len(server.jobs.list()) == before


def test_speak_falls_back_to_the_brand_of_the_voice(voice_client, studio):
    studio.library.save_design("Da marca", "female", brand="medlycare")
    voice_client.post(
        "/api/voices/pronunciation", json={"term": "MedlyCare", "spoken": "Médli Quér", "brand": "medlycare"}
    )

    body = {"text": "Conheça a MedlyCare.", "voice": "da-marca"}
    _wait_for_job(voice_client.post("/api/voices/speak", json=body).json()["job_id"])

    assert studio.synthesizer.requests[-1].text == "Conheça a Médli Quér."


def test_pronunciation_entries_carry_their_language_and_can_be_filtered(voice_client):
    voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Mêiker"})
    voice_client.post(
        "/api/voices/pronunciation", json={"term": "MedlyCare", "spoken": "Medly Care", "language": "en-US"}
    )

    everything = voice_client.get("/api/voices/pronunciation").json()["entries"]
    assert [(e["language"], e["term"]) for e in everything] == [("en", "MedlyCare"), ("pt", "DMaker")]
    only_english = voice_client.get("/api/voices/pronunciation", params={"language": "en_GB"}).json()[
        "entries"
    ]
    assert [e["term"] for e in only_english] == ["MedlyCare"]

    wrong_language = voice_client.delete("/api/voices/pronunciation", params={"term": "MedlyCare"})
    assert wrong_language.status_code == 400 and "idioma pt" in wrong_language.json()["detail"]
    removed = voice_client.delete("/api/voices/pronunciation", params={"term": "MedlyCare", "language": "en"})
    assert [e["term"] for e in removed.json()["entries"]] == ["DMaker"]


def test_speak_in_english_does_not_apply_the_portuguese_entry(voice_client, studio):
    voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Mêiker"})

    _wait_for_job(
        voice_client.post(
            "/api/voices/speak", json={"text": "Meet the DMaker app.", "language": "en"}
        ).json()["job_id"]
    )
    _wait_for_job(
        voice_client.post(
            "/api/voices/speak", json={"text": "Conheça o DMaker hoje.", "language": "pt"}
        ).json()["job_id"]
    )

    assert [r.text for r in studio.synthesizer.requests[-2:]] == [
        "Meet the DMaker app.",
        "Conheça o Di Mêiker hoje.",
    ]


def test_speak_output_file_follows_the_pronunciation_of_the_spoken_language(voice_client, studio):
    english = {"text": "Meet the DMaker app.", "language": "en"}
    first = _wait_for_job(voice_client.post("/api/voices/speak", json=english).json()["job_id"]).result[
        "output"
    ]
    voice_client.post("/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Di Mêiker"})  # só em pt
    same = _wait_for_job(voice_client.post("/api/voices/speak", json=english).json()["job_id"]).result[
        "output"
    ]
    voice_client.post(
        "/api/voices/pronunciation", json={"term": "DMaker", "spoken": "Dee Maker", "language": "en"}
    )
    changed = _wait_for_job(voice_client.post("/api/voices/speak", json=english).json()["job_id"]).result[
        "output"
    ]

    assert first == same and first != changed


def _job_events(client, job_id: str) -> list[dict]:
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


LIVE_TEXT = "Primeira fala da prévia.\n\nSegunda fala da prévia. Terceira fala da prévia."


def test_speak_publishes_each_ready_utterance_as_an_sse_event_before_the_job_ends(voice_client, studio):
    job_id = voice_client.post("/api/voices/speak", json={"text": LIVE_TEXT}).json()["job_id"]
    job = _wait_for_job(job_id)
    assert job.status == "done", job.error

    events = _job_events(voice_client, job_id)
    utterances = [e for e in events if e["kind"] == "utterance"]
    assert [(e["index"], e["total"]) for e in utterances] == [(1, 3), (2, 3), (3, 3)]
    assert [e["pause_after_s"] for e in utterances] == [0.7, 0.35, 0.0]  # a pausa do roteiro viaja junto

    for event in utterances:
        assert event["audio_url"].startswith("/api/voices/audio?path=")
        chunk = voice_client.get(event["audio_url"])
        assert chunk.status_code == 200 and chunk.content[:4] == b"RIFF"  # a fala crua do cache, em WAV
    durations = [e["duration_s"] for e in utterances]
    assert durations == [pytest.approx(0.05 * len(r.text), abs=0.01) for r in studio.synthesizer.requests]

    # cada fala é avisada logo depois do progresso dela e antes do fim do job
    kinds = [e["kind"] for e in events]
    assert kinds.index("utterance") < kinds.index("end") and kinds[-1] == "end"
    labels = [e["label"] for e in events if e["kind"] == "progress"]
    assert labels == ["fala 1 de 3", "fala 2 de 3", "fala 3 de 3"]
    for position, event in enumerate(utterances, 1):
        progress_at = next(i for i, e in enumerate(events) if e.get("label") == f"fala {position} de 3")
        assert progress_at < events.index(event)


def test_utterance_chunks_are_served_from_the_cache_and_never_outside_it(voice_client, studio, tmp_path):
    job_id = voice_client.post("/api/voices/speak", json={"text": LIVE_TEXT}).json()["job_id"]
    _wait_for_job(job_id)
    chunk_url = next(e["audio_url"] for e in _job_events(voice_client, job_id) if e["kind"] == "utterance")
    served = Path(parse_qs(urlparse(chunk_url).query)["path"][0])
    assert served.parent == config.VOICE_CACHE_DIR.resolve()

    secret = tmp_path / "segredo.wav"
    secret.write_bytes(b"RIFFsecreto")
    for escape in (config.VOICE_CACHE_DIR / ".." / "segredo.wav", config.VOICE_CACHE_DIR / ".." / ".." / "x"):
        reply = voice_client.get("/api/voices/audio", params={"path": str(escape)})
        assert reply.status_code == 404


class GatedSynthesizer(FakeSynthesizer):
    """Segura a síntese de uma fala até o teste mandar seguir, para cancelar com o job no meio da narração."""

    def __init__(self, hold_call: int):
        super().__init__()
        self.hold_call = hold_call
        self.reached = threading.Event()
        self.release = threading.Event()

    def synthesize(self, request: VoiceRequest) -> Speech:
        speech = super().synthesize(request)
        if len(self.requests) == self.hold_call:
            self.reached.set()
            assert self.release.wait(10)
        return speech


FIVE_UTTERANCES = " ".join(f"Esta é a fala número {n} da narração de teste." for n in range(1, 6))


def test_stop_cancels_between_utterances_and_generating_again_reuses_what_was_ready(voice_client, studio):
    studio.synthesizer = GatedSynthesizer(hold_call=2)
    body = {"text": FIVE_UTTERANCES}
    job_id = voice_client.post("/api/voices/speak", json=body).json()["job_id"]
    assert studio.synthesizer.reached.wait(10)  # a fala 2 está sendo gerada

    reply = voice_client.post(f"/api/jobs/{job_id}/cancel")
    assert reply.status_code == 200 and reply.json()["cancellable"] is True
    studio.synthesizer.release.set()
    job = _wait_for_job(job_id)

    assert job.status == "cancelled" and job.error is None
    assert job.result == {"ready": 2, "total": 5}
    assert len(studio.synthesizer.requests) == 2  # a fala 3 nunca foi sintetizada
    events = _job_events(voice_client, job_id)
    assert [e["index"] for e in events if e["kind"] == "utterance"] == [1, 2]
    assert events[-1]["kind"] == "end" and events[-1]["status"] == "cancelled"
    assert not list(config.OUTPUT_DIR.glob("narracao-*.wav"))  # sem arquivo final de narração pela metade

    again = _wait_for_job(voice_client.post("/api/voices/speak", json=body).json()["job_id"])
    assert again.status == "done", again.error
    texts = [r.text for r in studio.synthesizer.requests]
    assert len(texts) == 5 and len(set(texts)) == 5  # só as 3 que faltavam foram sintetizadas agora


def test_stop_while_waiting_in_the_queue_never_touches_the_synthesizer(voice_client, studio):
    from dmaker.ui import voice_routes

    voice_routes._synthesis_lock.acquire()  # outro trabalho de voz ocupando a CPU
    try:
        job_id = voice_client.post("/api/voices/speak", json={"text": LIVE_TEXT}).json()["job_id"]
        assert voice_client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        job = _wait_for_job(job_id)
    finally:
        voice_routes._synthesis_lock.release()
    assert job.status == "cancelled" and studio.synthesizer.requests == []


def test_cancel_rejects_unknown_jobs_and_jobs_that_cannot_be_cancelled(voice_client):
    assert voice_client.post("/api/jobs/fantasma/cancel").status_code == 404
    release = threading.Event()
    job = server.jobs.start("render qualquer", lambda _job: release.wait(10))
    try:
        assert voice_client.post(f"/api/jobs/{job.id}/cancel").status_code == 409
    finally:
        release.set()
        server.jobs.wait(job, 10)
    assert job.status == "done"
