"""O marcador `instalacao.json` e os lançadores do programa instalado. Puro: devolve texto."""

from __future__ import annotations

import json

from ..config import INSTALL_MARKER_NAME

# O instalador troca este texto pela pasta de dados que a pessoa escolheu (com as barras já escapadas para JSON).
DATA_PLACEHOLDER = "@@DADOS@@"


def marker_json(version: str, data_dir: str) -> str:
    return json.dumps({"versao": version, "dados": data_dir}, ensure_ascii=False, indent=2) + "\n"


def marker_template(version: str) -> str:
    """O marcador com o lugar da pasta de dados em branco, que o instalador preenche ao instalar."""
    return marker_json(version, DATA_PLACEHOLDER)


def _crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def windows_launcher(subcommand: str = "") -> str:
    """Um .cmd que roda o Python do programa ao lado dele. Não é o `dmaker.exe` do pip, que guarda o caminho absoluto
    do Python e quebra quando a pasta muda. `PYTHONUTF8` evita erro de acento quando a saída é redirecionada e
    `PYTHONNOUSERSITE` impede que pacotes do usuário se misturem aos do programa."""
    command = f'"%~dp0python\\python.exe" -m dmaker {subcommand}'.rstrip() + " %*"
    return _crlf(
        "@echo off\n"
        "rem Lançador do DMaker instalado: usa o Python que mora ao lado deste arquivo.\n"
        "setlocal\n"
        'set "PYTHONUTF8=1"\n'
        'set "PYTHONNOUSERSITE=1"\n'
        f"{command}\n"
        "exit /b %errorlevel%\n"
    )


def windows_launchers() -> dict[str, str]:
    return {"dmaker.cmd": windows_launcher(), "dmaker-mcp.cmd": windows_launcher("mcp")}


__all__ = [
    "DATA_PLACEHOLDER",
    "INSTALL_MARKER_NAME",
    "marker_json",
    "marker_template",
    "windows_launcher",
    "windows_launchers",
]
