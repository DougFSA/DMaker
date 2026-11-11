"""O texto das notas da release (aba Releases do GitHub): como baixar, instalar e conferir. Puro."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .licenses import non_commercial_models
from .naming import tag_for
from .platforms import PLATFORMS

# O GitHub aceita 125 000 caracteres no corpo de uma release; 120 000 deixa folga para o que ele acrescenta.
NOTES_LIMIT = 120_000
REPOSITORY_URL = "https://github.com/DougFSA/DMaker"
# O que só interessa a quem monta o pacote no computador de desenvolvimento: confunde quem baixa o instalador.
DEVELOPER_ONLY_SECTION = "Pré-requisitos na máquina"


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


def drop_subsection(section: str, title: str) -> str:
    """Tira de um bloco o `### <title>` até o próximo `###` (ou o fim)."""
    pattern = re.compile(rf"^### {re.escape(title)}\s*$.*?(?=^### |\Z)", re.MULTILINE | re.DOTALL)
    return pattern.sub("", section).strip()


def _files_table(files: list[ReleaseFile]) -> list[str]:
    rows = ["| Arquivo | Tamanho | SHA-256 |", "|---|---|---|"]
    rows += [f"| `{file.name}` | {human_size(file.size)} | `{file.sha256}` |" for file in files]
    return rows


def _how_to_install(platform: str, installer: str) -> list[str]:
    if platform == "windows":
        return [
            "1. Baixe **todos** os arquivos desta seção para a **mesma pasta**.",
            "2. Confira o SHA-256 de cada um: `certutil -hashfile <arquivo> SHA256` e compare com a tabela.",
            f"3. Execute `{installer}`. Ele não pede administrador.",
        ]
    return [
        "1. Baixe **todos** os arquivos desta seção (e o `SHA256SUMS.txt`) para a **mesma pasta**.",
        "2. Confira o SHA-256 de cada um: `sha256sum -c SHA256SUMS.txt --ignore-missing`.",
        f"3. Rode `sh {installer}`. Ele não pede administrador: instala em `~/.local/opt/dmaker` e `~/.local/share/dmaker`.",
    ]


def _platform_section(platform: str, files: list[ReleaseFile]) -> list[str]:
    installer = files[0].name
    return [
        f"## {PLATFORMS[platform].label}",
        "",
        *_how_to_install(platform, installer),
        "",
        *_files_table(files),
        "",
    ]


def _intro(version: str) -> list[str]:
    return [
        f"# DMaker {version}",
        "",
        "O pacote tem tudo (Python, FFmpeg, Chromium e os modelos de voz, legenda e recorte) e instala sem internet.",
        "Como o GitHub limita cada arquivo a 2 GiB, ele vem em partes: baixe todas as da sua seção para a mesma pasta.",
        "Atualizar é rodar o instalador da versão nova por cima: projetos, vozes, saídas e configurações ficam.",
        "Os modelos de linguagem do Ollama não vão no pacote: depois de instalar, rode `ollama pull gpt-oss:20b`.",
        "",
    ]


def _license_lines(excluded_models: Iterable[str]) -> list[str]:
    excluded = tuple(excluded_models)
    lines = []
    restricted = non_commercial_models(excluded)
    if restricted:
        lines += ["## Aviso de uso não comercial", ""]
        for item in restricted:
            lines.append(
                f"- **{item.name}** vai no pacote com a licença **{item.license}**: pode ser redistribuído com "
                "atribuição, mas os pesos não podem ser usados com fins comerciais."
            )
        lines.append("")
    if excluded:
        lines += [
            "## Modelos que baixam no primeiro uso",
            "",
            "Estes modelos **não** vão no pacote: " + ", ".join(f"`{model}`" for model in excluded) + ".",
            "Eles baixam na primeira vez que uma função precisa deles (`dmaker models download <modelo>`), com internet.",
            "",
        ]
    return lines


def release_notes(
    version: str,
    files_by_platform: Mapping[str, list[ReleaseFile]],
    changelog_text: str = "",
    excluded_models: Iterable[str] = (),
    limit: int = NOTES_LIMIT,
) -> str:
    """O corpo único da release: uma seção por sistema, o aviso de licença e o "O que mudou".
    Passou de `limit`, o "O que mudou" sai e entra o link do CHANGELOG na tag."""
    platforms = [platform for platform in PLATFORMS if files_by_platform.get(platform)]
    lines = _intro(version)
    for platform in platforms:
        lines += _platform_section(platform, files_by_platform[platform])
    lines += _license_lines(excluded_models)
    base = "\n".join(lines).rstrip() + "\n"
    section = drop_subsection(changelog_section(changelog_text, version), DEVELOPER_ONLY_SECTION)
    if not section:
        return base
    with_changes = base + f"\n## O que mudou\n\n{section}\n"
    if len(with_changes) <= limit:
        return with_changes
    link = f"{REPOSITORY_URL}/blob/{tag_for(version)}/CHANGELOG.md"
    return (
        base
        + f"\n## O que mudou\n\nO texto é longo demais para esta página: veja o [CHANGELOG.md]({link}).\n"
    )
