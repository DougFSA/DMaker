"""Rotas /api/models da interface: inventário, baixar como job com progresso, apagar com confirmação e sobras."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker.pipeline.models_service import ModelService
from dmaker.ui import server
from dmaker.ui.models_routes import get_model_service
from tests.test_models_service import ALPHA, BIG, SPECS, write


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()
    return folder


@pytest.fixture
def client(models_dir: Path):
    def fetch(directory: Path, variant: str) -> None:
        write(directory / "alpha" / "peso.bin", BIG)

    service = ModelService(
        models_dir,
        SPECS,
        fetcher_for=lambda dotted: fetch,
        disk_free=lambda path: 10**9,
        poll_seconds=0.01,
    )
    server.app.dependency_overrides[get_model_service] = lambda: service
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.pop(get_model_service, None)


def finished(job_id: str):
    job = server.jobs.get(job_id)
    server.jobs.wait(job, 15)
    return job


def test_inventory_lists_models_with_size_license_and_leftovers(client, models_dir: Path):
    write(models_dir / "beta.onnx", 200)
    write(models_dir / "sobra" / "x.bin", 30)
    body = client.get("/api/models").json()
    by_id = {model["id"]: model for model in body["models"]}
    assert by_id["beta"]["state"] == "installed" and by_id["beta"]["size_bytes"] == 200
    assert by_id["alpha"]["state"] == "absent" and by_id["alpha"]["license"] == "MIT"
    assert by_id["alpha"]["required_by"] == ["função de alpha"]
    assert body["leftovers"] == [{"path": "sobra", "size_bytes": 30, "size_label": "30 B", "is_dir": True}]
    assert body["total_bytes"] == 230 and body["disk_free_bytes"] == 10**9


def test_download_runs_as_a_job_with_progress_and_leaves_the_model_installed(client, models_dir: Path):
    response = client.post(f"/api/models/{ALPHA.id}/download")
    assert response.status_code == 200, response.text
    job = finished(response.json()["job_id"])
    assert job.status == "done", job.error
    assert job.result["state"] == "installed" and job.result["size_bytes"] == BIG
    assert job.progress["percent"] == 100 and "ALPHA" in job.progress["label"]
    assert job.meta == {"kind": "models", "model": "alpha"}
    assert (models_dir / "alpha" / "peso.bin").exists()


def test_download_of_an_unknown_model_is_a_404_and_starts_no_job(client):
    before = len(server.jobs.list())
    missing = client.post("/api/models/fantasma/download")
    assert missing.status_code == 404 and "fantasma" in missing.json()["detail"]
    assert len(server.jobs.list()) == before


def test_removal_plan_names_the_functions_and_remove_needs_confirm(client, models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    plan = client.get("/api/models/alpha/removal").json()
    assert plan["paths"] == ["alpha"] and plan["freed_bytes"] == BIG
    assert plan["stops_working"] == ["função de alpha"] and "função de alpha" in plan["warning"]

    refused = client.post("/api/models/alpha/remove", json={})
    assert refused.status_code == 409 and "função de alpha" in refused.json()["detail"]
    assert (models_dir / "alpha").exists()

    done = client.post("/api/models/alpha/remove", json={"confirm": True})
    assert done.status_code == 200 and done.json()["removed"]["freed_bytes"] == BIG
    assert not (models_dir / "alpha").exists()
    gone = client.post("/api/models/alpha/remove", json={"confirm": True})
    assert gone.status_code == 400 and "não está baixado" in gone.json()["detail"]


def test_prune_needs_confirm_and_only_deletes_the_listed_leftovers(client, models_dir: Path):
    write(models_dir / "beta.onnx", 200)
    write(models_dir / "sobra" / "x.bin", 30)
    write(models_dir / "outra" / "y.bin", 5)
    assert client.post("/api/models/prune", json={"paths": ["sobra"]}).status_code == 409
    assert (models_dir / "sobra").exists()
    done = client.post("/api/models/prune", json={"confirm": True, "paths": ["sobra", "beta.onnx"]})
    assert done.status_code == 200 and done.json()["removed"]["paths"] == ["sobra"]
    assert (models_dir / "beta.onnx").exists() and (models_dir / "outra").exists()
    assert not (models_dir / "sobra").exists()


def test_paths_that_try_to_leave_the_models_dir_are_never_deleted(client, models_dir: Path, tmp_path: Path):
    victim = tmp_path / "importante.txt"
    victim.write_text("nao apague")
    response = client.post("/api/models/prune", json={"confirm": True, "paths": ["../importante.txt"]})
    assert response.status_code == 200 and response.json()["removed"]["paths"] == []
    assert victim.exists()
