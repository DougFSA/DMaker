"""O build do instalador: orquestra os passos comuns, e cada sistema entra por um `PlatformTarget` (windows.py, linux.py).

Cada comando externo passa pelo `CommandRunner` injetado e cada download pelo `Downloader`, para o teste provar a ordem
sem rodar nada."""

from __future__ import annotations

import shutil
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .. import __version__
from .checksums import parse_sha256sums, sha256_file
from .licenses import blocked_models
from .manifest import ManifestEntry, build_manifest, check_model_ids
from .naming import installer_name, release_folder_name, slice_names
from .notes import ReleaseFile, release_notes
from .platforms import PLATFORMS, PlatformSpec
from .runner import CommandRunner, ReleaseError
from .staging import ISOLATED_ENV, constraints_from_freeze, stage_tree, wheel_requirement

DOWNLOADS_FOLDER = "_baixados"
MARKER_TEMPLATE_NAME = "instalacao.json.modelo"

__all__ = [
    "ISOLATED_ENV",
    "BuildOptions",
    "BuildResult",
    "Downloader",
    "ReleaseBuilder",
    "UrlDownloader",
    "constraints_from_freeze",
    "wheel_requirement",
]


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
    excluded_models: tuple[str, ...] = ()  # `--sem-modelo`: fora do pacote, baixam no primeiro uso
    docker: str = "docker"


@dataclass
class BuildResult:
    output_dir: Path
    files: list[ReleaseFile]
    seconds: float
    steps: list[tuple[str, float]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    notes: list[str] = field(
        default_factory=list
    )  # o que o build mediu e a pessoa precisa saber (filtros, tempos)


Step = tuple[str, Callable[[], object]]


class PlatformTarget(Protocol):
    """O que muda de um sistema para outro: onde se trabalha e quais passos montam o pacote e o instalador."""

    def work_dir(self, builder: ReleaseBuilder) -> Path:
        """A pasta de trabalho (grande: tem o Python, os pacotes e os modelos em montagem)."""

    def steps(self, builder: ReleaseBuilder, wheel: Path) -> list[Step]:
        """Os passos, na ordem, que levam do wheel do DMaker ao instalador e às partes em `builder.output`."""

    def clear_previous(self, builder: ReleaseBuilder) -> None:
        """Apaga da saída só os arquivos deste sistema (a outra plataforma pode estar lá)."""


def collect_release_files(output: Path, version: str) -> dict[str, list[ReleaseFile]]:
    """Os arquivos de cada sistema que já estão na pasta da release, com tamanho e SHA-256 (o instalador primeiro)."""
    found: dict[str, list[ReleaseFile]] = {}
    for platform in PLATFORMS:
        installer = output / installer_name(version, platform)
        if not installer.exists():
            continue
        names = [installer.name]
        count = 1
        while (output / slice_names(version, platform, count)[-1]).exists():
            count += 1
        names += slice_names(version, platform, count - 1)
        found[platform] = [
            ReleaseFile(name, (output / name).stat().st_size, sha256_file(output / name)) for name in names
        ]
    return found


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
        from .targets import target_for

        self.options = options
        self.spec: PlatformSpec = PLATFORMS[options.platform]
        self.target: PlatformTarget = target_for(options.platform)
        self.runner = runner
        self.downloader = downloader
        self.log = log
        self.releases = options.main_root / "releases"
        self.downloads = self.releases / DOWNLOADS_FOLDER
        self.output = self.releases / release_folder_name(options.version)
        self.work = self.target.work_dir(self)
        self.program = self.work / "programa"
        self.models = self.work / "dados"
        self.notes: list[str] = []
        self._steps: list[tuple[str, float]] = []
        try:
            check_model_ids(options.excluded_models)
        except ValueError as exc:
            raise ReleaseError(str(exc)) from exc

    # ---- o fio comum ----

    def build(self) -> BuildResult:
        started = time.monotonic()
        self.output.mkdir(parents=True, exist_ok=True)
        self.work.mkdir(parents=True, exist_ok=True)
        self.step("interface (npm run build)", self.build_frontend)
        wheel = self.step("wheel do DMaker", self.build_wheel)
        self.target.clear_previous(self)
        for name, action in self.target.steps(self, wheel):
            self.step(name, action)
        files = self.step("SHA-256 e notas", self.write_release_files)
        if not self.options.keep_staging:
            self.clean_work()
        return BuildResult(
            self.output,
            files,
            time.monotonic() - started,
            list(self._steps),
            blocked_models(),
            list(self.notes),
        )

    def step(self, name: str, action: Callable[[], object]):
        self.log(f"[{len(self._steps) + 1}] {name}")
        started = time.monotonic()
        result = action()
        self._steps.append((name, time.monotonic() - started))
        return result

    def clean_work(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def build_frontend(self) -> None:
        self.runner.run(["npm", "run", "build"], cwd=self.options.repo_root / "frontend")

    def build_wheel(self) -> Path:
        wheels = self.work / "wheels"
        shutil.rmtree(wheels, ignore_errors=True)
        wheels.mkdir(parents=True)
        self.runner.run(
            [self.options.host_python, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheels)],
            cwd=self.options.repo_root,
            env=ISOLATED_ENV,
        )
        found = sorted(wheels.glob("dmaker-*.whl"))
        if not found:
            raise ReleaseError(f"O pip não gerou o wheel em {wheels}")
        return found[-1]

    def host_constraints(self) -> Path:
        """As versões do ambiente de desenvolvimento, gravadas como restrições para o pip do pacote."""
        freeze = self.runner.run(
            [self.options.host_python, "-m", "pip", "freeze"], env=ISOLATED_ENV, quiet=True
        )
        constraints = self.work / "restricoes.txt"
        constraints.write_text(constraints_from_freeze(freeze), encoding="utf-8")
        return constraints

    def fetch_verified(self, url: str, name: str, expected: str | None) -> Path:
        path = self.downloads / name
        if not path.exists():
            self.downloader.fetch(url, path)
        if expected and sha256_file(path) != expected:
            path.unlink()
            raise ReleaseError(f"SHA-256 de {name} não confere com o publicado; apaguei o arquivo baixado.")
        return path

    def published_sum(self, sums_url: str, sums_name: str, asset: str) -> str | None:
        """O SHA-256 que o site do arquivo publica (o `SHA256SUMS` da release); None se a release não publica lista."""
        path = self.downloads / sums_name
        try:
            if not path.exists():
                self.downloader.fetch(sums_url, path)
            return parse_sha256sums(path.read_text(encoding="utf-8")).get(asset)
        except Exception as exc:  # a release pode não publicar a lista; o aviso fica no log
            self.log(f"  sem lista de SHA-256 ({exc}); sigo sem conferir")
            return None

    def tracked_files(self) -> list[str]:
        listing = self.runner.run(["git", "ls-files", "-z"], cwd=self.options.repo_root, quiet=True)
        names = [name for name in listing.split("\0") if name]
        self.log(f"  {len(names)} arquivos versionados no clone")
        return names

    def manifest(self) -> list[ManifestEntry]:
        return build_manifest(self.tracked_files(), self.spec.id, self.options.excluded_models)

    def stage_manifest(
        self, entries: list[ManifestEntry], targets: tuple[str, ...] = ("program", "data")
    ) -> None:
        """Leva para a pasta de trabalho o que o manifesto manda copiar (`build` é feito por outro passo). O Linux só leva
        o programa: os modelos seguem direto da pasta principal para o arquivo, sem uma cópia a mais."""
        shutil.rmtree(self.models, ignore_errors=True)
        for entry in entries:
            if entry.origin == "build" or entry.target not in targets:
                continue
            root = self.options.repo_root if entry.origin == "repo" else self.options.main_root
            source = root / entry.source
            if not source.exists():
                raise ReleaseError(f"Faltou {source} ({entry.reason})")
            base = self.program if entry.target == "program" else self.models
            stage_tree(source, base / entry.dest)

    def write_release_files(self) -> list[ReleaseFile]:
        """O SHA256SUMS.txt e as notas cobrem todos os sistemas que já estão na pasta (um build novo de um não apaga o outro)."""
        by_platform = collect_release_files(self.output, self.options.version)
        mine = by_platform.get(self.spec.id)
        if not mine:
            raise ReleaseError(
                f"O build não gerou o instalador {installer_name(self.options.version, self.spec.id)}"
            )
        (self.output / "SHA256SUMS.txt").write_text(
            "".join(f"{file.sha256}  {file.name}\n" for files in by_platform.values() for file in files),
            encoding="utf-8",
        )
        changelog = self.options.repo_root / "CHANGELOG.md"
        text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
        (self.output / "NOTAS.md").write_text(
            release_notes(self.options.version, by_platform, text, self.options.excluded_models),
            encoding="utf-8",
        )
        return mine
