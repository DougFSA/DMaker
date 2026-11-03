"""O `.mcp.json` sobe o servidor do clone em que a sessão está, em qualquer pasta (DMK-48).

O Claude Code só expande `${VAR}` no `.mcp.json` com o ambiente dele, e `CLAUDE_PROJECT_DIR` (a raiz do projeto) existe
apenas no ambiente do servidor que ele sobe; também não há campo `cwd`. Então o `cmd` lê a variável já dentro do
servidor, entra na raiz e roda o `.venv\\Scripts\\dmaker.exe mcp` do clone. Aqui o arquivo é conferido pela forma e,
no Windows, subindo o servidor com o comando exatamente como o arquivo o escreve, de uma pasta de trabalho que não é
a raiz e numa raiz com espaço e caracteres que o `cmd` costuma engolir.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dmaker import config

REPO = Path(__file__).resolve().parents[1]
ONLY_WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="o .mcp.json usa o cmd do Windows")

# raízes de clone de teste: com espaço e acento, e com os caracteres que o cmd interpreta (& ( ) ^ !)
AWKWARD_ROOTS = ["clone com espaço", "a & b (x86) ^ !é!"]


def _server() -> dict:
    servers = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == ["dmaker"]
    return servers["dmaker"]


def _command_and_args() -> tuple[str, list[str]]:
    server = _server()
    return server["command"], list(server["args"])


def _command_line() -> str:
    """O texto que o `cmd /c` executa: o último argumento."""
    return _command_and_args()[1][-1]


# ---------- a forma do arquivo (vale em qualquer sistema) ----------


def test_the_server_command_is_a_program_every_windows_has_and_never_an_absolute_path():
    command, args = _command_and_args()
    assert command == "cmd"
    assert args[:4] == ["/d", "/v:on", "/s", "/c"] and len(args) == 5
    assert set(_server()) == {"command", "args"}  # sem cwd (o Claude Code não tem) e sem env com caminho


def test_the_project_dir_is_read_inside_the_server_not_expanded_by_claude_code():
    """`${CLAUDE_PROJECT_DIR}` no arquivo viraria `.` antes de o servidor existir, porque a variável só nasce nele."""
    text = (REPO / ".mcp.json").read_text(encoding="utf-8")
    assert "${" not in text
    line = _command_line()
    # expansão tardia (/v:on): aguenta & ( ) ^ e acento no caminho
    assert "cd /d !CLAUDE_PROJECT_DIR!" in line
    assert "%CLAUDE_PROJECT_DIR%" not in line  # a expansão comum quebraria em `(x86)` e `&`


def test_it_runs_the_clone_venv_and_never_the_global_python():
    line = _command_line()
    assert "if exist .venv\\Scripts\\dmaker.exe (.venv\\Scripts\\dmaker.exe mcp)" in line
    assert "python" not in line.lower()
    assert ".venv" in line.split("else", 1)[1]  # sem o .venv, a mensagem diz onde procurou
    assert "exit /b 1" in line


def test_the_manual_shows_the_same_configuration_as_the_file():
    """O exemplo do manual é o próprio arquivo: copiar dele funciona, e os dois não divergem."""
    manual = (REPO / "docs" / "MANUAL.md").read_text(encoding="utf-8")
    assert (REPO / ".mcp.json").read_text(encoding="utf-8").strip() in manual


# ---------- subindo o servidor como o Claude Code sobe (Windows) ----------


def _launcher() -> Path:
    """O `dmaker.exe` do venv em que o teste roda: um clone de teste ganha uma cópia dele no seu `.venv`."""
    launcher = Path(sys.prefix) / "Scripts" / "dmaker.exe"
    if not launcher.is_file():
        pytest.skip(f"sem {launcher}: o teste precisa do dmaker.exe do venv")
    return launcher


def _fake_clone(parent: Path, name: str) -> Path:
    """Uma raiz de clone só com o `.venv\\Scripts\\dmaker.exe`: o que o `.mcp.json` procura, sem copiar o venv."""
    root = parent / name
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    copy = scripts / "dmaker.exe"
    shutil.copy2(_launcher(), copy)
    check = subprocess.run([str(copy), "--version"], capture_output=True, text=True, timeout=60, env=_env())
    if (
        check.returncode != 0
    ):  # o inicializador guarda o caminho do Python; se a cópia não roda, não há o que provar
        pytest.skip(f"a cópia do dmaker.exe não roda: {check.stderr.strip()[:200]}")
    return root


def _env(**extra: str) -> dict[str, str]:
    """O ambiente de um servidor MCP: o enxuto do SDK, mais a pasta de dados do teste e o PYTHONPATH do worktree."""
    from mcp.client.stdio import get_default_environment

    return {
        **get_default_environment(),
        "DMAKER_DATA_DIR": str(config.DATA_DIR),
        # num worktree o pacote instalado é o da pasta principal: sem o PYTHONPATH o servidor testaria o código errado
        **({"PYTHONPATH": os.environ["PYTHONPATH"]} if "PYTHONPATH" in os.environ else {}),
        **extra,
    }


def _tool_names(env: dict[str, str], cwd: Path) -> set[str]:
    """Sobe o servidor com o comando do `.mcp.json`, faz o aperto de mão e lista as ferramentas."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    command, args = _command_and_args()
    params = StdioServerParameters(command=command, args=args, env=env, cwd=str(cwd))

    async def handshake() -> set[str]:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return {tool.name for tool in (await session.list_tools()).tools}

    return asyncio.run(asyncio.wait_for(handshake(), timeout=120))


@ONLY_WINDOWS
@pytest.mark.parametrize("root_name", AWKWARD_ROOTS)
def test_server_starts_from_the_project_dir_even_when_the_working_dir_is_elsewhere(root_name, tmp_path):
    root = _fake_clone(tmp_path, root_name)
    elsewhere = tmp_path / "outra pasta"
    elsewhere.mkdir()
    names = _tool_names(_env(CLAUDE_PROJECT_DIR=str(root)), cwd=elsewhere)
    assert "dmaker_guide" in names and len(names) > 20


@ONLY_WINDOWS
def test_without_the_variable_the_server_starts_from_the_current_folder(tmp_path):
    """Um Claude Code que ainda não manda a variável cai na pasta atual, em vez de falhar calado."""
    root = _fake_clone(tmp_path, "clone com espaço")
    assert "dmaker_guide" in _tool_names(_env(), cwd=root)


@ONLY_WINDOWS
def test_without_the_variable_and_outside_the_clone_it_fails_with_a_message_instead_of_hanging(tmp_path):
    elsewhere = tmp_path / "sem venv"
    elsewhere.mkdir()
    command, args = _command_and_args()
    result = subprocess.run(
        [command, *args],
        cwd=elsewhere,
        env=_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    assert result.returncode != 0
    assert ".venv\\Scripts\\dmaker.exe" in result.stderr
    # a mensagem diz em que pasta procurou (só o nome: o cmd escreve na página de código dele, não em UTF-8)
    assert elsewhere.name in result.stderr
    assert result.stdout.strip() == ""  # nada fora do protocolo no stdout do servidor


@ONLY_WINDOWS
def test_a_project_dir_without_the_venv_fails_with_a_message(tmp_path):
    """O que acontece numa sessão aberta num worktree: a raiz da sessão não tem `.venv`."""
    worktree_like = tmp_path / "worktree"
    worktree_like.mkdir()
    command, args = _command_and_args()
    result = subprocess.run(
        [command, *args],
        cwd=tmp_path,
        env=_env(CLAUDE_PROJECT_DIR=str(worktree_like)),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    assert result.returncode != 0
    assert worktree_like.name in result.stderr and ".venv" in result.stderr
