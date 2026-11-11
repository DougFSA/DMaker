"""O build do instalador (DMK-71): manifesto, nomes, marcador, lançadores, licenças, notas e a ordem dos comandos."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from dmaker.agent.offline import REQUIRED_MODELS
from dmaker.config import read_install_info
from dmaker.release import licenses, manifest, naming, notes
from dmaker.release.build import (
    BuildOptions,
    ReleaseBuilder,
    constraints_from_freeze,
    wheel_requirement,
)
from dmaker.release.checksums import parse_sha256sums, sha256_file
from dmaker.release.marker import (
    DATA_PLACEHOLDER,
    marker_json,
    marker_template,
    windows_launcher,
    windows_launchers,
)
from dmaker.release.platforms import PLATFORMS, WINDOWS
from dmaker.release.runner import RecordingCommandRunner, ReleaseError

TRACKED = [
    "assets/fonts/Poppins-Regular.ttf",
    "assets/brands/medlycare/brand.json",
    "assets/html/three.module.min.js",
    "assets/pronunciation.json",
    "assets/sfx/click.wav",
    "assets/voices/cliente.wav",
    "assets/macros/minha.json",
    "assets/brands/medlycare/macros/m.json",
    "templates/podcast.json",
    "projects/casamento/spec.json",
    "output/final.mp4",
    "src/dmaker/cli.py",
]


# ---------- manifesto ----------


def test_manifest_never_ships_user_data():
    entries = manifest.repo_entries(TRACKED)
    paths = {entry.dest for entry in entries}
    assert "assets/fonts/Poppins-Regular.ttf" in paths and "templates/podcast.json" in paths
    for forbidden in ("voices", "macros", "projects", "output"):
        assert not any(forbidden in dest.split("/") for dest in paths)
    assert "src/dmaker/cli.py" not in paths


def test_manifest_has_all_default_models_and_the_binaries():
    entries = manifest.build_manifest(TRACKED)
    model_paths = {entry.dest for entry in entries if entry.target == "data"}
    assert {"cache/models/omnivoice", "cache/models/rvm_resnet50_fp32.onnx"} <= model_paths
    assert "cache/models/kokoro/kokoro-v1.0.onnx" in model_paths
    assert manifest.default_model_ids() == tuple(model_id for model_id, _ in REQUIRED_MODELS)
    assert len(model_paths) == len({e.dest for e in entries if e.target == "data"})  # sem repetidos
    programs = {entry.dest for entry in entries if entry.target == "program"}
    assert {"bin/ffmpeg", "bin/ffmpeg-lv2", "bin/playwright"} <= programs
    assert not any("innosetup" in dest for dest in programs)


def test_every_manifest_entry_has_a_reason():
    assert all(entry.reason for entry in manifest.build_manifest(TRACKED))


# ---------- nomes ----------


def test_names_carry_the_version():
    assert naming.installer_name("2.0.0", "windows") == "DMaker-2.0.0-windows-x64.exe"
    assert naming.slice_names("2.0.0", "windows", 3) == [
        "DMaker-2.0.0-windows-x64-1.bin",
        "DMaker-2.0.0-windows-x64-2.bin",
        "DMaker-2.0.0-windows-x64-3.bin",
    ]
    assert naming.installer_files("2.0.0", "windows", 1)[0].endswith(".exe")
    assert naming.release_folder_name("2.0.0") == "v2.0.0"


def test_slice_is_below_two_gib():
    assert naming.SLICE_BYTES < 2 * 1024**3


# ---------- marcador e lançadores ----------


def test_marker_json_round_trips_through_config(tmp_path):
    (tmp_path / "instalacao.json").write_text(
        marker_json("2.0.0", str(tmp_path / "dados ç")), encoding="utf-8"
    )
    info = read_install_info(tmp_path)
    assert info and info.version == "2.0.0" and info.data_dir.name == "dados ç"


def test_marker_template_has_the_placeholder():
    assert json.loads(marker_template("2.0.0")) == {"versao": "2.0.0", "dados": DATA_PLACEHOLDER}


def test_launchers_use_the_python_next_to_them():
    cmd = windows_launcher()
    assert '"%~dp0python\\python.exe" -m dmaker %*' in cmd
    assert "\r\n" in cmd and "PYTHONUTF8" in cmd
    mcp = windows_launchers()["dmaker-mcp.cmd"]
    assert "-m dmaker mcp %*" in mcp
    assert not any(
        ":\\" in line and "%~dp0" not in line for line in cmd.splitlines()
    )  # sem caminho de unidade


# ---------- licenças ----------


def test_every_default_model_has_a_license_and_the_blocked_ones_are_flagged():
    items = licenses.license_items()
    names = " ".join(item.name for item in items)
    for fragment in ("FFmpeg", "Python", "Chromium", "Ollama", "Whisper", "OmniVoice", "Kokoro", "Demucs"):
        assert fragment in names
    assert set(licenses.MODEL_LICENSES) >= set(manifest.default_model_ids())
    assert licenses.blocked_models() == ["omnivoice"]
    text = licenses.license_notice("2.0.0")
    assert "GPL v3" in text and "ATENÇÃO" in text


# ---------- notas ----------


def test_release_notes_list_every_file_with_sha256():
    files = [
        notes.ReleaseFile("DMaker-2.0.0-windows-x64.exe", 2_000_000, "a" * 64),
        notes.ReleaseFile("DMaker-2.0.0-windows-x64-1.bin", 3 * 1024**3, "b" * 64),
    ]
    changelog = "## [Não lançado]\n\n## v2 — 2026-11-03\n\n- DMK-1 algo novo\n\n## v1 — 2026-10-27\n- velho\n"
    text = notes.release_notes("2.0.0", files, "Windows x64", changelog)
    assert "a" * 64 in text and "b" * 64 in text and "3,00 GB" in text
    assert "mesma pasta" in text and "DMK-1 algo novo" in text and "velho" not in text


def test_changelog_section_missing_version_is_empty():
    assert notes.changelog_section("## v1 — x\n- a\n", "3.0.0") == ""


# ---------- build ----------


def test_constraints_drop_the_package_itself_and_non_pins():
    freeze = "torch==2.15.0+cpu\ndmaker @ file:///x\nDMaker==2.0.0\n-e git+x#egg=y\nnumpy==2.1.0\n"
    assert constraints_from_freeze(freeze) == "torch==2.15.0+cpu\nnumpy==2.1.0\n"


def test_wheel_requirement_has_the_extras():
    spec = wheel_requirement(Path("d.whl"))
    assert spec.endswith("[voice,captions,lote,agente,html,docs]")


def test_parse_sha256sums():
    assert parse_sha256sums(f"{'A' * 64}  a.tar.gz\n{'b' * 64} *b.exe\n") == {
        "a.tar.gz": "a" * 64,
        "b.exe": "b" * 64,
    }


class FakeDownloader:
    def __init__(self, python_archive: bytes):
        self.python_archive = python_archive
        self.fetched: list[str] = []

    def fetch(self, url: str, destination: Path) -> None:
        self.fetched.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith("SHA256SUMS"):
            from hashlib import sha256

            digest = sha256(self.python_archive).hexdigest()
            destination.write_text(f"{digest}  {WINDOWS.python_archive}\n", encoding="utf-8")
        elif url.endswith(".tar.gz"):
            destination.write_bytes(self.python_archive)
        elif url.endswith("sha256sum.txt"):
            raise OSError("sem lista")
        else:
            destination.write_bytes(b"ollama")


def fake_python_archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, data in (("python/python.exe", b"exe"), ("python/Lib/site-packages/x.py", b"x = 1")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
        scripts = tarfile.TarInfo("python/Scripts/pip.exe")
        scripts.size = 1
        bundle.addfile(scripts, io.BytesIO(b"p"))
    return buffer.getvalue()


@pytest.fixture
def tiny_roots(tmp_path):
    """Um clone e uma pasta principal minúsculos, com só o que o manifesto pede."""
    repo, main = tmp_path / "repo", tmp_path / "principal"
    for entry in manifest.build_manifest(TRACKED):
        root = repo if entry.origin == "repo" else main
        target = root / entry.source
        if entry.origin == "repo":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "arquivo.bin").write_bytes(b"m")
    (repo / "frontend").mkdir()
    (repo / "THIRD_PARTY.md").write_text("terceiros", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## v2 — 2026-11-03\n\n- DMK-1 algo\n", encoding="utf-8")
    return repo, main


def run_build(tiny_roots, **overrides):
    repo, main = tiny_roots
    tracked = "\0".join(TRACKED) + "\0"
    runner = RecordingCommandRunner(
        outputs={
            ("git", "ls-files"): tracked,
            ("host-python", "-m", "pip", "freeze"): "torch==2.15.0+cpu\ndmaker==2.0.0\n",
        }
    )
    options = BuildOptions(
        version="2.0.0",
        repo_root=repo,
        main_root=main,
        host_python="host-python",
        keep_staging=True,
        **overrides,
    )
    downloader = FakeDownloader(fake_python_archive())
    builder = ReleaseBuilder(options, runner, downloader, log=lambda _line: None)
    # o wheel e a saída do ISCC são feitos pelos comandos externos: aqui o teste os põe no lugar
    wheels = builder.work / "wheels"

    original_run = runner.run

    def run(command, **kwargs):
        text = original_run(command, **kwargs)
        if "wheel" in command:
            wheels.mkdir(parents=True, exist_ok=True)
            (wheels / "dmaker-2.0.0-py3-none-any.whl").write_bytes(b"w")
        if command[0].endswith("ISCC.exe"):
            (builder.output / "DMaker-2.0.0-windows-x64.exe").write_bytes(b"setup")
            (builder.output / "DMaker-2.0.0-windows-x64-1.bin").write_bytes(b"dados")
        return text

    runner.run = run  # type: ignore[method-assign]
    return builder, runner, downloader


def test_build_runs_the_external_commands_in_order(tiny_roots):
    builder, runner, _ = run_build(tiny_roots)
    result = builder.build()
    kinds = [" ".join(c.command[:3]) for c in runner.commands]
    wanted = [
        "npm run build",
        "host-python -m pip",  # wheel
        "git ls-files -z",  # tracked (no stage) vem depois do pip install
    ]
    assert kinds[0] == wanted[0]
    commands = [c.command for c in runner.commands]
    wheel_at = next(i for i, c in enumerate(commands) if "wheel" in c)
    freeze_at = next(i for i, c in enumerate(commands) if "freeze" in c)
    install_at = next(i for i, c in enumerate(commands) if "install" in c)
    compile_at = next(i for i, c in enumerate(commands) if "compileall" in c)
    git_at = next(i for i, c in enumerate(commands) if c[0] == "git")
    iscc_at = next(i for i, c in enumerate(commands) if c[0].endswith("ISCC.exe"))
    assert 0 < wheel_at < freeze_at < install_at < compile_at < git_at < iscc_at
    install = commands[install_at]
    assert install[0].endswith("python.exe") and "torch" in install and "torchaudio" in install
    assert "https://download.pytorch.org/whl/cpu" in install
    assert install[-3].endswith("[voice,captions,lote,agente,html,docs]")
    iscc = commands[iscc_at]
    assert "/DVersao=2.0.0" in iscc and any(a.startswith("/DFatia=") for a in iscc)
    assert [f.name for f in result.files] == [
        "DMaker-2.0.0-windows-x64.exe",
        "DMaker-2.0.0-windows-x64-1.bin",
    ]
    assert result.blocked == ["omnivoice"]


def test_build_stages_program_and_data_without_user_data(tiny_roots):
    builder, _, _ = run_build(tiny_roots)
    builder.build()
    program, data = builder.program, builder.models
    assert (program / "assets/fonts/Poppins-Regular.ttf").exists()
    assert (program / "bin/ffmpeg/arquivo.bin").exists()
    assert (data / "cache/models/omnivoice/arquivo.bin").exists()
    assert not (program / "assets/voices").exists() and not (program / "assets/macros").exists()
    assert not (program / "python/Scripts").exists()  # os .exe do pip têm caminho absoluto
    assert (program / "dmaker.cmd").exists() and (program / "dmaker-mcp.cmd").exists()
    assert (program / "licencas/LICENCAS.txt").read_text(encoding="utf-8-sig").startswith("DMaker 2.0.0")
    assert json.loads((program / "instalacao.json.modelo").read_text(encoding="utf-8"))["versao"] == "2.0.0"
    out = builder.output
    assert "mesma pasta" in (out / "NOTAS.md").read_text(encoding="utf-8")
    sums = parse_sha256sums((out / "SHA256SUMS.txt").read_text(encoding="utf-8"))
    assert sums["DMaker-2.0.0-windows-x64.exe"] == sha256_file(out / "DMaker-2.0.0-windows-x64.exe")


def test_build_checks_the_python_archive_checksum(tiny_roots):
    builder, _, downloader = run_build(tiny_roots)
    downloader.python_archive = (
        b"outra coisa"  # o SHA256SUMS é calculado dele; trocar depois quebra a conferência
    )
    (builder.downloads).mkdir(parents=True)
    (builder.downloads / WINDOWS.python_archive).write_bytes(b"corrompido")
    (builder.downloads / "SHA256SUMS-python-windows").write_text(
        f"{'0' * 64}  {WINDOWS.python_archive}\n", encoding="utf-8"
    )
    with pytest.raises(ReleaseError, match="SHA-256"):
        builder.build()


def test_windows_is_the_only_platform_for_now():
    assert set(PLATFORMS) == {"windows"}
    assert "%2B" in WINDOWS.python_url
