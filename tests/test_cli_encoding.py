"""A saída do `dmaker` sai em UTF-8 também quando vai para um arquivo ou para outro programa (DMK-49).

No console do Windows o Python escreve direto na tela e os acentos saem certos. Com a saída redirecionada e sem
`PYTHONIOENCODING`, ele cai na página de código do sistema (cp1252): quem lê como UTF-8 vê `indisponÃ­vel`, e o
Rich troca as molduras por `+- Error ---`. O ajuste mora no `__call__` do app (`dmaker.cli._Utf8Typer`): um
`@app.callback()` não serve, porque o `--help`, o `--version` e os erros de uso saem antes do corpo dele.

Os testes de comportamento rodam o app num processo à parte, pelo mesmo caminho do `dmaker.exe` (`app()`), com a
saída capturada e sem `PYTHONIOENCODING` nem `PYTHONUTF8` no ambiente.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import typer

import dmaker
from dmaker import __version__
from dmaker import cli as cli_module

REPO = Path(__file__).resolve().parents[1]
CODE_UNDER_TEST = Path(dmaker.__file__).resolve().parents[1]

# Como o inicializador `dmaker.exe` chama o app: o mesmo `app()` de `dmaker.cli:app`
ENTRY_POINT = "import sys; sys.argv[0] = 'dmaker'; from dmaker.cli import app; sys.exit(app())"

# None: o ambiente do caso real (no Windows, a página de código do sistema, cp1252). O cp1252 forçado reproduz o
# defeito em qualquer máquina, inclusive onde o sistema já usa UTF-8 por padrão e o caso real passaria à toa.
CONSOLES = [
    pytest.param(None, id="ambiente-sem-variavel"),
    pytest.param("cp1252", id="console-cp1252-forcado"),
]


def child_env(io_encoding: str | None = None) -> dict[str, str]:
    """O ambiente do processo filho: o do teste, sem a codificação de saída, e com o código em teste no caminho."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(CODE_UNDER_TEST), env.get("PYTHONPATH")]))
    if io_encoding:
        env["PYTHONIOENCODING"] = io_encoding
    return env


def run_dmaker(
    *args: str, io_encoding: str | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-c", ENTRY_POINT, *args],
        env=child_env(io_encoding),
        cwd=cwd,
        capture_output=True,
        timeout=120,
    )


def as_utf8(raw: bytes) -> str:
    """Os bytes lidos como UTF-8; se não forem, o teste reprova com os bytes à mostra."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(f"a saída não é UTF-8 válido ({exc}): {raw[:200]!r}")


def has_box_drawing(text: str) -> bool:
    """Alguma linha de moldura Unicode (U+2500 a U+257F); sem UTF-8 o Rich desenha `+- Error ---`."""
    return any("─" <= char <= "╿" for char in text)


@pytest.mark.parametrize("io_encoding", CONSOLES)
def test_help_comes_out_as_valid_utf8_with_the_unicode_frame(io_encoding, tmp_path):
    result = run_dmaker("--help", io_encoding=io_encoding, cwd=tmp_path)
    assert result.returncode == 0
    text = as_utf8(result.stdout)
    assert "vídeos" in text and "Mostra a versão." in text
    assert has_box_drawing(text)


@pytest.mark.parametrize("io_encoding", CONSOLES)
def test_a_command_prints_its_accents_as_utf8(io_encoding, tmp_path):
    """O `probe` de um arquivo que não existe imprime a tabela de sempre, com os acentos dos títulos."""
    result = run_dmaker("probe", str(tmp_path / "nao-existe.mp4"), io_encoding=io_encoding, cwd=tmp_path)
    assert result.returncode == 0
    text = as_utf8(result.stdout)
    for title in ("duração", "áudio", "orientação"):
        assert title in text
    assert has_box_drawing(text)


@pytest.mark.parametrize("io_encoding", CONSOLES)
def test_a_usage_error_comes_out_as_utf8_with_the_unicode_frame(io_encoding, tmp_path):
    result = run_dmaker("comando-que-nao-existe", io_encoding=io_encoding, cwd=tmp_path)
    assert result.returncode == 2
    text = as_utf8(result.stderr)
    assert "No such command" in text
    assert has_box_drawing(text)


@pytest.mark.parametrize("io_encoding", CONSOLES)
def test_version_still_prints_the_version_and_exits_zero(io_encoding, tmp_path):
    result = run_dmaker("--version", io_encoding=io_encoding, cwd=tmp_path)
    assert result.returncode == 0
    assert as_utf8(result.stdout).strip() == f"dmaker {__version__}"


def test_importing_the_cli_does_not_change_the_encoding_of_the_process(tmp_path):
    """A codificação muda quando o app é chamado, nunca na importação: um teste que importa `dmaker.cli` a manteria."""
    probe = (
        "import json, sys\n"
        "def seen(): return [[s.encoding, s.errors] for s in (sys.stdout, sys.stderr)]\n"
        "before = seen()\n"
        "import dmaker.cli\n"
        "print(json.dumps([before, seen()]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=child_env("latin-1"),  # um que não seja UTF-8, para a mudança aparecer em qualquer máquina
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    before, after = json.loads(result.stdout)
    assert before[1][0].lower() != "utf-8"  # o ponto de partida não é UTF-8: mudar na importação apareceria
    assert after == before


def test_the_console_entry_point_is_the_app_that_sets_utf8_when_called():
    """Trocar a entrada por outra função deixaria o `dmaker.exe` sem o ajuste, e só uma reinstalação o notaria."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"]["dmaker"] == "dmaker.cli:app"
    assert isinstance(cli_module.app, typer.Typer)
    assert type(cli_module.app).__call__ is not typer.Typer.__call__


def _app_callbacks(tree: ast.Module) -> list[str]:
    """Os nomes das funções decoradas com `@app.callback(...)` no nível do módulo."""
    names = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "callback"
                and isinstance(target.value, ast.Name)
                and target.value.id == "app"
            ):
                names.append(node.name)
    return names


def test_the_app_declares_a_single_callback():
    """O Typer guarda só o último `@app.callback()`: um segundo apagaria o primeiro sem aviso (foi o DMK-49)."""
    tree = ast.parse(Path(cli_module.__file__).read_text(encoding="utf-8"))
    assert _app_callbacks(tree) == ["_main"]
    assert cli_module.app.registered_callback.callback.__name__ == "_main"


def test_the_callback_scan_finds_a_second_callback():
    """A conferência acima enxerga um `@app.callback()` a mais, com ou sem parênteses."""
    tree = ast.parse(
        "@app.callback()\ndef a(): ...\n\n@app.callback\ndef b(): ...\n\n@other.callback()\ndef c(): ...\n"
    )
    assert _app_callbacks(tree) == ["a", "b"]


class _Stream:
    """Um fluxo de texto com `reconfigure`, para ver o que o ajuste pede sem tocar no stdout do teste."""

    def __init__(self, encoding: str, errors: str):
        self.encoding, self.errors = encoding, errors

    def reconfigure(self, *, encoding: str, errors: str) -> None:
        self.encoding, self.errors = encoding, errors


def test_console_utf8_switches_the_encoding_and_keeps_how_each_stream_handles_errors(monkeypatch):
    """O stderr segue sem estourar com um caractere raro (`backslashreplace`); o stdout segue estrito."""
    stdout, stderr = _Stream("cp1252", "strict"), _Stream("cp1252", "backslashreplace")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    cli_module._console_utf8()
    assert (stdout.encoding, stdout.errors) == ("utf-8", "strict")
    assert (stderr.encoding, stderr.errors) == ("utf-8", "backslashreplace")


def test_console_utf8_ignores_a_stream_that_cannot_be_reconfigured(monkeypatch):
    """Sem console (`pythonw`) o stdout é None, e um fluxo trocado por outro tipo não tem `reconfigure`."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", object())
    cli_module._console_utf8()
