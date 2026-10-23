"""Adaptadores da dublagem: `dmaker dub ...` e as ferramentas MCP, sobre o mesmo serviço com dublês."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import dmaker.mcp_server as mcp_server
from dmaker import config
from dmaker.cli import app
from dmaker.domain.dub import load_dub_project, save_dub_project
from tests.test_dubbing import DubHarness

cli = CliRunner()


@pytest.fixture
def dub(tmp_path: Path) -> DubHarness:
    return DubHarness(tmp_path / "media")


@pytest.fixture
def wired(monkeypatch, dub: DubHarness, tmp_path: Path) -> DubHarness:
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        "dmaker.pipeline.dubbing.default_dubbing_service", lambda *args, **kwargs: dub.service
    )
    monkeypatch.setattr(mcp_server, "_dubbing_service", lambda job: dub.service)
    monkeypatch.setattr("dmaker.voice.library.VOICES_DIR", tmp_path / "voices")
    monkeypatch.setattr(mcp_server, "_voice_library", lambda: dub.base.library)
    return dub


def default_project(tmp_path: Path) -> Path:
    return tmp_path / "output" / "dublagem" / "entrevista.en.dub.json"


# ---------- CLI ----------


def test_cli_prepare_writes_the_project_and_prints_the_segment_table(wired: DubHarness, tmp_path: Path):
    result = cli.invoke(app, ["dub", "prepare", str(wired.src), "--to", "en"])
    assert result.exit_code == 0, result.output
    assert "Olá pessoal" in result.output and "EN Olá pessoal" in result.output
    assert "entrevista.en.dub.json" in result.output and "tempo de processamento" in result.output
    project = load_dub_project(default_project(tmp_path))
    assert project.target_language == "en" and len(project.segments) == 3


def test_cli_prepare_passes_every_option_to_the_service(wired: DubHarness, tmp_path: Path):
    wired.base.library.save_design("Locutora", "female, low pitch", language="en")
    target = tmp_path / "meu.dub.json"
    result = cli.invoke(
        app,
        [
            "dub",
            "prepare",
            str(wired.src),
            "--to",
            "en",
            "--from",
            "pt",
            "--speaker",
            "single",
            "--voice",
            "locutora",
            "--keep-original",
            "-18",
            "--glossary",
            "DMaker",
            "--glossary",
            "MedlyCare",
            "--brand",
            "medlycare",
            "--project",
            str(target),
        ],
    )
    assert result.exit_code == 0, result.output
    project = load_dub_project(target)
    assert (project.speaker_mode, project.voice, project.keep_original_db) == ("single", "locutora", -18.0)
    assert project.glossary == ["DMaker", "MedlyCare"] and project.brand == "medlycare"


def test_cli_render_prints_the_report_the_srt_and_the_timings(wired: DubHarness, tmp_path: Path):
    wired.prepare()
    out = tmp_path / "dublado.mp4"
    result = cli.invoke(app, ["dub", "render", str(wired.project_path), "--out", str(out), "--draft"])
    assert result.exit_code == 0, result.output
    assert "Pronto" in result.output and "dublado.mp4" in result.output and out.exists()
    assert "legenda" in result.output and "dublado.srt" in result.output
    assert "3 fala(s) sintetizada(s) agora" in result.output and "Síntese das falas" in result.output
    assert {r.steps for r in wired.synthesizer.requests} == {8}


def test_cli_render_warns_about_speech_that_did_not_fit(wired: DubHarness):
    project = wired.prepare().edited("s1", text=" ".join(["muito longo para caber no tempo"] * 8))
    save_dub_project(project, wired.project_path)
    result = cli.invoke(app, ["dub", "render", str(wired.project_path), "--out", str(wired.out)])
    assert result.exit_code == 0, result.output
    assert "Atenção: Fala s1" in result.output and "encurte a tradução" in result.output


def test_cli_dub_with_only_a_file_prepares_and_renders(wired: DubHarness, tmp_path: Path):
    result = cli.invoke(app, ["dub", str(wired.src), "--to", "en", "--out", str(tmp_path / "tudo.mp4")])
    assert result.exit_code == 0, result.output
    assert default_project_path_exists(tmp_path) and (tmp_path / "tudo.mp4").exists()
    assert "Pronto" in result.output and len(wired.synthesizer.requests) == 3


def default_project_path_exists(tmp_path: Path) -> bool:
    return default_project(tmp_path).exists()


def test_cli_dub_explicit_run_and_help_still_work(wired: DubHarness, tmp_path: Path):
    help_output = cli.invoke(app, ["dub", "--help"]).output
    for command in ("prepare", "render", "retranslate", "run"):
        assert command in help_output
    assert (
        cli.invoke(
            app, ["dub", "run", str(wired.src), "--to", "en", "--out", str(tmp_path / "r.mp4")]
        ).exit_code
        == 0
    )
    assert cli.invoke(app, ["dub"]).exit_code in (0, 2)  # sem argumentos mostra a ajuda


def test_cli_retranslate_keeps_locked_segments(wired: DubHarness):
    project = wired.prepare().edited("s2", text="Minha tradução.", locked=True)
    save_dub_project(project, wired.project_path)
    wired.translator.replies = {"s1": "Novo um.", "s3": "Novo três."}
    result = cli.invoke(app, ["dub", "retranslate", str(wired.project_path)])
    assert result.exit_code == 0, result.output
    assert [s.text for s in load_dub_project(wired.project_path).segments] == [
        "Novo um.",
        "Minha tradução.",
        "Novo três.",
    ]


def test_cli_errors_are_portuguese_with_exit_code_1(wired: DubHarness, tmp_path: Path):
    same = cli.invoke(app, ["dub", "prepare", str(wired.src), "--to", "pt"])
    assert same.exit_code == 1 and "diferente do idioma de origem" in same.output
    mode = cli.invoke(app, ["dub", "prepare", str(wired.src), "--to", "en", "--speaker", "coro"])
    assert mode.exit_code == 1 and "per_speaker ou per_segment ou single" in mode.output
    missing = cli.invoke(app, ["dub", "render", str(tmp_path / "nada.dub.json")])
    assert missing.exit_code == 1 and "não encontrado" in missing.output
    no_file = cli.invoke(app, ["dub", "prepare", str(tmp_path / "nada.mp4"), "--to", "en"])
    assert no_file.exit_code == 1 and "não encontrado" in no_file.output
    assert cli.invoke(app, ["dub", "prepare", str(wired.src)]).exit_code != 0  # --to é obrigatório


# ---------- MCP ----------


def finished(started: dict) -> dict:
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)
    return mcp_server.job_status(started["job_id"])


def test_dub_prepare_runs_as_a_job_and_lists_the_segments(wired: DubHarness, tmp_path: Path):
    status = finished(mcp_server.dub_prepare(str(wired.src), "en", glossary=["DMaker"]))
    assert status["status"] == "done", status.get("error")
    result = status["result"]
    assert result["project"] == str(default_project(tmp_path)) and result["target_language"] == "en"
    assert [s["id"] for s in result["segments"]] == ["s1", "s2", "s3"]
    assert result["segments"][0]["original"].startswith("Olá") and result["segments"][0]["text"].startswith(
        "EN "
    )
    assert status["progress"]["percent"] == 100 and default_project(tmp_path).exists()


def test_dub_get_and_update_segment_edit_the_translation_and_the_lock(wired: DubHarness):
    wired.prepare()
    shown = mcp_server.dub_get(str(wired.project_path))
    assert shown["segments"][1]["id"] == "s2" and shown["translator_model"] == "tradutor-falso"
    updated = mcp_server.dub_update_segment(str(wired.project_path), "s2", text="Corrigida.", locked=True)
    assert updated == {
        "project": str(wired.project_path),
        "id": "s2",
        "text": "Corrigida.",
        "locked": True,
        "speaker": None,
    }
    saved = load_dub_project(wired.project_path)
    assert saved.segment("s2").text == "Corrigida." and saved.segment("s2").locked
    with pytest.raises(KeyError, match="s9"):
        mcp_server.dub_update_segment(str(wired.project_path), "s9", text="x")


def test_dub_render_runs_as_a_job_and_only_the_edited_segment_is_regenerated(
    wired: DubHarness, tmp_path: Path
):
    wired.prepare()
    out = tmp_path / "mcp.mp4"
    first = finished(mcp_server.dub_render(str(wired.project_path), out=str(out)))
    assert first["status"] == "done", first.get("error")
    result = first["result"]
    assert result["output"] == str(out) and result["srt"].endswith("mcp.srt") and result["regenerated"] == 3
    assert result["warnings"] == [] and len(result["segments"]) == 3
    assert result["segments"][0]["status"] == "advances" and "Síntese das falas" in result["timings"]
    assert first["progress"]["percent"] == 100

    mcp_server.dub_update_segment(str(wired.project_path), "s3", text="Then publish it.")
    second = finished(mcp_server.dub_render(str(wired.project_path), out=str(out), draft=False))
    assert second["result"]["regenerated"] == 1


def test_dub_render_draft_uses_eight_steps(wired: DubHarness):
    wired.prepare()
    finished(mcp_server.dub_render(str(wired.project_path), out=str(wired.out), draft=True))
    assert {r.steps for r in wired.synthesizer.requests} == {8}


def test_dub_retranslate_job_keeps_locked_segments(wired: DubHarness):
    wired.prepare()
    mcp_server.dub_update_segment(str(wired.project_path), "s1", text="Fixa.", locked=True)
    wired.translator.replies = {"s2": "Dois.", "s3": "Três."}
    status = finished(mcp_server.dub_retranslate(str(wired.project_path)))
    assert status["status"] == "done", status.get("error")
    assert [s["text"] for s in status["result"]["segments"]] == ["Fixa.", "Dois.", "Três."]


def test_dub_tools_reject_bad_calls_immediately(wired: DubHarness, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        mcp_server.dub_prepare(str(tmp_path / "nada.mp4"), "en")
    with pytest.raises(ValueError, match="diferente do idioma de origem"):
        mcp_server.dub_prepare(str(wired.src), "pt")
    with pytest.raises(Exception, match="fantasma"):
        mcp_server.dub_prepare(str(wired.src), "en", voice="fantasma")
    with pytest.raises(FileNotFoundError):
        mcp_server.dub_render(str(tmp_path / "nada.dub.json"))
    with pytest.raises(FileNotFoundError):
        mcp_server.dub_get(str(tmp_path / "nada.dub.json"))


def test_dub_job_failure_carries_the_translation_message(wired: DubHarness):
    from dmaker.text.translate import TranslationError

    def broken(*args, **kwargs):
        raise TranslationError("Não consegui falar com o Ollama em http://x. Abra o aplicativo do Ollama.")

    wired.translator.translate = broken
    status = finished(mcp_server.dub_prepare(str(wired.src), "en"))
    assert status["status"] == "error" and "Não consegui falar com o Ollama" in status["error"]


def test_dub_tools_are_listed():
    names = {tool.name for tool in asyncio.run(mcp_server.server.list_tools())}
    assert {"dub_prepare", "dub_render", "dub_get", "dub_update_segment", "dub_retranslate"} <= names


# ---------- falantes (diarização) ----------


def two_people(wired: DubHarness) -> DubHarness:
    from tests.test_dubbing_speakers import TWO_PEOPLE, FakeDiarizer

    wired.diarizer = FakeDiarizer(TWO_PEOPLE)
    wired.service.diarizer = wired.diarizer
    return wired


def test_cli_prepare_separates_the_speakers_by_default_and_can_force_the_count(
    wired: DubHarness, tmp_path: Path
):
    two_people(wired)
    result = cli.invoke(app, ["dub", "prepare", str(wired.src), "--to", "en", "--speakers", "2"])
    assert result.exit_code == 0, result.output
    assert "falante" in result.output and "Falante 2" in result.output
    project = load_dub_project(default_project(tmp_path))
    assert project.speaker_mode == "per_speaker" and project.speaker_names == ["Falante 1", "Falante 2"]
    assert wired.diarizer.calls[0][1] == 2


def test_cli_speakers_needs_the_per_speaker_mode_and_a_positive_count(wired: DubHarness):
    two_people(wired)
    other = cli.invoke(
        app, ["dub", "prepare", str(wired.src), "--to", "en", "--speaker", "single", "--speakers", "2"]
    )
    assert other.exit_code == 1 and "só vale no modo per_speaker" in other.output
    assert cli.invoke(app, ["dub", "prepare", str(wired.src), "--to", "en", "--speakers", "0"]).exit_code == 2


def test_mcp_dub_update_segment_swaps_the_speaker_and_refuses_an_unknown_one(wired: DubHarness):
    two_people(wired).prepare()
    updated = mcp_server.dub_update_segment(str(wired.project_path), "s3", speaker="Falante 2")
    assert (
        updated["speaker"] == "Falante 2" and updated["text"] == "EN Depois é só exportar o vídeo e publicar."
    )
    assert load_dub_project(wired.project_path).segment("s3").speaker == "Falante 2"
    with pytest.raises(ValueError, match="Falante 7"):
        mcp_server.dub_update_segment(str(wired.project_path), "s3", speaker="Falante 7")
    shown = mcp_server.dub_get(str(wired.project_path))
    assert shown["speakers"] == ["Falante 1", "Falante 2"] and shown["segments"][2]["speaker"] == "Falante 2"


def test_mcp_dub_prepare_passes_the_mode_and_the_count(wired: DubHarness):
    two_people(wired)
    status = finished(mcp_server.dub_prepare(str(wired.src), "en", num_speakers=2))
    assert status["status"] == "done", status
    assert status["result"]["speaker_mode"] == "per_speaker" and status["result"]["speakers"] == [
        "Falante 1",
        "Falante 2",
    ]
    assert wired.diarizer.calls[-1][1] == 2


def test_the_mcp_tool_documents_the_speaker_parameters():
    tools = asyncio.run(mcp_server.server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert "speaker" in by_name["dub_update_segment"].input_schema["properties"]
    prepare = by_name["dub_prepare"].input_schema["properties"]
    assert "num_speakers" in prepare and "per_speaker" in json.dumps(prepare["speaker_mode"])
