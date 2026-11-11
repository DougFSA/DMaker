"""O que muda de um sistema para outro no build: o Python portátil, os binários e o formato do instalador."""

from __future__ import annotations

from dataclasses import dataclass

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

# Os binários da pasta `bin/` da raiz principal que vão no pacote, com o porquê. O `innosetup` (a ferramenta do build)
# e qualquer outra coisa que esteja em `bin/` ficam de fora.
BINARIES: tuple[tuple[str, str], ...] = (
    ("ffmpeg", "FFmpeg completo (gyan.dev, com LADSPA): renderiza, mede e codifica"),
    ("ffmpeg-lv2", "FFmpeg dos plugins LV2 (BtbN)"),
    ("playwright", "Chromium da composição em HTML e do PDF do manual"),
)


@dataclass(frozen=True)
class PlatformSpec:
    id: str  # "windows" ou "linux": entra no nome do instalador
    label: str
    python_archive: str
    python_exe: str  # relativo ao programa
    site_packages: str  # relativo ao programa
    installer_extension: str
    launcher_scripts: str  # pasta que o pip enche de executáveis com caminho absoluto (apagada no pacote)

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
    launcher_scripts="python/Scripts",
)

PLATFORMS = {WINDOWS.id: WINDOWS}
