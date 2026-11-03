"""Ferramentas MCP do lote: validar, rodar como job, pausar, retomar e consultar o relatório."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dmaker import mcp_server
from dmaker.pipeline.batch import BatchService
from dmaker.pipeline.batch_state import BatchStore

from .batch_support import FakeRenderer, fake_prober, make_media, write_sheet


@pytest.fixture
def media(tmp_path: Path) -> Path:
    return make_media(tmp_path)


@pytest.fixture
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture(autouse=True)
def service(monkeypatch, tmp_path, renderer) -> BatchService:
    built = BatchService(store=BatchStore(tmp_path / "lotes"), renderer=renderer, prober=fake_prober)
    monkeypatch.setattr(mcp_server, "_batch_service", lambda: built)
    return built


def test_the_tools_are_registered_and_say_what_they_do():
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.server.list_tools())}

    assert {"validate_batch", "run_batch", "resume_batch", "pause_batch", "batch_status"} <= set(tools)
    assert "SEM renderizar" in tools["validate_batch"].description
    assert "skip_invalid" in tools["run_batch"].description and ".xlsx" in tools["validate_batch"].description


def test_validate_batch_returns_the_validation_with_a_readable_summary(media):
    sheet = write_sheet(media, ["Dica um", "Dica — dois"])

    result = mcp_server.validate_batch("stories-medlycare", str(sheet), "titulo")

    assert result["ok"] is False and result["valid"] == 1 and result["invalid"] == 1
    assert result["rows"][1]["issues"][0]["field"] == "titulo"
    assert "travessão" in result["text"]


def test_run_batch_without_skip_returns_the_validation_and_starts_nothing(media, renderer):
    sheet = write_sheet(media, broken={1: "sumiu.png"})

    result = mcp_server.run_batch("stories-medlycare", str(sheet), name_column="titulo")

    assert result["started"] is False and "1 linha(s) com problema" in result["reason"]
    assert result["validation"]["invalid"] == 1 and "linha 2, coluna print" in result["text"]
    assert renderer.calls == []


def test_run_batch_renders_in_a_job_and_batch_status_reports_it(media, renderer):
    sheet = write_sheet(media)

    started = mcp_server.run_batch(
        "stories-medlycare", str(sheet), name="serie", name_column="titulo", wait_seconds=30
    )

    assert started["started"] is True and started["status"] == "done", started
    assert started["result"]["done"] == 5 and started["batch"] == "serie"
    report = mcp_server.batch_status("serie")
    assert report["summary"].startswith("5 de 5") and "dica-um.mp4" in report["text"]
    listing = mcp_server.batch_status()
    assert [(item["name"], item["rows"]) for item in listing["batches"]] == [("serie", 5)]
    assert len(renderer.calls) == 5


def test_pause_then_resume_never_redoes_a_finished_video(media, renderer, service):
    def pause_on_second(project, rendered_so_far):
        if rendered_so_far == 1:
            mcp_server.pause_batch("serie")

    renderer.before = pause_on_second
    first = mcp_server.run_batch("stories-medlycare", str(write_sheet(media)), name="serie", wait_seconds=30)
    assert first["result"]["status"] == "paused" and first["result"]["done"] == 2

    renderer.before = None
    second = mcp_server.resume_batch("serie", wait_seconds=30)

    assert second["result"]["status"] == "finished" and second["result"]["done"] == 5
    assert len(renderer.calls) == 5


def test_resuming_a_lote_that_is_running_is_refused(media, service):
    mcp_server.run_batch("stories-medlycare", str(write_sheet(media)), name="serie", wait_seconds=30)
    from dmaker.pipeline.filelock import FileLock

    other = FileLock(service.store.lock_path("serie"))
    assert other.try_acquire()
    try:
        with pytest.raises(ValueError, match="já está rodando"):
            mcp_server.resume_batch("serie")
    finally:
        other.release()
