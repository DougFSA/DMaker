"""Os scripts do instalador do Linux: o `.run`, os lançadores e a lista de bibliotecas do Chromium. Puro: texto entra, texto sai.

Os modelos dos scripts ficam em `instalador/linux/` (versionados e revisáveis como shell de verdade); aqui só se
preenchem os valores que dependem do build (as partes e o SHA-256 delas, os tamanhos, as bibliotecas).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .naming import installer_basename

INSTALLER_FOLDER = Path("instalador") / "linux"
INSTALLER_TEMPLATE = "instalar.sh"
UNINSTALLER_TEMPLATE = "desinstalar.sh"
LAUNCHER_FOLDER = "lancadores"
# O que o instalador copia para `<programa>/lancadores` e preenche com os caminhos da pessoa.
LAUNCHER_FILES = ("dmaker.sh", "dmaker-mcp.sh", "ollama.sh", "dmaker.desktop", "dmaker-ollama.service")

# As bibliotecas que todo Linux tem: não vale avisar nem sugerir pacote para elas.
BASE_LIBRARIES = frozenset(
    {
        "libc.so.6",
        "libm.so.6",
        "libdl.so.2",
        "libpthread.so.0",
        "librt.so.1",
        "libgcc_s.so.1",
        "libstdc++.so.6",
        "libresolv.so.2",
        "libutil.so.1",
        "ld-linux-x86-64.so.2",
        "linux-vdso.so.1",
    }
)
# O Chromium abre estas por `dlopen`, então o `ldd` não as vê; sem elas a página não abre.
DLOPENED_LIBRARIES = ("libasound.so.2", "libcups.so.2", "libgbm.so.1", "libatspi.so.0", "libxkbcommon.so.0")

# biblioteca -> (pacote do apt, o nome muda no Ubuntu 24.04 em diante, com o sufixo t64). A lista é a que o Playwright usa
# para o Chromium no Ubuntu 22.04 e 24.04.
APT_PACKAGES: dict[str, tuple[str, bool]] = {
    "libnss3.so": ("libnss3", False),
    "libnssutil3.so": ("libnss3", False),
    "libsmime3.so": ("libnss3", False),
    "libnspr4.so": ("libnspr4", False),
    "libatk-1.0.so.0": ("libatk1.0-0", True),
    "libatk-bridge-2.0.so.0": ("libatk-bridge2.0-0", True),
    "libatspi.so.0": ("libatspi2.0-0", True),
    "libcups.so.2": ("libcups2", True),
    "libdrm.so.2": ("libdrm2", False),
    "libdbus-1.so.3": ("libdbus-1-3", False),
    "libxcb.so.1": ("libxcb1", False),
    "libxkbcommon.so.0": ("libxkbcommon0", False),
    "libX11.so.6": ("libx11-6", False),
    "libX11-xcb.so.1": ("libx11-xcb1", False),
    "libXcomposite.so.1": ("libxcomposite1", False),
    "libXdamage.so.1": ("libxdamage1", False),
    "libXext.so.6": ("libxext6", False),
    "libXfixes.so.3": ("libxfixes3", False),
    "libXrandr.so.2": ("libxrandr2", False),
    "libXi.so.6": ("libxi6", False),
    "libgbm.so.1": ("libgbm1", False),
    "libpango-1.0.so.0": ("libpango-1.0-0", False),
    "libcairo.so.2": ("libcairo2", False),
    "libasound.so.2": ("libasound2", True),
    "libglib-2.0.so.0": ("libglib2.0-0", True),
    "libgobject-2.0.so.0": ("libglib2.0-0", True),
    "libgio-2.0.so.0": ("libglib2.0-0", True),
    "libgmodule-2.0.so.0": ("libglib2.0-0", True),
    "libexpat.so.1": ("libexpat1", False),
    "libfontconfig.so.1": ("libfontconfig1", False),
    "libfreetype.so.6": ("libfreetype6", False),
}
T64_MARK = "@T64@"
RUNTIME_MARKS = frozenset({"@@PROGRAMA@@", "@@DADOS@@", "@@BIN@@"})


@dataclass(frozen=True)
class PartInfo:
    name: str
    size: int
    sha256: str


def parse_ldd_libraries(text: str) -> list[str]:
    """Os nomes de biblioteca de uma saída do `ldd` (a de cada binário do Chromium, junta), sem as do sistema base."""
    found: set[str] = set()
    for line in text.splitlines():
        if "=>" not in line:
            continue
        name = line.split("=>", 1)[0].strip()
        if name and name not in BASE_LIBRARIES:
            found.add(name)
    return sorted(found)


def chromium_libraries(ldd_text: str) -> list[str]:
    """O que o instalador confere: o que o `ldd` achou mais o que o Chromium abre por `dlopen`."""
    return sorted({*parse_ldd_libraries(ldd_text), *DLOPENED_LIBRARIES})


def apt_packages_for(libraries: Iterable[str], ubuntu_major: int) -> list[str]:
    """Os pacotes do apt que trazem as bibliotecas dadas, na ordem de aparição e sem repetir (t64 no Ubuntu 24.04+)."""
    packages: list[str] = []
    for library in libraries:
        entry = APT_PACKAGES.get(library)
        if entry is None:
            continue
        name, renamed = entry
        package = name + ("t64" if renamed and ubuntu_major >= 24 else "")
        if package not in packages:
            packages.append(package)
    return packages


def apt_case_lines(libraries: Iterable[str]) -> str:
    """As linhas do `case` do instalador que traduzem biblioteca em pacote (o instalador acrescenta o sufixo t64)."""
    lines = []
    for library in libraries:
        entry = APT_PACKAGES.get(library)
        if entry is None:
            continue
        name, renamed = entry
        lines.append(f'        {library}) echo "{name}{T64_MARK if renamed else ""}" ;;')
    return "\n".join(lines)


def parts_listing(parts: Iterable[PartInfo]) -> str:
    return "\n".join(f"{part.sha256} {part.size} {part.name}" for part in parts)


def render_installer(
    template: str,
    version: str,
    parts: list[PartInfo],
    libraries: list[str],
    program_bytes: int,
    data_bytes: int,
) -> str:
    """O `.run`: o modelo `instalar.sh` com a versão, o SHA-256 de cada parte e as bibliotecas do Chromium embutidos."""
    replacements = {
        "@@VERSAO@@": version,
        "@@NOME_BASE@@": installer_basename(version, "linux"),
        "@@BYTES_PROGRAMA@@": str(program_bytes),
        "@@BYTES_DADOS@@": str(data_bytes),
        "@@PARTES@@": parts_listing(parts),
        "@@BIBLIOTECAS@@": "\n".join(libraries),
        "@@PACOTES_APT@@": apt_case_lines(libraries),
    }
    text = template
    for token, value in replacements.items():
        text = text.replace(token, value)
    # As marcas dos lançadores (@@PROGRAMA@@, @@DADOS@@, @@BIN@@) são preenchidas pelo próprio instalador, na máquina de quem instala.
    leftover = [mark for mark in re.findall(r"@@[A-Z_]+@@", text) if mark not in RUNTIME_MARKS]
    if leftover:
        raise ValueError(f"O instalador ficou com marcas sem valor: {sorted(set(leftover))}")
    return text


def read_installer_templates(repo_root: Path) -> dict[str, str]:
    """Os arquivos de `instalador/linux/` que o build usa, pelo nome relativo a essa pasta."""
    base = repo_root / INSTALLER_FOLDER
    names = [
        INSTALLER_TEMPLATE,
        UNINSTALLER_TEMPLATE,
        *(f"{LAUNCHER_FOLDER}/{name}" for name in LAUNCHER_FILES),
    ]
    return {name: (base / name).read_text(encoding="utf-8") for name in names}


def parse_filters(ffmpeg_filters_output: str) -> dict[str, bool]:
    """Se o `ffmpeg -filters` lista o `ladspa` e o `lv2` (o Linux do BtbN pode não ter um dos dois)."""
    names = {line.split()[1] for line in ffmpeg_filters_output.splitlines() if len(line.split()) >= 2}
    return {"ladspa": "ladspa" in names, "lv2": "lv2" in names}
