"""Subcomandos `dmaker voice queue`: enfileirar, listar, controlar e executar em primeiro plano."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.pipeline.voice_batch import ItemOutput
from dmaker.pipeline.voice_queue import CANCELLED, DONE, PAUSED, PENDING, VoiceQueue
from dmaker.pipeline.voice_worker import QueueWorker, WorkerLock

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr("dmaker.voice.library.VOICES_DIR", tmp_path / "voices")


def invoke(*args: str):
    return runner.invoke(app, ["voice", "queue", *args])


def first_id() -> str:
    return VoiceQueue().list()[0].id


def test_add_text_lists_and_shows_the_estimate():
    added = invoke("add", "--text", "Uma frase para narrar na fila.", "--voice", "dora", "--title", "Aviso")
    assert added.exit_code == 0, added.output
    assert "Na fila" in added.output and "Aviso" in added.output and "1 capítulo(s)" in added.output

    listed = invoke("list").output
    assert "Aviso" in listed and "Pendente" in listed and "Tempo estimado" in listed


def test_add_file_creates_one_chapter_per_title(tmp_path):
    script = tmp_path / "curso.md"
    script.write_text(
        "# Um\nPrimeiro texto.\n\n# Dois\nSegundo texto.\n\n# Tres\nTerceiro texto.", encoding="utf-8"
    )

    added = invoke("add", "--file", str(script), "--format", "mp3", "--draft")

    assert added.exit_code == 0, added.output
    assert "3 capítulo(s)" in added.output
    item = VoiceQueue().list()[0]
    assert item.options.draft is True and item.options.audio_format == "mp3" and item.title == "curso"


def test_add_needs_exactly_one_source_and_valid_options(tmp_path):
    neither = invoke("add")
    assert neither.exit_code == 1 and "--text" in neither.output and "--file" in neither.output
    both = invoke("add", "--text", "a", "--file", str(tmp_path / "x.txt"))
    assert both.exit_code == 1
    assert invoke("add", "--text", "Oi.", "--voice", "fantasma").exit_code == 1
    assert invoke("add", "--text", "Oi.", "--format", "ogg").exit_code == 1
    missing = invoke("add", "--file", str(tmp_path / "nao-existe.md"))
    assert missing.exit_code == 1
    assert VoiceQueue().list() == []


def test_empty_queue_message():
    assert "vazia" in invoke("list").output


def test_cancel_pause_resume_by_id():
    invoke("add", "--text", "Uma frase para narrar na fila.")
    item_id = first_id()

    assert invoke("pause", item_id).exit_code == 0 and VoiceQueue().get(item_id).state == PAUSED
    assert invoke("resume", item_id).exit_code == 0 and VoiceQueue().get(item_id).state == PENDING
    assert invoke("cancel", item_id).exit_code == 0 and VoiceQueue().get(item_id).state == CANCELLED

    again = invoke("cancel", item_id)
    assert again.exit_code == 1 and "cancelado não pode ir para cancelado" in again.output
    unknown = invoke("cancel", "naoexiste")
    assert unknown.exit_code == 1 and "naoexiste" in unknown.output


class _Done:
    def __init__(self, order):
        self.order = order

    def process(self, item):
        self.order.append(item.title)
        return ItemOutput([f"{item.title}.wav"], 1.0)


def fake_build_worker(order, processor=None):
    def build(queue, guard=None, log=None):
        return QueueWorker(queue, lambda: processor or _Done(order), log=log)

    return build


def test_run_processes_every_item_in_order_and_reports(monkeypatch):
    invoke("add", "--text", "Primeira frase para narrar.", "--title", "Primeiro")
    invoke("add", "--text", "Segunda frase para narrar.", "--title", "Segundo")
    order: list[str] = []
    monkeypatch.setattr("dmaker.pipeline.voice_queue_service.build_worker", fake_build_worker(order))

    result = invoke("run")

    assert result.exit_code == 0, result.output
    assert order == ["Primeiro", "Segundo"] and "2 item(ns)" in result.output
    assert [i.state for i in VoiceQueue().list()] == [DONE, DONE]


def test_run_refuses_when_another_runner_holds_the_queue(monkeypatch):
    invoke("add", "--text", "Uma frase para narrar na fila.")
    monkeypatch.setattr("dmaker.pipeline.voice_queue_service.build_worker", fake_build_worker([]))
    other = WorkerLock(lambda: VoiceQueue().index_path.with_name("voice_queue.lock"))
    assert other.try_acquire()
    try:
        result = invoke("run")
    finally:
        other.release()
    assert result.exit_code == 1 and "Outra fila" in result.output
    assert VoiceQueue().list()[0].state == PENDING


def test_ctrl_c_during_run_puts_the_item_back_for_the_next_run(monkeypatch):
    invoke("add", "--text", "Uma frase para narrar na fila.")

    class Interrupted:
        def process(self, item):
            raise KeyboardInterrupt

    monkeypatch.setattr(
        "dmaker.pipeline.voice_queue_service.build_worker", fake_build_worker([], processor=Interrupted())
    )

    result = invoke("run")

    assert result.exit_code == 1 and "retoma" in result.output
    assert VoiceQueue().list()[0].state == PENDING
