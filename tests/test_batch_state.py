"""Estado do lote no disco (arquivo atômico, pedido de pausa à parte) e a trava de execução entre processos."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dmaker import config
from dmaker.pipeline.batch_report import build_report
from dmaker.pipeline.batch_state import (
    DONE,
    FAILED,
    INVALID,
    PENDING,
    Batch,
    BatchFileError,
    BatchNotFoundError,
    BatchRow,
    BatchStore,
)
from dmaker.pipeline.filelock import FileLock


def sample() -> Batch:
    return Batch(
        "semana",
        "stories-medlycare",
        "C:/planilhas/semana.csv",
        "titulo",
        rows=[
            BatchRow(
                1, 2, "Dica um", "dica-um", "semana-dica-um", DONE, output="o/dica-um.mp4", render_s=12.0
            ),
            BatchRow(
                2, 3, "Dica dois", "dica-dois", "semana-dica-dois", FAILED, error="RuntimeError: ffmpeg"
            ),
            BatchRow(
                3, 4, "", "video-03", None, INVALID, issues=[{"level": "erro", "message": "sem imagem"}]
            ),
            BatchRow(4, 5, "Dica quatro", "dica-quatro", "semana-dica-quatro", PENDING),
        ],
    )


def test_the_default_folder_sits_next_to_the_projects_and_follows_the_config(tmp_path):
    assert BatchStore().folder == config.PROJECTS_DIR / "_lotes"
    assert BatchStore().path("semana") == config.PROJECTS_DIR / "_lotes" / "semana.json"


def test_a_saved_batch_comes_back_the_same(tmp_path):
    store = BatchStore(tmp_path)
    store.save(sample())

    loaded = store.load("semana")

    assert loaded.rows == sample().rows
    assert (loaded.template, loaded.sheet, loaded.name_column, loaded.preview) == (
        "stories-medlycare",
        "C:/planilhas/semana.csv",
        "titulo",
        False,
    )
    assert not list(tmp_path.glob("*.tmp"))  # o temporário foi renomeado


def test_unknown_fields_in_the_file_are_ignored_so_a_newer_file_still_opens(tmp_path):
    store = BatchStore(tmp_path)
    store.save(sample())
    data = json.loads(store.path("semana").read_text(encoding="utf-8"))
    data["campo_novo"] = 1
    data["rows"][0]["outro_campo"] = 2
    store.path("semana").write_text(json.dumps(data), encoding="utf-8")

    assert store.load("semana").rows[0].title == "Dica um"


def test_a_missing_batch_and_an_unreadable_file_have_their_own_errors(tmp_path):
    store = BatchStore(tmp_path)
    with pytest.raises(BatchNotFoundError, match='Não existe o lote "x"'):
        store.load("x")
    store.path("quebrado").write_text("{ não é json", encoding="utf-8")
    with pytest.raises(BatchFileError, match="Não consegui ler o lote"):
        store.load("quebrado")


def test_change_applies_and_saves_in_one_step(tmp_path):
    store = BatchStore(tmp_path)
    store.save(sample())

    store.change("semana", lambda batch: setattr(batch.rows[3], "state", DONE))

    assert store.load("semana").rows[3].state == DONE


def test_the_pause_request_is_a_separate_marker_that_does_not_touch_the_batch_file(tmp_path):
    store = BatchStore(tmp_path)
    store.save(sample())
    before = store.path("semana").read_bytes()

    assert not store.pause_requested("semana")
    store.request_pause("semana")
    assert store.pause_requested("semana") and store.path("semana").read_bytes() == before
    store.clear_pause("semana")
    assert not store.pause_requested("semana")
    with pytest.raises(BatchNotFoundError):
        store.request_pause("não-existe")


def test_list_names_puts_the_most_recent_first_and_remove_forgets_only_the_state(tmp_path):
    store = BatchStore(tmp_path)
    older = sample()
    older.name = "antigo"
    store.save(older)
    os.utime(store.path("antigo"), (1, 1))
    store.save(sample())
    store.request_pause("semana")

    assert store.list_names() == ["semana", "antigo"]
    store.remove("semana")
    assert store.list_names() == ["antigo"] and not store.pause_requested("semana")


def test_the_report_counts_what_came_out_what_failed_and_what_was_skipped():
    report = build_report(sample(), "paused", Path("output") / "semana")

    assert (report.done, report.failed, report.skipped, report.waiting, report.total) == (1, 1, 1, 1, 3)
    assert (
        report.summary()
        == "1 de 3 vídeo(s) pronto(s), 1 falhou(aram), 1 linha(s) pulada(s) por problema, 1 esperando"
    )
    text = report.to_text()
    assert "[pronto] Dica um (linha 2): o/dica-um.mp4, renderizou em 12 s" in text
    assert "[falhou] Dica dois (linha 3): RuntimeError: ffmpeg" in text
    assert "[pulada] linha 4: não renderizada. sem imagem" in text
    assert report.to_dict()["status_label"] == "Pausado"
    assert "—" not in text and "–" not in text


def test_the_file_lock_lets_only_one_holder_in_and_frees_on_release(tmp_path):
    first, second = FileLock(tmp_path / "x.lock"), FileLock(tmp_path / "x.lock")

    assert first.try_acquire() and first.held and first.try_acquire()
    assert not second.try_acquire() and not second.held
    first.release()
    assert second.try_acquire()
    second.release()
    second.release()  # soltar duas vezes é inofensivo
