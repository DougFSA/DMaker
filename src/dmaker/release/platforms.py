"""O que muda de um sistema para outro no build: o Python portátil, os binários e o formato do instalador."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Python portátil do projeto python-build-standalone (a release de 26/10/2026). `install_only_stripped` é o
# menor: sem símbolos de depuração e sem os testes, e já traz o pip.
PYTHON_VERSION = "3.13.18"
PYTHON_BUILD_TAG = "20261026"
PYTHON_RELEASE_BASE = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/{PYTHON_BUILD_TAG}"
)
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"

# Os extras do pip que o pacote leva (o `dev` não entra).
PACKAGE_EXTRAS = ("voice", "captions", "lote", "agente", "html", "docs")

BinaryOrigin = Literal["pasta", "build"]


@dataclass(frozen=True)
class PlatformSpec:
    id: str  # "windows" ou "linux": entra no nome do instalador
    label: str
    python_archive: str
    python_exe: str  # relativo ao programa
    site_packages: str  # relativo ao programa
    installer_extension: str  # o instalador em si (.exe, .run)
    part_extension: str  # as partes de dados que acompanham o instalador (.bin, .part)
    launcher_scripts: str  # pasta que o pip enche de executáveis com caminho absoluto (apagada no pacote)
    # Os binários de `bin/` que vão no pacote, com o porquê. No Windows vêm da `bin/` da pasta principal; no Linux o
    # build os baixa (`build`), porque a pasta principal tem os do Windows.
    binaries: tuple[tuple[str, str], ...]
    binaries_origin: BinaryOrigin

    @property
    def python_url(self) -> str:
        return f"{PYTHON_RELEASE_BASE}/{self.python_archive.replace('+', '%2B')}"

    @property
    def sums_url(self) -> str:
        return f"{PYTHON_RELEASE_BASE}/SHA256SUMS"


WINDOWS = PlatformSpec(
    id="windows",
    label="Windows x64",
    python_archive=f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
    python_exe="python/python.exe",
    site_packages="python/Lib/site-packages",
    installer_extension=".exe",
    part_extension=".bin",
    launcher_scripts="python/Scripts",
    binaries=(
        ("ffmpeg", "FFmpeg completo (gyan.dev, com LADSPA): renderiza, mede e codifica"),
        ("ffmpeg-lv2", "FFmpeg dos plugins LV2 (BtbN)"),
        ("playwright", "Chromium da composição em HTML e do PDF do manual"),
    ),
    binaries_origin="pasta",
)

LINUX = PlatformSpec(
    id="linux",
    label="Linux x64",
    python_archive=f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD_TAG}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
    python_exe="python/bin/python3",
    site_packages="python/lib/python3.13/site-packages",
    installer_extension=".run",
    part_extension=".part",
    launcher_scripts="python/bin",
    binaries=(
        ("ffmpeg", "FFmpeg n9.0 (BtbN, estático): renderiza, mede e codifica, com os filtros LADSPA e LV2"),
        ("ffmpeg-lv2", "O mesmo FFmpeg, no lugar onde o DMaker procura o que hospeda os plugins LV2"),
        ("playwright", "Chromium da composição em HTML e do PDF do manual"),
    ),
    binaries_origin="build",
)

PLATFORMS = {WINDOWS.id: WINDOWS, LINUX.id: LINUX}
