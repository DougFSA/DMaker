"""Guarda de isolamento: nenhum teste pode escrever nos dados reais de quem usa o editor.

Sem CI, a suíte é o último portão, e ela não pode depender do que existe (ou está sendo gravado agora, por
uma dublagem em andamento, por exemplo) em cache/, output/, projects/, conversations/, assets/voices/ ou nos léxicos de
pronúncia. Um gancho de auditoria do Python observa as escritas do processo de teste: ele enxerga só o que
os testes fazem, então um render real rodando em paralelo não dá falso positivo.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from dmaker import config

LEXICON_NAME = "pronunciation.json"
_WRITE_MODE_CHARS = frozenset("wax+")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# eventos de auditoria que mexem no disco sem passar por `open`: (evento, posições dos caminhos afetados)
_PATH_EVENTS = {
    "os.mkdir": (0,),
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.rename": (0, 1),
    "shutil.copyfile": (1,),
    "shutil.rmtree": (0,),
}


def _key(path: str | bytes | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.fsdecode(path)))


def _is_inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + os.sep)


class Guard:
    """Reúne as escritas feitas fora da pasta temporária de dados e diz de qual teste vieram."""

    def __init__(self, root: Path, models_are_real: bool) -> None:
        self.protected_dirs = [
            _key(root / "cache"),
            _key(root / "output"),
            _key(root / "projects"),
            _key(root / "conversations"),
            _key(root / "assets" / "voices"),
        ]
        self.protected_files = [_key(root / "assets" / LEXICON_NAME), _key(root / "layouts.json")]
        self.brands_dir = _key(root / "assets" / "brands")
        # com DMAKER_VOICE_SMOKE=1 os modelos de verdade baixam para cá, e isso é esperado
        self.allowed_dirs = [_key(root / "cache" / "models")] if models_are_real else []
        self.current_test = "<fora de um teste>"
        self._violations: list[str] = []
        self._lock = threading.Lock()

    def is_protected(self, path: str) -> bool:
        if any(_is_inside(path, folder) for folder in self.allowed_dirs):
            return False
        if path in self.protected_files or any(_is_inside(path, d) for d in self.protected_dirs):
            return True
        return _is_inside(path, self.brands_dir) and os.path.basename(path) == LEXICON_NAME

    def audit(self, event: str, args: tuple) -> None:
        paths: list[str | bytes | os.PathLike] = []
        if event == "open":
            target, mode, flags = args
            if isinstance(target, int):
                return
            if (isinstance(mode, str) and _WRITE_MODE_CHARS & set(mode)) or (flags or 0) & _WRITE_FLAGS:
                paths = [target]
        elif event in _PATH_EVENTS:
            paths = [args[i] for i in _PATH_EVENTS[event] if i < len(args) and not isinstance(args[i], int)]
        for target in paths:
            path = _key(target)
            if self.is_protected(path):
                with self._lock:
                    self._violations.append(f"{event}: {path} (teste: {self.current_test})")

    def take_violations(self) -> list[str]:
        with self._lock:
            found, self._violations = self._violations, []
        return found


def install(guard: Guard) -> None:
    """O gancho de auditoria não pode ser removido depois de instalado; vale pelo resto do processo."""
    sys.addaudithook(guard.audit)


def make_guard() -> Guard:
    return Guard(config.ROOT, models_are_real=os.environ.get("DMAKER_VOICE_SMOKE") == "1")
