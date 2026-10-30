"""O relé do turno: a confirmação por botão e o que o Parar faz com ela."""

from __future__ import annotations

import threading
import time

from dmaker.agent import ConfirmationRequest
from dmaker.pipeline.jobs import JobManager
from dmaker.ui.agent_turns import TurnRelay

REQUEST = ConfirmationRequest("render_project", {}, "Posso gerar o vídeo final?")


def started_job(manager: JobManager, relay: TurnRelay, outcome: list):
    return manager.start("t", lambda job: relay.attach(job) or outcome.append(relay.confirm(REQUEST)))


def wait_waiting(relay: TurnRelay, count: int = 1) -> None:
    deadline = time.time() + 5
    while relay.waiting < count and time.time() < deadline:
        time.sleep(0.01)
    assert relay.waiting == count


def test_cancelling_releases_a_pending_confirmation_as_a_no():
    relay, outcome = TurnRelay(confirmation_timeout=30), []
    manager = JobManager()
    job = started_job(manager, relay, outcome)
    wait_waiting(relay)
    began = time.monotonic()

    relay.cancel()
    manager.wait(job, timeout=5)

    assert outcome == [False] and time.monotonic() - began < 2  # não esperou os 30 s do prazo
    assert [e["approved"] for e in job.events if e["kind"] == "confirmation_answered"] == [False]
    assert relay.waiting == 0


def test_a_confirmation_asked_after_the_stop_is_refused_without_ever_being_shown():
    relay, outcome = TurnRelay(confirmation_timeout=30), []
    manager = JobManager()
    relay.attach(manager.start("t", lambda job: None))
    relay.cancel()

    outcome.append(relay.confirm(REQUEST))

    assert outcome == [False] and relay.waiting == 0
    assert not [e for e in relay.job.events if e["kind"] == "confirmation_request"]


def test_the_next_turn_starts_clean_after_a_stop():
    relay = TurnRelay(confirmation_timeout=5)
    manager = JobManager()
    relay.attach(manager.start("um", lambda job: None))
    relay.cancel()
    outcome: list[bool] = []

    job = started_job(manager, relay, outcome)  # attach de um turno novo: o Parar do anterior não vale
    wait_waiting(relay)
    confirmation_id = next(iter(relay._pending))
    assert relay.resolve(confirmation_id, True) is True
    manager.wait(job, timeout=5)

    assert outcome == [True]


def test_cancel_with_nothing_pending_is_harmless():
    relay = TurnRelay()

    relay.cancel()
    relay.cancel()

    assert relay.waiting == 0


def test_a_confirmation_the_person_already_approved_is_not_overturned_by_a_stop_that_comes_later():
    relay, outcome = TurnRelay(confirmation_timeout=30), []
    manager = JobManager()
    job = started_job(manager, relay, outcome)
    wait_waiting(relay)
    confirmation_id = next(iter(relay._pending))

    relay.resolve(confirmation_id, True)
    manager.wait(job, timeout=5)
    relay.cancel()  # tarde demais: nada mais está pendente

    assert outcome == [True]


def test_the_tap_sees_every_event_before_the_job_does_and_a_failing_tap_never_breaks_the_turn():
    manager = JobManager()
    relay = TurnRelay()
    order: list[str] = []
    seen_by_job = threading.Event()

    def tap(kind, data):
        order.append(f"tap:{kind}")
        if kind == "boom":
            raise RuntimeError("a transcrição falhou")

    relay.tap = tap

    def work(job):
        relay.attach(job)
        relay.emit("boom", {"x": 1})
        relay.emit("answer", {"text": "ok"})
        order.append("job:" + ",".join(e["kind"] for e in job.events))
        seen_by_job.set()

    job = manager.start("t", work)
    manager.wait(job, timeout=5)

    assert order == ["tap:boom", "tap:answer", "job:start,boom,answer"]
    assert job.status == "done"
