"""O texto das notas da release (aba Releases do GitHub): como baixar, instalar e conferir. Puro."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseFile:
    name: str
    size: int
    sha256: str


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.2f} {unit}".replace(".", ",")
        value /= 1024
    raise AssertionError("inalcançável")  # pragma: no cover


def changelog_section(changelog: str, version: str) -> str:
    """O bloco `## v<N>` do CHANGELOG (as notas da versão); vazio se a versão não está lá."""
    major = version.split(".")[0]
    heading = re.compile(rf"^## v{re.escape(major)}\b.*$", re.MULTILINE)
    match = heading.search(changelog)
    if not match:
        return ""
    following = re.search(r"^## ", changelog[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(changelog)
    return changelog[match.end() : end].strip()


def release_notes(
    version: str, files: list[ReleaseFile], platform_label: str, changelog_text: str = ""
) -> str:
    installer = files[0].name
    lines = [
        f"# DMaker {version} para {platform_label}",
        "",
        "## Como instalar",
        "",
        "O pacote tem tudo (Python, FFmpeg, Chromium e os modelos de voz, legenda e recorte) e instala sem internet.",
        "Como o GitHub limita cada arquivo a 2 GiB, ele vem em partes:",
        "",
        "1. Baixe **todos** os arquivos abaixo para a **mesma pasta**.",
        "2. Confira o SHA-256 de cada um (`certutil -hashfile <arquivo> SHA256` no Windows).",
        f"3. Execute `{installer}`. Ele não pede administrador.",
        "",
        "Atualizar é rodar o instalador da versão nova por cima: projetos, vozes, saídas e configurações ficam.",
        "Os modelos de linguagem do Ollama não vão no pacote: depois de instalar, rode `ollama pull gpt-oss:20b`.",
        "",
        "## Arquivos",
        "",
        "| Arquivo | Tamanho | SHA-256 |",
        "|---|---|---|",
    ]
    lines += [f"| `{file.name}` | {human_size(file.size)} | `{file.sha256}` |" for file in files]
    section = changelog_section(changelog_text, version) if changelog_text else ""
    if section:
        lines += ["", "## O que mudou", "", section]
    return "\n".join(lines) + "\n"
