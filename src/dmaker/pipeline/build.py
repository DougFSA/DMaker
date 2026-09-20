"""Identificador do código que um processo da interface carregou.

Serve para o `RenderDispatcher` (`pipeline/remote.py`) perceber quando o servidor da interface está
rodando uma versão antiga do pacote (ex.: subiu antes de uma mudança na spec) e decidir se é seguro
reiniciá-lo sozinho. Não executa nada nem chama ffmpeg: só lê metadados dos arquivos em disco.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import config


def _tracked_files(root: Path) -> list[Path]:
    """Todo `.py` do pacote, mais os estáticos da interface (`ui/static`) e os recursos
    (`resources`), que também mudam o comportamento do servidor mesmo sem tocar em código Python."""
    files: set[Path] = set(root.rglob("*.py"))
    for extra_dir in (root / "ui" / "static", root / "resources"):
        if extra_dir.exists():
            files.update(p for p in extra_dir.rglob("*") if p.is_file())
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def build_id(root: Path = config.PACKAGE_DIR) -> str:
    """Sha1 curto e estável do estado atual do código: caminho relativo, data de modificação e
    tamanho de cada arquivo rastreado. Dois processos com o mesmo `build_id` carregaram o mesmo
    código; um `build_id` diferente do atual do disco indica um processo desatualizado."""
    digest = hashlib.sha1()
    for path in _tracked_files(root):
        try:
            st = path.stat()
        except OSError:
            continue  # arquivo pode ter sido apagado entre o rglob e o stat; ignora
        rel = path.relative_to(root).as_posix()
        digest.update(f"{rel}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    return digest.hexdigest()[:16]
