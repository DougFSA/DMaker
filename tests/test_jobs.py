"""Jobs em segundo plano: eventos, progresso e assinantes (o que a interface e o MCP consomem)."""

from dmaker.media.ffmpeg import NullSink, RichSink
from dmaker.pipeline.jobs import JobManager


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
