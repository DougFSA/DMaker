"""Fila de narrações: persistência atômica, transições de estado, retomada, reordenação e pastas de saída."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker import config
from dmaker.pipeline.voice_queue import (
    CANCELLED,
    DONE,
    FAILED,
    PAUSED,
    PENDING,
    RUNNING,
    ItemNotFoundError,
    QueueFileError,
    QueueItem,
    QueueOptions,
    VoiceQueue,
)
from dmaker.voice.manuscript import Chapter


@pytest.fixture
def output_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    return tmp_path / "output"


@pytest.fixture
def queue(tmp_path, output_dir) -> VoiceQueue:
    return VoiceQueue(tmp_path / "cache" / "voice_queue.json")


def add(queue: VoiceQueue, title: str = "Livro", chapters: int = 2, **options) -> QueueItem:
    pieces = [Chapter(f"Capítulo {n}", f"Texto do capítulo {n}.") for n in range(1, chapters + 1)]
    return queue.add(title, pieces, QueueOptions(**options), "text")


def states(queue: VoiceQueue) -> list[str]:
    return [item.state for item in queue.list()]


# ---------- persistência ----------


def test_added_item_survives_a_new_queue_object_reading_the_same_file(queue):
    item = add(queue, "Meu audiobook", voice="dora", draft=True, audio_format="mp3", speed=1.1)

    reloaded = VoiceQueue(queue.index_path).get(item.id)

    assert reloaded.title == "Meu audiobook" and reloaded.state == PENDING
    assert reloaded.options == QueueOptions(voice="dora", speed=1.1, draft=True, audio_format="mp3")
    assert reloaded.chapters_total == 2
    assert VoiceQueue(queue.index_path).load_chapters(item.id) == [
        Chapter("Capítulo 1", "Texto do capítulo 1."),
        Chapter("Capítulo 2", "Texto do capítulo 2."),
    ]


def test_index_holds_metadata_only_and_the_text_goes_to_its_own_file(queue):
    item = add(queue)
    index = json.loads(queue.index_path.read_text(encoding="utf-8"))
    assert "Texto do capítulo" not in json.dumps(index)
    assert queue.chapters_path(item.id).exists()
    assert queue.chapters_path(item.id).parent == queue.index_path.parent / "voice_queue"


def test_writes_go_through_a_temporary_file_and_leave_none_behind(queue, monkeypatch):
    replaced: list[tuple[str, str]] = []
    original = __import__("os").replace

    def spy(source, destination):
        replaced.append((Path(source).name, Path(destination).name))
        assert Path(source).read_text(encoding="utf-8")  # o temporário já está completo quando é renomeado
        original(source, destination)

    monkeypatch.setattr("dmaker.pipeline.voice_queue.os.replace", spy)
    add(queue)

    assert any(dest == "voice_queue.json" and src.endswith(".tmp") for src, dest in replaced)
    assert not list(queue.index_path.parent.glob("*.tmp"))
    assert not list((queue.index_path.parent / "voice_queue").glob("*.tmp"))


def test_a_failed_write_keeps_the_previous_index_intact(queue, monkeypatch):
    item = add(queue, "Primeiro")
    before = queue.index_path.read_text(encoding="utf-8")

    def broken(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr("dmaker.pipeline.voice_queue.os.replace", broken)
    with pytest.raises(OSError):
        queue.pause(item.id)

    assert queue.index_path.read_text(encoding="utf-8") == before
    assert queue.get(item.id).state == PENDING


def test_a_broken_index_is_reported_in_portuguese_not_swallowed(queue):
    queue.index_path.parent.mkdir(parents=True)
    queue.index_path.write_text("{ isto não é json", encoding="utf-8")
    with pytest.raises(QueueFileError, match="Não consegui ler a fila"):
        queue.list()


def test_directories_come_from_the_config_at_the_time_of_use(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "primeiro")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "saida-1")
    lazy = VoiceQueue()
    first = add(lazy)
    assert lazy.index_path == tmp_path / "primeiro" / "voice_queue.json"
    assert Path(first.output_dir).parent == tmp_path / "saida-1" / "narracoes"

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "segundo")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "saida-2")
    assert lazy.list() == []  # a mesma instância passou a olhar a outra pasta
    second = add(lazy)
    assert Path(second.output_dir).parent == tmp_path / "saida-2" / "narracoes"
    assert (tmp_path / "segundo" / "voice_queue.json").exists()


def test_unknown_fields_in_an_old_index_are_ignored(queue):
    item = add(queue)
    data = json.loads(queue.index_path.read_text(encoding="utf-8"))
    data["items"][0]["campo_futuro"] = 1
    data["items"][0]["options"]["outro"] = 2
    queue.index_path.write_text(json.dumps(data), encoding="utf-8")
    assert queue.get(item.id).title == item.title


# ---------- pasta de saída ----------


def test_output_folder_is_the_title_slug_and_repeated_titles_get_a_suffix(queue, output_dir):
    first = add(queue, "Meu Livro: Parte 1")
    second = add(queue, "Meu Livro: Parte 1")
    third = add(queue, "Meu Livro: Parte 1")
    assert Path(first.output_dir) == output_dir / "narracoes" / "meu-livro-parte-1"
    assert Path(second.output_dir).name == "meu-livro-parte-1-2"
    assert Path(third.output_dir).name == "meu-livro-parte-1-3"


def test_empty_title_falls_back_to_the_first_chapter(queue):
    item = queue.add("   ", [Chapter("Abertura", "Texto.")], QueueOptions(), "text")
    assert item.title == "Abertura"


def test_a_script_without_chapters_is_refused(queue):
    with pytest.raises(ValueError, match="não tem capítulos"):
        queue.add("Vazio", [], QueueOptions(), "text")


def test_invalid_audio_format_is_refused():
    with pytest.raises(ValueError, match="wav ou mp3"):
        QueueOptions(audio_format="ogg")


# ---------- transições ----------


def test_claim_takes_the_first_pending_item_in_order(queue):
    first, second = add(queue, "A"), add(queue, "B")
    claimed = queue.claim_next()
    assert claimed.id == first.id and claimed.state == RUNNING and claimed.started_at is not None
    assert queue.claim_next().id == second.id
    assert queue.claim_next() is None
    assert states(queue) == [RUNNING, RUNNING]


def test_paused_items_are_skipped_by_the_worker_until_resumed(queue):
    first, second = add(queue, "A"), add(queue, "B")
    queue.pause(first.id)
    assert queue.claim_next().id == second.id
    queue.resume(first.id)
    assert queue.get(first.id).state == PENDING
    assert queue.claim_next().id == first.id


def test_progress_updates_only_apply_while_the_item_is_running(queue):
    item = add(queue)
    assert queue.update_progress(item.id, utterance=1) is False  # ainda pendente
    queue.claim_next()
    assert queue.update_progress(item.id, utterance=3, utterances=9, chars_left=40) is True
    assert (queue.get(item.id).utterance, queue.get(item.id).chars_left) == (3, 40)

    queue.pause(item.id)  # o usuário pausa enquanto o worker trabalha
    assert queue.update_progress(item.id, utterance=4) is False  # o worker percebe e larga o item
    assert queue.get(item.id).state == PAUSED and queue.get(item.id).utterance == 3


def test_finish_and_fail_only_close_a_running_item(queue):
    done, failed, cancelled = add(queue, "A"), add(queue, "B"), add(queue, "C")
    queue.claim_next(), queue.claim_next(), queue.claim_next()

    assert queue.finish(done.id, ["a.wav", "a.srt"], 12.345) is True
    assert queue.fail(failed.id, "ValueError: quebrou") is True
    queue.cancel(cancelled.id)
    assert (
        queue.finish(cancelled.id, ["x.wav"], 1.0) is False
    )  # cancelado no último instante continua cancelado

    finished = queue.get(done.id)
    assert (finished.state, finished.outputs, finished.duration_s, finished.chars_left) == (
        DONE,
        ["a.wav", "a.srt"],
        12.35,
        0,
    )
    assert queue.get(failed.id).state == FAILED and "quebrou" in queue.get(failed.id).error
    assert queue.get(cancelled.id).state == CANCELLED


def test_cancel_is_allowed_from_any_unfinished_state_and_final_states_are_protected(queue):
    pending, running, paused = add(queue, "A"), add(queue, "B"), add(queue, "C")
    queue.claim_next()  # A passa a rodando
    queue.claim_next()  # B passa a rodando
    queue.pause(paused.id)
    queue.requeue_interrupted()
    for item in (pending, running, paused):
        assert queue.cancel(item.id).state == CANCELLED
    with pytest.raises(ValueError, match="cancelado não pode ir para cancelado"):
        queue.cancel(pending.id)
    with pytest.raises(ValueError, match="não pode ir para pausado"):
        queue.pause(pending.id)


def test_retry_brings_back_failed_and_cancelled_items_clean(queue):
    item = add(queue)
    queue.claim_next()
    queue.fail(item.id, "ValueError: x")
    retried = queue.retry(item.id)
    assert retried.state == PENDING and retried.error is None and retried.finished_at is None
    queue.cancel(item.id)
    assert queue.retry(item.id).state == PENDING
    with pytest.raises(ValueError):
        queue.retry(item.id)  # pendente não precisa tentar de novo


def test_unknown_item_raises_a_clear_error(queue):
    with pytest.raises(ItemNotFoundError, match="abc"):
        queue.get("abc")
    with pytest.raises(ItemNotFoundError):
        queue.cancel("abc")


# ---------- retomada ----------


def test_items_left_running_by_a_dead_process_go_back_to_pending(queue):
    interrupted, paused, finished = add(queue, "A"), add(queue, "B"), add(queue, "C")
    queue.pause(paused.id)
    queue.claim_next()  # A rodando
    queue.claim_next()  # C rodando
    queue.finish(finished.id, ["c.wav"], 1.0)

    # "o processo caiu": um worker novo começa devolvendo à fila o que ficou rodando
    assert queue.requeue_interrupted() == 1  # só A (B está pausado e C terminou)
    assert [i.state for i in queue.list()] == [PENDING, PAUSED, DONE]
    assert queue.claim_next().id == interrupted.id


def test_requeue_keeps_the_progress_already_recorded(queue):
    item = add(queue)
    queue.claim_next()
    queue.update_progress(item.id, chapter=2, utterances_done=17, chars_left=300)
    queue.requeue_interrupted()
    again = queue.get(item.id)
    assert (again.state, again.chapter, again.utterances_done) == (PENDING, 2, 17)
    assert again.started_at is not None


# ---------- reordenar ----------


def test_move_swaps_with_the_neighbour_among_waiting_items_only(queue):
    a, b, c = add(queue, "A"), add(queue, "B"), add(queue, "C")
    queue.move(c.id, -1)
    assert [i.title for i in queue.list()] == ["A", "C", "B"]
    queue.move(c.id, -1)
    queue.move(c.id, -1)  # já é o primeiro: não faz nada
    assert [i.title for i in queue.list()] == ["C", "A", "B"]
    queue.move(c.id, +1)
    queue.move(b.id, +1)  # já é o último
    assert [i.title for i in queue.list()] == ["A", "C", "B"]
    assert a.id == queue.list()[0].id


def test_move_skips_over_running_and_finished_items(queue):
    first, second, third = add(queue, "A"), add(queue, "B"), add(queue, "C")
    queue.claim_next()  # A rodando
    queue.cancel(second.id)  # B cancelado entre os dois
    queue.move(third.id, -1)  # não há outro item esperando acima de C
    assert [i.title for i in queue.list()] == ["A", "B", "C"]
    with pytest.raises(ValueError, match="pendentes ou pausados"):
        queue.move(first.id, +1)


def test_move_between_two_waiting_items_with_a_cancelled_one_in_the_middle(queue):
    a, b, c = add(queue, "A"), add(queue, "B"), add(queue, "C")
    queue.cancel(b.id)
    queue.move(c.id, -1)
    assert [i.title for i in queue.list()] == ["C", "B", "A"]
    assert a.id == queue.list()[2].id


# ---------- limpeza ----------


def test_clear_finished_removes_done_and_cancelled_but_keeps_failures_and_waiting(queue):
    done, cancelled, failed, waiting = add(queue, "A"), add(queue, "B"), add(queue, "C"), add(queue, "D")
    for _ in range(3):
        queue.claim_next()
    queue.finish(done.id, ["a.wav"], 1.0)
    queue.cancel(cancelled.id)
    queue.fail(failed.id, "ValueError: x")

    assert queue.clear_finished() == 2

    assert [i.title for i in queue.list()] == ["C", "D"]
    assert not queue.chapters_path(done.id).exists() and not queue.chapters_path(cancelled.id).exists()
    assert queue.chapters_path(waiting.id).exists()


def test_remove_refuses_the_running_item_and_deletes_the_text_of_the_others(queue):
    running, other = add(queue, "A"), add(queue, "B")
    queue.claim_next()
    with pytest.raises(ValueError, match="cancele antes"):
        queue.remove(running.id)
    queue.remove(other.id)
    assert [i.id for i in queue.list()] == [running.id] and not queue.chapters_path(other.id).exists()


# ---------- medidas de velocidade ----------


def test_speed_samples_are_kept_per_key_and_capped(queue):
    queue.record_samples("omnivoice:final", [(100, 140.0)])
    queue.record_samples("omnivoice:final", [(50, 70.0)])
    queue.record_samples("kokoro:final", [(80, 16.0)])
    queue.record_samples("kokoro:draft", [])
    assert queue.samples("omnivoice:final") == [(100, 140.0), (50, 70.0)]
    assert queue.samples("kokoro:final") == [(80, 16.0)]
    assert queue.samples("nunca-medido") == []
    queue.record_samples("omnivoice:final", [(10, 1.0)] * 100)
    assert len(queue.samples("omnivoice:final")) == 40


def test_a_read_denied_for_an_instant_by_another_process_is_retried(queue, monkeypatch):
    add(queue)
    real = Path.read_text
    denied = {"left": 2}

    def flaky(self, *args, **kwargs):
        if self.name == "voice_queue.json" and denied["left"]:
            denied["left"] -= 1
            raise PermissionError("em uso por outro processo")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    monkeypatch.setattr("dmaker.pipeline.voice_queue.REPLACE_WAIT_SECONDS", 0)

    assert len(queue.list()) == 1 and denied["left"] == 0
