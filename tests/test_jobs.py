"""Jobs em segundo plano: eventos, progresso e assinantes (o que a interface e o MCP consomem)."""

import threading
import time

from dmaker.media.ffmpeg import NullSink, RichSink
from dmaker.pipeline.jobs import JobCancelled, JobManager


def test_job_runs_work_and_emits_lifecycle_events():
    manager = JobManager()

    def work(job):
        job.log("preparando")
        return 42

    job = manager.wait(manager.start("teste", work), timeout=5)
    kinds = [e["kind"] for e in job.events]
    assert job.status == "done" and job.result == 42
    assert kinds == ["start", "log", "end"]
    assert job.snapshot()["elapsed_s"] >= 0


def test_job_error_is_captured():
    manager = JobManager()

    def boom(job):
        raise ValueError("deu ruim")

    job = manager.wait(manager.start("erro", boom), timeout=5)
    assert job.status == "error" and "deu ruim" in job.error
    assert job.events[-1]["kind"] == "end" and job.events[-1]["status"] == "error"


def test_sink_emits_progress_without_flooding():
    manager = JobManager()

    def work(job):
        sink = job.sink()
        sink.start("montagem", 10.0)
        for done in (0.4, 0.45, 0.49, 5.0, 10.0):  # 4% três vezes, depois 50%, 100%
            sink.update(done)
        sink.finish()
        return None

    job = manager.wait(manager.start("progresso", work), timeout=5)
    percents = [e["percent"] for e in job.events if e["kind"] == "progress"]
    assert percents == [0, 4, 50, 100, 100]
    assert job.progress["percent"] == 100 and job.progress["label"] == "montagem"


def test_subscribe_replays_past_events_then_streams():
    manager = JobManager()

    def work(job):
        job.log("um")
        return None

    job = manager.wait(manager.start("assinatura", work), timeout=5)
    q = job.subscribe()
    kinds = []
    while not q.empty():
        kinds.append(q.get()["kind"])
    assert kinds == ["start", "log", "end"]
    job.unsubscribe(q)
    job.emit("log", message="depois")
    assert q.empty()


def test_manager_trims_finished_jobs():
    manager = JobManager(keep=2)
    for i in range(4):
        manager.wait(manager.start(f"j{i}", lambda job: None), timeout=5)
    assert len(manager.list()) <= 3


def test_terminal_sinks_are_safe_without_total():
    for sink in (NullSink(), RichSink()):
        sink.start("x", None)
        sink.update(1.0)
        sink.finish()


def test_running_lists_only_jobs_in_progress():
    manager = JobManager()
    gate = threading.Event()
    running_job = manager.start("lento", lambda job: gate.wait(5))
    finished_job = manager.wait(manager.start("rapido", lambda job: None), timeout=5)
    try:
        running_ids = {j.id for j in manager.running()}
        assert running_ids == {running_job.id}
        assert finished_job.id not in running_ids
    finally:
        gate.set()
        manager.wait(running_job, timeout=5)


def test_find_running_matches_by_predicate():
    manager = JobManager()
    gate = threading.Event()
    job = manager.start("proxies", lambda job: gate.wait(5), meta={"project": "p1", "kind": "proxies"})
    try:
        found = manager.find_running(
            lambda j: j.meta.get("project") == "p1" and j.meta.get("kind") == "proxies"
        )
        assert found is not None and found.id == job.id
        assert manager.find_running(lambda j: j.meta.get("project") == "outro") is None
    finally:
        gate.set()
        manager.wait(job, timeout=5)


def test_clear_finished_removes_only_jobs_not_running():
    manager = JobManager()
    gate = threading.Event()
    running_job = manager.start("lento", lambda job: gate.wait(5))
    manager.wait(manager.start("rapido1", lambda job: None), timeout=5)
    manager.wait(manager.start("rapido2", lambda job: None), timeout=5)
    try:
        removed = manager.clear_finished()
        assert removed == 2
        assert {j["job_id"] for j in manager.list()} == {running_job.id}
        assert manager.clear_finished() == 0  # nada mais para limpar
    finally:
        gate.set()
        manager.wait(running_job, timeout=5)


def test_cancel_is_cooperative_and_ends_the_job_as_cancelled_with_the_partial_result():
    manager = JobManager()
    started = threading.Event()

    def work(job):
        started.set()
        while not job.cancel_requested:
            time.sleep(0.01)
        raise JobCancelled("parado", result={"ready": 2})

    job = manager.start("longo", work, meta={"cancellable": True})
    assert started.wait(5) and job.snapshot()["cancellable"] is True
    assert manager.cancel(job.id) is job
    manager.wait(job, timeout=5)

    assert job.status == "cancelled" and job.error is None and job.result == {"ready": 2}
    end = job.events[-1]
    assert end["kind"] == "end" and end["status"] == "cancelled" and end["result"] == {"ready": 2}


def test_cancel_ignores_jobs_that_did_not_declare_themselves_cancellable_and_finished_ones():
    manager = JobManager()
    release = threading.Event()
    rigid = manager.start("render", lambda job: release.wait(5))
    assert manager.cancel(rigid.id) is rigid and not rigid.cancel_requested
    release.set()
    manager.wait(rigid, timeout=5)

    done = manager.start("curto", lambda job: 1, meta={"cancellable": True})
    manager.wait(done, timeout=5)
    manager.cancel(done.id)
    assert not done.cancel_requested and done.status == "done"
    assert manager.cancel("inexistente") is None
