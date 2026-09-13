"""Execução de renders em segundo plano com acompanhamento (usado pelo servidor MCP)."""

from __future__ import annotations

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

    def snapshot(self) -> dict:
        return {
            "job_id": self.id,
            "description": self.description,
            "status": self.status,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "error": self.error,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, description: str, work: Callable[[], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], description=description)
        with self._lock:
            self._jobs[job.id] = job

        def runner() -> None:
            try:
                job.result = work()
                job.status = "done"
            except Exception as exc:  # noqa: BLE001 - o erro é reportado ao cliente
                job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
                job.status = "error"
            finally:
                job.finished_at = time.time()

        threading.Thread(target=runner, daemon=True, name=f"dmaker-job-{job.id}").start()
        return job

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
