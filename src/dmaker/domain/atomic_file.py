"""Gravação e leitura de arquivo que não deixam ninguém ver a metade de um arquivo, e a revisão de um conteúdo.

A spec do projeto é escrita pela interface, pelo MCP e pela CLI, às vezes ao mesmo tempo que alguém a lê. Gravar
num temporário da mesma pasta e trocar de nome faz o leitor ver sempre o arquivo antigo inteiro ou o novo inteiro.
A `revision` (impressão digital curta dos bytes) é o que a interface compara para saber se o disco mudou.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path

# O Windows nega a troca (ou a leitura) por um instante quando outro processo está com o arquivo aberto; tentar de
# novo por alguns décimos de segundo cobre o caso sem esconder um erro de verdade.
REPLACE_ATTEMPTS = 40
REPLACE_WAIT_SECONDS = 0.05
REVISION_LENGTH = 16


def content_revision(data: bytes) -> str:
    """Revisão de um conteúdo: o começo do SHA-256 dos bytes. Muda sempre que o arquivo muda, e é igual quando uma
    gravação reescreve exatamente o que já estava lá (nada a reconciliar)."""
    return hashlib.sha256(data).hexdigest()[:REVISION_LENGTH]


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Grava `data` em `path` por um temporário na mesma pasta e `os.replace`, que troca o arquivo de uma vez."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        temporary.write_bytes(data)
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_WAIT_SECONDS)
    finally:
        temporary.unlink(
            missing_ok=True
        )  # depois da troca o temporário já não existe; se falhou, não fica lixo


def read_bytes_retrying(path: Path) -> bytes:
    """Lê o arquivo; o Windows nega a leitura por um instante se outro processo está trocando o arquivo."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            return path.read_bytes()
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)
    raise AssertionError("inalcançável")  # pragma: no cover - o laço sempre retorna ou levanta
