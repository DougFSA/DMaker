"""Tradutor do Ollama: lotes com contexto, ids, JSON inválido, glossário e erros em português (chat falso)."""

from __future__ import annotations

import json

import pytest

from dmaker.agent.llm import OllamaChat, Reply
from dmaker.text.translate import (
    Line,
    OllamaTranslator,
    TranslationError,
    build_request,
    parse_translations,
    system_prompt,
)

LINES = [
    Line("s1", "Olá, pessoal.", 1.5),
    Line("s2", "Hoje vamos falar do DMaker.", 3.0),
    Line("s3", "Até a próxima.", 1.2),
]


def answer(**texts: str) -> str:
    return json.dumps({"translations": [{"id": k, "text": v} for k, v in texts.items()]})


class FakeChat:
    """Responde com a lista de respostas, na ordem; guarda as mensagens de cada chamada."""

    def __init__(self, replies: list[str | Exception], alive: bool = True, has_model: bool = True):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []
        self.alive = alive
        self.installed = has_model
        self.base_url = "http://ollama.teste:11434"

    def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls.append([dict(m) for m in messages])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Reply(content=reply)

    def is_alive(self) -> bool:
        return self.alive

    def has_model(self) -> bool:
        return self.installed


def translate(chat: FakeChat, lines=LINES, glossary=(), **options) -> list[str]:
    return OllamaTranslator("modelo-teste", chat, **options).translate(lines, "pt", "en", glossary)


# ---------- o caminho feliz ----------


def test_translates_every_line_in_order_with_the_whole_script_as_context():
    chat = FakeChat(
        [answer(s1="Hello, everyone.", s2="Today we talk about DMaker.", s3="See you next time.")]
    )
    assert translate(chat) == ["Hello, everyone.", "Today we talk about DMaker.", "See you next time."]
    request = json.loads(chat.calls[0][1]["content"])
    assert [entry["id"] for entry in request["script"]] == ["s1", "s2", "s3"]
    assert request["translate_ids"] == ["s1", "s2", "s3"]
    assert request["script"][1] == {"id": "s2", "seconds": 3.0, "text": "Hoje vamos falar do DMaker."}


def test_batches_carry_the_earlier_translations_as_context():
    chat = FakeChat([answer(s1="Hello, everyone.", s2="Today we talk."), answer(s3="See you next time.")])
    result = translate(chat, batch_lines=2)
    assert result[2] == "See you next time." and len(chat.calls) == 2
    second = json.loads(chat.calls[1][1]["content"])
    assert second["translate_ids"] == ["s3"]
    assert {e["id"]: e.get("translation") for e in second["script"]} == {
        "s1": "Hello, everyone.",
        "s2": "Today we talk.",
        "s3": None,
    }


def test_long_scripts_send_only_a_window_around_the_batch():
    many = [Line(f"s{n}", f"fala {n}", 1.0) for n in range(100)]
    request = json.loads(build_request(many, many[50:52], {}))
    ids = [entry["id"] for entry in request["script"]]
    assert 0 < len(ids) < 100 and "s50" in ids and "s51" in ids and "s0" not in ids


def test_locked_lines_come_back_unchanged_and_are_only_context():
    lines = [
        LINES[0],
        Line("s2", "Hoje vamos falar do DMaker.", 3.0, known="Today it's about DMaker."),
        LINES[2],
    ]
    chat = FakeChat([answer(s1="Hello, everyone.", s3="See you next time.")])
    result = translate(chat, lines)
    assert result[1] == "Today it's about DMaker."
    request = json.loads(chat.calls[0][1]["content"])
    assert request["translate_ids"] == ["s1", "s3"]
    assert request["script"][1]["translation"] == "Today it's about DMaker."


def test_empty_source_lines_are_skipped_and_nothing_to_translate_never_calls_the_model():
    chat = FakeChat([], alive=False)  # sem nada a traduzir, nem a checagem do Ollama roda
    lines = [Line("s1", "   ", 1.0), Line("s2", "ok", 1.0, known="fine")]
    assert translate(chat, lines) == ["", "fine"] and chat.calls == []


def test_progress_reports_translated_lines():
    chat = FakeChat([answer(s1="a", s2="b"), answer(s3="c")])
    seen: list[tuple[int, int]] = []
    OllamaTranslator("m", chat, batch_lines=2).translate(
        LINES, "pt", "en", on_progress=lambda d, t: seen.append((d, t))
    )
    assert seen == [(0, 3), (2, 3), (3, 3)]


# ---------- glossário e instruções ----------


def test_glossary_goes_into_the_prompt_and_the_prompt_asks_for_short_natural_lines():
    chat = FakeChat([answer(s1="a", s2="b", s3="c")])
    translate(chat, glossary=["DMaker", "MedlyCare"])
    system = chat.calls[0][0]["content"]
    assert '"DMaker", "MedlyCare"' in system and "never translate" in system
    assert "Brazilian Portuguese" in system and "English" in system
    assert "about as long to say as the original" in system
    assert "—" not in system  # sem travessão, nem no prompt


def test_prompt_without_glossary_has_no_terms_rule():
    assert "exactly as written" not in system_prompt("pt", "en", [])


# ---------- respostas inválidas ----------


def test_invalid_json_repeats_the_batch_with_the_problem_in_the_message():
    chat = FakeChat(["isto não é json", answer(s1="a", s2="b", s3="c")])
    assert translate(chat) == ["a", "b", "c"]
    retry = chat.calls[1]
    assert retry[-2] == {"role": "assistant", "content": "isto não é json"}
    assert "Invalid answer" in retry[-1]["content"] and '["s1", "s2", "s3"]' in retry[-1]["content"]


def test_wrong_count_missing_and_extra_ids_are_rejected():
    for bad in (
        answer(s1="a", s2="b"),  # faltou s3
        answer(s1="a", s2="b", s3="c", s4="d"),  # sobrou s4
        answer(s1="a", s2="b", x="c"),  # id trocado
        json.dumps({"translations": [{"id": "s1", "text": "a"}] * 3}),  # repetidos
    ):
        with pytest.raises(ValueError):
            parse_translations(bad, ["s1", "s2", "s3"])


def test_empty_translation_and_malformed_items_are_rejected():
    with pytest.raises(ValueError, match="vazia"):
        parse_translations(answer(s1="  ", s2="b"), ["s1", "s2"])
    with pytest.raises(ValueError, match="id"):
        parse_translations('{"translations": [{"texto": "a"}]}', ["s1"])
    with pytest.raises(ValueError, match="translations"):
        parse_translations('{"other": []}', ["s1"])


def test_fenced_json_with_chatter_is_accepted():
    wrapped = "Claro!\n```json\n" + answer(s1="a b", s2="c") + "\n```"
    assert parse_translations(wrapped, ["s1", "s2"]) == {"s1": "a b", "s2": "c"}


def test_gives_up_after_the_attempts_with_a_clear_message():
    chat = FakeChat(["x", "y", "z"])
    with pytest.raises(TranslationError, match="3 tentativas"):
        translate(chat)
    assert len(chat.calls) == 3


# ---------- Ollama fora do ar ----------


def test_ollama_not_running_is_a_portuguese_error_before_any_work():
    chat = FakeChat([], alive=False)
    with pytest.raises(
        TranslationError, match="Não consegui falar com o Ollama em http://ollama.teste:11434"
    ):
        translate(chat)
    assert chat.calls == []


def test_missing_model_tells_how_to_install_it():
    chat = FakeChat([], has_model=False)
    with pytest.raises(TranslationError, match="ollama pull modelo-teste"):
        translate(chat)


def test_a_connection_error_during_the_chat_is_reported_in_portuguese():
    chat = FakeChat([ConnectionResetError("caiu")])
    with pytest.raises(TranslationError, match="A conversa com o Ollama falhou"):
        translate(chat)


# ---------- o cliente real, sem rede ----------


def test_default_model_comes_from_the_configuration(monkeypatch):
    monkeypatch.setattr("dmaker.config.TRANSLATE_MODEL", "outro-modelo")
    assert OllamaTranslator(chat=FakeChat([])).model == "outro-modelo"


def test_default_chat_uses_low_temperature_json_and_short_reasoning_only_for_gpt_oss():
    sent: list[dict] = []

    class Response:
        def __init__(self, payload: dict):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def opener(request, timeout):
        if request.data:
            sent.append(json.loads(request.data))
            return Response({"message": {"content": answer(s1="a", s2="b", s3="c")}})
        return Response({"models": [{"name": "gpt-oss:20b"}]})

    translator = OllamaTranslator("gpt-oss:20b")
    assert isinstance(translator.chat, OllamaChat)
    translator.chat.opener = opener
    assert translator.translate(LINES, "pt", "en") == ["a", "b", "c"]
    body = sent[0]
    assert body["options"]["temperature"] < 0.5 and body["format"] == "json" and body["think"] == "low"
    assert body["model"] == "gpt-oss:20b"

    other = OllamaTranslator("qwen3-coder:30b")
    assert isinstance(other.chat, OllamaChat) and other.chat.think is None
