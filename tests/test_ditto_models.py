"""Os arquivos do motor realista: o registro de modelos, os caminhos e o fetcher (com fonte falsa, sem rede)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dmaker.domain.models import REGISTRY, exclusive_paths, find_model
from dmaker.media import ditto_models
from dmaker.media.ditto_models import FILES, ModelFile, mirror_downloader, paths_in
from dmaker.media.downloads import RemoteFile
from dmaker.pipeline.model_fetchers import fetch_persona_realista, resolve_fetcher


def fake_file(folder: str, name: str, content: bytes) -> ModelFile:
    remote = RemoteFile(
        name, f"{ditto_models.BASE_URL}/{folder}/{name}", len(content), hashlib.sha256(content).hexdigest()
    )
    return ModelFile(folder, remote)


@pytest.fixture
def tiny_files(monkeypatch) -> tuple[ModelFile, ...]:
    """Dois arquivos pequenos no lugar dos dez reais (que somam 2,3 GB)."""
    files = (
        fake_file("ditto_onnx", "a.onnx", b"aaaa"),
        fake_file("ditto_pytorch/models", "warp_network.pth", b"bbbbbb"),
    )
    monkeypatch.setattr(ditto_models, "FILES", files)
    return files


def test_the_ten_files_have_a_pinned_revision_a_size_and_a_sha256_each():
    assert len(FILES) == 10
    for item in FILES:
        assert len(item.remote.sha256) == 64 and int(item.remote.sha256, 16) >= 0
        assert item.remote.size > 0
        assert ditto_models.REVISION in item.remote.url and item.remote.url.endswith(item.remote.name)
    assert {item.remote.name for item in FILES} >= {"hubert.onnx", "decoder.onnx", "warp_network.pth"}
    assert ditto_models.EXPECTED_SIZE == sum(item.remote.size for item in FILES) == 2_291_086_562


def test_the_model_is_in_the_registry_with_its_files_and_the_openvino_folder():
    spec = find_model("persona-realista")
    assert spec is not None and spec.license == "Apache-2.0" and spec.required_by == ("Persona realista",)
    assert spec.expected_size == ditto_models.EXPECTED_SIZE
    assert "persona-realista/ditto_onnx/hubert.onnx" in spec.paths
    assert "persona-realista/ditto_pytorch/models/warp_network.pth" in spec.paths
    assert "persona-realista/openvino" in spec.paths
    assert set(exclusive_paths(spec)) == set(spec.paths)  # nenhum outro modelo divide os arquivos dele
    assert resolve_fetcher(spec.fetch) is fetch_persona_realista
    assert sum(1 for other in REGISTRY if other.id == spec.id) == 1


def test_paths_say_where_each_piece_lives_and_which_files_are_missing(tmp_path):
    paths = paths_in(tmp_path)
    assert paths.onnx("hubert.onnx") == tmp_path / "persona-realista" / "ditto_onnx" / "hubert.onnx"
    assert paths.warp_weights.name == "warp_network.pth" and paths.face_detector.name == "blaze_face.onnx"
    assert len(paths.missing_files()) == 10 and not paths.has_warp_ir()
    first = FILES[0]
    target = paths.root / first.folder / first.remote.name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    assert first.relative not in paths.missing_files() and len(paths.missing_files()) == 9


def test_the_fetcher_downloads_checks_the_hash_and_then_builds_the_openvino_ir(tmp_path, tiny_files):
    contents = {item.remote.url: item.remote.sha256 for item in tiny_files}
    served = {tiny_files[0].remote.url: b"aaaa", tiny_files[1].remote.url: b"bbbbbb"}
    downloads: list[str] = []

    def download(url: str, destination: Path) -> None:
        downloads.append(url)
        destination.write_bytes(served[url])

    built: list[Path] = []

    def build_ir(paths) -> None:
        built.append(paths.root)
        paths.warp_head_ir.parent.mkdir(parents=True, exist_ok=True)
        paths.warp_head_ir.write_text("x")
        paths.warp_tail_ir.write_text("x")

    fetch_persona_realista(tmp_path, "", downloader=download, build_ir=build_ir)
    assert sorted(downloads) == sorted(contents)
    assert built == [tmp_path / "persona-realista"] and paths_in(tmp_path).has_warp_ir()
    for item in tiny_files:
        assert (tmp_path / "persona-realista" / item.folder / item.remote.name).is_file()

    fetch_persona_realista(tmp_path, "", downloader=download, build_ir=build_ir)  # de novo: tudo já está lá
    assert len(downloads) == 2 and len(built) == 1


def test_a_corrupted_download_is_refused_and_leaves_no_file_behind(tmp_path, tiny_files):
    def corrupt(url: str, destination: Path) -> None:
        destination.write_bytes(b"zzzz")  # o tamanho certo do primeiro arquivo, mas não o conteúdo

    with pytest.raises(RuntimeError, match="corrompido"):
        fetch_persona_realista(tmp_path, "", downloader=corrupt, build_ir=lambda paths: None)
    assert not list((tmp_path / "persona-realista").rglob("*.onnx*"))


def test_the_mirror_downloader_installs_from_a_local_folder_with_the_repository_layout(tmp_path, tiny_files):
    mirror = tmp_path / "espelho"
    (mirror / "ditto_onnx").mkdir(parents=True)
    (mirror / "ditto_pytorch" / "models").mkdir(parents=True)
    (mirror / "ditto_onnx" / "a.onnx").write_bytes(b"aaaa")
    (mirror / "ditto_pytorch" / "models" / "warp_network.pth").write_bytes(b"bbbbbb")
    fetch_persona_realista(
        tmp_path / "models", "", downloader=mirror_downloader(mirror), build_ir=lambda paths: None
    )
    assert (tmp_path / "models" / "persona-realista" / "ditto_onnx" / "a.onnx").read_bytes() == b"aaaa"
