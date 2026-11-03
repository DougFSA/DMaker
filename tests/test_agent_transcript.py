"""A transcrição que o servidor monta dos eventos do turno, e como ela se fecha quando o DMaker reinicia."""

from __future__ import annotations

from dmaker.agent.transcript import (
    RESULT_LIMIT,
    TranscriptBuilder,
    first_line,
    short_result,
)


def builder() -> TranscriptBuilder:
    return TranscriptBuilder(clock=lambda: "2026-10-30T12:00:00+00:00")


def kinds(transcript: TranscriptBuilder) -> list[str]:
    return [entry["kind"] for entry in transcript.entries]


def test_a_plain_turn_is_the_message_the_kit_and_the_answer():
    transcript = builder()

    transcript.add_user("Quais formatos existem?")
    transcript.apply("triage", {"kits": ["editing"], "method": "keywords"})
    transcript.apply("answer", {"text": "Reels e Shorts."})

    assert transcript.entries == [
        {"kind": "user", "id": "e1", "text": "Quais formatos existem?", "at": "2026-10-30T12:00:00+00:00"},
        {"kind": "kits", "id": "e2", "kits": ["editing"], "method": "keywords"},
        {"kind": "answer", "id": "e3", "text": "Reels e Shorts.", "interrupted": False},
    ]


def test_the_reasoning_is_its_own_entry_apart_from_the_answer():
    transcript = builder()

    transcript.apply("thinking", {"text": "  Preciso listar os presets.  "})
    transcript.apply("thinking", {"text": "   "})  # raciocínio vazio não vira entrada
    transcript.apply("answer", {"text": "Pronto."})

    assert [(e["kind"], e["text"]) for e in transcript.entries] == [
        ("thinking", "Preciso listar os presets."),
        ("answer", "Pronto."),
    ]


def test_a_tool_step_carries_the_name_the_arguments_a_one_line_summary_and_the_short_result():
    transcript = builder()
    long_result = "linha um\n" + "x" * 5000

    transcript.apply("tool_call", {"name": "presets", "arguments": {"platform": "reels"}})
    assert transcript.entries[0]["state"] == "running"
    transcript.apply("tool_result", {"name": "presets", "result": long_result})

    step = transcript.entries[0]
    assert (step["name"], step["arguments"], step["state"]) == ("presets", {"platform": "reels"}, "done")
    assert step["detail"] == "linha um"
    assert len(step["result"]) == RESULT_LIMIT and step["result"].endswith("…")


def test_an_error_result_is_marked_as_an_error():
    transcript = builder()

    transcript.apply("tool_call", {"name": "render_project", "arguments": {}})
    transcript.apply("tool_result", {"name": "render_project", "result": "erro: projeto não existe"})

    assert transcript.entries[0]["state"] == "error"
    assert transcript.entries[0]["detail"] == "erro: projeto não existe"


def test_a_blocked_call_stays_blocked_with_the_reason_even_after_its_result_arrives():
    transcript = builder()

    transcript.apply("tool_call", {"name": "render_project", "arguments": {}})
    transcript.apply(
        "tool_blocked", {"name": "render_project", "reason": "O usuário não autorizou: Posso?\nmais"}
    )
    transcript.apply(
        "tool_result", {"name": "render_project", "result": "O usuário não autorizou: Posso?\nmais"}
    )

    step = transcript.entries[0]
    assert step["state"] == "blocked" and step["detail"] == "O usuário não autorizou: Posso?"
    assert step["result"].startswith("O usuário não autorizou")
    assert len(transcript.entries) == 1


def test_two_calls_to_the_same_tool_are_two_steps_matched_in_order():
    transcript = builder()

    transcript.apply("tool_call", {"name": "probe_media", "arguments": {"path": "a"}})
    transcript.apply("tool_result", {"name": "probe_media", "result": "A"})
    transcript.apply("tool_call", {"name": "probe_media", "arguments": {"path": "b"}})
    transcript.apply("tool_result", {"name": "probe_media", "result": "erro: B"})

    assert [(e["arguments"]["path"], e["state"]) for e in transcript.entries] == [
        ("a", "done"),
        ("b", "error"),
    ]


def test_a_confirmation_keeps_the_question_and_gets_the_answer():
    transcript = builder()

    transcript.apply(
        "confirmation_request",
        {"id": "abc", "tool": "render_project", "question": "Posso gerar o vídeo final?", "type": "action"},
    )
    assert transcript.entries[0]["state"] == "pending"
    transcript.apply("confirmation_answered", {"id": "abc", "approved": True})
    transcript.apply("confirmation_answered", {"id": "outra", "approved": False})  # de outro turno: ignorada

    confirmation = transcript.entries[0]
    assert confirmation["state"] == "approved" and confirmation["confirmation_id"] == "abc"
    assert (confirmation["tool"], confirmation["question"], confirmation["type"]) == (
        "render_project",
        "Posso gerar o vídeo final?",
        "action",
    )


def test_an_interrupted_answer_keeps_the_partial_text_marked():
    transcript = builder()

    transcript.apply("answer", {"text": "Os formatos são", "interrupted": True})

    assert transcript.entries == [
        {"kind": "answer", "id": "e1", "text": "Os formatos são", "interrupted": True}
    ]


def test_stopping_before_anything_arrived_leaves_a_notice_instead_of_an_empty_answer():
    transcript = builder()

    transcript.apply("answer", {"text": "", "interrupted": True})

    assert [(e["kind"], e["code"]) for e in transcript.entries] == [("notice", "interrupted")]


def test_the_trim_warning_becomes_a_notice():
    transcript = builder()

    transcript.apply("history_trimmed", {"turns": 2, "text": "As 2 trocas mais antigas saíram."})

    assert transcript.entries == [
        {
            "kind": "notice",
            "id": "e1",
            "level": "info",
            "code": "history_trimmed",
            "text": "As 2 trocas mais antigas saíram.",
        }
    ]


def test_events_only_the_live_screen_needs_never_reach_the_transcript():
    transcript = builder()

    for kind, data in (
        ("answer_delta", {"text": "x"}),
        ("thinking_delta", {"text": "y"}),
        ("status", {"stage": "reading", "label": "Lendo o pedido"}),
        ("model_reply", {"seconds": 1.0}),
        ("tool_progress", {"name": "render", "progress": {"percent": 5}}),
        ("facts", {"text": "..."}),
        ("progress", {"percent": 3}),
    ):
        transcript.apply(kind, data)

    assert transcript.entries == []


def test_ids_keep_counting_after_the_transcript_is_loaded_from_disk():
    saved = [
        {"kind": "user", "id": "e7", "text": "oi", "at": "x"},
        {"kind": "answer", "id": "e9", "text": "ola"},
    ]
    transcript = TranscriptBuilder(saved)

    transcript.add_user("de novo")

    assert transcript.entries[-1]["id"] == "e10"


def test_snapshot_is_a_copy_that_later_events_do_not_change():
    transcript = builder()
    transcript.apply("tool_call", {"name": "presets", "arguments": {}})

    frozen = transcript.snapshot()
    transcript.apply("tool_result", {"name": "presets", "result": "ok"})

    assert frozen[0]["state"] == "running" and transcript.entries[0]["state"] == "done"


# ---------- o que fica aberto quando o DMaker fecha ----------


def test_settling_marks_an_unanswered_confirmation_as_not_confirmed_and_a_running_tool_as_interrupted():
    transcript = builder()
    transcript.add_user("renderiza o projeto x")
    transcript.apply("tool_call", {"name": "probe_media", "arguments": {}})
    transcript.apply(
        "confirmation_request",
        {"id": "abc", "tool": "render_project", "question": "Posso?", "type": "action"},
    )

    changed = transcript.settle()

    assert changed is True
    tool, confirmation, notice = transcript.entries[1], transcript.entries[2], transcript.entries[3]
    assert tool["state"] == "interrupted" and "fechado" in tool["detail"]
    assert confirmation["state"] == "unconfirmed"
    assert notice["kind"] == "notice" and notice["code"] == "unfinished" and notice["level"] == "warning"


def test_settling_a_finished_conversation_changes_nothing():
    transcript = builder()
    transcript.add_user("oi")
    transcript.apply("answer", {"text": "olá"})
    before = transcript.snapshot()

    assert transcript.settle() is False
    assert transcript.entries == before
    assert TranscriptBuilder().settle() is False


def test_helpers_cut_long_text_for_a_line_and_for_a_block():
    assert first_line("a\nb") == "a"
    assert first_line("x" * 300).endswith("…") and len(first_line("x" * 300)) == 160
    assert short_result("curto") == "curto"
    assert first_line("") == ""
