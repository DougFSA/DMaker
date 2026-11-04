"""A gravação do microfone pelos adaptadores que não são o navegador: CLI e MCP recuperam o que a aba deixou no disco e
editam os takes; a clonagem recebe o WAV direto da gravação (a biblioteca de vozes e o ffmpeg são falsos).

A captura em si (getUserMedia e o AudioWorklet) só existe no navegador e se confere nos testes da interface e na
verificação manual; aqui o cliente de teste faz o papel do navegador mandando os pedaços."""

from __future__ import annotations

import asyncio
import json
import shutil
import struct
from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.domain.spec import Project
from dmaker.media.wavio import write_wav
from dmaker.pipeline.recording_attach import attach_recording, listing
from dmaker.pipeline.recordings import RecordingError, RecordingStore

from .test_mcp import _session, _text

runner = CliRunner()
RATE = 8000


def make_project(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    t = np.arange(6 * 16000) / 16000
    write_wav(folder / "fala.wav", 0.3 * np.sin(2 * np.pi * 220 * t), 16000)
    project = Project.model_validate(
        {
            "name": folder.name,
            "timeline": [],
            "output": {"preset": "audio/wav"},
            "audio": {"normalize": "off", "voiceover": [{"src": "fala.wav", "start": 2}]},
        }
    )
    return project.save(folder / "spec.json")


def record(folder: Path, seconds: int, start: float, finish: bool, punch: dict | None = None) -> str:
    store = RecordingStore(folder)
    status = store.create(RATE, 1, start=start, punch=punch)
    chunk = (0.3 * np.sin(2 * np.pi * 300 * np.arange(RATE) / RATE)).astype("<f4").tobytes()
    for seq in range(seconds):
        store.put_chunk(status.id, seq, chunk)
    if finish:
        store.finish(status.id)
    return status.id


def saved(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_listagem_mostra_so_as_abertas_com_a_duracao_que_chegou(tmp_path):
    spec = make_project(tmp_path / "p")
    aberta = record(spec.parent, 7, 1.0, finish=False)
    record(spec.parent, 3, 5.0, finish=True)
    found = listing(spec, unfinished=True)
    assert [item["id"] for item in found] == [aberta]
    assert found[0]["duration"] == 7.0 and found[0]["state"] == "open"
    assert len(listing(spec)) == 2


def test_recuperar_poe_a_gravacao_como_voz_nova_num_passo_do_historico(tmp_path):
    spec = make_project(tmp_path / "p")
    record(spec.parent, 7, 1.0, finish=False)
    status, report = attach_recording(spec)
    assert status.duration == 7.0
    voices = saved(spec)["audio"]["voiceover"]
    assert [v["src"].split("/")[0] for v in voices] == ["fala.wav", "recordings"]
    assert voices[1]["start"] == 1.0
    assert report.project.audio.voiceover[1].src == status.src
    assert listing(spec, unfinished=True) == []


def test_sem_id_e_com_duas_abertas_a_recuperacao_pede_qual(tmp_path):
    spec = make_project(tmp_path / "p")
    first = record(spec.parent, 2, 0.0, finish=False)
    record(spec.parent, 2, 3.0, finish=False)
    try:
        attach_recording(spec)
    except RecordingError as exc:
        assert "diga qual" in str(exc)
    else:
        raise AssertionError("devia recusar")
    status, _ = attach_recording(spec, first)
    assert status.id == first


def test_cli_lista_recupera_e_desfaz(tmp_path):
    spec = make_project(tmp_path / "p")
    record(spec.parent, 4, 2.5, finish=False)
    listed = runner.invoke(app, ["audio", "recordings", "list", str(spec), "--unfinished"])
    assert listed.exit_code == 0 and "aberta" in listed.output and "4.0 s" in listed.output
    as_json = runner.invoke(app, ["audio", "recordings", "list", str(spec), "--json"])
    assert json.loads(as_json.output)["recordings"][0]["state"] == "open"
    recovered = runner.invoke(app, ["audio", "recordings", "recover", str(spec)])
    assert recovered.exit_code == 0 and "posta na linha do tempo" in recovered.output
    assert len(saved(spec)["audio"]["voiceover"]) == 2
    undone = runner.invoke(app, ["undo", str(spec)])
    assert undone.exit_code == 0
    assert len(saved(spec)["audio"]["voiceover"]) == 1
    nothing = runner.invoke(app, ["audio", "recordings", "recover", str(spec)])
    assert nothing.exit_code != 0 and "nenhuma gravação aberta" in nothing.output


def test_cli_punch_e_troca_de_take(tmp_path):
    spec = make_project(tmp_path / "p")
    punch = {"target": "audio.voiceover.0", "start": 3.0, "end": 5.0}
    identifier = record(spec.parent, 5, 2.0, finish=True, punch=punch)
    done = runner.invoke(
        app,
        ["audio", "punch", str(spec), "audio.voiceover.0", identifier, "--start", "3", "--end", "5"],
    )
    assert done.exit_code == 0, done.output
    voices = saved(spec)["audio"]["voiceover"]
    assert len(voices) == 3 and voices[1]["take_label"] == "Take 2"
    assert [t["label"] for t in voices[1]["takes"]] == ["Original"]
    swapped = runner.invoke(app, ["audio", "take", str(spec), "audio.voiceover.1", "0"])
    assert swapped.exit_code == 0, swapped.output
    after = saved(spec)["audio"]["voiceover"][1]
    assert after["src"] == "fala.wav" and after["take_label"] == "Original"
    unfinished = record(spec.parent, 2, 0.0, finish=False)
    refused = runner.invoke(
        app, ["audio", "punch", str(spec), "audio.voiceover.0", unfinished, "--start", "3", "--end", "4"]
    )
    assert refused.exit_code != 0 and "ainda não foi finalizada" in refused.output


def test_mcp_lista_recupera_e_troca_o_take_por_stdio(tmp_path):
    name = "mcp-gravacao-teste"
    folder = config.PROJECTS_DIR / name
    make_project(folder)
    aberta = record(folder, 5, 1.0, finish=False)

    async def go(session):
        tools = await session.list_tools()
        found = await session.call_tool(
            "audio_recordings", {"name": name, "action": "list", "unfinished": True}
        )
        recovered = await session.call_tool("audio_recordings", {"name": name, "action": "recover"})
        again = await session.call_tool("audio_recordings", {"name": name, "action": "recover"})
        bad = await session.call_tool("audio_recordings", {"name": name, "action": "gravar"})
        return {t.name for t in tools.tools}, _text(found), recovered, again, bad

    try:
        tools, found, recovered, again, bad = asyncio.run(_session(go))
        assert "audio_recordings" in tools
        assert [r["id"] for r in json.loads(found)["recordings"]] == [aberta]
        assert not recovered.is_error and json.loads(_text(recovered))["recording"]["duration"] == 5.0
        assert again.is_error and "nenhuma gravação aberta" in _text(again)
        assert bad.is_error and "list, recover ou punch" in _text(bad)
        assert len(saved(folder / "spec.json")["audio"]["voiceover"]) == 2
    finally:
        shutil.rmtree(folder)


def test_o_wav_que_o_servidor_escreve_abre_no_leitor_de_float(tmp_path):
    """O cabeçalho do WAV float32 em blocos é o mesmo de `write_wav_float`: o ffmpeg e o leitor o aceitam."""
    from dmaker.media.wavio import read_wav_float, write_wav_float

    folder = tmp_path / "p"
    folder.mkdir()
    store = RecordingStore(folder)
    status = store.create(RATE, 2)
    stereo = np.stack([np.linspace(-0.5, 0.5, RATE), np.linspace(0.5, -0.5, RATE)], axis=1).astype("<f4")
    store.put_chunk(status.id, 0, stereo.tobytes())
    done = store.finish(status.id)
    path = folder / str(done.src)
    reference = tmp_path / "ref.wav"
    write_wav_float(reference, stereo, RATE)
    assert path.read_bytes() == reference.read_bytes()
    samples, rate = read_wav_float(path)
    assert rate == RATE and samples.shape == (RATE, 2) and np.allclose(samples, stereo)
    assert struct.unpack("<I", path.read_bytes()[4:8])[0] == path.stat().st_size - 8
