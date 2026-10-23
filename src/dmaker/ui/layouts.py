"""Persistência dos layouts nomeados da interface (arraste e redimensionamento de painéis).

Os layouts embutidos (Edição, Efeitos, Áudio, Player, Revisão) vivem no JavaScript
(static/layout.js); aqui só ficam os layouts salvos pela pessoa usando a interface,
guardados em um único arquivo JSON na raiz do projeto (`config.LAYOUTS_FILE`).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path


def serialize_layouts(layouts: dict[str, dict]) -> str:
    """Serializa o dicionário {nome: layout} em JSON legível, com as chaves em ordem estável."""
    return json.dumps(layouts, ensure_ascii=False, indent=2, sort_keys=True)


def deserialize_layouts(text: str) -> dict[str, dict]:
    """Interpreta o conteúdo de layouts.json; texto vazio ou de formato inesperado vira {}."""
    if not text.strip():
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


class LayoutStore:
    """Guarda os layouts nomeados salvos pela pessoa usando a interface, em um arquivo JSON.

    Um lock protege a sequência ler-modificar-escrever entre requisições concorrentes do
    servidor local (a interface pode ter mais de uma aba aberta).
    """

    def __init__(self, path: Path | Callable[[], Path]) -> None:
        # a função deixa o caminho ser lido a cada uso, sem fixar na importação a pasta de dados
        self._locate = path if callable(path) else lambda: path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._locate()

    def list(self) -> dict[str, dict]:
        with self._lock:
            return self._read()

    def get(self, name: str) -> dict | None:
        with self._lock:
            return self._read().get(name)

    def save(self, name: str, layout: dict) -> None:
        with self._lock:
            layouts = self._read()
            layouts[name] = layout
            self._write(layouts)

    def delete(self, name: str) -> bool:
        with self._lock:
            layouts = self._read()
            if name not in layouts:
                return False
            del layouts[name]
            self._write(layouts)
            return True

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return deserialize_layouts(self.path.read_text(encoding="utf-8"))

    def _write(self, layouts: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(serialize_layouts(layouts), encoding="utf-8")
