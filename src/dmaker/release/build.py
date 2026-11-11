"""O build do instalador: orquestra os passos, e cada comando externo passa pelo `CommandRunner` injetado."""

from __future__ import annotations

import os
import re
import shutil
import tarfile
import time
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .. import __version__
from .checksums import parse_sha256sums, sha256_file
from .licenses import blocked_models, license_notice
from .manifest import ManifestEntry, build_manifest
from .marker import marker_template, windows_launchers
from .naming import SLICE_BYTES, installer_basename, installer_files, release_folder_name
from .notes import ReleaseFile, release_notes
from .platforms import PACKAGE_EXTRAS, PLATFORMS, TORCH_CPU_INDEX, PlatformSpec
from .runner import CommandRunner, ReleaseError

OLLAMA_VERSION = "0.40.16"
OLLAMA_INSTALLER = "OllamaSetup.exe"
OLLAMA_BASE = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}"
DOWNLOADS_FOLDER = "_baixados"
INSTALLER_SCRIPT = Path("instalador") / "windows" / "dmaker.iss"
MARKER_TEMPLATE_NAME = "instalacao.json.modelo"


# O Python portátil não pode enxergar nada da máquina de quem monta o pacote: sem isto o pip do build achou o
# `site-packages` do usuário, deu os pacotes dele por instalados e chegou a desinstalá-los de lá.
ISOLATED_ENV = {"PYTHONNOUSERSITE": "1", "PYTHONPATH": "", "PYTHONHOME": "", "PIP_USER": "0"}


class Downloader(Protocol):
    def fetch(self, url: str, destination: Path) -> None:
        """Baixa `url` para `destination` (o arquivo inteiro ou erro)."""


class UrlDownloader:
    """Download simples por HTTPS, em pedaços, com um aviso de progresso por cento a cada 10%."""

    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log

    def fetch(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        self.log(f"baixando {url}")
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            done, next_mark = 0, 10
            while block := response.read(8 * 1024 * 1024):
                out.write(block)
                done += len(block)
                if total and done * 100 // total >= next_mark:
                    self.log(f"  {done * 100 // total}% de {total // (1024 * 1024)} MB")
                    next_mark += 10
        partial.replace(destination)


@dataclass(frozen=True)
class BuildOptions:
    version: str = __version__
    platform: str = "windows"
    repo_root: Path = Path(".")  # o clone que se empacota (código, interface, assets e templates)
    main_root: Path = Path(".")  # a pasta principal: binários, modelos, ferramenta do instalador e a saída
    host_python: str = "python"  # o Python do ambiente de desenvolvimento (de onde sai o `pip freeze`)
    iscc: Path | None = None
    keep_staging: bool = False


@dataclass
class BuildResult:
    output_dir: Path
    files: list[ReleaseFile]
    seconds: float
    steps: list[tuple[str, float]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


def constraints_from_freeze(freeze_text: str, own_name: str = "dmaker") -> str:
    """Do `pip freeze` do ambiente de desenvolvimento, as linhas `pacote==versão` (menos o próprio DMaker), que fixam
    no pacote as mesmas versões que passam nos testes. Linhas editáveis ou por caminho não servem de restrição."""
    pinned = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)$")
    kept = []
    for line in freeze_text.splitlines():
        match = pinned.match(line.strip())
        if match and match.group(1).lower().replace("_", "-") != own_name:
            kept.append(line.strip())
    return "\n".join(kept) + "\n"


def wheel_requirement(wheel: Path, extras: Iterable[str] = PACKAGE_EXTRAS) -> str:
    return f"{wheel}[{','.join(extras)}]"


def link_or_copy(source: Path, destination: Path) -> None:
    """Hardlink quando dá (mesmo volume: instantâneo e sem ocupar disco), cópia quando não."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def stage_tree(source: Path, destination: Path) -> int:
    """Leva uma pasta (ou um arquivo) para o destino e devolve quantos arquivos foram."""
    if source.is_file():
        link_or_copy(source, destination)
        return 1
    count = 0
    for folder, _dirs, names in os.walk(source):
        relative = Path(folder).relative_to(source)
        (destination / relative).mkdir(parents=True, exist_ok=True)
        for name in names:
            link_or_copy(Path(folder) / name, destination / relative / name)
            count += 1
    return count


class ReleaseBuilder:
    def __init__(
        self,
        options: BuildOptions,
        runner: CommandRunner,
        downloader: Downloader,
        log: Callable[[str], None] = print,
    ) -> None:
        if options.platform not in PLATFORMS:
            raise ReleaseError(f"Plataforma sem build: {options.platform}")
        self.options = options
        self.spec: PlatformSpec = PLATFORMS[options.platform]
        self.runner = runner
        self.downloader = downloader
        self.log = log
        self.releases = options.main_root / "releases"
        self.downloads = self.releases / DOWNLOADS_FOLDER
        self.output = self.releases / release_folder_name(options.version)
        self.work = self.output / "_trabalho"
        self.program = self.work / "programa"
        self.models = self.work / "dados"
        self._steps: list[tuple[str, float]] = []

    # ---- passos ----

    def build(self) -> BuildResult:
        started = time.monotonic()
        self.output.mkdir(parents=True, exist_ok=True)
        self.work.mkdir(parents=True, exist_ok=True)
        self.step("interface (npm run build)", self.build_frontend)
        wheel = self.step("wheel do DMaker", self.build_wheel)
        self.step("Python portátil", self.extract_python)
        self.step("pacotes Python (pip install)", lambda: self.install_packages(wheel))
        self.step("compileall", self.compile_python)
        self.step("copiar binários, assets e modelos", self.stage_manifest)
        self.step("marcador, lançadores e licenças", self.write_support_files)
        ollama = self.step("instalador do Ollama", self.fetch_ollama)
        self.step("Inno Setup (ISCC)", lambda: self.run_installer_compiler(ollama))
        files = self.step("SHA-256 e notas", self.write_release_files)
        if not self.options.keep_staging:
            shutil.rmtree(self.work, ignore_errors=True)
        return BuildResult(
            self.output, files, time.monotonic() - started, list(self._steps), blocked_models()
        )

    def step(self, name: str, action: Callable[[], object]):
        self.log(f"[{len(self._steps) + 1}] {name}")
        started = time.monotonic()
        result = action()
        self._steps.append((name, time.monotonic() - started))
        return result

    def build_frontend(self) -> None:
        self.runner.run(["npm", "run", "build"], cwd=self.options.repo_root / "frontend")

    def build_wheel(self) -> Path:
        wheels = self.work / "wheels"
        shutil.rmtree(wheels, ignore_errors=True)
        wheels.mkdir(parents=True)
        self.runner.run(
            [self.options.host_python, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheels)],
            cwd=self.options.repo_root,
        )
        found = sorted(wheels.glob("dmaker-*.whl"))
        if not found:
            raise ReleaseError(f"O pip não gerou o wheel em {wheels}")
        return found[-1]

    def fetch_verified(self, url: str, name: str, expected: str | None) -> Path:
        path = self.downloads / name
        if not path.exists():
            self.downloader.fetch(url, path)
        if expected and sha256_file(path) != expected:
            path.unlink()
            raise ReleaseError(f"SHA-256 de {name} não confere com o publicado; apaguei o arquivo baixado.")
        return path

    def extract_python(self) -> None:
        sums_path = self.downloads / f"SHA256SUMS-python-{self.spec.id}"
        if not sums_path.exists():
            self.downloader.fetch(self.spec.sums_url, sums_path)
        expected = parse_sha256sums(sums_path.read_text(encoding="utf-8")).get(self.spec.python_archive)
        if not expected:
            raise ReleaseError(f"O SHA256SUMS da release não lista {self.spec.python_archive}")
        archive = self.fetch_verified(self.spec.python_url, self.spec.python_archive, expected)
        shutil.rmtree(self.program, ignore_errors=True)
        self.program.mkdir(parents=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(self.program, filter="data")

    @property
    def python(self) -> Path:
        return self.program / self.spec.python_exe

    def install_packages(self, wheel: Path) -> None:
        freeze = self.runner.run([self.options.host_python, "-m", "pip", "freeze"])
        constraints = self.work / "restricoes.txt"
        constraints.write_text(constraints_from_freeze(freeze), encoding="utf-8")
        self.runner.run(
            [
                str(self.python),
                "-m",
                "pip",
                "install",
                "--no-warn-script-location",
                "--disable-pip-version-check",
                "--no-input",
                "-c",
                str(constraints),
                "--extra-index-url",
                TORCH_CPU_INDEX,
                wheel_requirement(wheel),
                "torch",
                "torchaudio",
            ],
            env=ISOLATED_ENV,
        )

    def compile_python(self) -> None:
        # arquivo de terceiros com erro de sintaxe (ex.: de exemplo, em Python 2) faz o compileall sair com 1: não é falha
        self.runner.run(
            [str(self.python), "-m", "compileall", "-q", "-j", "0", str(self.program / "python")],
            env=ISOLATED_ENV,
            check=False,
        )
        # os executáveis que o pip gera guardam o caminho absoluto do Python e quebram ao mudar de pasta
        shutil.rmtree(self.program / self.spec.launcher_scripts, ignore_errors=True)

    def tracked_files(self) -> list[str]:
        listing = self.runner.run(["git", "ls-files", "-z"], cwd=self.options.repo_root)
        return [name for name in listing.split("\0") if name]

    def stage_manifest(self) -> list[ManifestEntry]:
        entries = build_manifest(self.tracked_files())
        shutil.rmtree(self.models, ignore_errors=True)
        for entry in entries:
            root = self.options.repo_root if entry.origin == "repo" else self.options.main_root
            source = root / entry.source
            if not source.exists():
                raise ReleaseError(f"Faltou {source} ({entry.reason})")
            base = self.program if entry.target == "program" else self.models
            stage_tree(source, base / entry.dest)
        return entries

    def write_support_files(self) -> None:
        (self.program / MARKER_TEMPLATE_NAME).write_text(
            marker_template(self.options.version), encoding="utf-8"
        )
        for name, content in windows_launchers().items():
            (self.program / name).write_bytes(content.encode("utf-8"))
        licenses = self.program / "licencas"
        licenses.mkdir(exist_ok=True)
        (licenses / "LICENCAS.txt").write_text(license_notice(self.options.version), encoding="utf-8-sig")
        third_party = self.options.repo_root / "THIRD_PARTY.md"
        if third_party.exists():
            shutil.copy2(third_party, licenses / "THIRD_PARTY.md")

    def fetch_ollama(self) -> Path:
        sums_name = f"sha256sum-ollama-{OLLAMA_VERSION}.txt"
        sums_path = self.downloads / sums_name
        expected = None
        try:
            if not sums_path.exists():
                self.downloader.fetch(f"{OLLAMA_BASE}/sha256sum.txt", sums_path)
            expected = parse_sha256sums(sums_path.read_text(encoding="utf-8")).get(OLLAMA_INSTALLER)
        except Exception as exc:  # a release pode não publicar a lista; o aviso fica no log
            self.log(f"  sem lista de SHA-256 do Ollama ({exc}); sigo sem conferir")
        return self.fetch_verified(
            f"{OLLAMA_BASE}/{OLLAMA_INSTALLER}", f"OllamaSetup-{OLLAMA_VERSION}.exe", expected
        )

    def run_installer_compiler(self, ollama: Path) -> None:
        iscc = self.options.iscc or self.options.main_root / "bin" / "innosetup" / "ISCC.exe"
        for old in self.output.glob("DMaker-*"):
            old.unlink()
        self.runner.run(
            [
                str(iscc),
                "/Qp",
                f"/DVersao={self.options.version}",
                f"/DPrograma={self.program}",
                f"/DDados={self.models}",
                f"/DSaida={self.output}",
                f"/DNomeBase={installer_basename(self.options.version, self.spec.id)}",
                f"/DOllama={ollama}",
                f"/DOllamaVersao={OLLAMA_VERSION}",
                f"/DFatia={SLICE_BYTES}",
                str(self.options.repo_root / INSTALLER_SCRIPT),
            ]
        )

    def write_release_files(self) -> list[ReleaseFile]:
        base = installer_basename(self.options.version, self.spec.id)
        slices = len(list(self.output.glob(f"{base}-*.bin")))
        names = installer_files(self.options.version, self.spec.id, slices)
        files = []
        for name in names:
            path = self.output / name
            if not path.exists():
                raise ReleaseError(f"O instalador não gerou {name}")
            files.append(ReleaseFile(name, path.stat().st_size, sha256_file(path)))
        (self.output / "SHA256SUMS.txt").write_text(
            "".join(f"{file.sha256}  {file.name}\n" for file in files), encoding="utf-8"
        )
        changelog = self.options.repo_root / "CHANGELOG.md"
        text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
        (self.output / "NOTAS.md").write_text(
            release_notes(self.options.version, files, self.spec.label, text), encoding="utf-8"
        )
        return files
