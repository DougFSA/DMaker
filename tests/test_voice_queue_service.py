"""Serviço da fila: entrada por texto ou arquivo, validações e a visão com o tempo estimado."""

from __future__ import annotations

import pytest

from dmaker import config
from dmaker.pipeline.voice_queue import PAUSED, QueueOptions, VoiceQueue
from dmaker.pipeline.voice_queue_service import MAX_FILE_BYTES, VoiceQueueService, default_title, file_url
from dmaker.voice.library import VoiceLibrary, VoiceNotFoundError

MANUSCRIPT = b"# Primeiro\nTexto do primeiro capitulo.\n\n# Segundo\nTexto do segundo capitulo."


@pytest.fixture
def service(tmp_path, monkeypatch) -> VoiceQueueService:
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    woken: list[bool] = []
    created = VoiceQueueService(
        VoiceQueue(tmp_path / "cache" / "voice_queue.json"),
        VoiceLibrary(tmp_path / "voices"),
        on_change=lambda: woken.append(True),
    )
    created.woken = woken
    return created


def test_pasted_text_with_chapter_markers_becomes_chapters_and_wakes_the_worker(service):
    item = service.add_text("# Um\nPrimeiro texto.\n\n# Dois\nSegundo texto.", QueueOptions())

    assert item.chapters_total == 2 and item.source_kind == "text" and item.title == "Um"
    assert service.woken == [True]


def test_pasted_text_without_markers_is_one_chapter_titled_by_its_first_words(service):
    item = service.add_text("Hoje vamos falar sobre vozes sintéticas e como usar a fila.", QueueOptions())
    assert item.chapters_total == 1 and item.title == "Hoje vamos falar sobre vozes sintéticas"
    assert default_title("   ...  ") == "Narração"


def test_explicit_title_names_the_item_and_the_folder(service):
    item = service.add_text("Um texto.", QueueOptions(), title="Meu Audiobook")
    assert item.title == "Meu Audiobook" and item.output_dir.endswith("meu-audiobook")


def test_a_file_is_parsed_into_chapters_and_remembers_its_name(service):
    item = service.add_file(
        MANUSCRIPT, "pasta/roteiro_do_curso.md", QueueOptions(voice="dora", audio_format="mp3")
    )

    assert (
        item.chapters_total == 2 and item.source_kind == "file" and item.source_name == "roteiro_do_curso.md"
    )
    assert item.title == "roteiro do curso"  # vários capítulos: o nome do arquivo dá o título do item
    assert [c.title for c in service.queue.load_chapters(item.id)] == ["Primeiro", "Segundo"]


def test_a_single_chapter_file_takes_the_chapter_title_unless_one_is_given(service):
    assert service.add_file(b"# O Tema\nUm texto.", "x.md", QueueOptions()).title == "O Tema"
    assert service.add_file(b"# O Tema\nUm texto.", "x.md", QueueOptions(), title="Outro").title == "Outro"


def test_add_path_reads_the_file_from_disk(service, tmp_path):
    path = tmp_path / "livro.txt"
    path.write_bytes(MANUSCRIPT)
    assert service.add_path(path, QueueOptions()).chapters_total == 2


def test_invalid_requests_are_refused_before_entering_the_queue(service):
    with pytest.raises(ValueError, match="Escreva o texto"):
        service.add_text("   ", QueueOptions())
    with pytest.raises(VoiceNotFoundError):
        service.add_text("Texto.", QueueOptions(voice="fantasma"))
    with pytest.raises(ValueError, match="grande demais"):
        service.add_file(b"x" * (MAX_FILE_BYTES + 1), "enorme.txt", QueueOptions())
    with pytest.raises(ValueError, match="não suportado"):
        service.add_file(b"x", "livro.pdf", QueueOptions())
    assert service.queue.list() == []
    assert service.woken == []


# ---------- visão e tempo estimado ----------


def test_estimate_starts_from_the_documented_guess_per_engine_and_quality(service):
    final = service.add_text("a" * 1000, QueueOptions())
    draft = service.add_text("b" * 1000, QueueOptions(draft=True))
    kokoro = service.add_text("c" * 1000, QueueOptions(voice="dora"))

    by_id = {v["id"]: v for v in service.view()["items"]}

    assert by_id[final.id]["eta_seconds"] == 1400  # 1,4 s por caractere a 16 passos
    assert by_id[draft.id]["eta_seconds"] == 700  # 0,7 s por caractere no rascunho
    assert by_id[kokoro.id]["eta_seconds"] == 200  # o Kokoro é bem mais rápido
    assert by_id[final.id]["eta_label"] == "23 min"


def test_measured_speed_replaces_the_guess_and_is_kept_per_engine(service):
    item = service.add_text("a" * 1000, QueueOptions())
    other = service.add_text("b" * 1000, QueueOptions(voice="dora"))
    service.queue.record_samples("omnivoice:final", [(100, 20.0), (100, 20.0)])  # 0,2 s por caractere

    by_id = {v["id"]: v for v in service.view()["items"]}

    assert by_id[item.id]["eta_seconds"] == 200
    assert by_id[other.id]["eta_seconds"] == 200  # o Kokoro continua no chute dele (0,2), sem herdar a medida


def test_queue_total_counts_waiting_and_running_items_but_not_paused_or_finished(service):
    first = service.add_text("a" * 100, QueueOptions())
    second = service.add_text("b" * 100, QueueOptions())
    third = service.add_text("c" * 100, QueueOptions())
    service.queue.pause(second.id)
    service.queue.claim_next()
    service.queue.update_progress(first.id, chars_left=40)  # já narrou 60 caracteres
    service.queue.cancel(third.id)

    view = service.view()

    assert [v["eta_seconds"] for v in view["items"]] == [56, None, None]
    assert view["eta_seconds"] == 56 and view["eta_label"] == "56 s" and view["running"] is True
    assert view["items"][1]["state"] == PAUSED


def test_empty_queue_has_no_estimate(service):
    assert service.view() == {"items": [], "eta_seconds": None, "eta_label": None, "running": False}


def test_progress_percent_follows_the_utterances_and_files_become_links(service):
    item = service.add_text("Um texto longo o bastante.", QueueOptions())
    service.queue.claim_next()
    service.queue.update_progress(
        item.id, utterances_total=8, utterances_done=2, chapter=1, utterance=3, utterances=8
    )
    assert service.view()["items"][0]["percent"] == 25

    service.queue.finish(item.id, ["01-um.wav", "um-completo.srt"], 9.0)
    done = service.view()["items"][0]
    assert done["percent"] == 100 and done["eta_seconds"] is None
    assert done["files"] == [
        {"name": "01-um.wav", "url": file_url(item.id, "01-um.wav"), "audio": True},
        {"name": "um-completo.srt", "url": file_url(item.id, "um-completo.srt"), "audio": False},
    ]


def test_a_removed_voice_does_not_break_the_view(service, monkeypatch):
    item = service.add_text("Texto.", QueueOptions(voice="dora"))
    monkeypatch.setattr(
        service.library, "get", lambda _id: (_ for _ in ()).throw(VoiceNotFoundError("sumiu"))
    )
    assert service.view()["items"][0]["id"] == item.id


def test_file_url_escapes_the_name():
    assert file_url("abc", "01 capítulo.wav") == "/api/voices/queue/abc/files/01%20cap%C3%ADtulo.wav"
