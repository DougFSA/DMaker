"""A instalação do FFmpeg pelo `dmaker setup`: o build completo no lugar do essentials, o FFmpeg dos plugins LV2 e a conferência do
SHA-256 de cada download. Sem rede: o download e o arquivo de soma entram por injeção."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from dmaker import config, setup_tools
from dmaker.setup_tools import (
    FFMPEG_BUILDS,
    FFMPEG_ESSENTIALS,
    FFMPEG_FULL,
    FfmpegBuild,
    extract_archive,
    install_ffmpeg,
    install_lv2_ffmpeg,
    lv2_build,
    parse_checksum,
    sha256_of,
    verify_download,
)

HASH = "a" * 64
EXE = "ffmpeg.exe" if config.os.name == "nt" else "ffmpeg"


def make_zip(content: bytes = b"binario novo") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"ffmpeg-build/bin/{EXE}", content)
    return buffer.getvalue()


class FakeNetwork:
    """O download que grava um zip pronto e o arquivo de soma, e lembra o que foi pedido."""

    def __init__(self, payload: bytes | None = None, honest: bool = True) -> None:
        self.payload = payload if payload is not None else make_zip()
        self.honest = honest
        self.downloaded: list[str] = []

    def download(self, url: str, dst: Path, label: str | None = None) -> Path:
        self.downloaded.append(url)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(self.payload)
        return dst

    def read_text(self, url: str) -> str:
        digest = hashlib.sha256(self.payload).hexdigest() if self.honest else HASH
        return f"{digest}  {url.rsplit('/', 1)[-1].removesuffix('.sha256')}\n"


ZIP_BUILD = FfmpegBuild(
    "de teste", "https://exemplo.test/ffmpeg-build.zip", "https://exemplo.test/ffmpeg-build.zip.sha256", "zip"
)


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """O `bin/` do DMaker numa pasta temporária (o config e o setup_tools guardam o caminho cada um)."""
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(config, "BIN_DIR", bin_dir)
    monkeypatch.setattr(config, "FFMPEG_DIR", bin_dir / "ffmpeg")
    monkeypatch.setattr(config, "FFMPEG_LV2_DIR", bin_dir / "ffmpeg-lv2")
    monkeypatch.setattr(setup_tools, "BIN_DIR", bin_dir)
    monkeypatch.setattr(setup_tools, "FFMPEG_DIR", bin_dir / "ffmpeg")
    monkeypatch.delenv("DMAKER_FFMPEG_DIR", raising=False)
    monkeypatch.setattr(setup_tools, "find_tool", lambda name: _installed(bin_dir / "ffmpeg"))
    return bin_dir


def _installed(folder: Path) -> Path | None:
    found = folder / "bin" / EXE
    return found if found.exists() else None


# ---------- a soma ----------


def test_the_checksum_is_read_from_a_bare_hash_or_from_a_list_by_file_name():
    assert parse_checksum(HASH.upper() + "\n", "x.7z") == HASH  # só o hash, como o .sha256 do gyan.dev
    listing = f"{'b' * 64}  outro.zip\n{HASH} *ffmpeg-n9.0-latest-win64-gpl-9.0.zip\n"  # a lista do BtbN
    assert parse_checksum(listing, "ffmpeg-n9.0-latest-win64-gpl-9.0.zip") == HASH
    with pytest.raises(RuntimeError, match="não achei o SHA-256 de falta.zip"):
        parse_checksum(listing, "falta.zip")
    with pytest.raises(RuntimeError, match="não achei o SHA-256"):
        parse_checksum("isto não é um hash\n", "x.7z")


def test_a_download_whose_sum_does_not_match_is_refused(tmp_path):
    file = tmp_path / "ffmpeg.zip"
    file.write_bytes(b"conteudo")
    verify_download(file, sha256_of(file))
    with pytest.raises(RuntimeError, match="SHA-256 de ffmpeg.zip não confere"):
        verify_download(file, HASH)


# ---------- descompactar ----------


def test_a_zip_is_opened_with_python_and_other_formats_with_the_system_tar(tmp_path, monkeypatch):
    archive = tmp_path / "a.zip"
    archive.write_bytes(make_zip())
    extract_archive(archive, "zip", tmp_path / "saida")
    assert (tmp_path / "saida" / "ffmpeg-build" / "bin" / EXE).read_bytes() == b"binario novo"

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Done", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(setup_tools.subprocess, "run", fake_run)
    extract_archive(tmp_path / "b.7z", "7z", tmp_path / "saida7z")
    assert calls[0][1:] == ["-xf", str(tmp_path / "b.7z"), "-C", str(tmp_path / "saida7z")]
    if config.os.name == "nt":  # o tar do Git Bash é o GNU e não abre .7z: tem de ser o do System32
        assert calls[0][0].lower().endswith("system32\\tar.exe")


def test_a_failing_tar_says_which_archive_and_why(tmp_path, monkeypatch):
    monkeypatch.setattr(
        setup_tools.subprocess,
        "run",
        lambda command, **kwargs: type("Done", (), {"returncode": 1, "stderr": "formato desconhecido"})(),
    )
    with pytest.raises(RuntimeError, match=r"não conseguiu abrir b\.7z: formato desconhecido"):
        extract_archive(tmp_path / "b.7z", "7z", tmp_path / "saida")


# ---------- o ffmpeg principal ----------


def test_the_default_builds_are_the_full_one_first_and_the_essentials_as_a_fallback():
    assert FFMPEG_BUILDS == [FFMPEG_FULL, FFMPEG_ESSENTIALS]
    assert FFMPEG_FULL.url.endswith("ffmpeg-release-full.7z") and FFMPEG_FULL.archive == "7z"
    assert FFMPEG_FULL.checksum == FFMPEG_FULL.url + ".sha256"


def test_a_fresh_install_downloads_checks_and_unpacks_into_bin_ffmpeg(folders):
    network = FakeNetwork()
    installed = install_ffmpeg(
        builds=[ZIP_BUILD], download_file=network.download, read_text=network.read_text
    )
    assert installed == folders / "ffmpeg" / "bin" / EXE and installed.read_bytes() == b"binario novo"
    assert network.downloaded == [ZIP_BUILD.url]
    assert not (folders / "ffmpeg_tmp").exists() and not (folders / "ffmpeg.antigo").exists()


def test_an_essentials_already_installed_is_replaced_without_force_because_it_has_no_ladspa(
    folders, monkeypatch
):
    (folders / "ffmpeg" / "bin").mkdir(parents=True)
    (folders / "ffmpeg" / "bin" / EXE).write_bytes(b"essentials")
    monkeypatch.setattr(setup_tools, "_has_ladspa", lambda executable: False)
    network = FakeNetwork()
    installed = install_ffmpeg(
        builds=[ZIP_BUILD], download_file=network.download, read_text=network.read_text
    )
    assert installed.read_bytes() == b"binario novo" and network.downloaded


def test_a_build_that_already_has_ladspa_is_left_alone_unless_forced(folders, monkeypatch):
    (folders / "ffmpeg" / "bin").mkdir(parents=True)
    (folders / "ffmpeg" / "bin" / EXE).write_bytes(b"completo")
    monkeypatch.setattr(setup_tools, "_has_ladspa", lambda executable: True)
    network = FakeNetwork()
    kept = install_ffmpeg(builds=[ZIP_BUILD], download_file=network.download, read_text=network.read_text)
    assert kept.read_bytes() == b"completo" and network.downloaded == []
    forced = install_ffmpeg(
        force=True, builds=[ZIP_BUILD], download_file=network.download, read_text=network.read_text
    )
    assert forced.read_bytes() == b"binario novo"


def test_a_corrupt_download_is_refused_and_the_next_build_is_tried(folders):
    bad = FakeNetwork(honest=False)
    good = FakeNetwork(make_zip(b"reserva"))

    def download(url, dst, label=None):
        return (bad if "ruim" in url else good).download(url, dst, label)

    def read_text(url):
        return (bad if "ruim" in url else good).read_text(url)

    first = FfmpegBuild(
        "ruim", "https://exemplo.test/ruim.zip", "https://exemplo.test/ruim.zip.sha256", "zip"
    )
    installed = install_ffmpeg(builds=[first, ZIP_BUILD], download_file=download, read_text=read_text)
    assert installed.read_bytes() == b"reserva"
    assert bad.downloaded and good.downloaded


def test_when_every_build_fails_the_install_says_so_and_leaves_no_temporary_folder(folders):
    network = FakeNetwork(honest=False)
    with pytest.raises(RuntimeError, match="Não foi possível baixar o FFmpeg: .*SHA-256"):
        install_ffmpeg(builds=[ZIP_BUILD], download_file=network.download, read_text=network.read_text)
    assert not (folders / "ffmpeg_tmp").exists() and not (folders / "ffmpeg").exists()


def test_a_running_ffmpeg_that_cannot_be_renamed_keeps_the_old_install_and_says_to_close_the_interface(
    folders, monkeypatch
):
    (folders / "ffmpeg" / "bin").mkdir(parents=True)
    (folders / "ffmpeg" / "bin" / EXE).write_bytes(b"em uso")
    monkeypatch.setattr(setup_tools, "_has_ladspa", lambda executable: False)

    def locked(self, target):
        raise PermissionError("em uso por outro processo")

    monkeypatch.setattr(Path, "rename", locked)
    network = FakeNetwork()
    with pytest.raises(RuntimeError, match="Feche a interface"):
        install_ffmpeg(builds=[ZIP_BUILD], download_file=network.download, read_text=network.read_text)
    assert (folders / "ffmpeg" / "bin" / EXE).read_bytes() == b"em uso"


# ---------- o ffmpeg dos plugins LV2 ----------


def test_the_lv2_build_is_picked_by_system_and_only_exists_for_windows_and_linux_x64():
    windows = lv2_build("win32", "AMD64")
    assert windows is not None and windows.url.endswith("win64-gpl-9.0.zip") and windows.archive == "zip"
    assert windows.checksum.endswith("/checksums.sha256")
    linux = lv2_build("linux", "x86_64")
    assert linux is not None and linux.archive == "tar.xz"
    assert lv2_build("darwin", "arm64") is None and lv2_build("win32", "arm64") is None


def test_the_lv2_ffmpeg_goes_to_bin_ffmpeg_lv2_next_to_the_main_one(folders):
    network = FakeNetwork()
    installed = install_lv2_ffmpeg(
        build=ZIP_BUILD, download_file=network.download, read_text=network.read_text
    )
    assert installed == folders / "ffmpeg-lv2" / "bin" / EXE and installed.read_bytes() == b"binario novo"
    assert not (folders / "ffmpeg").exists()  # o principal não é tocado


def test_installing_the_lv2_ffmpeg_again_does_not_download_unless_forced(folders):
    network = FakeNetwork()
    install_lv2_ffmpeg(build=ZIP_BUILD, download_file=network.download, read_text=network.read_text)
    install_lv2_ffmpeg(build=ZIP_BUILD, download_file=network.download, read_text=network.read_text)
    assert len(network.downloaded) == 1
    install_lv2_ffmpeg(
        force=True, build=ZIP_BUILD, download_file=network.download, read_text=network.read_text
    )
    assert len(network.downloaded) == 2


def test_without_a_build_for_the_system_the_lv2_install_points_at_the_environment_variable(
    folders, monkeypatch
):
    monkeypatch.setattr(setup_tools, "lv2_build", lambda platform=None, machine=None: None)
    with pytest.raises(RuntimeError, match="DMAKER_FFMPEG_LV2_DIR"):
        install_lv2_ffmpeg()


def test_the_plugin_ffmpeg_is_found_by_the_environment_variable_then_bin_then_the_main_one(
    tmp_path, monkeypatch
):
    for folder in ("env", "lv2", "principal"):
        (tmp_path / folder / "bin").mkdir(parents=True)
        (tmp_path / folder / "bin" / EXE).write_bytes(b"x")
    monkeypatch.setattr(config, "FFMPEG_LV2_DIR", tmp_path / "lv2")
    monkeypatch.setattr(config, "find_tool", lambda name: tmp_path / "principal" / "bin" / EXE)
    monkeypatch.setenv("DMAKER_FFMPEG_LV2_DIR", str(tmp_path / "env"))
    names = [candidate.parent.parent.name for candidate in config.plugin_ffmpeg_candidates("lv2")]
    assert names == ["env", "lv2", "principal"]
    monkeypatch.delenv("DMAKER_FFMPEG_LV2_DIR")
    assert [c.parent.parent.name for c in config.plugin_ffmpeg_candidates("lv2")] == ["lv2", "principal"]
    assert [c.parent.parent.name for c in config.plugin_ffmpeg_candidates("ladspa")] == [
        "principal"
    ]  # o LADSPA não tem pasta própria
    monkeypatch.setenv("DMAKER_FFMPEG_LADSPA_DIR", str(tmp_path / "env"))
    assert [c.parent.parent.name for c in config.plugin_ffmpeg_candidates("ladspa")] == ["env", "principal"]
