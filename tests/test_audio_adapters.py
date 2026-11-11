"""Os adaptadores da saída só de áudio: MCP, CLI, interface e o gate do agente, sobre os mesmos serviços."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rich.console import Console
from typer.testing import CliRunner

from dmaker import cli, config, mcp_server
from dmaker.agent.kits import EXCLUDED_TOOLS
from dmaker.agent.safety import ApproveAll, ToolGate
from dmaker.cli import app
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.projects import save_project, summarize
from dmaker.pipeline.report import build_report
from dmaker.pipeline.timeline_service import project_timeline_view
from dmaker.ui import server

pytestmark = pytest.mark.skipif(config.find_tool("ffmpeg") is None, reason="precisa do ffmpeg")
runner = CliRunner()

LOUDNORM = json.dumps(
    {
        "input_i": "-16.1",
        "input_tp": "-3.0",
        "input_lra": "4.0",
        "input_thresh": "-26.0",
        "target_offset": "0.1",
    }
)


def make_tone(path: Path, seconds: float = 6.0, hz: float = 220) -> Path:
    subprocess.run(
        [
            str(config.find_tool("ffmpeg")),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=f={hz}:d={seconds}:r=48000",
            "-af",
            "aformat=channel_layouts=stereo,tremolo=f=0.2:d=0.5",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def episode() -> str:
    """Um projeto só de áudio, salvo na pasta de projetos (temporária) com uma voz gravada e duas regiões."""
    folder = config.PROJECTS_DIR / "ep"
    folder.mkdir(parents=True)
    make_tone(folder / "voz.wav", 8)
    project = Project.model_validate(
        {
            "name": "ep",
            "output": {"preset": "audio/wav", "metadata": {"title": "Teste"}},
            "audio": {"voiceover": [{"src": "voz.wav"}], "target_lufs": -16},
            "markers": [{"start": 0, "end": 3, "text": "Um"}, {"start": 3, "end": 8, "text": "Dois"}],
        }
    )
    save_project(project)
    return "ep"


# ---------- MCP ----------


def test_the_mcp_lists_the_formats_and_the_loudness_targets():
    body = mcp_server.audio_presets()
    assert {f["id"] for f in body["formats"]} >= {
        "audio/wav",
        "audio/mp3",
        "audio/flac",
        "audio/ogg",
        "audio/opus",
        "audio/m4a",
        "audio/aiff",
    }
    assert body["loudness_targets"] == {"redes": -14.0, "podcast": -16.0, "broadcast": -23.0}
    assert all("width" not in p for p in body["formats"])
    assert all("width" in p for p in mcp_server.presets())  # a lista de vídeo continua só de vídeo


def test_the_mcp_exports_regions_and_stems_and_the_selection(episode):
    regions = mcp_server.audio_export(episode, preset="audio/flac", mode="regions", loudness="podcast")
    assert regions["status"] == "done", regions
    names = [Path(f["path"]).name for f in regions["result"]["files"]]
    assert names == ["Um.flac", "Dois.flac"]
    assert [f["duration_s"] for f in regions["result"]["files"]] == [3.0, 5.0]
    stems = mcp_server.audio_export(episode, mode="stems")
    assert [f["track"] for f in stems["result"]["files"]] == ["VO"]
    selection = mcp_server.audio_export(
        episode, mode="selection", start="marker:Dois", end=None, preset="mp3", bitrate_k=128
    )
    assert (
        selection["result"]["files"][0]["duration_s"] == 5.0 and selection["result"]["preset"] == "audio/mp3"
    )


def test_the_mcp_explains_a_request_the_format_cannot_honour(episode):
    result = mcp_server.audio_export(episode, preset="audio/mp3", bit_depth=24)
    assert result["status"] == "error" and "formato com perda" in json.dumps(result)


def test_export_project_and_render_project_accept_an_audio_preset_and_make_no_video(episode):
    exported = mcp_server.export_project(episode, ["audio/mp3", "audio/wav"], show_ui=False)
    assert exported["status"] == "done", exported
    files = [Path(item["output"]) for item in exported["result"]]
    assert [p.suffix for p in files] == [".mp3", ".wav"]
    for item in exported["result"]:
        assert item["preset"].startswith("audio/") and not item["thumbnail"]
    probe = subprocess.run(
        [
            str(config.find_tool("ffprobe")),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(files[0]),
        ],
        capture_output=True,
        text=True,
    )
    assert probe.stdout.split() == ["audio"]
    rendered = mcp_server.render_project(episode, preset="audio/flac", show_ui=False)
    assert rendered["status"] == "done" and rendered["result"]["output"].endswith(".flac")
    assert "QA" in rendered["result"]["qa"] and "quadros pretos" not in rendered["result"]["qa"]


def test_the_mcp_imports_raw_audio_and_keeps_the_original(tmp_path):
    raw = tmp_path / "bruto.pcm"
    data = (np.sin(2 * np.pi * 330 * np.arange(24000) / 48000) * 12000).astype("<i2").tobytes()
    raw.write_bytes(data)
    result = mcp_server.import_raw_audio("novo", str(raw), sample_rate=48000, start=1.0)
    assert (
        result["project_created"] and result["duration_s"] == 0.5 and result["voiceover_src"] == "bruto.wav"
    )
    assert raw.read_bytes() == data
    saved = Project.load(config.PROJECTS_DIR / "novo" / "spec.json")
    assert saved.audio.voiceover[0].start == 1.0 and saved.output.preset == "audio/wav"


# ---------- CLI ----------


@pytest.fixture
def wide_console(monkeypatch):
    monkeypatch.setattr(cli, "console", Console(width=200))


def test_the_cli_lists_the_audio_formats_in_presets_and_in_audio_presets(wide_console):
    listing = runner.invoke(app, ["presets"]).output
    assert "audio/mp3" in listing and "instagram/reels" in listing
    audio = runner.invoke(app, ["audio", "presets"]).output
    assert "audio/opus" in audio and "podcast (-16)" in audio and "broadcast (-23)" in audio


def test_the_cli_exports_by_region_and_refuses_what_the_format_cannot_do(episode, wide_console, tmp_path):
    out_dir = tmp_path / "saida"
    ok = runner.invoke(
        app,
        [
            "audio",
            "export",
            episode,
            "--mode",
            "regions",
            "--preset",
            "audio/wav",
            "--out-dir",
            str(out_dir),
            "--loudness",
            "-14",
        ],
    )
    assert ok.exit_code == 0, ok.output
    assert sorted(p.name for p in out_dir.iterdir()) == ["Dois.wav", "Um.wav"]
    bad = runner.invoke(app, ["audio", "export", episode, "--preset", "audio/flac", "--bitrate", "128"])
    assert bad.exit_code == 1 and "sem perda" in bad.output
    nothing = runner.invoke(app, ["audio", "export", episode, "--mode", "wat"])
    assert nothing.exit_code == 1 and "modo de exportação desconhecido" in nothing.output


def test_the_cli_validate_and_render_work_on_an_audio_project(episode, wide_console):
    shown = runner.invoke(app, ["validate", episode])
    assert shown.exit_code == 0 and "audio/wav" in shown.output and "8.0s" in shown.output
    done = runner.invoke(app, ["render", episode, "--no-ui"])
    assert (
        done.exit_code == 0
        and "audio/wav" in done.output
        and (config.OUTPUT_DIR / "ep__audio-wav.wav").exists()
    )


def test_the_cli_imports_raw_audio(tmp_path, wide_console):
    raw = tmp_path / "x.raw"
    raw.write_bytes(np.zeros(4800, dtype="<i2").tobytes())
    done = runner.invoke(
        app, ["audio", "import-raw", "meu", str(raw), "--sample-rate", "48000", "--name", "silencio"]
    )
    assert done.exit_code == 0 and "Projeto novo" in done.output
    again = runner.invoke(
        app, ["audio", "import-raw", "meu", str(raw), "--sample-rate", "48000", "--name", "silencio"]
    )
    assert again.exit_code == 1 and "já existe" in again.output
    assert (
        runner.invoke(
            app,
            [
                "audio",
                "import-raw",
                "meu",
                str(raw),
                "--sample-rate",
                "48000",
                "--name",
                "silencio",
                "--overwrite",
            ],
        ).exit_code
        == 0
    )


# ---------- interface ----------


def wait_for(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError("a exportação não terminou")


def test_the_ui_state_lists_the_audio_formats(episode):
    with TestClient(server.app) as client:
        state = client.get("/api/state").json()
        assert {p["id"] for p in state["audio_presets"]} >= {"audio/mp3", "audio/wav"}
        assert state["loudness_targets"]["podcast"] == -16
        assert all("width" in p for p in state["presets"])  # os presets de vídeo seguem em `presets`
        assert client.get("/api/audio/catalog").json()["audio_presets"][0]["id"].startswith("audio/")


def test_the_ui_never_overwrites_without_a_yes(episode):
    with TestClient(server.app) as client:
        first = client.post(
            f"/api/projects/{episode}/audio-export", json={"mode": "regions", "preset": "audio/mp3"}
        )
        assert first.status_code == 200, first.text
        done = wait_for(client, first.json()["job_id"])
        assert done["status"] == "done" and len(done["result"]["files"]) == 2
        again = client.post(
            f"/api/projects/{episode}/audio-export", json={"mode": "regions", "preset": "audio/mp3"}
        )
        assert again.status_code == 409 and len(again.json()["detail"]["existing"]) == 2
        confirmed = client.post(
            f"/api/projects/{episode}/audio-export",
            json={"mode": "regions", "preset": "audio/mp3", "overwrite": True},
        )
        assert confirmed.status_code == 200
        wait_for(client, confirmed.json()["job_id"])
        assert (
            client.post(f"/api/projects/{episode}/audio-export", json={"mode": "nao-existe"}).status_code
            == 400
        )
        assert client.post("/api/projects/nao-existe/audio-export", json={}).status_code == 404


def test_the_ui_imports_raw_audio(tmp_path):
    raw = tmp_path / "a.raw"
    raw.write_bytes(np.zeros(9600, dtype="<i2").tobytes())
    with TestClient(server.app) as client:
        body = {"src": str(raw), "sample_rate": 48000, "wav_name": "gravacao"}
        done = client.post("/api/projects/bruto/audio-import-raw", json=body)
        assert done.status_code == 200 and done.json()["duration_s"] == 0.2
        assert client.post("/api/projects/bruto/audio-import-raw", json=body).status_code == 409
        assert (
            client.post("/api/projects/bruto/audio-import-raw", json={**body, "encoding": "s12"}).status_code
            == 400
        )


# ---------- agente ----------


def gate(existing: set[str]) -> ToolGate:
    return ToolGate(schemas={}, policy=ApproveAll(), exists=lambda path: path in existing)


def test_the_agent_asks_before_an_audio_export_overwrites_a_file(episode):
    target = str(config.OUTPUT_DIR / "ep__audio-wav__regioes" / "Um.wav")
    asked = gate({target}).confirmations("audio_export", {"name": episode, "mode": "regions"})
    assert [r.question for r in asked] == [f"O arquivo '{target}' já existe. Posso sobrescrevê-lo?"]
    assert gate(set()).confirmations("audio_export", {"name": episode, "mode": "regions"}) == []
    # com a pasta do pedido, só pergunta se algum arquivo igual já está lá
    other = str(Path("D:/fora") / "Dois.wav")
    only_same = gate({other}).confirmations(
        "audio_export", {"name": episode, "mode": "regions", "out_dir": "D:/fora"}
    )
    assert len(only_same) == 1
    assert (
        gate({"D:/fora"}).confirmations(
            "audio_export", {"name": episode, "mode": "regions", "out_dir": "D:/fora"}
        )
        == []
    )
    # um pedido que o servidor recusa (modo que não existe) não grava nada: não há o que perguntar
    assert gate({target}).confirmations("audio_export", {"name": episode, "mode": "wat"}) == []


def test_the_agent_asks_to_replace_an_imported_wav_only_when_overwrite_is_on(episode):
    wav = str(config.PROJECTS_DIR / episode / "gravacao.wav")
    arguments = {"name": episode, "src": "C:/x/gravacao.pcm"}
    assert (
        gate({wav}).confirmations("import_raw_audio", arguments) == []
    )  # sem a flag o servidor recusa sozinho
    asked = gate({wav}).confirmations("import_raw_audio", {**arguments, "overwrite": True})
    assert len(asked) == 1 and "já existe" in asked[0].question
    assert gate(set()).confirmations("import_raw_audio", {**arguments, "overwrite": True}) == []


def test_the_export_with_an_audio_preset_keeps_the_agent_confirmation():
    asked = gate(set()).confirmations("export_project", {"name_or_path": "ep", "presets": ["audio/mp3"]})
    assert len(asked) == 1 and "exportar o projeto" in asked[0].question


def test_the_new_tools_are_declared_out_of_the_small_model_kits_with_a_reason():
    for tool in ("audio_export", "audio_presets", "import_raw_audio"):
        assert EXCLUDED_TOOLS[tool]


# ---------- validação, vista e QA ----------


def fake_prober(path: Path) -> MediaInfo:
    # a voz gravada tem 600 s e entra em 4 s; o arquivo exportado (.mp3) tem os 604 s do projeto
    seconds = 604.0 if path.suffix == ".mp3" else 600.0
    return MediaInfo(path, seconds, 0, 0, 0.0, False, True, False, sample_rate=48000, channels=2)


def audio_only(tmp_path: Path, **audio) -> Project:
    (tmp_path / "voz.wav").write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "x",
            "output": {"preset": "audio/mp3"},
            "audio": {"voiceover": [{"src": "voz.wav", "start": 4}], **audio},
        }
    )
    project.base_dir = tmp_path
    return project


def test_validate_shows_the_duration_the_audio_items_give(tmp_path):
    summary = summarize(audio_only(tmp_path), fake_prober)
    assert summary.total == 604.0 and summary.preset.id == "audio/mp3" and summary.segments == []
    assert summary.preset.resolution == "48 kHz estéreo"


def test_validate_explains_what_is_missing_when_nothing_gives_a_duration(tmp_path):
    empty = Project.model_validate({"name": "x", "output": {"preset": "audio/wav"}})
    empty.base_dir = tmp_path
    summary = summarize(empty, fake_prober)
    assert summary.total == 0 and any("nenhum áudio que dê duração" in w for w in summary.warnings)


def test_validate_warns_about_audio_options_on_a_video_output(tmp_path):
    video = Project.model_validate(
        {
            "name": "x",
            "timeline": [{"type": "card", "title": "t", "duration": 1}],
            "output": {"preset": "instagram/reels", "metadata": {"title": "a"}},
        }
    )
    video.base_dir = tmp_path
    assert any(
        "output.metadata só vale com um preset de áudio" in w for w in summarize(video, fake_prober).warnings
    )


def test_the_timeline_view_of_an_audio_project_shows_the_audio_tracks(tmp_path):
    project = audio_only(tmp_path, music={"src": "voz.wav", "spans": [{"start": 0, "end": 8}]})
    view = project_timeline_view(project, prober=fake_prober)
    ids = [track.id for track in view.tracks]
    assert view.total == 604.0 and "VO" in ids and "MUS" in ids and "V1" in ids  # V1 existe, vazia
    voice = next(track for track in view.tracks if track.id == "VO")
    assert [(item.kind, item.start, item.end) for item in voice.items] == [("voiceover", 4.0, 604.0)]
    assert next(track for track in view.tracks if track.id == "V1").items == []


def test_the_qa_of_an_audio_output_checks_loudness_and_peak_and_nothing_of_video(tmp_path):
    project = audio_only(tmp_path)
    out = tmp_path / "x.mp3"
    out.write_bytes(b"x")
    recorder = RecordingRunner(capture_stderr=LOUDNORM)
    report = build_report(project, prober=fake_prober, output=out, runner=recorder)
    text = report.to_text()
    assert report.preset == "audio/mp3" and "0 erro(s)" in text
    assert "loudness e pico" in text and "quadros pretos" not in text and "contraste" not in text.lower()
    assert not any("-vf" in command or "blackdetect" in " ".join(command) for command in recorder.commands)
    wrong = RecordingRunner(capture_stderr=LOUDNORM.replace("-16.1", "-23.0").replace("-3.0", "0.5"))
    findings = [
        f.message for f in build_report(project, prober=fake_prober, output=out, runner=wrong).findings
    ]
    assert any("loudness integrado" in m for m in findings) and any("pico verdadeiro" in m for m in findings)


def test_the_qa_flags_a_picture_stream_in_an_audio_file(tmp_path):
    project = audio_only(tmp_path)
    out = tmp_path / "x.mp3"
    out.write_bytes(b"x")

    def with_picture(path: Path) -> MediaInfo:
        return MediaInfo(path, 604.0, 640, 480, 25.0, True, True, False, sample_rate=48000, channels=2)

    report = build_report(
        project, prober=with_picture, output=out, runner=RecordingRunner(capture_stderr=LOUDNORM)
    )
    assert any(f.level == "erro" and "faixa de imagem" in f.message for f in report.findings)
