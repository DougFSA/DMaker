"""O gancho de cancelamento do job: quem espera numa chamada que bloqueia é acordado na hora, com a bandeira já levantada."""

from __future__ import annotations

import threading

from dmaker.pipeline.jobs import Job, JobManager


def make_job() -> Job:
    return Job(id="j", description="teste", meta={"cancellable": True})


def test_the_flag_is_up_before_the_hooks_run():
    job = make_job()
    seen = []
    job.on_cancel(lambda: seen.append(job.cancel_requested))

    job.cancel()

    assert seen == [True]


def test_a_hook_registered_after_the_cancel_runs_at_once():
    job = make_job()
    job.cancel()
    seen = []

    job.on_cancel(lambda: seen.append("tarde"))

    assert seen == ["tarde"]


def test_a_failing_hook_does_not_stop_the_others_or_the_cancel():
    job = make_job()
    seen = []

    def broken():
        raise RuntimeError("falhou")

    job.on_cancel(broken)
    job.on_cancel(lambda: seen.append("segundo"))

    job.cancel()

    assert job.cancel_requested and seen == ["segundo"]


def test_a_job_that_waits_on_a_blocking_call_is_woken_by_the_cancel():
    manager = JobManager()
    release = threading.Event()

    def work(job: Job) -> str:
        job.on_cancel(release.set)
        release.wait(timeout=10)  # como a espera pela resposta do modelo
        return "acordou" if job.cancel_requested else "esgotou"

    job = manager.start("espera", work, meta={"cancellable": True})
    manager.cancel(job.id)
    manager.wait(job, timeout=5)

    assert job.status == "done" and job.result == "acordou"


def test_a_job_that_is_not_cancellable_never_runs_the_hooks():
    manager = JobManager()
    gate = threading.Event()
    seen = []

    def work(job: Job) -> None:
        job.on_cancel(lambda: seen.append("não devia"))
        gate.wait(timeout=5)

    job = manager.start("longo", work)
    manager.cancel(job.id)
    gate.set()
    manager.wait(job, timeout=5)

    assert seen == []
