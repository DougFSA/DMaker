"""Nenhum arquivo versionado depende da máquina em que o DMaker foi escrito (DMK-48).

O DMaker e o servidor MCP têm que funcionar em qualquer máquina e em qualquer pasta do clone. O que quebrou foi
um caminho fixo (`<unidade>:\\...\\DMaker`) no `.mcp.json` e nas instruções, e uma música padrão de uma pasta de
usuário de outra máquina nos modelos. Este teste lê os arquivos que o git versiona e reprova esses dois jeitos de
voltar, dizendo o arquivo, a linha e o porquê.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

REPO = Path(__file__).resolve().parents[1]

# `C:\`, `D:/`... só com uma letra solta antes dos dois-pontos: `https://` e `file:///` não contam
DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
UNC_PATH = re.compile(r"(?<![\\\w])\\\\[\w.$-]+\\")
# um caminho de unidade em que alguma pasta se chama dmaker: é o clone citado por onde ele estava, não onde ele está
CLONE_FOLDER = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:[^\s\"'`<>|]*?[\\/])?dmaker(?![\w.-])",
    re.IGNORECASE,
)
USER_FOLDER = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+users[\\/]", re.IGNORECASE)

# onde nem a pasta do clone nem a de um usuário podem aparecer (o que o Claude e as pessoas leem como instrução)
INSTRUCTION_ROOTS = (".claude/", "scripts/", "src/")
INSTRUCTION_FILES = ("CLAUDE.md", "README.md", "docs/MANUAL.md")
TEMPLATES_ROOT = "templates/"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    text: str
    why: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.why}\n    {self.text.strip()[:160]}"


def versioned_files() -> list[str]:
    """Os arquivos que o git versiona (com o que está no índice, inclusive o que ainda não foi commitado)."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True, timeout=60
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("sem o git ou fora de um repositório: não há o que listar")
    return [name for name in listed.decode("utf-8").split("\0") if name]


def read_text(path: str) -> str | None:
    """O texto do arquivo, ou None se for binário, para não procurar caminho dentro de imagem e fonte."""
    try:
        raw = (REPO / path).read_bytes()
    except OSError:  # saiu do disco e ainda está no índice
        return None
    if b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


def is_instruction_file(path: str) -> bool:
    return path in INSTRUCTION_FILES or path.startswith(INSTRUCTION_ROOTS) or is_template_doc(path)


def is_template_doc(path: str) -> bool:
    """O texto que explica os modelos (README): lê-se como instrução, e os exemplos de uso dele podem citar arquivos."""
    return path.startswith(TEMPLATES_ROOT) and path.endswith(".md")


def scan_instruction_text(path: str, text: str) -> Iterator[Finding]:
    """A pasta do clone ou de um usuário citada numa instrução: troque por a raiz do clone ou por um marcador."""
    for number, line in enumerate(text.splitlines(), start=1):
        if CLONE_FOLDER.search(line):
            yield Finding(
                path,
                number,
                line,
                "cita a pasta do clone por um caminho de unidade; escreva 'a raiz do clone' ou use um marcador "
                "como <pasta do DMaker>",
            )
        if USER_FOLDER.search(line):
            yield Finding(
                path,
                number,
                line,
                "cita uma pasta de usuário (<unidade>:\\Users\\...), que só existe numa máquina; use um marcador",
            )


def scan_mcp_config(path: str, text: str) -> Iterator[Finding]:
    """O `.mcp.json` com qualquer caminho absoluto: o clone pode estar em qualquer pasta, então ele não cita nenhuma."""
    why = (
        "caminho absoluto no .mcp.json; o servidor tem que subir da pasta do clone em qualquer máquina "
        "(use o CLAUDE_PROJECT_DIR, como o resto do arquivo faz)"
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        yield Finding(path, 1, text, "o .mcp.json não é um JSON válido")
        return
    # lê os textos já decodificados: no arquivo a barra invertida vem em dobro (`D:\DMaker`)
    for trail, value in _strings_outside_examples(data):
        if DRIVE_PATH.search(value) or UNC_PATH.search(value):
            yield Finding(path, _line_of(text, value), f"{trail}: {value}", why)


def _strings_outside_examples(node: object, trail: str = "") -> Iterator[tuple[str, str]]:
    """Cada texto do modelo com o caminho dele no JSON, pulando o valor de `example`, que é exemplo declarado."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "example":
                continue
            yield from _strings_outside_examples(value, f"{trail}.{key}" if trail else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings_outside_examples(value, f"{trail}[{index}]")
    elif isinstance(node, str):
        yield trail, node


def scan_template(path: str, text: str) -> Iterator[Finding]:
    """Um modelo com caminho de unidade fora de um `example`: um padrão que só funciona numa máquina."""
    why = (
        'caminho absoluto de unidade fora de um "example"; um caminho padrão aponta para um arquivo de uma '
        'máquina só, então o parâmetro é obrigatório (sem default) e o exemplo vai em "example"'
    )
    if PurePosixPath(path).suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            for trail, value in _strings_outside_examples(data):
                if DRIVE_PATH.search(value) or UNC_PATH.search(value):
                    yield Finding(path, _line_of(text, value), f"{trail}: {value}", why)
            return
    for number, line in enumerate(text.splitlines(), start=1):
        if DRIVE_PATH.search(line) or UNC_PATH.search(line):
            yield Finding(path, number, line, why)


def _line_of(text: str, value: str) -> int:
    """A linha onde o texto aparece no arquivo, para a mensagem apontar para ela (a primeira que o contém)."""
    needle = json.dumps(value, ensure_ascii=False)[1:-1]
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    return 1


def scan_repository(files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        text = read_text(path)
        if text is None:  # binário, ou arquivo que saiu do disco e ainda está no índice
            continue
        if path == ".mcp.json":
            findings.extend(scan_mcp_config(path, text))
        elif path.startswith(TEMPLATES_ROOT) and not is_template_doc(path):
            findings.extend(scan_template(path, text))
        if is_instruction_file(path):
            findings.extend(scan_instruction_text(path, text))
    return findings


def test_no_versioned_file_depends_on_the_machine_it_was_written_on():
    findings = scan_repository(versioned_files())
    assert not findings, (
        "caminho de máquina em arquivo versionado (o DMaker tem que funcionar em qualquer pasta):\n"
        + "\n".join(str(finding) for finding in findings)
    )


def test_the_scan_covers_the_files_the_card_names():
    files = versioned_files()
    assert ".mcp.json" in files and "README.md" in files and "docs/MANUAL.md" in files
    assert any(name.startswith(".claude/skills/") for name in files)
    assert any(name.startswith("templates/") and name.endswith(".json") for name in files)
    assert any(name.startswith("scripts/") for name in files) and any(
        name.startswith("src/") for name in files
    )


# ---------- o que o varredor reconhece (o teste do teste) ----------


def _paths(findings: Iterator[Finding]) -> list[int]:
    return [finding.line for finding in findings]


@pytest.mark.parametrize(
    "line",
    [
        "cd D:\\DMaker",
        "& D:\\DMaker\\.venv\\Scripts\\python.exe -m pytest",
        'mklink /J "$wt\\bin" "d:/dmaker/bin"',
        "leia X:\\Douglas\\DMaker\\CLAUDE.md antes",
        "git clone https://github.com/DougFSA/DMaker.git C:/dmaker",
    ],
)
def test_clone_folder_citations_are_found(line):
    assert _paths(scan_instruction_text("x.md", line)) == [1]


@pytest.mark.parametrize(
    "line",
    [
        "C:\\Users\\alguem\\Videos\\musica.m4a",
        "c:/users/alguem/trilha.mp3",
    ],
)
def test_user_folder_citations_are_found(line):
    assert _paths(scan_instruction_text("x.md", line)) == [1]


@pytest.mark.parametrize(
    "line",
    [
        "gravacao em C:/videos/gravacao.mp4",
        "os exemplos usam D:/imagens/assunto1.png",
        "a fonte fica em C:/Windows/Fonts",
        "git clone https://github.com/DougFSA/DMaker.git",
        "cd <pasta do DMaker>",
        "cd DMaker",
        "http://dmaker.composicao/index.html",
        ".venv\\Scripts\\dmaker.exe mcp",
        "C:/dm/cap",
    ],
)
def test_examples_of_user_files_and_system_folders_are_not_flagged(line):
    assert _paths(scan_instruction_text("x.md", line)) == []


def test_mcp_config_with_an_absolute_path_is_found_and_the_portable_one_is_not():
    absolute = '{"command": "D:\\\\DMaker\\\\.venv\\\\Scripts\\\\dmaker.exe"}'
    assert _paths(scan_mcp_config(".mcp.json", absolute)) == [1]
    assert _paths(scan_mcp_config(".mcp.json", '{"command": "\\\\\\\\servidor\\\\pasta\\\\dmaker.exe"}')) == [
        1
    ]
    portable = (REPO / ".mcp.json").read_text(encoding="utf-8")
    assert _paths(scan_mcp_config(".mcp.json", portable)) == []


def test_a_template_default_with_a_drive_path_is_found_but_an_example_is_not():
    bad = json.dumps({"params": {"musica": {"type": "path", "default": "D:/musicas/trilha.mp3"}}}, indent=2)
    found = list(scan_template("templates/x.json", bad))
    assert [finding.line for finding in found] == [5]
    assert "obrigatório" in found[0].why
    declared = json.dumps({"params": {"imagens": {"example": [{"imagem": "C:/imagens/a.png"}]}}})
    assert list(scan_template("templates/x.json", declared)) == []
    body = json.dumps({"timeline": [{"src": "C:\\Users\\alguem\\Videos\\a.mp4"}]})
    assert list(scan_template("templates/x.json", body))
    assert list(scan_template("templates/x/index.html", '<img src="E:/fotos/a.png">'))
