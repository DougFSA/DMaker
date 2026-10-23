"""Worker da fila: um item por vez e em série, retomada ao subir, falha isolada e trava entre processos."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from dmaker import config
from dmaker.pipeline.voice_batch import ItemOutput
from dmaker.pipeline.voice_queue import (
    DONE,
    FAILED,
    PAUSED,
    PENDING,
    RUNNING,
    ItemInterrupted,
    QueueOptions,
    VoiceQueue,
)
from dmaker.pipeline.voice_worker import QueueWorker, WorkerBusyError, WorkerLock
from dmaker.voice.manuscript import Chapter


@pytest.fixture
def queue(tmp_path, monkeypatch) -> VoiceQueue:
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    return VoiceQueue(tmp_path / "cache" / "voice_queue.json")


def add(queue: VoiceQueue, title: str):
    return queue.add(title, [Chapter("Único", "Um texto qualquer para narrar.")], QueueOptions(), "text")


class FakeProcessor:
    def __init__(self, queue: VoiceQueue, behaviour=None) -> None:
        self.queue, self.behaviour = queue, behaviour or {}
        self.order: list[str] = []
        self.active = 0
        self.max_active = 0
        self.created = 0

    def process(self, item) -> ItemOutput:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            self.order.append(item.title)
            action = self.behaviour.get(item.title)
            if isinstance(action, Exception):
                raise action
            if callable(action):
                action(item)
            return ItemOutput([f"{item.title}.wav"], 3.0)
        finally:
            self.active -= 1


def worker_for(queue: VoiceQueue, processor: FakeProcessor, **kwargs) -> QueueWorker:
    def factory():
        processor.created += 1
        return processor

    return QueueWorker(queue, factory, idle_seconds=0.02, **kwargs)


# ---------- série ----------


def test_two_queued_items_run_one_after_the_other_without_intervention(queue):
    add(queue, "primeiro"), add(queue, "segundo")
    processor = FakeProcessor(queue)

    processed = worker_for(queue, processor).run_pending()

    assert processed == 2
    assert processor.order == ["primeiro", "segundo"]
    assert processor.max_active == 1  # nunca dois ao mesmo tempo
    assert [(i.state, i.outputs, i.duration_s) for i in queue.list()] == [
        (DONE, ["primeiro.wav"], 3.0),
        (DONE, ["segundo.wav"], 3.0),
    ]


def test_the_processor_is_only_built_when_there_is_something_to_do(queue):
    processor = FakeProcessor(queue)
    assert worker_for(queue, processor).run_pending() == 0
    assert processor.created == 0


def test_reordering_changes_who_runs_first(queue):
    add(queue, "A")
    second = add(queue, "B")
    queue.move(second.id, -1)
    processor = FakeProcessor(queue)
    worker_for(queue, processor).run_pending()
    assert processor.order == ["B", "A"]


# ---------- falha e interrupção ----------


def test_a_failing_item_is_marked_failed_with_the_error_and_the_next_one_still_runs(queue):
    add(queue, "quebra"), add(queue, "segue")
    processor = FakeProcessor(queue, {"quebra": ValueError("voz inexistente")})
    logs: list[str] = []

    worker_for(queue, processor, log=logs.append).run_pending()

    broken, fine = queue.list()
    assert broken.state == FAILED and broken.error == "ValueError: voz inexistente"
    assert fine.state == DONE
    assert any("Falhou" in line for line in logs)


def test_an_interrupted_item_keeps_the_state_the_user_gave_it(queue):
    item = add(queue, "pausado no meio")
    processor = FakeProcessor(
        queue, {"pausado no meio": lambda _item: (queue.pause(item.id), _raise_interrupted())}
    )

    worker_for(queue, processor).run_pending()

    assert queue.get(item.id).state == PAUSED and queue.get(item.id).outputs == []


def _raise_interrupted():
    raise ItemInterrupted("x")


def test_an_item_cancelled_while_running_is_not_overwritten_by_the_result(queue):
    item = add(queue, "cancelado no fim")
    processor = FakeProcessor(queue, {"cancelado no fim": lambda _item: queue.cancel(item.id)})

    worker_for(queue, processor).run_pending()

    assert queue.get(item.id).state == "cancelled" and queue.get(item.id).outputs == []


# ---------- retomada ----------


def test_starting_a_worker_puts_back_the_item_a_dead_process_left_running(queue):
    stuck = add(queue, "ficou rodando")
    queue.claim_next()
    assert queue.get(stuck.id).state == RUNNING  # o processo anterior caiu aqui
    processor = FakeProcessor(queue)
    logs: list[str] = []

    worker_for(queue, processor, log=logs.append).run_pending()

    assert processor.order == ["ficou rodando"]
    assert queue.get(stuck.id).state == DONE
    assert any("voltam para a fila" in line for line in logs)


def test_paused_items_are_left_alone_by_the_worker(queue):
    paused = add(queue, "pausado")
    add(queue, "normal")
    queue.pause(paused.id)
    processor = FakeProcessor(queue)

    worker_for(queue, processor).run_pending()

    assert processor.order == ["normal"] and queue.get(paused.id).state == PAUSED


# ---------- trava entre processos ----------


def test_only_one_lock_holder_at_a_time_and_release_frees_it(tmp_path):
    path = tmp_path / "cache" / "voice_queue.lock"
    first, second = WorkerLock(lambda: path), WorkerLock(lambda: path)

    assert first.try_acquire() is True and first.held
    assert second.try_acquire() is False and not second.held
    assert first.try_acquire() is True  # quem já tem a trava continua com ela
    first.release()
    assert second.try_acquire() is True
    second.release()


def test_a_second_runner_is_refused_while_another_one_holds_the_queue(queue):
    add(queue, "ocupado")
    other = WorkerLock(lambda: queue.index_path.with_name("voice_queue.lock"))
    assert other.try_acquire()
    processor = FakeProcessor(queue)

    with pytest.raises(WorkerBusyError, match="Outra fila"):
        worker_for(queue, processor).run_pending()

    assert queue.get(queue.list()[0].id).state == PENDING  # nada foi tocado
    other.release()
    worker_for(queue, processor).run_pending()
    assert processor.order == ["ocupado"]


def test_the_lock_path_follows_the_queue_folder_at_the_time_of_use(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "um")
    lazy = VoiceQueue()
    worker = QueueWorker(lazy, lambda: FakeProcessor(lazy))
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "dois")
    assert worker.run_pending() == 0
    assert (tmp_path / "dois" / "voice_queue.lock").exists()
    assert not (tmp_path / "um").exists()


# ---------- thread da interface ----------


def wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_the_background_thread_picks_up_items_added_while_it_is_idle_and_stops_cleanly(queue):
    processor = FakeProcessor(queue)
    worker = worker_for(queue, processor)
    worker.start()
    try:
        assert wait_for(lambda: worker.running)
        item = add(queue, "chegou depois")
        worker.wake()
        assert wait_for(lambda: queue.get(item.id).state == DONE)
        second = add(queue, "outro")  # sem wake: o ciclo de espera curto também pega
        assert wait_for(lambda: queue.get(second.id).state == DONE)
    finally:
        worker.stop()
    assert not worker.running
    assert processor.order == ["chegou depois", "outro"]
    assert WorkerLock(
        lambda: queue.index_path.with_name("voice_queue.lock")
    ).try_acquire()  # a trava foi solta


def test_the_thread_waits_for_the_lock_while_another_process_runs_the_queue(queue):
    other = WorkerLock(lambda: queue.index_path.with_name("voice_queue.lock"))
    assert other.try_acquire()
    item = add(queue, "espera")
    processor = FakeProcessor(queue)
    worker = worker_for(queue, processor)
    worker.start()
    try:
        time.sleep(0.15)
        assert queue.get(item.id).state == PENDING and processor.order == []
        other.release()
        assert wait_for(lambda: queue.get(item.id).state == DONE)
    finally:
        worker.stop()


def test_worker_threads_are_daemons_so_closing_the_ui_never_hangs(queue):
    worker = worker_for(queue, FakeProcessor(queue))
    worker.start()
    try:
        assert wait_for(lambda: worker.running)
        names = {t.name for t in threading.enumerate() if t.name == "dmaker-voice-queue"}
        assert names == {"dmaker-voice-queue"}
        assert all(t.daemon for t in threading.enumerate() if t.name == "dmaker-voice-queue")
    finally:
        worker.stop()


def test_logs_name_the_item_being_narrated(queue):
    add(queue, "Meu livro")
    logs: list[str] = []
    worker_for(queue, FakeProcessor(queue), log=logs.append).run_pending()
    assert logs == ["Narrando 'Meu livro'", "Pronto 'Meu livro'"]
    assert isinstance(Path(queue.list()[0].output_dir), Path)
