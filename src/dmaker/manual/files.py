"""Onde o manual está no disco e como ler e gravar: a única parte do pacote que mexe em arquivos do manual.

No checkout (instalação editável) o manual é `docs/MANUAL.md` e as versões para IA ficam em `docs/ia`. Numa
instalação comum o `setup.py` leva uma cópia para `dmaker/resources/manual`, para a busca funcionar sem o
repositório e sem internet.
"""

from __future__ import annotations

from pathlib import Path

from .. import config

MANUAL_NAME = "MANUAL.md"
IA_FOLDER = "ia"
IMAGES_FOLDER = "img"
PACKAGED_FOLDER = "manual"


def checkout_docs_dir() -> Path:
    """`docs/` do repositório: lida a cada uso, porque `DMAKER_HOME` pode mudar a raiz."""
    return config.ROOT / "docs"


def packaged_docs_dir() -> Path:
    return config.PACKAGE_DIR / "resources" / PACKAGED_FOLDER


def docs_dir() -> Path:
    """A pasta do manual: a do repositório quando existe, senão a cópia que veio no pacote instalado."""
    local = checkout_docs_dir()
    return local if (local / MANUAL_NAME).exists() else packaged_docs_dir()


def is_checkout() -> bool:
    return docs_dir() == checkout_docs_dir()


def manual_path() -> Path:
    return docs_dir() / MANUAL_NAME


def ia_dir() -> Path:
    return docs_dir() / IA_FOLDER


def images_dir() -> Path:
    return docs_dir() / IMAGES_FOLDER


def read_manual() -> str:
    path = manual_path()
    if not path.exists():
        raise FileNotFoundError(f"Manual não encontrado em {path}.")
    return path.read_text(encoding="utf-8")


def read_ia_files(folder: Path | None = None) -> dict[str, str]:
    """Os arquivos de `docs/ia` (`.md` e `llms.txt`) por nome; vazio se a pasta ainda não existe."""
    folder = folder or ia_dir()
    if not folder.exists():
        return {}
    return {
        item.name: item.read_text(encoding="utf-8")
        for item in sorted(folder.iterdir())
        if item.is_file() and item.suffix in {".md", ".txt"}
    }


def read_ia_doc(task_id: str) -> str | None:
    path = ia_dir() / f"{task_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def write_text(path: Path, text: str) -> bool:
    """Grava com fim de linha LF (como o repositório); devolve se o arquivo mudou."""
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True
