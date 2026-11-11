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
    collect_release_files,
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
from dmaker.release.platforms import LINUX, PLATFORMS, WINDOWS
from dmaker.release.runner import RecordingCommandRunner, ReleaseError
from dmaker.release.staging import longest_relative_path
from dmaker.release.targets.windows import max_install_folder

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


def test_linux_manifest_has_the_same_models_but_builds_its_own_binaries():
    windows = manifest.build_manifest(TRACKED, "windows")
    linux = manifest.build_manifest(TRACKED, "linux")
    assert {e.dest for e in windows if e.target == "data"} == {e.dest for e in linux if e.target == "data"}
    binaries = {e.dest: e.origin for e in linux if e.dest.startswith("bin/")}
    assert binaries == {"bin/ffmpeg": "build", "bin/ffmpeg-lv2": "build", "bin/playwright": "build"}
    assert {e.dest: e.origin for e in windows if e.dest.startswith("bin/")}["bin/ffmpeg"] == "pasta"


def test_excluded_model_leaves_the_manifest_and_a_typo_is_refused():
    entries = manifest.build_manifest(TRACKED, "windows", ("omnivoice",))
    assert "cache/models/omnivoice" not in {e.dest for e in entries}
    assert "cache/models/kokoro/kokoro-v1.0.onnx" in {e.dest for e in entries}
    with pytest.raises(ValueError, match="fora do pacote"):
        manifest.build_manifest(TRACKED, "windows", ("omnivoyce",))


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


def test_linux_names_are_run_and_part():
    assert naming.installer_name("2.0.0", "linux") == "DMaker-2.0.0-linux-x64.run"
    assert naming.slice_names("2.0.0", "linux", 2) == [
        "DMaker-2.0.0-linux-x64-1.part",
        "DMaker-2.0.0-linux-x64-2.part",
    ]


def test_slice_is_below_two_gib():
    assert naming.SLICE_BYTES < 2 * 1024**3


def test_tag_is_the_version_name():
    assert naming.tag_for("2.0.0") == "v2"
    assert naming.tag_for("12.0.0") == "v12"


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


def test_every_default_model_has_a_license_and_omnivoice_ships_with_the_non_commercial_notice():
    items = licenses.license_items()
    names = " ".join(item.name for item in items)
    for fragment in ("FFmpeg", "Python", "Chromium", "Ollama", "Whisper", "OmniVoice", "Kokoro", "Demucs"):
        assert fragment in names
    assert set(licenses.MODEL_LICENSES) >= set(manifest.default_model_ids())
    assert licenses.blocked_models() == []  # o OmniVoice (CC BY-NC) vai no pacote, com o aviso
    omni = licenses.MODEL_LICENSES["omnivoice"]
    assert omni.redistributable and omni.non_commercial and "CC BY-NC 4.0" in omni.license
    text = licenses.license_notice("2.0.0")
    assert "GPL v3" in text and "AVISO DE USO NÃO COMERCIAL" in text and "somente não comercial" in text


def test_excluded_model_leaves_the_notice_and_the_list():
    text = licenses.license_notice("2.0.0", "windows", ("omnivoice",))
    assert "AVISO DE USO NÃO COMERCIAL" not in text
    assert "baixam no primeiro uso: omnivoice" in text
    assert "OmniVoice" not in " ".join(
        item.name for item in licenses.license_items("windows", ("omnivoice",))
    )
    assert licenses.non_commercial_models(("omnivoice",)) == []


def test_linux_license_list_names_the_linux_binaries():
    names = " ".join(item.name for item in licenses.license_items("linux"))
    assert "BtbN" in names and "gyan" not in names


# ---------- notas ----------


def _files(platform: str) -> list[notes.ReleaseFile]:
    ext, part = (".exe", ".bin") if platform == "windows" else (".run", ".part")
    return [
        notes.ReleaseFile(f"DMaker-2.0.0-{platform}-x64{ext}", 2_000_000, "a" * 64),
        notes.ReleaseFile(f"DMaker-2.0.0-{platform}-x64-1{part}", 3 * 1024**3, "b" * 64),
    ]


CHANGELOG = (
    "## [Não lançado]\n\n## v2 — 2026-11-03\n\n### Added\n\n- DMK-1 algo novo\n\n"
    "### Pré-requisitos na máquina\n\n- instale o extra voice\n\n### Fixed\n\n- DMK-2 conserto\n\n"
    "## v1 — 2026-10-27\n- velho\n"
)


def test_release_notes_have_one_section_per_system_with_sha256_and_how_to_check():
    text = notes.release_notes("2.0.0", {"windows": _files("windows"), "linux": _files("linux")}, CHANGELOG)
    assert "## Windows x64" in text and "## Linux x64" in text
    assert text.count("a" * 64) == 2 and text.count("b" * 64) == 2 and "3,00 GB" in text
    assert "certutil -hashfile" in text and "sha256sum -c SHA256SUMS.txt --ignore-missing" in text
    assert "sh DMaker-2.0.0-linux-x64.run" in text and "mesma pasta" in text
    assert "DMK-1 algo novo" in text and "DMK-2 conserto" in text and "velho" not in text


def test_release_notes_drop_the_developer_prerequisites_section():
    text = notes.release_notes("2.0.0", {"windows": _files("windows")}, CHANGELOG)
    assert "Pré-requisitos" not in text and "instale o extra voice" not in text
    assert "## Linux x64" not in text  # só os sistemas que têm arquivo


def test_release_notes_carry_the_non_commercial_notice_and_the_excluded_models():
    text = notes.release_notes("2.0.0", {"windows": _files("windows")}, "")
    assert "Aviso de uso não comercial" in text and "CC BY-NC 4.0" in text
    without = notes.release_notes("2.0.0", {"windows": _files("windows")}, "", ("omnivoice",))
    assert "Aviso de uso não comercial" not in without
    assert "baixam no primeiro uso" in without and "`omnivoice`" in without


def test_release_notes_over_the_limit_cut_the_changes_and_link_the_changelog():
    huge = "## v2 — 2026-11-03\n\n### Added\n\n"
    huge += "".join(f"- DMK-{n} linha comprida de verdade {'y' * 120}\n" for n in range(1000))
    text = notes.release_notes("2.0.0", {"windows": _files("windows")}, huge, limit=5000)
    assert "linha comprida" not in text and len(text) < 5000
    assert "https://github.com/DougFSA/DMaker/blob/v2/CHANGELOG.md" in text


def test_changelog_section_missing_version_is_empty():
    assert notes.changelog_section("## v1 — x\n- a\n", "3.0.0") == ""


def test_drop_subsection_keeps_the_neighbours():
    section = "### Added\n\n- a\n\n### Pré-requisitos na máquina\n\n- b\n\n### Fixed\n\n- c"
    out = notes.drop_subsection(section, "Pré-requisitos na máquina")
    assert "- a" in out and "- c" in out and "- b" not in out


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


def make_tiny_roots(tmp_path: Path) -> tuple[Path, Path]:
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


@pytest.fixture
def tiny_roots(tmp_path):
    return make_tiny_roots(tmp_path)


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
    commands = [c.command for c in runner.commands]
    assert commands[0][:3] == ("npm", "run", "build")
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
    assert result.blocked == []


def test_every_pip_and_python_of_the_build_runs_isolated(tiny_roots):
    """Na parte 1 o pip enxergou o site-packages do usuário e desinstalou pacotes dele: nenhum python do build pode."""
    builder, runner, _ = run_build(tiny_roots)
    builder.build()
    isolated = {"PYTHONNOUSERSITE": "1", "PYTHONPATH": "", "PYTHONHOME": "", "PIP_USER": "0"}
    for recorded in runner.commands:
        if recorded.command[0] == "host-python" or recorded.command[0].endswith("python.exe"):
            assert recorded.env and isolated.items() <= recorded.env.items(), recorded.command


def test_iscc_receives_the_path_length_limits(tiny_roots):
    builder, runner, _ = run_build(tiny_roots)
    builder.build()
    iscc = next(c.command for c in runner.commands if c.command[0].endswith("ISCC.exe"))
    max_program = next(a for a in iscc if a.startswith("/DMaxPrograma="))
    max_data = next(a for a in iscc if a.startswith("/DMaxDados="))
    longest = longest_relative_path(builder.program)
    assert longest > 0
    assert max_program == f"/DMaxPrograma={max_install_folder(longest)}"
    assert max_data == f"/DMaxDados={max_install_folder(longest_relative_path(builder.models))}"
    # a pasta mais longa permitida, uma barra e o caminho mais longo do pacote cabem em 259 caracteres
    assert int(max_program.split("=")[1]) + 1 + longest == 259


def test_the_git_listing_is_not_printed_in_the_log(tiny_roots):
    builder, runner, _ = run_build(tiny_roots)
    logged: list[str] = []
    builder.log = logged.append
    builder.build()
    listing = next(c for c in runner.commands if c.command[0] == "git")
    assert listing.quiet
    assert any("arquivos versionados" in line for line in logged)
    assert not any("Poppins" in line for line in logged)


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
    text = (out / "NOTAS.md").read_text(encoding="utf-8")
    assert "mesma pasta" in text and "## Windows x64" in text
    sums = parse_sha256sums((out / "SHA256SUMS.txt").read_text(encoding="utf-8"))
    assert sums["DMaker-2.0.0-windows-x64.exe"] == sha256_file(out / "DMaker-2.0.0-windows-x64.exe")


def test_without_model_leaves_it_out_of_the_package_and_the_notes(tiny_roots):
    builder, _, _ = run_build(tiny_roots, excluded_models=("omnivoice",))
    builder.build()
    assert not (builder.models / "cache/models/omnivoice").exists()
    assert (builder.models / "cache/models/kokoro/kokoro-v1.0.onnx").exists()
    notes_text = (builder.output / "NOTAS.md").read_text(encoding="utf-8")
    assert "baixam no primeiro uso" in notes_text and "Aviso de uso não comercial" not in notes_text
    licenses_text = (builder.program / "licencas/LICENCAS.txt").read_text(encoding="utf-8-sig")
    assert "baixam no primeiro uso: omnivoice" in licenses_text


def test_without_model_refuses_an_unknown_id(tiny_roots):
    repo, main = tiny_roots
    options = BuildOptions(version="2.0.0", repo_root=repo, main_root=main, excluded_models=("naoexiste",))
    with pytest.raises(ReleaseError, match="fora do pacote"):
        ReleaseBuilder(options, RecordingCommandRunner(), FakeDownloader(b""), log=lambda _l: None)


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


def test_rebuilding_one_system_keeps_the_files_of_the_other(tiny_roots):
    builder, _, _ = run_build(tiny_roots)
    for name in ("DMaker-2.0.0-linux-x64.run", "DMaker-2.0.0-linux-x64-1.part"):
        builder.output.mkdir(parents=True, exist_ok=True)
        (builder.output / name).write_bytes(b"linux")
    builder.build()
    found = collect_release_files(builder.output, "2.0.0")
    assert set(found) == {"windows", "linux"}
    sums = (builder.output / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert "linux-x64.run" in sums and "windows-x64.exe" in sums
    assert "## Linux x64" in (builder.output / "NOTAS.md").read_text(encoding="utf-8")


def test_both_systems_are_registered_platforms():
    assert set(PLATFORMS) == {"windows", "linux"}
    assert "%2B" in WINDOWS.python_url and "linux-gnu" in LINUX.python_archive
    assert LINUX.installer_extension == ".run" and LINUX.part_extension == ".part"


def test_doctor_offline_names_the_installed_python_not_the_venv(monkeypatch, tmp_path):
    from dmaker import config
    from dmaker.agent.offline import python_environment_label

    monkeypatch.setattr(config, "INSTALL", config.InstallInfo(tmp_path, "2.0.0", tmp_path / "dados"))
    label = python_environment_label()
    assert "o Python do programa instalado" in label and str(tmp_path / "python") in label
    assert ".venv" not in label
    monkeypatch.setattr(config, "INSTALL", None)
    assert python_environment_label() == "o ambiente Python do DMaker (.venv)"
