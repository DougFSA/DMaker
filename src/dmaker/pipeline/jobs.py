"""Execução de renders em segundo plano com acompanhamento em tempo real (MCP e interface).

Cada job guarda os eventos (mensagens de etapa, progresso de cada comando ffmpeg, fim) e
alimenta filas de quem estiver assistindo, o que permite streaming por SSE.

O cancelamento é cooperativo: `Job.cancel()` só levanta uma bandeira, e quem executa o trabalho a consulta
nos pontos seguros (entre falas, por exemplo) e encerra com `JobCancelled`. Nada é morto à força.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class JobCancelled(Exception):
    """O trabalho parou a pedido de quem o disparou; `result` guarda o que já ficou pronto."""

    def __init__(self, message: str = "Cancelado.", result: Any = None) -> None:
        super().__init__(message)
        self.result = result


@dataclass
class Job:
    id: str
    description: str
    status: str = "running"  # running | done | error | cancelled
    result: Any = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    events: list[dict] = field(default_factory=list)
    progress: dict = field(default_factory=dict)  # {"label", "done", "total", "percent"}
    meta: dict = field(default_factory=dict)  # dados de quem criou o job (ex.: focus, project)
    _listeners: list[queue.Queue] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancel_requested: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancellable(self) -> bool:
        """O trabalho consulta `cancel_requested`; só esses aceitam o pedido (renders, por ora, não)."""
        return bool(self.meta.get("cancellable", False))

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    def cancel(self) -> None:
        self._cancel_requested.set()
        self.log("Cancelamento pedido")

    def snapshot(self) -> dict:
        return {
            "job_id": self.id,
            "description": self.description,
            "status": self.status,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "progress": self.progress,
            "error": self.error,
            "cancellable": self.cancellable,
            "focus": bool(self.meta.get("focus", False)),
            "project": self.meta.get("project"),
        }

    def emit(self, kind: str, **data: Any) -> None:
        event = {"kind": kind, "t": round(time.time() - self.started_at, 2), **data}
        with self._lock:
            self.events.append(event)
            listeners = list(self._listeners)
        for q in listeners:
            q.put(event)

    def log(self, message: str) -> None:
        self.emit("log", message=message)

    def sink(self) -> JobSink:
        return JobSink(self)

    def subscribe(self) -> queue.Queue:
        """Fila com os eventos passados e os futuros (para SSE)."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            for event in self.events:
                q.put(event)
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)


class JobSink:
    """ProgressSink que transforma o andamento de cada comando ffmpeg em eventos do job."""

    def __init__(self, job: Job):
        self.job = job
        self.label = ""
        self.total: float | None = None
        self._last_percent = -1

    def start(self, label: str, total: float | None) -> None:
        self.label, self.total, self._last_percent = label, total, -1
        if not total:  # comandos curtos sem duração conhecida (thumbnail) não viram barra
            return
        self.job.progress = {"label": label, "done": 0.0, "total": total, "percent": 0}
        self.job.emit("progress", **self.job.progress)

    def update(self, done: float) -> None:
        if not self.total:
            return
        percent = int(min(done / self.total, 1.0) * 100)
        if percent == self._last_percent:
            return  # evita inundar a fila com o mesmo valor
        self._last_percent = percent
        self.job.progress = {
            "label": self.label,
            "done": round(done, 2),
            "total": self.total,
            "percent": percent,
        }
        self.job.emit("progress", **self.job.progress)

    def finish(self) -> None:
        if self.total:
            self.job.progress = {"label": self.label, "done": self.total, "total": self.total, "percent": 100}
            self.job.emit("progress", **self.job.progress)


def stage_progress(job: Job) -> Callable[[str, float], None]:
    """Etapa e fração (0 a 1) de um serviço sem ffmpeg para acompanhar (ex.: transcrição) viram progresso do job."""

    def report(label: str, fraction: float) -> None:
        percent = round(fraction * 100)
        job.progress = {"label": label, "done": percent, "total": 100, "percent": percent}
        job.emit("progress", **job.progress)

    return report


class JobManager:
    def __init__(self, keep: int = 50) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.keep = keep

    def start(self, description: str, work: Callable[[Job], Any], meta: dict | None = None) -> Job:
        """`work` recebe o job para emitir eventos (job.log, job.sink()) e devolve o resultado."""
        job = Job(id=uuid.uuid4().hex[:10], description=description, meta=meta or {})
        with self._lock:
            self._jobs[job.id] = job
            self._trim()

        def runner() -> None:
            job.emit("start", description=description)
            try:
                job.result = work(job)
                job.status = "done"
            except JobCancelled as exc:
                job.result = exc.result
                job.status = "cancelled"
            except Exception as exc:  # noqa: BLE001 - o erro é reportado ao cliente
                job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
                job.status = "error"
            finally:
                job.finished_at = time.time()
                job.emit("end", status=job.status, error=job.error, result=job.result)

        threading.Thread(target=runner, daemon=True, name=f"dmaker-job-{job.id}").start()
        return job

    def _trim(self) -> None:
        finished = [j for j in self._jobs.values() if j.status != "running"]
        for old in finished[: max(0, len(self._jobs) - self.keep)]:
            self._jobs.pop(old.id, None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        """Pede o cancelamento do job (None se não existe); quem decide o momento de parar é o trabalho."""
        job = self.get(job_id)
        if job is not None and job.status == "running" and job.cancellable:
            job.cancel()
        return job

    def wait(self, job: Job, timeout: float) -> Job:
        deadline = time.time() + timeout
        while job.status == "running" and time.time() < deadline:
            time.sleep(0.25)
        return job

    def list(self) -> list[dict]:
        with self._lock:
            return [j.snapshot() for j in self._jobs.values()]

    def running(self) -> list[Job]:
        """Jobs ainda em andamento, para decidir se é seguro encerrar o processo ou trocar de versão."""
        with self._lock:
            return [j for j in self._jobs.values() if j.status == "running"]

    def find_running(self, predicate: Callable[[Job], bool]) -> Job | None:
        """Primeiro job rodando que satisfaz `predicate` (ex.: mesmo projeto e tipo), para reaproveitar
        em vez de disparar um duplicado (dois pedidos de proxies para a mesma fonte, por exemplo)."""
        for job in self.running():
            if predicate(job):
                return job
        return None

    def clear_finished(self) -> int:
        """Remove da lista os jobs que não estão mais rodando (concluídos ou com erro); devolve quantos."""
        with self._lock:
            finished_ids = [job_id for job_id, job in self._jobs.items() if job.status != "running"]
            for job_id in finished_ids:
                del self._jobs[job_id]
            return len(finished_ids)
