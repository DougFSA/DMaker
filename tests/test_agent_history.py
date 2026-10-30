"""Aparo do histórico: o que sai quando a conversa passa do contexto, e o reparo de uma conversa cortada ao meio."""

from __future__ import annotations

import pytest

from dmaker.agent.history import (
    DEFAULT_CHARS_PER_TOKEN,
    IMAGE_TOKENS,
    INTERRUPTED_TOOL_RESULT,
    MESSAGE_FRAME_TOKENS,
    calibrated_chars_per_token,
    estimate_tokens,
    prompt_budget,
    repair_history,
    trim_history,
    turn_starts,
)

SYSTEM = {"role": "system", "content": "sistema"}


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def assistant(text: str) -> dict:
    return {"role": "assistant", "content": text}


def tool_turn(name: str, result: str) -> list[dict]:
    """Uma chamada de ferramenta e o seu resultado: o par que o aparo nunca pode separar."""
    return [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": {}}}]},
        {"role": "tool", "tool_name": name, "content": result},
    ]


def long_turns(count: int, size: int = 3000) -> list[dict]:
    messages = [SYSTEM]
    for index in range(count):
        messages += [user(f"pergunta {index} " + "x" * size), assistant(f"resposta {index} " + "y" * size)]
    return messages


def test_the_budget_leaves_room_for_the_reply():
    assert prompt_budget(16384) == 16384 - 4096  # um quarto do contexto fica para a resposta
    assert prompt_budget(2048) == 1024  # contextos pequenos mantêm um mínimo de 1024 tokens
    assert prompt_budget(512) == 0


def test_a_conversation_that_fits_is_left_alone():
    messages = long_turns(2, size=100)

    result = trim_history(messages, 16384)

    assert result.removed_turns == 0 and result.messages == messages


def test_the_oldest_turns_leave_first_and_the_system_prompt_stays():
    messages = long_turns(10)  # uns 60 mil caracteres: não cabe em 8192 tokens

    result = trim_history(messages, 8192)

    assert result.removed_turns > 0
    assert result.messages[0] == SYSTEM
    texts = [m["content"] for m in result.messages if m["role"] == "user"]
    assert texts[-1].startswith("pergunta 9 ")  # o mais recente fica
    assert texts[0] != messages[1]["content"]  # o mais antigo saiu
    assert result.estimated_tokens <= result.budget_tokens
    assert len(turn_starts(result.messages)) == 10 - result.removed_turns


def test_the_current_request_is_never_trimmed_even_when_alone_it_is_too_big():
    messages = [SYSTEM, user("antiga"), assistant("ok"), user("z" * 60000)]

    result = trim_history(messages, 4096)

    assert result.removed_turns == 1
    assert result.messages == [SYSTEM, messages[3]]  # sobrou só o pedido de agora, mesmo acima do limite


def test_a_tool_call_never_loses_its_result():
    old = [user("renderiza")] + tool_turn("render_project", "r" * 9000) + [assistant("feito")]
    new = [user("e agora?"), assistant("agora sim")]

    result = trim_history([SYSTEM, *old, *new], 2048)

    roles = [m["role"] for m in result.messages]
    assert result.removed_turns == 1
    assert "tool" not in roles and all("tool_calls" not in m for m in result.messages)  # o par saiu junto


def test_the_tool_definitions_count_against_the_context():
    messages = long_turns(3, size=500)

    without = trim_history(messages, 4096)
    with_tools = trim_history(messages, 4096, overhead_chars=9000)

    assert without.removed_turns == 0
    assert with_tools.removed_turns > 0


def test_images_cost_tokens_instead_of_their_base64_text():
    one = [SYSTEM, {"role": "user", "content": "olha", "images": ["A" * 500_000]}]

    assert estimate_tokens(one) == round(len("sistema" + "olha") / DEFAULT_CHARS_PER_TOKEN) + (
        MESSAGE_FRAME_TOKENS * 2 + IMAGE_TOKENS
    )


def test_a_denser_text_makes_the_estimate_more_conservative():
    assert calibrated_chars_per_token(sent_chars=9000, prompt_tokens=4500) == 2.0  # 2 caracteres por token
    # o Ollama pode contar só os tokens novos quando reaproveita o começo do pedido: isso não afrouxa a conta
    assert calibrated_chars_per_token(sent_chars=9000, prompt_tokens=300) == DEFAULT_CHARS_PER_TOKEN
    assert calibrated_chars_per_token(sent_chars=0, prompt_tokens=100) == DEFAULT_CHARS_PER_TOKEN
    assert calibrated_chars_per_token(sent_chars=100, prompt_tokens=None) == DEFAULT_CHARS_PER_TOKEN
    assert calibrated_chars_per_token(sent_chars=100, prompt_tokens=1000) == 1.5  # nunca abaixo do piso


def test_the_calibration_discounts_the_images_from_the_prompt_tokens():
    assert calibrated_chars_per_token(sent_chars=3000, prompt_tokens=IMAGE_TOKENS + 1500, images=1) == 2.0
    assert calibrated_chars_per_token(sent_chars=3000, prompt_tokens=IMAGE_TOKENS - 5, images=1) == (
        DEFAULT_CHARS_PER_TOKEN
    )


@pytest.mark.parametrize("chars_per_token", [2.0, 3.0, 4.0])
def test_a_measured_density_changes_what_fits(chars_per_token):
    messages = long_turns(4, size=2000)

    result = trim_history(messages, 4096, chars_per_token=chars_per_token)

    assert result.estimated_tokens <= result.budget_tokens or len(turn_starts(result.messages)) == 1


# ---------- reparo de uma conversa cortada no meio ----------


def test_a_tool_call_without_its_result_gets_one_that_says_what_happened():
    cut = [user("renderiza"), tool_turn("render_project", "")[0]]

    repaired = repair_history(cut)

    assert repaired[-1] == {"role": "tool", "tool_name": "render_project", "content": INTERRUPTED_TOOL_RESULT}
    assert repaired[:-1] == cut


def test_a_batch_with_only_some_results_is_completed_in_order():
    calls = [{"function": {"name": "a", "arguments": {}}}, {"function": {"name": "b", "arguments": {}}}]
    cut = [
        user("faz"),
        {"role": "assistant", "content": "", "tool_calls": calls},
        {"role": "tool", "tool_name": "a", "content": "ok"},
    ]

    repaired = repair_history(cut)

    assert [m.get("tool_name") for m in repaired[2:]] == ["a", "b"]
    assert repaired[-1]["content"] == INTERRUPTED_TOOL_RESULT


def test_a_healthy_history_is_returned_unchanged():
    healthy = [user("oi"), *tool_turn("presets", "lista"), assistant("pronto")]

    assert repair_history(healthy) == healthy
    assert repair_history([]) == []
