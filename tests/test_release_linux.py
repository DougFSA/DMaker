"""O pacote do Linux (DMK-71): o contêiner, o `.run`, os lançadores, o desinstalador e a ordem dos comandos."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from dmaker.release import linux_container as container
from dmaker.release import linux_scripts as scripts
from dmaker.release.build import BuildOptions, ReleaseBuilder
from dmaker.release.checksums import sha256_file
from dmaker.release.manifest import build_manifest
from dmaker.release.platforms import LINUX
from dmaker.release.runner import RecordingCommandRunner
from dmaker.setup_tools import FFMPEG_LV2_BUILDS
from tests.test_release import TRACKED, make_tiny_roots

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def tiny_roots(tmp_path):
    return make_tiny_roots(tmp_path)


FFMPEG_NAME = FFMPEG_LV2_BUILDS[("linux", "x64")].url.rsplit("/", 1)[-1]
GIT_BASH = Path("C:/Program Files/Git/usr/bin")


def _find_shell() -> str | None:
    """O dash (o `sh` do Ubuntu) onde houver; no Windows, o que acompanha o Git."""
    found = shutil.which("dash") or shutil.which("sh")
    if found:
        return found
    for name in ("dash.exe", "sh.exe"):
        if (GIT_BASH / name).exists():
            return str(GIT_BASH / name)
    return None


SHELL = _find_shell()


def _plan(**overrides) -> container.ContainerPlan:
    values = {
        "version": "2.0.0",
        "python_archive": LINUX.python_archive,
        "ffmpeg_archive": FFMPEG_NAME,
        "ollama_archive": "ollama-linux-amd64-0.40.16.tar.zst",
        "wheel_name": "dmaker-2.0.0-py3-none-any.whl",
        "extras": ("voice", "captions"),
        "model_paths": ["omnivoice", "kokoro/kokoro-v1.0.onnx"],
    }
    values.update(overrides)
    return container.ContainerPlan(**values)


# ---------- o script do contêiner ----------


def test_container_script_runs_the_steps_in_order():
    script = container.build_script(_plan())
    steps = [
        "apt-get install",
        "== Python portátil",
        "== pip install",
        "== compileall",
        "== FFmpeg",
        "== Chromium (Playwright)",
        "== Ollama",
        "== permissões e tamanhos",
        "== partes (tar | gzip | split)",
    ]
    positions = [script.index(step) for step in steps]
    assert positions == sorted(positions)


def test_container_script_isolates_every_python_and_keeps_the_heavy_work_off_the_wsl_disk():
    script = container.build_script(_plan())
    assert "export PYTHONNOUSERSITE=1 PYTHONPATH= PYTHONHOME= PIP_USER=0" in script
    assert "export TMPDIR=/work/tmp" in script  # o temporário do pip no X:, não no disco do contêiner
    assert "--no-cache-dir" in script  # sem cache do pip no disco virtual do WSL
    assert "-c /work/restricoes.txt" in script and "https://download.pytorch.org/whl/cpu" in script
    assert "/work/wheels/dmaker-2.0.0-py3-none-any.whl[voice,captions]" in script
    assert "torch torchaudio" in script


def test_container_script_builds_the_binaries_and_measures_what_the_notes_report():
    script = container.build_script(_plan())
    assert f"/baixados/{FFMPEG_NAME}" in script and "--strip-components=1" in script
    assert "ln -sfn ffmpeg" in script and "bin/ffmpeg-lv2" in script
    assert "-hide_banner -filters >/work/filtros.txt" in script
    assert (
        'PLAYWRIGHT_BROWSERS_PATH="$PROGRAMA/bin/playwright"' in script
        and "playwright install chromium" in script
    )
    assert "ldd" in script and "/work/chromium-libs.txt" in script
    assert "zstd -dc" in script and "ollama-linux-amd64-0.40.16.tar.zst" in script
    assert "du -sb" in script and "/work/tamanho-programa.txt" in script


def test_container_script_streams_into_parts_below_two_gib():
    script = container.build_script(_plan())
    assert "tar -cf -" in script and "| gzip -3" in script
    assert "split -b 2000000000 -d -a 1 --numeric-suffixes=1 --additional-suffix=.part" in script
    assert "/saida/DMaker-2.0.0-linux-x64-" in script
    assert container.SLICE_BYTES < 2 * 1024**3


def test_model_transform_prefixes_only_the_listed_paths():
    expression = container.model_transform(["omnivoice", "kokoro/kokoro-v1.0.onnx"])
    assert expression == "s,^(kokoro/kokoro-v1[.]0[.]onnx|omnivoice),dados/cache/models/&,x"


def test_docker_run_mounts_and_clean_command():
    command = container.docker_run(
        "docker", [(Path("X:/w"), "/work", False), (Path("X:/d"), "/baixados", True)], ["sh", "x.sh"]
    )
    assert command[:3] == ["docker", "run", "--rm"]
    assert "X:/w:/work" in command and "X:/d:/baixados:ro" in command
    assert command[-3:] == ["ubuntu:22.04", "sh", "x.sh"] or command[-3:] == [
        container.BUILD_IMAGE,
        "sh",
        "x.sh",
    ]
    clean = container.clean_command("docker", Path("X:/w"))
    assert "rm -rf /work/programa" in clean[-1] and "/work/wheels" not in clean[-1]  # o wheel já foi feito


# ---------- scripts puros ----------


LDD = """\
\tlinux-vdso.so.1 (0x00007ffd)
\tlibnss3.so => /lib/x86_64-linux-gnu/libnss3.so (0x00007f)
\tlibatk-1.0.so.0 => not found
\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f)
\tlibX11.so.6 => not found
\t/lib64/ld-linux-x86-64.so.2 (0x00007f)
"""


def test_ldd_parsing_keeps_only_non_base_libraries():
    assert scripts.parse_ldd_libraries(LDD) == ["libX11.so.6", "libatk-1.0.so.0", "libnss3.so"]
    libraries = scripts.chromium_libraries(LDD)
    assert "libasound.so.2" in libraries  # o Chromium abre por dlopen, o ldd não vê
    assert "libc.so.6" not in libraries


def test_apt_packages_follow_the_ubuntu_rename():
    libraries = ["libatk-1.0.so.0", "libnss3.so", "libnssutil3.so", "libasound.so.2", "libdesconhecida.so.1"]
    assert scripts.apt_packages_for(libraries, 22) == ["libatk1.0-0", "libnss3", "libasound2"]
    assert scripts.apt_packages_for(libraries, 24) == ["libatk1.0-0t64", "libnss3", "libasound2t64"]


def test_parse_filters_finds_ladspa_and_lv2():
    listing = (
        " T.. ladspa            N->A       Apply LADSPA effect.\n ... lv2   N->A  x\n TSC volume  A->A  y\n"
    )
    assert scripts.parse_filters(listing) == {"ladspa": True, "lv2": True}
    assert scripts.parse_filters(" TSC volume  A->A  y\n") == {"ladspa": False, "lv2": False}


def _parts() -> list[scripts.PartInfo]:
    return [
        scripts.PartInfo("DMaker-2.0.0-linux-x64-1.part", 1900, "a" * 64),
        scripts.PartInfo("DMaker-2.0.0-linux-x64-2.part", 700, "b" * 64),
    ]


def _render(**overrides) -> str:
    template = (REPO / scripts.INSTALLER_FOLDER / scripts.INSTALLER_TEMPLATE).read_text(encoding="utf-8")
    values = {
        "version": "2.0.0",
        "parts": _parts(),
        "libraries": ["libnss3.so", "libatk-1.0.so.0"],
        "program_bytes": 10 * 1024**3,
        "data_bytes": 4 * 1024**3,
    }
    values.update(overrides)
    return scripts.render_installer(template, **values)


def test_run_script_embeds_the_part_names_sizes_and_hashes():
    text = _render()
    assert f"{'a' * 64} 1900 DMaker-2.0.0-linux-x64-1.part" in text
    assert f"{'b' * 64} 700 DMaker-2.0.0-linux-x64-2.part" in text
    assert 'VERSAO="2.0.0"' in text and 'NOME_BASE="DMaker-2.0.0-linux-x64"' in text
    assert f"BYTES_PROGRAMA={10 * 1024**3}" in text
    assert "@@" not in text.replace("@@PROGRAMA@@", "").replace("@@DADOS@@", "").replace("@@BIN@@", "")
    assert '        libnss3.so) echo "libnss3" ;;' in text
    assert '        libatk-1.0.so.0) echo "libatk1.0-0@T64@" ;;' in text


def test_run_script_is_posix_shell_and_checks_what_it_must():
    text = _render()
    assert text.startswith("#!/bin/sh\n")
    for must in ("--sim", "--programa", "--dados", "sha256sum", "df -Pk", "ldconfig", "--skip-old-files"):
        assert must in text
    assert "sudo apt install" in text and "~/.local/opt/dmaker" in text.replace(
        "$HOME/.local/opt/dmaker", "~/.local/opt/dmaker"
    )
    for bashism in ("[[", "function ", "local ", "<<<"):
        assert bashism not in text, bashism
    assert "\r" not in text


def test_run_script_refuses_to_mix_the_folders_and_foreign_folders():
    text = _render()
    assert "não pode ficar dentro da pasta do programa" in text
    assert "não pode ficar dentro da pasta dos dados" in text
    assert "não é uma instalação do DMaker" in text
    assert "ollama" in text and "command -v ollama" in text and "systemctl --user" in text


def test_render_refuses_a_template_with_an_unknown_mark():
    with pytest.raises(ValueError, match="sem valor"):
        scripts.render_installer("x @@DESCONHECIDO@@", "2.0.0", _parts(), [], 1, 1)


def _templates() -> dict[str, str]:
    return scripts.read_installer_templates(REPO)


def test_launchers_use_the_program_python_without_user_site():
    templates = _templates()
    dmaker = templates["lancadores/dmaker.sh"]
    assert 'PYTHONNOUSERSITE=1 PYTHONUTF8=1 exec "@@PROGRAMA@@/python/bin/python3" -m dmaker "$@"' in dmaker
    assert '-m dmaker mcp "$@"' in templates["lancadores/dmaker-mcp.sh"]
    assert 'exec "@@PROGRAMA@@/ollama/bin/ollama" "$@"' in templates["lancadores/ollama.sh"]
    for name in ("dmaker.sh", "dmaker-mcp.sh", "ollama.sh"):
        assert templates[f"lancadores/{name}"].startswith("#!/bin/sh\n")


def test_desktop_entry_and_user_service():
    templates = _templates()
    desktop = templates["lancadores/dmaker.desktop"]
    assert "Exec=@@BIN@@/dmaker ui" in desktop and "Type=Application" in desktop and "Name=DMaker" in desktop
    service = templates["lancadores/dmaker-ollama.service"]
    assert (
        "ExecStart=@@PROGRAMA@@/ollama/bin/ollama serve" in service and "WantedBy=default.target" in service
    )


def test_uninstaller_keeps_data_unless_told_and_only_removes_what_is_ours():
    text = _templates()["desinstalar.sh"]
    assert "--sim" in text and "--apagar-dados" in text
    assert 'OLLAMA_NOSSO" != "true"' in text  # o Ollama de outra origem fica
    assert "disable --now dmaker-ollama.service" in text
    assert "grep -qF" in text  # só tira o lançador que ainda aponta para este programa
    assert (
        'rm -rf "${DADOS:?}/$item"' in text and 'rmdir "$DADOS"' in text
    )  # nunca um rm -rf da pasta inteira
    assert "recuso apagar uma pasta que não reconheço" in text


@pytest.mark.skipif(SHELL is None, reason="sem sh/dash na máquina")
@pytest.mark.parametrize(
    "name",
    [
        "instalar.sh",
        "desinstalar.sh",
        "lancadores/dmaker.sh",
        "lancadores/dmaker-mcp.sh",
        "lancadores/ollama.sh",
    ],
)
def test_shell_scripts_pass_syntax_check(name, tmp_path):
    text = _render() if name == "instalar.sh" else _templates()[name]
    path = tmp_path / "script.sh"
    path.write_bytes(text.encode("utf-8"))
    done = subprocess.run([SHELL, "-n", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# ---------- o build do Linux, com o executor falso ----------


class LinuxFakeDownloader:
    def __init__(self) -> None:
        self.fetched: list[str] = []
        self.python = b"python-linux"
        self.ffmpeg = b"ffmpeg-linux"

    def fetch(self, url: str, destination: Path) -> None:
        self.fetched.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith("SHA256SUMS"):
            destination.write_text(
                f"{hashlib.sha256(self.python).hexdigest()}  {LINUX.python_archive}\n", encoding="utf-8"
            )
        elif url.endswith("checksums.sha256"):
            destination.write_text(
                f"{hashlib.sha256(self.ffmpeg).hexdigest()}  {FFMPEG_NAME}\n", encoding="utf-8"
            )
        elif url.endswith("sha256sum.txt"):
            raise OSError("sem lista")
        elif url.endswith(".tar.gz"):
            destination.write_bytes(self.python)
        elif url.endswith(".tar.xz"):
            destination.write_bytes(self.ffmpeg)
        else:
            destination.write_bytes(b"ollama")


def run_linux_build(tiny_roots, **overrides):
    repo, main = tiny_roots
    shutil.copytree(REPO / "instalador" / "linux", repo / "instalador" / "linux")
    (main / "cache").mkdir(exist_ok=True)
    # os modelos que o manifesto lista: o build confere que existem na pasta principal
    for dest in {e.dest for e in build_manifest(TRACKED, "linux") if e.target == "data"}:
        target = main / dest
        target.mkdir(parents=True, exist_ok=True)
        (target / "arquivo.bin").write_bytes(b"m")
    runner = RecordingCommandRunner(
        outputs={
            ("git", "ls-files"): "\0".join(TRACKED) + "\0",
            ("host-python", "-m", "pip", "freeze"): "torch==2.15.0+cpu\ndmaker==2.0.0\n",
        }
    )
    options = BuildOptions(
        version="2.0.0",
        platform="linux",
        repo_root=repo,
        main_root=main,
        host_python="host-python",
        keep_staging=True,
        **overrides,
    )
    builder = ReleaseBuilder(options, runner, LinuxFakeDownloader(), log=lambda _line: None)
    original_run = runner.run

    def run(command, **kwargs):
        text = original_run(command, **kwargs)
        if "wheel" in command:
            (builder.work / "wheels").mkdir(parents=True, exist_ok=True)
            (builder.work / "wheels" / "dmaker-2.0.0-py3-none-any.whl").write_bytes(b"w")
        if command[0] == "docker" and command[-2:] == ["sh", "/work/build.sh"]:
            # o que o contêiner deixa: as partes na saída e as medidas na pasta de trabalho
            (builder.output / "DMaker-2.0.0-linux-x64-1.part").write_bytes(b"parte um")
            (builder.output / "DMaker-2.0.0-linux-x64-2.part").write_bytes(b"parte dois!")
            (builder.work / "tamanho-programa.txt").write_text("123456\n", encoding="utf-8")
            (builder.work / "chromium-libs.txt").write_text(LDD, encoding="utf-8")
            (builder.work / "filtros.txt").write_text(" T.. ladspa  N->A  x\n", encoding="utf-8")
            (builder.work / "ffmpeg-versao.txt").write_text("ffmpeg version n9.0-linux\n", encoding="utf-8")
        return text

    runner.run = run  # type: ignore[method-assign]
    return builder, runner


def test_linux_build_runs_the_commands_in_order(tiny_roots):
    builder, runner = run_linux_build(tiny_roots)
    result = builder.build()
    commands = [c.command for c in runner.commands]
    npm_at = 0
    wheel_at = next(i for i, c in enumerate(commands) if "wheel" in c)
    clean_at = next(i for i, c in enumerate(commands) if c[0] == "docker" and "rm -rf" in c[-1])
    git_at = next(i for i, c in enumerate(commands) if c[0] == "git")
    freeze_at = next(i for i, c in enumerate(commands) if "freeze" in c)
    build_at = next(
        i for i, c in enumerate(commands) if c[0] == "docker" and c[-2:] == ("sh", "/work/build.sh")
    )
    assert commands[npm_at][:3] == ("npm", "run", "build")
    assert npm_at < wheel_at < clean_at < git_at < freeze_at < build_at == len(commands) - 1
    docker = commands[build_at]
    assert docker[:3] == ("docker", "run", "--rm") and docker[-3] == "ubuntu:22.04"
    mounts = [docker[i + 1] for i, part in enumerate(docker) if part == "-v"]
    assert any(m.endswith(":/work") for m in mounts)
    assert any(m.endswith(":/baixados:ro") for m in mounts)
    assert any(m.endswith("cache/models:/modelos:ro") for m in mounts)
    assert any(m.endswith(":/saida") for m in mounts)
    assert [f.name for f in result.files] == [
        "DMaker-2.0.0-linux-x64.run",
        "DMaker-2.0.0-linux-x64-1.part",
        "DMaker-2.0.0-linux-x64-2.part",
    ]


def test_linux_build_downloads_only_what_the_briefing_allows(tiny_roots):
    builder, _ = run_linux_build(tiny_roots)
    builder.build()
    fetched = builder.downloader.fetched  # type: ignore[attr-defined]
    assert any("linux-gnu-install_only_stripped.tar.gz" in url for url in fetched)
    assert any(url.endswith("ffmpeg-n9.0-latest-linux64-gpl-9.0.tar.xz") for url in fetched)
    assert any(url.endswith("ollama-linux-amd64.tar.zst") for url in fetched)
    assert all(
        url.startswith(
            (
                "https://github.com/astral-sh/python-build-standalone/",
                "https://github.com/BtbN/FFmpeg-Builds/",
                "https://github.com/ollama/ollama/",
            )
        )
        for url in fetched
    )


def test_linux_build_writes_the_run_script_with_the_real_hashes(tiny_roots):
    builder, _ = run_linux_build(tiny_roots)
    builder.build()
    run = (builder.output / "DMaker-2.0.0-linux-x64.run").read_text(encoding="utf-8")
    for part in ("DMaker-2.0.0-linux-x64-1.part", "DMaker-2.0.0-linux-x64-2.part"):
        digest = sha256_file(builder.output / part)
        size = (builder.output / part).stat().st_size
        assert f"{digest} {size} {part}" in run
    assert "BYTES_PROGRAMA=123456" in run
    assert "libnss3.so" in run and "libasound.so.2" in run and "libc.so.6" not in run
    assert "@@" not in run.replace("@@PROGRAMA@@", "").replace("@@DADOS@@", "").replace("@@BIN@@", "")


def test_linux_build_stages_the_program_files_the_container_needs(tiny_roots):
    builder, _ = run_linux_build(tiny_roots)
    builder.build()
    program, work = builder.program, builder.work
    assert (program / "assets/fonts/Poppins-Regular.ttf").exists()
    assert not (program / "assets/voices").exists()
    assert not (builder.models).exists() or not any(
        builder.models.rglob("*.bin")
    )  # modelos seguem direto ao arquivo
    for name in scripts.LAUNCHER_FILES:
        assert (program / "lancadores" / name).exists()
    assert (program / "lancadores" / "desinstalar.sh").exists()
    assert "\r" not in (program / "lancadores" / "dmaker.sh").read_text(encoding="utf-8")
    notice = (program / "licencas" / "LICENCAS.txt").read_text(encoding="utf-8")
    assert "BtbN" in notice and "AVISO DE USO NÃO COMERCIAL" in notice
    listed = (work / "modelos.txt").read_text(encoding="utf-8").splitlines()
    assert "omnivoice" in listed and "kokoro/kokoro-v1.0.onnx" in listed
    script = (work / "build.sh").read_text(encoding="utf-8")
    assert "playwright install chromium" in script
    assert (work / "restricoes.txt").read_text(encoding="utf-8") == "torch==2.15.0+cpu\n"


def test_linux_build_reports_the_filters_the_ffmpeg_has(tiny_roots):
    builder, _ = run_linux_build(tiny_roots)
    result = builder.build()
    assert "filtro ladspa no FFmpeg do Linux: sim" in result.notes
    assert "filtro lv2 no FFmpeg do Linux: NÃO" in result.notes


def test_linux_build_without_model_drops_it_from_the_archive_list(tiny_roots):
    builder, _ = run_linux_build(tiny_roots, excluded_models=("omnivoice",))
    builder.build()
    listed = (builder.work / "modelos.txt").read_text(encoding="utf-8").splitlines()
    assert "omnivoice" not in listed and "kokoro/kokoro-v1.0.onnx" in listed
    notice = (builder.program / "licencas" / "LICENCAS.txt").read_text(encoding="utf-8")
    assert "baixam no primeiro uso: omnivoice" in notice
