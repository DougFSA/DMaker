"""Os dois motores do agente (Ollama e compatível com a OpenAI) e a configuração, contra um servidor HTTP falso local."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dmaker.agent.llm import OllamaChat, ToolCall
from dmaker.agent.openai_chat import DEFAULT_OPENAI_URL, OpenAICompatibleChat, to_openai_messages
from dmaker.agent.settings import (
    DEFAULT_MODEL,
    AgentSettings,
    SettingsError,
    build_chat,
    load_settings,
)

# ---------- conversão de mensagens ----------


def test_messages_become_openai_messages_with_paired_tool_call_ids():
    history = [
        {"role": "system", "content": "regras"},
        {"role": "user", "content": "valida o x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "validate_project", "arguments": {"name_or_path": "x"}}},
                {"function": {"name": "presets", "arguments": {}}},
            ],
        },
        {"role": "tool", "tool_name": "validate_project", "content": "ok"},
        {"role": "tool", "tool_name": "presets", "content": "lista"},
        {"role": "assistant", "content": "pronto"},
    ]

    converted = to_openai_messages(history)

    calls = converted[2]["tool_calls"]
    assert [call["id"] for call in calls] == ["call_1", "call_2"]
    assert calls[0]["type"] == "function"
    assert json.loads(calls[0]["function"]["arguments"]) == {"name_or_path": "x"}
    assert converted[3] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    assert converted[4] == {"role": "tool", "tool_call_id": "call_2", "content": "lista"}
    assert converted[5] == {"role": "assistant", "content": "pronto"}


def test_a_second_round_of_tool_calls_gets_new_ids():
    history = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "a", "arguments": {}}}]},
        {"role": "tool", "tool_name": "a", "content": "1"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "b", "arguments": {}}}]},
        {"role": "tool", "tool_name": "b", "content": "2"},
    ]

    converted = to_openai_messages(history)

    assert converted[2]["tool_calls"][0]["id"] == "call_2" and converted[3]["tool_call_id"] == "call_2"


# ---------- servidor falso ----------


class FakeOpenAIServer:
    """Um servidor compatível com a OpenAI na própria máquina: guarda o que recebeu e devolve respostas prontas."""

    def __init__(self, models: list[str], reply: dict):
        self.requests: list[tuple[str, str, dict | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, payload: dict) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802 - nome fixo do http.server
                outer.requests.append(("GET", self.path, None))
                self._send({"data": [{"id": name} for name in models]})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                outer.requests.append(("POST", self.path, body))
                self._send(reply)

            def log_message(self, *args):  # silencia o log do servidor de teste
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FakeOpenAIServer:
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.shutdown()
        self._server.server_close()


def tool_call_reply() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "preciso validar",
                    "tool_calls": [
                        {
                            "id": "abc",
                            "type": "function",
                            "function": {
                                "name": "validate_project",
                                "arguments": '{"name_or_path": "meu-video"}',
                            },
                        }
                    ],
                }
            }
        ]
    }


def test_openai_usage_becomes_prompt_and_completion_tokens():
    reply = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 4100, "completion_tokens": 9},
    }
    with FakeOpenAIServer([], reply) as server:
        result = OpenAICompatibleChat(model="m", base_url=server.url, timeout=5).chat([], [])

    assert (result.prompt_tokens, result.completion_tokens) == (4100, 9)


def test_chat_posts_to_the_chat_completions_route_and_parses_tool_calls():
    with FakeOpenAIServer(["qualquer"], tool_call_reply()) as server:
        chat = OpenAICompatibleChat(model="qualquer", base_url=server.url, timeout=5)
        reply = chat.chat(
            [{"role": "user", "content": "valida"}],
            [
                {
                    "type": "function",
                    "function": {"name": "validate_project", "description": "d", "parameters": {}},
                }
            ],
        )

    assert reply.tool_calls == [ToolCall("validate_project", {"name_or_path": "meu-video"})]
    assert reply.content == "" and reply.thinking == "preciso validar"
    method, path, body = server.requests[0]
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert body["model"] == "qualquer" and body["stream"] is False
    assert body["messages"] == [{"role": "user", "content": "valida"}]
    assert body["tools"][0]["function"]["name"] == "validate_project"


def test_chat_returns_plain_text_and_omits_tools_when_there_are_none():
    reply = {"choices": [{"message": {"role": "assistant", "content": "Olá!"}}]}
    with FakeOpenAIServer([], reply) as server:
        result = OpenAICompatibleChat(model="m", base_url=server.url, timeout=5).chat(
            [{"role": "user", "content": "oi"}], []
        )

    assert result.content == "Olá!" and result.tool_calls == []
    assert "tools" not in server.requests[0][2]


def test_chat_accepts_content_given_as_a_list_of_parts():
    reply = {
        "choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]
    }
    with FakeOpenAIServer([], reply) as server:
        result = OpenAICompatibleChat(model="m", base_url=server.url, timeout=5).chat([], [])

    assert result.content == "ab"


def test_health_checks_use_the_models_route():
    with FakeOpenAIServer(["meu-modelo"], {}) as server:
        assert OpenAICompatibleChat(model="meu-modelo", base_url=server.url).is_alive() is True
        assert OpenAICompatibleChat(model="meu-modelo", base_url=server.url).has_model() is True
        assert OpenAICompatibleChat(model="outro", base_url=server.url).has_model() is False
        assert OpenAICompatibleChat(model="x", base_url=server.url).served_models() == ["meu-modelo"]


def test_health_checks_report_a_server_that_is_down_without_raising():
    chat = OpenAICompatibleChat(model="m", base_url="http://127.0.0.1:1")  # nada escuta na porta 1

    assert chat.is_alive() is False and chat.has_model() is False and chat.served_models() == []


def test_the_api_key_goes_in_the_authorization_header_only_when_set():
    seen = {}

    class Opener:
        def __call__(self, req, timeout=None):
            seen["auth"] = req.get_header("Authorization")
            raise OSError("fim")

    with pytest.raises(OSError):
        OpenAICompatibleChat(model="m", api_key="segredo", opener=Opener()).chat([], [])
    assert seen["auth"] == "Bearer segredo"


# ---------- configuração ----------


def test_defaults_come_from_the_code_only_when_nothing_is_configured():
    settings = load_settings(env={})

    assert settings == AgentSettings(engine="ollama", model=DEFAULT_MODEL)
    assert settings.url == "http://127.0.0.1:11434" and settings.free_html is False


def test_environment_variables_choose_engine_model_and_address():
    env = {
        "DMAKER_AGENT_ENGINE": "openai",
        "DMAKER_AGENT_MODEL": "qwen-pequeno",
        "DMAKER_AGENT_URL": "http://127.0.0.1:1234",
        "DMAKER_AGENT_NUM_CTX": "8192",
        "DMAKER_AGENT_TIMEOUT": "60",
        "DMAKER_AGENT_FREE_HTML": "sim",
    }

    settings = load_settings(env=env)

    assert (settings.engine, settings.model, settings.url) == (
        "openai",
        "qwen-pequeno",
        "http://127.0.0.1:1234",
    )
    assert settings.num_ctx == 8192 and settings.timeout == 60.0 and settings.free_html is True


def test_command_line_options_win_over_the_environment_and_none_does_not_count():
    env = {"DMAKER_AGENT_MODEL": "do-ambiente", "DMAKER_AGENT_ENGINE": "ollama"}

    settings = load_settings(env=env, model="da-linha", engine=None, url=None)

    assert settings.model == "da-linha" and settings.engine == "ollama"


def test_switching_the_engine_does_not_inherit_the_other_engines_address():
    assert (
        load_settings(env={"DMAKER_OLLAMA_URL": "http://10.0.0.5:11434"}, engine="openai").url
        == DEFAULT_OPENAI_URL
    )
    assert (
        load_settings(env={"DMAKER_AGENT_ENGINE": "openai"}, engine="ollama").url == "http://127.0.0.1:11434"
    )


def test_the_reasoning_effort_is_optional_validated_and_passed_to_ollama_only():
    assert load_settings(env={}).think is None
    settings = load_settings(env={"DMAKER_AGENT_THINK": " Low "})

    assert settings.think == "low"
    assert build_chat(settings).think == "low"
    with pytest.raises(SettingsError, match="DMAKER_AGENT_THINK"):
        load_settings(env={"DMAKER_AGENT_THINK": "enorme"})


def test_the_ollama_address_variable_the_project_already_used_still_works():
    assert load_settings(env={"DMAKER_OLLAMA_URL": "http://10.0.0.5:11434"}).url == "http://10.0.0.5:11434"


def test_invalid_values_name_the_variable_to_fix():
    with pytest.raises(SettingsError, match="DMAKER_AGENT_ENGINE"):
        load_settings(env={"DMAKER_AGENT_ENGINE": "gpt"})
    with pytest.raises(SettingsError, match="DMAKER_AGENT_NUM_CTX"):
        load_settings(env={"DMAKER_AGENT_NUM_CTX": "muito"})


def test_build_chat_picks_the_engine_without_a_fixed_model_name():
    ollama = build_chat(AgentSettings(engine="ollama", model="m1", url="http://127.0.0.1:1", num_ctx=4096))
    openai = build_chat(AgentSettings(engine="openai", model="m2", url="http://127.0.0.1:2"))

    assert isinstance(ollama, OllamaChat) and ollama.model == "m1" and ollama.num_ctx == 4096
    assert (
        isinstance(openai, OpenAICompatibleChat) and openai.model == "m2" and openai.base_url.endswith(":2")
    )
