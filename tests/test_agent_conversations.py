"""Conversas salvas: o registro em JSON, o repositório em disco e as escolhas que a conversa faz sobre o motor."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from dmaker import config
from dmaker.agent.conversations import (
    DEFAULT_TITLE,
    MODE_FREE,
    MODE_OPERATE,
    TITLE_LIMIT,
    ConversationFormatError,
    ConversationInUseError,
    ConversationOptions,
    ConversationRecord,
    DiskConversationStore,
    configure_chat,
    new_record,
    settings_for_conversation,
    title_from_message,
)
from dmaker.agent.llm import OllamaChat
from dmaker.agent.openai_chat import OpenAICompatibleChat
from dmaker.agent.settings import AgentSettings


@pytest.fixture
def store(tmp_path) -> DiskConversationStore:
    return DiskConversationStore(lambda: tmp_path / "conversas")


def record(store: DiskConversationStore, **fields) -> ConversationRecord:
    created = new_record(store.new_id(), fields.pop("mode", MODE_OPERATE), fields.pop("model", "gpt-oss:20b"))
    for name, value in fields.items():
        setattr(created, name, value)
    return created


# ---------- título ----------


def test_the_title_is_the_first_line_of_the_first_message():
    assert title_from_message("Corta as pausas do vídeo da viagem") == "Corta as pausas do vídeo da viagem"
    assert title_from_message("\n\n  primeira linha  \nsegunda") == "primeira linha"
    assert title_from_message("muito    espaço\tno meio") == "muito espaço no meio"
    assert title_from_message("   \n  ") == DEFAULT_TITLE


def test_a_long_title_is_cut_on_a_word_with_an_ellipsis_within_the_limit():
    line = "Preciso que você corte todas as pausas longas do vídeo da viagem e depois legende em português"

    title = title_from_message(line)

    assert len(title) <= TITLE_LIMIT and title.endswith("…")
    assert line.startswith(title[:-1]) and line[len(title) - 1] == " "  # parou no fim de uma palavra
    unbroken = title_from_message("x" * 200)
    assert len(unbroken) == TITLE_LIMIT and unbroken.endswith("…")


# ---------- registro ----------


def test_the_record_round_trips_through_json_with_every_field():
    original = ConversationRecord(
        id="abc123",
        mode=MODE_FREE,
        model="gpt-oss:20b",
        created_at="2026-10-30T12:00:00+00:00",
        updated_at="2026-10-30T12:05:00+00:00",
        title="Conversa",
        effort="low",
        options=ConversationOptions(num_ctx=8192, temperature=0.2, seed=7),
        kits=["editing"],
        history=[{"role": "user", "content": "oi"}],
        transcript=[{"kind": "user", "id": "e1", "text": "oi", "at": "x"}],
    )

    loaded = ConversationRecord.from_json_dict(json.loads(json.dumps(original.to_json_dict())))

    assert loaded == original
    saved = original.to_json_dict()
    assert saved["version"] == 1 and saved["options"] == {"num_ctx": 8192, "temperature": 0.2, "seed": 7}


def test_a_record_without_a_title_shows_the_default_one_but_stores_it_empty():
    created = new_record("abc", MODE_OPERATE, "m")

    assert created.title == "" and created.display_title == DEFAULT_TITLE
    assert created.to_json_dict()["title"] == "" and created.message_count == 0


def test_the_message_count_is_the_number_of_user_messages_in_the_transcript():
    created = new_record("abc", MODE_OPERATE, "m")
    created.transcript = [{"kind": "user"}, {"kind": "answer"}, {"kind": "user"}]

    assert created.message_count == 2


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"id": 3, "mode": "operate"},
        {"id": "a", "mode": "desconhecido"},
        {"id": "a", "mode": "free", "version": 99},
    ],
)
def test_a_file_that_is_not_a_conversation_is_refused(data):
    with pytest.raises(ConversationFormatError):
        ConversationRecord.from_json_dict(data)


# ---------- repositório ----------


def test_saving_and_opening_gives_back_the_same_conversation(store):
    saved = record(store, title="Primeira", effort="high", kits=["voice"])
    saved.history = [{"role": "user", "content": "áudio com acento: ação"}]

    store.save(saved)

    assert store.load(saved.id) == saved
    text = (store.root() / f"{saved.id}.json").read_text(encoding="utf-8")
    assert "ação" in text  # gravado em UTF-8 legível, não escapado


def test_saving_is_atomic_and_leaves_no_temporary_file(store):
    saved = record(store)

    store.save(saved)
    saved.title = "Mudou"
    store.save(saved)

    assert sorted(path.name for path in store.root().iterdir()) == [f"{saved.id}.json"]
    assert store.load(saved.id).title == "Mudou"


def test_a_half_written_file_never_replaces_the_good_one(store, monkeypatch):
    saved = record(store, title="Boa")
    store.save(saved)
    saved.title = "Nova"

    def boom(source, target):
        raise OSError("disco cheio")

    with monkeypatch.context() as patched:
        patched.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            store.save(saved)

    assert store.load(saved.id).title == "Boa"  # o arquivo antigo continua inteiro


def test_opening_something_that_does_not_exist_is_none(store):
    assert store.load("naoexiste") is None
    assert store.load("../fora") is None  # um identificador com caminho nunca chega ao disco
    assert store.load("a/b") is None


def test_an_unreadable_file_is_a_clear_error_when_opened_and_does_not_hide_the_others_in_the_list(store):
    good = record(store, title="Boa")
    store.save(good)
    (store.root() / "quebrada.json").write_text("{ isto não é json", encoding="utf-8")

    with pytest.raises(ConversationFormatError, match="quebrada"):
        store.load("quebrada")

    assert [summary.id for summary in store.list()] == [good.id]


def test_the_list_is_most_recent_first_with_what_the_sidebar_needs(store):
    older = record(store, title="Antiga", updated_at="2026-10-01T10:00:00+00:00")
    newer = record(store, title="Nova", updated_at="2026-10-30T10:00:00+00:00", mode=MODE_FREE)
    newer.transcript = [{"kind": "user"}, {"kind": "answer"}]
    store.save(older)
    store.save(newer)

    listed = store.list()

    assert [summary.title for summary in listed] == ["Nova", "Antiga"]
    assert listed[0].to_dict() == {
        "id": newer.id,
        "title": "Nova",
        "created_at": newer.created_at,
        "updated_at": "2026-10-30T10:00:00+00:00",
        "mode": "free",
        "model": "gpt-oss:20b",
        "effort": None,
        "messages": 1,
    }


def test_the_list_notices_a_file_that_changed_and_forgets_one_that_was_deleted(store):
    saved = record(store, title="Antes")
    store.save(saved)
    assert store.list()[0].title == "Antes"

    saved.title = "Depois com um título bem maior para mudar o tamanho do arquivo"
    store.save(saved)
    assert store.list()[0].title.startswith("Depois")

    (store.root() / f"{saved.id}.json").unlink()
    assert store.list() == []


def test_an_empty_or_missing_folder_lists_nothing(store, tmp_path):
    assert store.list() == []
    (tmp_path / "conversas").mkdir()
    assert store.list() == []


def test_new_ids_are_unique_and_safe_as_file_names(store):
    first = store.new_id()
    store.save(new_record(first, MODE_OPERATE, "m"))

    assert store.new_id() != first
    assert first.isalnum() and len(first) == 10


def test_deleting_removes_the_file_and_the_attachments_folder(store):
    saved = record(store)
    store.save(saved)
    attachments = store.attachments_dir(saved.id)
    (attachments / "sub").mkdir(parents=True)
    (attachments / "sub" / "foto.png").write_bytes(b"png")

    assert store.delete(saved.id) is True

    assert not attachments.exists() and store.load(saved.id) is None and store.list() == []
    assert store.delete(saved.id) is False


def test_deleting_an_id_with_a_path_touches_nothing(store, tmp_path):
    outside = tmp_path / "importante"
    outside.mkdir()
    (outside / "arquivo.txt").write_text("fica", encoding="utf-8")
    store.save(record(store))

    assert store.delete("../importante") is False
    with pytest.raises(ValueError):
        store.attachments_dir("../importante")

    assert (outside / "arquivo.txt").exists()


def test_a_file_in_use_is_explained_and_the_conversation_stays_whole(store, monkeypatch):
    saved = record(store)
    store.save(saved)
    held = store.attachments_dir(saved.id) / "video.mp4"
    held.parent.mkdir(parents=True)
    held.write_bytes(b"x")
    real_unlink = os.unlink

    def locked(path, *args, **kwargs):
        if Path(path).name == "video.mp4":
            raise PermissionError(13, "O arquivo está sendo usado por outro processo")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(os, "unlink", locked)
        patched.setattr(os, "remove", locked)
        with pytest.raises(ConversationInUseError, match="video.mp4.*aberto em outro programa"):
            store.delete(saved.id)

    assert store.load(saved.id) is not None  # a conversa continua lá, para tentar de novo
    assert store.delete(saved.id) is True


def test_the_folder_is_read_from_config_when_used_not_when_imported(tmp_path, monkeypatch):
    first = tmp_path / "um"
    default_store = DiskConversationStore()

    monkeypatch.setattr(config, "CONVERSATIONS_DIR", first)
    default_store.save(new_record("aaa", MODE_OPERATE, "m"))

    assert (first / "aaa.json").exists()


def test_two_threads_saving_the_same_conversation_never_corrupt_it(store):
    saved = record(store)

    def hammer(label: str) -> None:
        for index in range(30):
            saved.title = f"{label}{index}"
            store.save(saved)

    threads = [threading.Thread(target=hammer, args=(name,)) for name in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert store.load(saved.id).title[0] in "ab"


# ---------- o que a conversa escolhe sobre o motor ----------


def test_the_conversation_choices_override_the_environment_ones():
    base = AgentSettings(model="env-model", num_ctx=16384, think="medium", temperature=0.7, seed=1)
    chosen = new_record("a", MODE_OPERATE, "gpt-oss:20b", "high", ConversationOptions(8192, 0.1, 99))

    settings = settings_for_conversation(base, chosen)

    assert (settings.model, settings.think, settings.num_ctx, settings.temperature, settings.seed) == (
        "gpt-oss:20b",
        "high",
        8192,
        0.1,
        99,
    )


def test_what_the_conversation_leaves_open_falls_back_to_the_environment():
    base = AgentSettings(model="env-model", num_ctx=16384, think="medium", temperature=0.7, seed=1)

    settings = settings_for_conversation(base, new_record("a", MODE_FREE, ""))

    assert (settings.model, settings.think, settings.num_ctx, settings.temperature, settings.seed) == (
        "env-model",
        "medium",
        16384,
        0.7,
        1,
    )


def test_the_effort_becomes_the_think_value_the_server_takes():
    base = AgentSettings()

    def think(effort):
        return settings_for_conversation(base, new_record("a", MODE_OPERATE, "m", effort)).think

    assert think("low") == "low" and think("on") is True and think("off") is False and think(None) is None


def test_a_zero_temperature_is_a_choice_and_not_the_same_as_none():
    base = AgentSettings(temperature=0.9)

    settings = settings_for_conversation(
        base, new_record("a", MODE_OPERATE, "m", None, ConversationOptions(None, 0.0, 0))
    )

    assert settings.temperature == 0.0 and settings.seed == 0


def test_configure_chat_updates_the_ollama_client_between_messages():
    chat = OllamaChat(model="velho", num_ctx=1024)
    base = AgentSettings(model="novo", num_ctx=4096, think="high", temperature=0.3, seed=5)

    configure_chat(chat, base)

    assert (chat.model, chat.num_ctx, chat.think, chat.temperature, chat.seed) == (
        "novo",
        4096,
        "high",
        0.3,
        5,
    )
    body = chat._chat_body([], [], stream=True)
    assert body["model"] == "novo" and body["think"] == "high" and body["options"]["num_ctx"] == 4096


def test_configure_chat_skips_what_the_engine_does_not_have():
    chat = OpenAICompatibleChat(model="velho")
    base = AgentSettings(engine="openai", model="novo", think="high", num_ctx=4096, temperature=0.3)

    configure_chat(chat, base)

    assert chat.model == "novo" and chat.temperature == 0.3
    assert not hasattr(chat, "think") and not hasattr(chat, "num_ctx")


def test_configure_chat_leaves_a_scripted_fake_alone():
    class Fake:
        def chat(self, messages, tools): ...

    fake = Fake()

    configure_chat(fake, AgentSettings(model="x"))

    assert vars(fake) == {}
