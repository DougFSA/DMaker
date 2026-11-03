"""Trava exclusiva de arquivo entre processos: quem a segura é o único a executar aquele trabalho.

O sistema operacional solta a trava quando o processo cai, então não sobra trava velha para limpar, e
conseguir pegá-la prova que ninguém mais está rodando (o que sobrou "rodando" no disco é resto de uma queda).
"""

from __future__ import annotations

import os
from pathlib import Path

if os.name == "nt":
    import msvcrt

    def _lock_file(descriptor: int) -> bool:
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock_file(descriptor: int) -> None:
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_file(descriptor: int) -> bool:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock_file(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


class FileLock:
    """Trava não bloqueante sobre um arquivo; `try_acquire` diz na hora se outro processo já a segura."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._descriptor: int | None = None

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def try_acquire(self) -> bool:
        if self._descriptor is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT)
        if not _lock_file(descriptor):
            os.close(descriptor)
            return False
        self._descriptor = descriptor
        return True

    def release(self) -> None:
        if self._descriptor is None:
            return
        _unlock_file(self._descriptor)
        os.close(self._descriptor)
        self._descriptor = None
