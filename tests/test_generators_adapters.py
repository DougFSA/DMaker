"""Os geradores de som pelos três adaptadores: ferramenta MCP, linha de comando e rota da interface."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.domain.generators import GENERATOR_CLASSES
from dmaker.domain.spec import Project
from dmaker.media.wavio import read_wav_float
from dmaker.ui import server

from .conftest import requires_ffmpeg
from .test_mcp import _session, _text

runner = CliRunner()


def write_spec(folder: Path, **audio) -> Path:
    project = Project.model_validate(
        {
            "name": "cli-gerados",
            "timeline": [],
            "output": {"preset": "audio/wav"},
            "audio": {"normalize": "off", "voiceover": [{"src": "fala.wav", "start": 1}], **audio},
        }
    )
    return project.save(folder / "spec.json")


def saved(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fake_voice(folder: Path) -> None:
    """Um WAV de 8 s de tom, para a voz gravada do projeto (o `edit_project` mede a duração dele)."""
    from dmaker.media.wavio import write_wav

    t = np.arange(8 * 16000) / 16000
    write_wav(folder / "fala.wav", 0.3 * np.sin(2 * np.pi * 220 * t), 16000)


# ---------- rota da interface ----------


def test_the_route_serves_the_generator_catalog_and_one_generator():
    client = TestClient(server.app)
    everything = client.get("/api/audio-generators")
    assert everything.status_code == 200
    data = everything.json()
    assert [info["type"] for info in data["generators"]] == list(GENERATOR_CLASSES)
    assert data["target"] == "audio.generated.N" and data["track"] == "SFX"
    one = client.get("/api/audio-generators", params={"type": "dtmf"}).json()
    assert [info["type"] for info in one["generators"]] == ["dtmf"]
    assert one["generators"][0]["parameters"][0]["kind"] == "text"
    assert client.get("/api/audio-generators", params={"type": "violino"}).status_code == 404


# ---------- CLI ----------


def test_the_cli_lists_the_generators_as_a_table_and_as_json():
    table = runner.invoke(app, ["audio", "generators"])
    assert table.exit_code == 0, table.output
    for name in (
        "Tom",
        "Chirp",
        "Ruído",
        "Tons DTMF",
        "Silêncio",
        "Pluck",
        "Tambor de Risset",
        "Faixa de ritmo",
    ):
        assert name in table.output
    as_json = runner.invoke(app, ["audio", "generators", "tone", "--json"])
    assert as_json.exit_code == 0 and [g["type"] for g in json.loads(as_json.output)["generators"]] == [
        "tone"
    ]
    missing = runner.invoke(app, ["audio", "generators", "violino"])
    assert missing.exit_code != 0 and "desconhecido" in missing.output


@requires_ffmpeg
def test_the_cli_generates_a_loose_sound_and_refuses_to_overwrite(tmp_path):
    out = tmp_path / "tom.wav"
    done = runner.invoke(
        app,
        [
            "audio",
            "generate",
            "tone",
            "-p",
            "frequency_hz=1000",
            "-p",
            "amplitude_db=-6",
            "--duration",
            "1",
            "--out",
            str(out),
        ],
    )
    assert done.exit_code == 0, done.output
    samples, rate = read_wav_float(out)
    assert rate == 48000 and samples.shape == (48000, 2)
    assert 20 * np.log10(float(np.max(np.abs(samples)))) == __import__("pytest").approx(-6.0, abs=0.02)
    assert "pico -6.0" in done.output
    again = runner.invoke(app, ["audio", "generate", "tone", "--out", str(out)])
    assert again.exit_code != 0 and "já existe" in again.output
    replaced = runner.invoke(
        app, ["audio", "generate", "silence", "--duration", "0.5", "--out", str(out), "--overwrite"]
    )
    assert replaced.exit_code == 0 and "mudo" in replaced.output
    bad = runner.invoke(
        app, ["audio", "generate", "tone", "-p", "frequency_hz=0", "--out", str(tmp_path / "x.wav")]
    )
    assert bad.exit_code != 0 and "frequency_hz" in bad.output
    not_wav = runner.invoke(app, ["audio", "generate", "tone", "--out", str(tmp_path / "x.mp3")])
    assert not_wav.exit_code != 0 and ".wav" in not_wav.output


def test_the_cli_puts_lists_changes_and_removes_generated_sounds_in_a_project(tmp_path):
    fake_voice(tmp_path)
    spec = write_spec(tmp_path)
    added = runner.invoke(
        app,
        [
            "audio",
            "generated",
            "add",
            str(spec),
            "tone",
            "-p",
            "frequency_hz=880",
            "--start",
            "2",
            "--duration",
            "0.5",
        ],
    )
    assert added.exit_code == 0, added.output
    rhythm = runner.invoke(
        app, ["audio", "generated", "add", str(spec), "rhythm_track", "-p", "beats=8", "--start", "3"]
    )
    assert rhythm.exit_code == 0, rhythm.output
    sounds = saved(spec)["audio"]["generated"]
    assert [s["generator"] for s in sounds] == ["tone", "rhythm_track"]
    assert sounds[0]["params"]["frequency_hz"] == 880 and sounds[1]["duration"] == 4.0  # 8 batidas a 120 BPM
    listing = runner.invoke(app, ["audio", "generated", "list", str(spec)])
    assert "Tom 880 Hz" in listing.output and "Faixa de ritmo 120 BPM" in listing.output
    changed = runner.invoke(
        app, ["audio", "generated", "set", str(spec), "0", "-p", "amplitude_db=-8", "--volume", "0.5"]
    )
    assert changed.exit_code == 0
    first = saved(spec)["audio"]["generated"][0]
    assert (
        first["params"]["amplitude_db"] == -8
        and first["params"]["frequency_hz"] == 880
        and first["volume"] == 0.5
    )
    removed = runner.invoke(app, ["audio", "generated", "remove", str(spec), "0"])
    assert removed.exit_code == 0 and [s["generator"] for s in saved(spec)["audio"]["generated"]] == [
        "rhythm_track"
    ]
    undone = runner.invoke(app, ["undo", str(spec)])
    assert (
        undone.exit_code == 0 and len(saved(spec)["audio"]["generated"]) == 2
    )  # o desfazer vale para o som gerado
    wrong = runner.invoke(app, ["audio", "generated", "remove", str(spec), "9"])
    assert wrong.exit_code != 0 and "fora do intervalo" in wrong.output


def test_the_cli_beeps_an_interval_and_the_undo_takes_both_changes_back(tmp_path):
    fake_voice(tmp_path)
    spec = write_spec(tmp_path)
    done = runner.invoke(
        app,
        [
            "audio",
            "censor",
            str(spec),
            "audio.voiceover.0",
            "--start",
            "3",
            "--end",
            "3.4",
            "--frequency",
            "800",
        ],
    )
    assert done.exit_code == 0, done.output
    data = saved(spec)["audio"]
    assert data["voiceover"][0]["effects"][0]["type"] == "silence"
    assert data["generated"][0]["start"] == 3 and data["generated"][0]["params"]["frequency_hz"] == 800
    undone = runner.invoke(app, ["undo", str(spec)])
    assert undone.exit_code == 0
    after = saved(spec)["audio"]
    assert "generated" not in after and "effects" not in after["voiceover"][0]  # um passo só do desfazer
    nothing = runner.invoke(app, ["audio", "censor", str(spec), "audio.voiceover.0"])
    assert nothing.exit_code != 0 and "diga o que bipar" in nothing.output


# ---------- MCP ----------


@requires_ffmpeg
def test_the_mcp_lists_generates_and_puts_a_sound_in_a_project_over_stdio(tmp_path):
    out = tmp_path / "ruido.wav"
    spec = {
        "output": {"preset": "audio/wav"},
        "timeline": [],
        "audio": {"normalize": "off", "generated": [{"generator": "silence", "duration": 2}]},
    }

    async def go(session):
        tools = await session.list_tools()
        catalog = await session.call_tool("audio_generators", {})
        only = await session.call_tool("audio_generators", {"type": "pluck"})
        unknown = await session.call_tool("audio_generators", {"type": "violino"})
        made = await session.call_tool(
            "audio_generate",
            {
                "generator": "noise",
                "params": {"noise_type": "pink", "amplitude_db": -6},
                "duration": 1,
                "out": str(out),
            },
        )
        exists = await session.call_tool("audio_generate", {"generator": "noise", "out": str(out)})
        await session.call_tool("save_project", {"name": "mcp-gerados-teste", "spec": spec})
        added = await session.call_tool(
            "edit_project",
            {
                "name": "mcp-gerados-teste",
                "op": {
                    "type": "generated_add",
                    "generator": "tone",
                    "params": {"frequency_hz": 1000},
                    "start": 0.5,
                    "duration": 1,
                },
            },
        )
        refused = await session.call_tool(
            "edit_project",
            {"name": "mcp-gerados-teste", "op": {"type": "generated_add", "generator": "violino"}},
        )
        return (
            {t.name for t in tools.tools},
            _text(catalog),
            _text(only),
            unknown,
            _text(made),
            exists,
            _text(added),
            refused,
        )

    tools, catalog, only, unknown, made, exists, added, refused = asyncio.run(_session(go))
    assert {"audio_generators", "audio_generate"} <= tools
    assert [g["type"] for g in json.loads(catalog)["generators"]] == list(GENERATOR_CLASSES)
    assert [g["type"] for g in json.loads(only)["generators"]] == ["pluck"]
    assert unknown.is_error and "desconhecido" in _text(unknown)
    result = json.loads(made)
    assert (
        result["path"] == str(out)
        and result["duration_s"] == 1.0
        and result["params"]["noise_type"] == "pink"
    )
    assert exists.is_error and "já existe" in _text(exists)
    assert json.loads(added)["total_s"] == 2.0
    assert refused.is_error and "generator" in _text(refused)

    spec_path = config.PROJECTS_DIR / "mcp-gerados-teste" / "spec.json"
    assert [s["generator"] for s in saved(spec_path)["audio"]["generated"]] == ["silence", "tone"]
    shutil.rmtree(spec_path.parent)
