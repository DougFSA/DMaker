"""Agente local (Ollama + ferramentas MCP em processo): tudo com dublês, nunca contra um Ollama real."""

from __future__ import annotations

import json

import pytest

from dmaker.agent.llm import OllamaChat, Reply, ToolCall, _normalize_model_name
from dmaker.agent.loop import GIVE_UP_WARNING, AgentLoop
from dmaker.agent.prompt import ESSENTIAL_RULES, system_prompt, task_prompt
from dmaker.agent.tools import AGENT_TOOLS, McpToolHost, ToolSpec, to_ollama_tools, truncate_result

# ---------- OllamaChat ----------


class FakeResponse:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return self._data


class FakeOpener:
    """Dublê de `urllib.request.urlopen`: grava a requisição e devolve uma resposta programada."""

    def __init__(self, payload: dict | None = None, raises: Exception | None = None):
        self.payload = payload or {}
        self.raises = raises
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        if self.raises is not None:
            raise self.raises
        return FakeResponse(self.payload)


def test_chat_sends_model_tools_stream_false_and_num_ctx():
    opener = FakeOpener({"message": {"role": "assistant", "content": "oi", "tool_calls": []}})
    chat = OllamaChat(model="gpt-oss:20b", opener=opener, num_ctx=8192)

    reply = chat.chat([{"role": "user", "content": "oi"}], tools=[{"type": "function"}])

    assert reply == Reply(content="oi", tool_calls=[], thinking=None)
    req, timeout = opener.requests[0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "gpt-oss:20b"
    assert body["tools"] == [{"type": "function"}]
    assert body["stream"] is False
    assert body["options"] == {"num_ctx": 8192}
    assert body["keep_alive"] == "60m"  # ferramentas longas não podem descarregar o modelo
    assert req.get_full_url().endswith("/api/chat")
    assert timeout == chat.timeout


def test_chat_parses_tool_calls_with_dict_arguments():
    opener = FakeOpener(
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "presets", "arguments": {"platform": "instagram"}}}],
            }
        }
    )
    chat = OllamaChat(model="gpt-oss:20b", opener=opener)

    reply = chat.chat([], [])

    assert reply.tool_calls == [ToolCall(name="presets", arguments={"platform": "instagram"})]


def test_chat_parses_tool_calls_with_string_arguments():
    opener = FakeOpener(
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "presets", "arguments": '{"platform": "instagram"}'}}],
            }
        }
    )
    chat = OllamaChat(model="gpt-oss:20b", opener=opener)

    reply = chat.chat([], [])

    assert reply.tool_calls == [ToolCall(name="presets", arguments={"platform": "instagram"})]


def test_chat_captures_thinking_when_present():
    opener = FakeOpener({"message": {"content": "pronto", "thinking": "planejando...", "tool_calls": []}})
    chat = OllamaChat(model="gpt-oss:20b", opener=opener)

    reply = chat.chat([], [])

    assert reply.thinking == "planejando..."


def test_normalize_model_name_strips_only_latest_tag():
    assert _normalize_model_name("gpt-oss:20b") == "gpt-oss:20b"
    assert _normalize_model_name("gpt-oss:latest") == "gpt-oss"
    assert _normalize_model_name("gpt-oss") == "gpt-oss"


def test_has_model_matches_with_and_without_latest_tag():
    opener = FakeOpener({"models": [{"name": "gpt-oss:latest"}, {"name": "llama3:8b"}]})
    assert OllamaChat(model="gpt-oss", opener=opener).has_model() is True
    assert OllamaChat(model="gpt-oss:latest", opener=opener).has_model() is True
    assert OllamaChat(model="llama3:8b", opener=opener).has_model() is True
    assert OllamaChat(model="llama3:70b", opener=opener).has_model() is False


def test_is_alive_false_when_connection_fails():
    opener = FakeOpener(raises=OSError("conexão recusada"))
    chat = OllamaChat(model="gpt-oss:20b", opener=opener)

    assert chat.is_alive() is False
    assert chat.has_model() is False


def test_is_alive_true_when_tags_responds():
    opener = FakeOpener({"models": []})
    assert OllamaChat(model="gpt-oss:20b", opener=opener).is_alive() is True


# ---------- McpToolHost (servidor MCP real, em processo) ----------


def test_specs_only_include_agent_tools_and_have_valid_parameters():
    host = McpToolHost()
    specs = host.specs()

    # os kits podem citar ferramentas que o servidor ainda não tem: o host entrega só as que existem
    assert {s.name for s in specs} <= set(AGENT_TOOLS)
    assert {"quick_edit", "narrate_into_project", "dub_prepare", "autocut"} <= {s.name for s in specs}
    for spec in specs:
        assert isinstance(spec, ToolSpec)
        assert spec.description
        assert spec.parameters.get("type") == "object"


def test_call_presets_returns_text():
    host = McpToolHost()

    text = host.call("presets", {})

    assert "instagram/reels" in text


def test_call_unknown_tool_becomes_error_text_not_exception():
    host = McpToolHost()

    text = host.call("nao_existe", {})

    assert text.startswith("erro:")


def test_call_tool_outside_allowed_list_is_blocked():
    host = McpToolHost()

    text = host.call("clean_cache", {})  # excluída dos kits: apagaria o cache de um render em andamento

    assert text.startswith("erro:") and "clean_cache" in text


def test_call_get_project_missing_project_becomes_error_text():
    host = McpToolHost()

    text = host.call("get_project", {"name_or_path": "projeto-inexistente-xyz"})

    assert text.startswith("erro:")


def test_host_accepts_custom_allowed_subset():
    host = McpToolHost(allowed=["presets", "brands"])

    assert {s.name for s in host.specs()} == {"presets", "brands"}
    assert host.call("list_templates", {}).startswith("erro:")


def test_to_ollama_tools_is_pure_conversion():
    specs = [ToolSpec(name="presets", description="descrição", parameters={"type": "object"})]

    tools = to_ollama_tools(specs)

    assert tools == [
        {
            "type": "function",
            "function": {"name": "presets", "description": "descrição", "parameters": {"type": "object"}},
        }
    ]


# ---------- truncate_result ----------


def test_truncate_result_leaves_short_text_untouched():
    assert truncate_result("abc", limit=10) == "abc"


def test_truncate_result_cuts_the_middle_with_warning():
    text = "a" * 5000 + "b" * 5000
    out = truncate_result(text, limit=100)

    assert len(out) < len(text)
    assert out.startswith("a" * 10)
    assert out.endswith("b" * 10)
    assert "cortado" in out
    assert "9900 caracteres" in out


# ---------- system_prompt ----------


def test_system_prompt_is_the_essential_rules_plus_the_manual_of_each_kit():
    manuals = {
        "agente-editing": "# Kit Edição\n\nCorpo do kit de edição.",
        "agente-voice": "# Kit Voz\n\nCorpo da voz.",
    }

    prompt = system_prompt(["editing", "voice"], manual_loader=manuals.get)

    assert prompt.startswith(ESSENTIAL_RULES.strip())
    assert prompt.index("Corpo do kit de edição.") < prompt.index("Corpo da voz.")
    assert "português do Brasil" in prompt and "pergunte ao usuário" in prompt


def test_system_prompt_without_the_kit_file_falls_back_to_the_kit_description():
    prompt = system_prompt(["batch"], manual_loader=lambda name: None)

    assert "# Kit Lote" in prompt and "planilha" in prompt


def test_system_prompt_accepts_custom_extra_rules():
    prompt = system_prompt(["batch"], manual_loader=lambda name: None, extra_rules="## Regra\n\nSó isso.")

    assert "Só isso." in prompt
    assert "português do Brasil" not in prompt


def test_default_system_prompt_uses_the_generated_kit_manual_and_is_dash_free():
    prompt = system_prompt(["multicam"])

    assert "—" not in prompt and "–" not in prompt
    assert "casamento-pascom" in prompt and "plan_multicam" in prompt
    assert "camera_altar" in prompt and "camera_lateral" in prompt


def test_the_biggest_kit_prompt_leaves_room_in_a_16k_context():
    """Regras mais manual do kit ficam em cerca de 2 mil tokens; as ferramentas somam outros 3 a 4 mil. Medido com
    o modelo real, o maior histórico de um pedido da bateria foi de uns 7 mil tokens."""
    from dmaker.agent.kits import KITS
    from dmaker.manual.ia_docs import estimate_tokens

    for kit in KITS:
        assert estimate_tokens(system_prompt([kit.name])) <= 2600, kit.name


def test_task_prompt_is_the_rules_plus_the_task_file():
    prompt = task_prompt("# Tarefa X\n\nPasso a passo.")

    assert prompt.startswith(ESSENTIAL_RULES.strip())
    assert "## Manual da tarefa" in prompt and "Passo a passo." in prompt


# ---------- AgentLoop ----------


class ScriptedModel:
    """Dublê de `ChatModel`: devolve as respostas de `script`, uma por chamada de `chat`."""

    def __init__(self, script: list[Reply]):
        self.script = list(script)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def chat(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        return self.script.pop(0)


class FakeToolHost:
    def __init__(self, call_result: str = "ok", raises: Exception | None = None):
        self.call_result = call_result
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    def specs(self):
        return [ToolSpec(name="presets", description="presets", parameters={"type": "object"})]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.raises is not None:
            raise self.raises
        return self.call_result


def test_ask_without_tool_calls_returns_content_directly():
    model = ScriptedModel([Reply(content="tudo pronto", tool_calls=[])])
    events = []
    loop = AgentLoop(
        model=model, tools=FakeToolHost(), system="sistema", on_event=lambda k, d: events.append((k, d))
    )

    answer = loop.ask("oi")

    assert answer == "tudo pronto"
    assert ("answer", {"text": "tudo pronto"}) in events


def test_ask_runs_tool_call_then_answers_and_keeps_message_order():
    model = ScriptedModel(
        [
            Reply(content="", tool_calls=[ToolCall(name="presets", arguments={"platform": "instagram"})]),
            Reply(content="pronto, veja os presets", tool_calls=[]),
        ]
    )
    tools = FakeToolHost(call_result="lista de presets")
    events = []
    loop = AgentLoop(model=model, tools=tools, system="sistema", on_event=lambda k, d: events.append((k, d)))

    answer = loop.ask("quais presets existem?")

    assert answer == "pronto, veja os presets"
    assert tools.calls == [("presets", {"platform": "instagram"})]

    roles = [m["role"] for m in loop._messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert loop._messages[3] == {"role": "tool", "tool_name": "presets", "content": "lista de presets"}

    kinds = [kind for kind, _ in events if kind != "model_reply"]
    assert kinds == ["tool_call", "tool_result", "answer"]
    assert [kind for kind, _ in events].count("model_reply") == 2
    assert loop.steps_taken == 2


def test_tool_error_becomes_tool_message_content_not_exception():
    model = ScriptedModel(
        [
            Reply(content="", tool_calls=[ToolCall(name="presets", arguments={})]),
            Reply(content="corrigido", tool_calls=[]),
        ]
    )
    tools = FakeToolHost(raises=RuntimeError("ferramenta explodiu"))
    loop = AgentLoop(model=model, tools=tools, system="sistema")

    answer = loop.ask("faça algo")

    assert answer == "corrigido"
    tool_message = next(m for m in loop._messages if m["role"] == "tool")
    assert "erro" in tool_message["content"] and "ferramenta explodiu" in tool_message["content"]


def test_max_steps_gives_up_with_a_warning_instead_of_looping_forever():
    infinite_tool_calls = Reply(content="", tool_calls=[ToolCall(name="presets", arguments={})])
    model = ScriptedModel([infinite_tool_calls] * 3)
    loop = AgentLoop(model=model, tools=FakeToolHost(), system="sistema", max_steps=3)

    answer = loop.ask("nunca termina")

    assert answer == GIVE_UP_WARNING
    assert len(model.calls) == 3


def test_reset_clears_history_back_to_system_message():
    model = ScriptedModel([Reply(content="ok", tool_calls=[])])
    loop = AgentLoop(model=model, tools=FakeToolHost(), system="sistema")
    loop.ask("oi")

    loop.reset()

    assert loop._messages == [{"role": "system", "content": "sistema"}]


def test_ollama_chat_and_mcp_host_are_valid_chat_model_and_tool_host_protocols():
    # Confere a integração real (specs -> to_ollama_tools) sem depender de um Ollama de verdade.
    host = McpToolHost()
    tools = to_ollama_tools(host.specs())
    assert all(t["type"] == "function" for t in tools)


def test_chat_reports_how_many_prompt_tokens_the_server_read():
    opener = FakeOpener({"message": {"content": "oi"}, "prompt_eval_count": 5400, "eval_count": 37})

    reply = OllamaChat(model="m", opener=opener).chat([], [])

    assert (reply.prompt_tokens, reply.completion_tokens) == (5400, 37)


def test_the_model_reply_event_carries_the_token_usage():
    model = ScriptedModel([Reply(content="ok", prompt_tokens=7000, completion_tokens=12)])
    events = []
    loop = AgentLoop(
        model=model, tools=FakeToolHost(), system="s", on_event=lambda k, d: events.append((k, d))
    )

    loop.ask("oi")

    data = next(d for k, d in events if k == "model_reply")
    assert data["prompt_tokens"] == 7000 and data["completion_tokens"] == 12


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
