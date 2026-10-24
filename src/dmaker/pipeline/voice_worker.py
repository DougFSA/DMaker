"""Quem executa a fila de narrações: um só worker por máquina, um item por vez, retomando de onde parou.

O worker roda numa thread do `dmaker ui` ou em primeiro plano (`dmaker voice queue run`). Uma trava de arquivo
garante que só um processo execute a fila, porque a CPU não aguenta duas sínteses ao mesmo tempo e dois
workers pegariam o mesmo item. O sistema operacional solta a trava quando o processo cai, então não sobra
trava velha para limpar.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .voice_batch import ItemOutput
from .voice_queue import ItemInterrupted, QueueItem, VoiceQueue

LOCK_FILE = "voice_queue.lock"
IDLE_POLL_SECONDS = (
    2.0  # de quanto em quanto o worker olha a fila vazia (pega o que o CLI ou o MCP acrescentou)
)

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


class WorkerBusyError(RuntimeError):
    """Outro processo já está executando a fila."""


class WorkerLock:
    """Trava exclusiva de arquivo; `path` é uma função porque a pasta de cache vem do config na hora do uso."""

    def __init__(self, path: Callable[[], Path]) -> None:
        self._path = path
        self._descriptor: int | None = None

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def try_acquire(self) -> bool:
        if self._descriptor is not None:
            return True
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT)
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


class Processor(Protocol):
    def process(self, item: QueueItem) -> ItemOutput: ...


class QueueWorker:
    """Pega o primeiro item pendente, entrega ao `processor` e grava o desfecho; repete até a fila esvaziar."""

    def __init__(
        self,
        queue: VoiceQueue,
        processor_factory: Callable[[], Processor],
        lock: WorkerLock | None = None,
        idle_seconds: float = IDLE_POLL_SECONDS,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.queue = queue
        self._processor_factory = processor_factory
        self._processor: Processor | None = None
        self.lock = lock or WorkerLock(lambda: queue.index_path.with_name(LOCK_FILE))
        self.idle_seconds = idle_seconds
        self.log = log or (lambda _message: None)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------- execução ----------

    def _acquire(self) -> bool:
        """Pega a trava e, na primeira vez, devolve à fila o item que o processo anterior deixou `rodando`."""
        if self.lock.held:
            return True
        if not self.lock.try_acquire():
            return False
        requeued = self.queue.requeue_interrupted()
        if requeued:
            self.log(f"{requeued} item(ns) que estavam rodando voltam para a fila")
        return True

    def _process(self, item: QueueItem) -> None:
        if self._processor is None:
            self._processor = self._processor_factory()
        self.log(f"Narrando {item.title!r}")
        try:
            output = self._processor.process(item)
        except ItemInterrupted:
            return  # quem pausou ou cancelou já deixou o estado certo
        except Exception as exc:  # noqa: BLE001 - o erro vai para o item, para o Douglas ler na fila
            self.queue.fail(item.id, f"{type(exc).__name__}: {exc}")
            self.log(f"Falhou {item.title!r}: {exc}")
            return
        self.queue.finish(item.id, output.files, output.duration)
        self.log(f"Pronto {item.title!r}")

    def run_pending(self) -> int:
        """Executa os itens pendentes em primeiro plano e volta quando a fila esvazia; devolve quantos rodou."""
        if not self._acquire():
            raise WorkerBusyError("Outra fila de narrações já está rodando (o dmaker ui, talvez).")
        processed = 0
        try:
            while not self._stop.is_set() and (item := self.queue.claim_next()) is not None:
                self._process(item)
                processed += 1
        finally:
            self.lock.release()
        return processed

    # ---------- thread da interface ----------

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                if not self._acquire():
                    self._stop.wait(self.idle_seconds)
                    continue
                item = self.queue.claim_next()
                if item is None:
                    self._wake.wait(self.idle_seconds)
                    self._wake.clear()
                    continue
                self._process(item)
        finally:
            self.lock.release()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="dmaker-voice-queue")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def wake(self) -> None:
        """Avisa que entrou item novo, para não esperar o próximo ciclo de espera."""
        self._wake.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
