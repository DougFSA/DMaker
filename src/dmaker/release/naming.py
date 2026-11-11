"""Os nomes dos arquivos do instalador, com a versão. Puro."""

from __future__ import annotations

from .platforms import PLATFORMS

# O GitHub limita cada arquivo de uma release a 2 GiB (2 147 483 648 bytes); a fatia fica abaixo disso com folga.
SLICE_BYTES = 2_000_000_000
GITHUB_FILE_LIMIT = 2 * 1024**3


def installer_basename(version: str, platform: str) -> str:
    return f"DMaker-{version}-{platform}-x64"


def installer_name(version: str, platform: str) -> str:
    return installer_basename(version, platform) + PLATFORMS[platform].installer_extension


def slice_names(version: str, platform: str, count: int) -> list[str]:
    """As partes de dados ao lado do instalador: `<base>-1.bin` (Inno Setup) ou `<base>-1.part` (Linux)."""
    base = installer_basename(version, platform)
    extension = PLATFORMS[platform].part_extension
    return [f"{base}-{number}{extension}" for number in range(1, count + 1)]


def installer_files(version: str, platform: str, slice_count: int) -> list[str]:
    return [installer_name(version, platform), *slice_names(version, platform, slice_count)]


def release_folder_name(version: str) -> str:
    return f"v{version}"


def tag_for(version: str) -> str:
    """A tag do git de uma versão do pacote: `2.0.0` é a tag `v2` (o nome da versão no Jira), como o `dmaker-producao` cria."""
    return f"v{version.split('.')[0]}"
