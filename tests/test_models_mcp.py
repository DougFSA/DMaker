"""Ferramenta MCP `models`: listar, baixar como job, e apagar só com confirm=true."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker import mcp_server
from dmaker.pipeline.models_service import ModelService
from tests.test_models_service import BIG, SPECS, write


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()

    def fetch(directory: Path, variant: str) -> None:
        write(directory / "alpha" / "peso.bin", BIG)

    service = ModelService(
        folder, SPECS, fetcher_for=lambda dotted: fetch, disk_free=lambda path: 10**9, poll_seconds=0.01
    )
    monkeypatch.setattr("dmaker.pipeline.models_service.shared_service", lambda: service)
    return folder


def test_the_tool_is_registered_with_a_description_that_mentions_confirm():
    import asyncio

    tools = asyncio.run(mcp_server.server.list_tools())
    tool = next(tool for tool in tools if tool.name == "models")
    assert "confirm=true" in tool.description and "action" in str(tool.input_schema)


def test_list_returns_the_inventory_with_sizes_licenses_and_leftovers(models_dir: Path):
    write(models_dir / "beta.onnx", 200)
    write(models_dir / "sobra" / "x.bin", 30)
    listing = mcp_server.models()
    by_id = {model["id"]: model for model in listing["models"]}
    assert by_id["beta"]["state"] == "installed" and by_id["alpha"]["state"] == "absent"
    assert by_id["beta"]["license"] == "MIT" and by_id["beta"]["purpose"]
    assert [item["path"] for item in listing["leftovers"]] == ["sobra"]
    assert listing["total_bytes"] == 230


def test_download_is_a_job_that_installs_the_model(models_dir: Path):
    started = mcp_server.models("download", model_id="alpha", wait_seconds=15)
    assert started["status"] == "done", started
    assert started["result"]["state"] == "installed"
    assert (models_dir / "alpha" / "peso.bin").exists()


def test_remove_and_prune_refuse_without_confirm_and_explain_why(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    write(models_dir / "sobra" / "x.bin", 30)
    with pytest.raises(ValueError, match="função de alpha.*confirm=true"):
        mcp_server.models("remove", model_id="alpha")
    with pytest.raises(ValueError, match="confirm=true"):
        mcp_server.models("prune")
    assert (models_dir / "alpha").exists() and (models_dir / "sobra").exists()

    removed = mcp_server.models("remove", model_id="alpha", confirm=True)
    assert removed["removed"]["freed_bytes"] == BIG and not (models_dir / "alpha").exists()
    pruned = mcp_server.models("prune", confirm=True)
    assert pruned["removed"]["paths"] == ["sobra"] and not (models_dir / "sobra").exists()


def test_download_and_remove_need_a_model_id(models_dir: Path):
    for action in ("download", "remove"):
        with pytest.raises(ValueError, match="model_id"):
            mcp_server.models(action)
    with pytest.raises(Exception, match="fantasma"):
        mcp_server.models("download", model_id="fantasma")
