"""O alvo do Linux: o pacote é montado num contêiner `ubuntu:22.04` e o instalador é um `.run` (script POSIX) com as partes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ...setup_tools import FFMPEG_LV2_BUILDS
from ..checksums import sha256_file
from ..licenses import license_notice
from ..linux_container import (
    BUILD_IMAGE,
    DOWNLOADS,
    MODELS,
    OUTPUT,
    WORK,
    ContainerPlan,
    build_script,
    clean_command,
    docker_run,
)
from ..linux_scripts import (
    INSTALLER_TEMPLATE,
    LAUNCHER_FILES,
    LAUNCHER_FOLDER,
    UNINSTALLER_TEMPLATE,
    PartInfo,
    chromium_libraries,
    parse_filters,
    read_installer_templates,
    render_installer,
)
from ..manifest import MODELS_DEST
from ..naming import installer_name, slice_names
from ..ollama import OLLAMA_SUMS_NAME, OLLAMA_SUMS_URL, ollama_asset, ollama_local_name, ollama_url
from ..platforms import PACKAGE_EXTRAS
from ..runner import ReleaseError
from ..staging import tree_size

if TYPE_CHECKING:
    from ..build import ReleaseBuilder, Step

WORK_FOLDER = "_linux"
MODELS_LIST = "modelos.txt"
BUILD_SCRIPT = "build.sh"


class LinuxTarget:
    def work_dir(self, builder: ReleaseBuilder) -> Path:
        # Fora da pasta da release: a árvore montada tem dezenas de GB e fica no X:, ao lado de `_baixados`.
        return builder.releases / WORK_FOLDER / f"v{builder.options.version}"

    def clear_previous(self, builder: ReleaseBuilder) -> None:
        version = builder.options.version
        for old in builder.output.glob(f"DMaker-{version}-linux-*"):
            old.unlink()

    def steps(self, builder: ReleaseBuilder, wheel: Path) -> list[Step]:
        state: dict[str, object] = {}
        return [
            ("baixar Python, FFmpeg e Ollama", lambda: self.fetch_archives(builder, state)),
            (
                "limpar a pasta de trabalho (contêiner)",
                lambda: builder.runner.run(clean_command(builder.options.docker, builder.work)),
            ),
            ("copiar assets e listar os modelos", lambda: self.stage(builder, state)),
            ("restrições, scripts e licenças", lambda: self.write_support_files(builder, wheel, state)),
            (
                "montar o pacote no contêiner (pip, FFmpeg, Chromium, Ollama, partes)",
                lambda: self.run_container(builder, state),
            ),
            ("script .run", lambda: self.write_installer(builder, state)),
        ]

    # ---- passos ----

    def fetch_archives(self, builder: ReleaseBuilder, state: dict[str, object]) -> None:
        spec = builder.spec
        python_sum = builder.published_sum(spec.sums_url, f"SHA256SUMS-python-{spec.id}", spec.python_archive)
        if not python_sum:
            raise ReleaseError(f"O SHA256SUMS da release não lista {spec.python_archive}")
        builder.fetch_verified(spec.python_url, spec.python_archive, python_sum)
        ffmpeg = FFMPEG_LV2_BUILDS[("linux", "x64")]
        ffmpeg_name = ffmpeg.url.rsplit("/", 1)[-1]
        ffmpeg_sum = builder.published_sum(ffmpeg.checksum, "checksums-btbn.sha256", ffmpeg_name)
        builder.fetch_verified(ffmpeg.url, ffmpeg_name, ffmpeg_sum)
        ollama_sum = builder.published_sum(OLLAMA_SUMS_URL, OLLAMA_SUMS_NAME, ollama_asset("linux"))
        builder.fetch_verified(ollama_url("linux"), ollama_local_name("linux"), ollama_sum)
        state["ffmpeg_archive"] = ffmpeg_name

    def stage(self, builder: ReleaseBuilder, state: dict[str, object]) -> None:
        entries = builder.manifest()
        builder.stage_manifest(entries, targets=("program",))
        prefix = f"{MODELS_DEST}/"
        models_root = builder.options.main_root / MODELS_DEST
        paths = [entry.dest.removeprefix(prefix) for entry in entries if entry.target == "data"]
        for path in paths:
            if not (models_root / path).exists():
                raise ReleaseError(f"Faltou o modelo {models_root / path}")
        state["model_paths"] = paths
        state["data_bytes"] = sum(tree_size(models_root / path) for path in paths)
        builder.log(f"  {len(paths)} caminhos de modelo, {state['data_bytes']} bytes")

    def write_support_files(self, builder: ReleaseBuilder, wheel: Path, state: dict[str, object]) -> None:
        options = builder.options
        builder.host_constraints()
        templates = read_installer_templates(options.repo_root)
        program = builder.program
        launchers = program / LAUNCHER_FOLDER
        launchers.mkdir(parents=True, exist_ok=True)
        for name in LAUNCHER_FILES:
            (launchers / name).write_text(
                templates[f"{LAUNCHER_FOLDER}/{name}"], encoding="utf-8", newline="\n"
            )
        (launchers / UNINSTALLER_TEMPLATE).write_text(
            templates[UNINSTALLER_TEMPLATE], encoding="utf-8", newline="\n"
        )
        licenses = program / "licencas"
        licenses.mkdir(exist_ok=True)
        (licenses / "LICENCAS.txt").write_text(
            license_notice(options.version, "linux", options.excluded_models), encoding="utf-8", newline="\n"
        )
        third_party = options.repo_root / "THIRD_PARTY.md"
        if third_party.exists():
            (licenses / "THIRD_PARTY.md").write_bytes(third_party.read_bytes())
        paths = list(state["model_paths"])  # type: ignore[call-overload]
        (builder.work / MODELS_LIST).write_text(
            "".join(f"{path}\n" for path in paths), encoding="utf-8", newline="\n"
        )
        plan = ContainerPlan(
            version=options.version,
            python_archive=builder.spec.python_archive,
            ffmpeg_archive=str(state["ffmpeg_archive"]),
            ollama_archive=ollama_local_name("linux"),
            wheel_name=wheel.name,
            extras=PACKAGE_EXTRAS,
            model_paths=paths,
        )
        (builder.work / BUILD_SCRIPT).write_text(build_script(plan), encoding="utf-8", newline="\n")

    def run_container(self, builder: ReleaseBuilder, state: dict[str, object]) -> None:
        mounts = [
            (builder.work, WORK, False),
            (builder.downloads, DOWNLOADS, True),
            (builder.options.main_root / MODELS_DEST, MODELS, True),
            (builder.output, OUTPUT, False),
        ]
        builder.runner.run(
            docker_run(builder.options.docker, mounts, ["sh", f"{WORK}/{BUILD_SCRIPT}"], BUILD_IMAGE)
        )

    def write_installer(self, builder: ReleaseBuilder, state: dict[str, object]) -> None:
        options = builder.options
        names = sorted(builder.output.glob(f"DMaker-{options.version}-linux-x64-*.part"))
        if not names:
            raise ReleaseError("O contêiner não gerou nenhuma parte do pacote do Linux")
        expected = slice_names(options.version, "linux", len(names))
        if [path.name for path in names] != expected:
            raise ReleaseError(f"As partes não estão em sequência: {[path.name for path in names]}")
        parts = [PartInfo(path.name, path.stat().st_size, sha256_file(path)) for path in names]
        program_bytes = self.read_number(builder.work / "tamanho-programa.txt")
        libraries = chromium_libraries(self.read_text(builder.work / "chromium-libs.txt"))
        template = read_installer_templates(options.repo_root)[INSTALLER_TEMPLATE]
        script = render_installer(
            template, options.version, parts, libraries, program_bytes, int(state["data_bytes"])
        )  # type: ignore[call-overload]
        target = builder.output / installer_name(options.version, "linux")
        target.write_text(script, encoding="utf-8", newline="\n")
        filters = parse_filters(self.read_text(builder.work / "filtros.txt"))
        version = self.read_text(builder.work / "ffmpeg-versao.txt").strip()
        builder.notes.append(f"FFmpeg do Linux: {version or 'versão não lida'}")
        for name, present in filters.items():
            builder.notes.append(f"filtro {name} no FFmpeg do Linux: {'sim' if present else 'NÃO'}")
        builder.notes.append(
            f"tamanho do programa instalado: {program_bytes} bytes; dos modelos: {state['data_bytes']} bytes"
        )
        builder.notes.append(f"bibliotecas do Chromium conferidas pelo instalador: {len(libraries)}")

    @staticmethod
    def read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    @classmethod
    def read_number(cls, path: Path) -> int:
        text = cls.read_text(path).strip()
        return int(text) if text.isdigit() else 0
