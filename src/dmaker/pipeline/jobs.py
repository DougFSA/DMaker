"""Execução de renders em segundo plano com acompanhamento em tempo real (MCP e interface).

Cada job guarda os eventos (mensagens de etapa, progresso de cada comando ffmpeg, fim) e
alimenta filas de quem estiver assistindo, o que permite streaming por SSE.
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


@dataclass
class Job:
    id: str
    description: str
    status: str = "running"  # running | done | error
    result: Any = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    events: list[dict] = field(default_factory=list)
    progress: dict = field(default_factory=dict)  # {"label", "done", "total", "percent"}
    _listeners: list[queue.Queue] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        return {
            "job_id": self.id,
            "description": self.description,
            "status": self.status,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "progress": self.progress,
            "error": self.error,
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


class JobManager:
    def __init__(self, keep: int = 50) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.keep = keep

    def start(self, description: str, work: Callable[[Job], Any]) -> Job:
        """`work` recebe o job para emitir eventos (job.log, job.sink()) e devolve o resultado."""
        job = Job(id=uuid.uuid4().hex[:10], description=description)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()

        def runner() -> None:
            job.emit("start", description=description)
            try:
                job.result = work(job)
                job.status = "done"
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

    def wait(self, job: Job, timeout: float) -> Job:
        deadline = time.time() + timeout
        while job.status == "running" and time.time() < deadline:
            time.sleep(0.25)
        return job

    def list(self) -> list[dict]:
        with self._lock:
            return [j.snapshot() for j in self._jobs.values()]
