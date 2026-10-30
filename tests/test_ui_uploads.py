"""Receber arquivos da interface: gravar com limite, nome seguro e nada pela metade no disco."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.ui import uploads
from dmaker.ui.uploads import media_upload_dir, read_upload, save_upload, upload_file_name


@pytest.fixture
def client(tmp_path: Path):
    app = FastAPI()

    @app.post("/save")
    def save(file: Annotated[UploadFile, File()], limit: int = 1000, prefix: str | None = None) -> dict:
        saved = save_upload(file, tmp_path / "destino", limit, "grande demais para o teste", prefix)
        return {"path": saved.path.as_posix(), "size": saved.size}

    @app.post("/read")
    def read(file: Annotated[UploadFile, File()], limit: int = 1000) -> dict:
        return {"size": len(read_upload(file, limit, "grande demais para o teste"))}

    return TestClient(app)


def test_the_content_goes_into_the_name_so_the_same_file_keeps_its_path(client, tmp_path):
    first = client.post("/save", files={"file": ("Minha Entrevista.mp4", b"bytes", "video/mp4")}).json()
    again = client.post("/save", files={"file": ("Minha Entrevista.mp4", b"bytes", "video/mp4")}).json()

    path = Path(first["path"])
    assert first == again and first["size"] == 5
    assert path.name == f"{hashlib.sha256(b'bytes').hexdigest()[:10]}-Minha-Entrevista.mp4"
    assert path.read_bytes() == b"bytes" and path.parent == tmp_path / "destino"


def test_a_name_prefix_replaces_the_hash_so_equal_files_do_not_share_one_path(client):
    one = client.post(
        "/save", params={"prefix": "a1"}, files={"file": ("foto.png", b"x", "image/png")}
    ).json()
    two = client.post(
        "/save", params={"prefix": "b2"}, files={"file": ("foto.png", b"x", "image/png")}
    ).json()

    assert Path(one["path"]).name == "a1-foto.png" and Path(two["path"]).name == "b2-foto.png"
    assert one["path"] != two["path"]


def test_a_file_over_the_limit_is_refused_and_leaves_nothing_behind(client, tmp_path):
    response = client.post("/save", params={"limit": 10}, files={"file": ("grande.bin", b"x" * 11)})

    assert response.status_code == 413 and response.json()["detail"] == "grande demais para o teste"
    assert list((tmp_path / "destino").iterdir()) == []  # nem o arquivo final, nem o `.part`


def test_an_empty_file_is_refused(client, tmp_path):
    response = client.post("/save", files={"file": ("vazio.txt", b"")})

    assert response.status_code == 400 and "vazio" in response.json()["detail"]
    assert list((tmp_path / "destino").iterdir()) == []


def test_reading_into_memory_has_the_same_limit_and_the_same_empty_rule(client):
    assert client.post("/read", files={"file": ("a.txt", b"abc")}).json() == {"size": 3}
    assert client.post("/read", params={"limit": 2}, files={"file": ("a.txt", b"abc")}).status_code == 413
    assert client.post("/read", files={"file": ("a.txt", b"")}).status_code == 400


def test_the_upload_name_is_safe_for_the_disk():
    class Fake:
        def __init__(self, filename):
            self.filename = filename

    assert upload_file_name(Fake("../../Pasta/Meu Vídeo!.MP4")) == "Meu-V-deo.mp4"  # type: ignore[arg-type]
    assert upload_file_name(Fake(None)) == "arquivo.bin"  # type: ignore[arg-type]
    assert upload_file_name(Fake("sem_extensao")) == "sem_extensao.bin"  # type: ignore[arg-type]


def test_the_media_folder_is_read_from_the_config_at_use_time():
    assert media_upload_dir() == config.CACHE_DIR / uploads.UPLOADS_SUBDIR
