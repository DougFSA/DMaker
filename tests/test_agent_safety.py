"""Proteções do agente local: esquema da ferramenta, caminho inventado e confirmação do usuário."""

from __future__ import annotations

import json

from dmaker.agent.llm import Reply, ToolCall
from dmaker.agent.loop import AgentLoop
from dmaker.agent.safety import (
    CONFIRMATION_RULES,
    ApproveAll,
    ConfirmationRequest,
    DenyAll,
    KnownPaths,
    ToolGate,
    ask_user_about_paths,
    input_paths,
    looks_like_file_path,
    missing_paths,
    validate_arguments,
)
from dmaker.agent.tools import ToolSpec

SCHEMA = {
    "type": "object",
    "properties": {
        "name_or_path": {"type": "string"},
        "preview": {"type": "boolean", "default": False},
        "intensity": {"enum": ["suave", "normal", "agressiva"]},
        "cut_id": {"type": "integer"},
        "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    },
    "required": ["name_or_path"],
}


# ---------- esquema ----------


def test_valid_arguments_have_no_problems():
    assert validate_arguments(SCHEMA, {"name_or_path": "meu-video", "preview": True, "limit": None}) == []


def test_missing_required_argument_is_said_in_simple_portuguese():
    problems = validate_arguments(SCHEMA, {})

    assert problems == ["falta o argumento 'name_or_path'"]


def test_wrong_type_says_what_was_expected_and_what_came():
    problems = validate_arguments(SCHEMA, {"name_or_path": "x", "preview": "sim", "cut_id": 2.5})

    assert "o argumento 'preview' deve ser sim ou não (true ou false), mas veio texto" in problems
    assert any("'cut_id' deve ser número inteiro" in problem for problem in problems)


def test_value_outside_the_allowed_list_names_the_options():
    problems = validate_arguments(SCHEMA, {"name_or_path": "x", "intensity": "forte"})

    assert problems == ["o argumento 'intensity' deve ser um destes valores: suave, normal, agressiva"]


def test_unknown_argument_lists_the_accepted_ones():
    problems = validate_arguments(SCHEMA, {"name_or_path": "x", "projeto": "y"})

    assert problems and "'projeto' não existe nesta ferramenta" in problems[0] and "cut_id" in problems[0]


def test_union_type_error_is_not_a_json_schema_dump():
    problems = validate_arguments(SCHEMA, {"name_or_path": "x", "limit": "dez"})

    assert problems == ["o argumento 'limit' tem um tipo que a ferramenta não aceita"]


# ---------- caminhos ----------


def test_looks_like_file_path_accepts_drives_absolute_paths_and_media_extensions_only():
    assert looks_like_file_path("C:/videos/a.mp4") and looks_like_file_path("D:\\x\\y")
    assert looks_like_file_path("/home/a") and looks_like_file_path("gravacao.mp4")
    assert not looks_like_file_path("Bem-vindo ao DMaker.") and not looks_like_file_path("dora")


def test_input_paths_reads_path_arguments_and_files_inside_params():
    found = input_paths(
        {
            "src": "C:/a.mp4",
            "paths": ["C:/b.mp4", "C:/c.png"],
            "params": {"titulo": "Olá", "print": "prints/x.png", "nomes": ["Ana & Carlos"]},
            "name": "projeto",
        }
    )

    assert found == ["C:/a.mp4", "C:/b.mp4", "C:/c.png", "prints/x.png"]


def test_structured_arguments_only_count_src_and_absolute_paths():
    found = input_paths({"op": {"type": "insert", "segment": {"src": "foto.png", "text": "ver notas.txt"}}})

    assert found == ["foto.png"]


def test_missing_paths_ignores_what_exists_and_what_the_user_or_a_tool_already_wrote():
    known = KnownPaths()
    known.remember("o vídeo está em D:\\Videos\\Aula.mp4")
    known.remember('{"files": ["C:\\\\saidas\\\\pronto.mp4"]}')
    exists = {"C:/real.mp4"}.__contains__

    absent = missing_paths(
        {"paths": ["C:/real.mp4", "d:/videos/aula.mp4", "C:/saidas/pronto.mp4", "C:/inventado.mp4"]},
        exists,
        known,
    )

    assert absent == ["C:/inventado.mp4"]


def test_the_message_for_an_invented_path_tells_the_model_to_ask_the_user():
    text = ask_user_about_paths(["C:/inventado.mp4"])

    assert text.startswith("erro:") and "pergunte ao usuário" in text and "C:/inventado.mp4" in text


# ---------- confirmação ----------


def gate(policy=None, existing=(), projects=(), schemas=None):
    return ToolGate(
        schemas=schemas or {},
        policy=policy or DenyAll(),
        exists=set(existing).__contains__,
        project_exists=set(projects).__contains__,
    )


def test_preview_render_goes_through_but_the_final_render_asks_first():
    asked = ApproveAll()
    g = gate(asked)

    assert g.check("render_project", {"name_or_path": "x", "preview": True}) is None
    assert asked.asked == []
    assert g.check("render_project", {"name_or_path": "x"}) is None
    assert [r.tool for r in asked.asked] == ["render_project"]


def test_a_refused_confirmation_blocks_the_call_and_tells_the_model_not_to_retry():
    text = gate(DenyAll()).check("render_project", {"name_or_path": "x"})

    assert text is not None and "não autorizou" in text and "Não execute esta ação" in text


def test_every_confirmation_rule_has_a_reason_and_the_expected_tools_are_listed():
    assert all(rule.reason for rule in CONFIRMATION_RULES)
    listed = {rule.tool for rule in CONFIRMATION_RULES}
    assert {
        "render_project",
        "export_project",
        "quick_edit",
        "dub_render",
        "clone_voice",
        "run_batch",
    } <= listed


def test_an_existing_project_name_asks_before_overwriting():
    asked = ApproveAll()
    g = gate(asked, projects={"meu-video"})

    g.check("new_from_template", {"template": "t", "name": "meu-video", "params": {}})
    g.check("new_from_template", {"template": "t", "name": "novo", "params": {}})

    assert len(asked.asked) == 1 and "já existe" in asked.asked[0].question


def test_an_existing_output_file_asks_before_overwriting():
    asked = ApproveAll()
    g = gate(asked, existing={"C:/saida.wav"})

    g.check("synthesize_speech", {"text": "oi", "out": "C:/saida.wav"})
    g.check("synthesize_speech", {"text": "oi", "out": "C:/nova.wav"})

    assert len(asked.asked) == 1 and "C:/saida.wav" in asked.asked[0].question


def test_removing_content_and_pronunciations_asks_but_editing_does_not():
    asked = ApproveAll()
    g = gate(asked)

    g.check("edit_project", {"name": "x", "op": {"type": "set_field", "path": "a", "value": 1}})
    g.check("edit_project", {"name": "x", "op": {"type": "remove", "index": 0}})
    g.check("edit_project", {"name": "x", "op": {"type": "overlay_remove", "index": 0}})
    g.check("pronunciation", {"action": "remove", "term": "x"})
    g.check("pronunciation", {"action": "list"})

    assert [r.tool for r in asked.asked] == ["edit_project", "edit_project", "pronunciation"]


def test_autocut_asks_only_when_it_will_overwrite():
    asked = ApproveAll()
    g = gate(asked, existing={"a.mp4"})

    g.check("autocut", {"source": "a.mp4", "name": "x"})
    g.check("autocut", {"source": "a.mp4", "name": "x", "overwrite": True})

    assert len(asked.asked) == 1


def test_cloning_a_voice_needs_the_explicit_authorization_of_the_owner():
    class Spy:
        def __init__(self):
            self.requests: list[ConfirmationRequest] = []

        def confirm(self, request):
            self.requests.append(request)
            return False

    spy = Spy()
    text = gate(spy, existing={"C:/v.wav"}).check(
        "clone_voice", {"name": "joao", "reference_audio": "C:/v.wav"}
    )

    assert text is not None and "não autorizou" in text
    assert spy.requests[0].kind == "voice_consent"
    assert "autorizou o uso" in spy.requests[0].question and "joao" in spy.requests[0].question


def test_the_gate_checks_schema_then_paths_then_confirmation_in_that_order():
    asked = ApproveAll()
    g = gate(
        asked,
        schemas={
            "render_project": {
                "type": "object",
                "properties": {"name_or_path": {}},
                "required": ["name_or_path"],
            }
        },
    )

    assert "falta o argumento 'name_or_path'" in g.check("render_project", {})
    assert asked.asked == []
    assert "pergunte ao usuário" in g.check("probe_media", {"paths": ["C:/inventado.mp4"]})


# ---------- no loop ----------


class Script:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools):
        return self.replies.pop(0)


class Host:
    def __init__(self):
        self.calls = []

    def specs(self):
        return [
            ToolSpec(
                "render_project",
                "r",
                {
                    "type": "object",
                    "properties": {"name_or_path": {"type": "string"}, "preview": {"type": "boolean"}},
                    "required": ["name_or_path"],
                },
            )
        ]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return "feito"


def run(policy, arguments):
    host = Host()
    events = []
    loop = AgentLoop(
        model=Script([Reply("", [ToolCall("render_project", arguments)]), Reply("fim")]),
        tools=host,
        system="s",
        on_event=lambda kind, data: events.append((kind, data)),
        gate=ToolGate(schemas={}, policy=policy),
    )
    loop.ask("renderiza o x")
    return host, events, loop


def test_the_loop_never_runs_a_refused_tool_and_reports_it_as_an_event():
    host, events, loop = run(DenyAll(), {"name_or_path": "x"})

    assert host.calls == []
    assert [kind for kind, _ in events if kind == "tool_blocked"] == ["tool_blocked"]
    tool_message = next(m for m in loop._messages if m["role"] == "tool")
    assert "não autorizou" in tool_message["content"]


def test_the_loop_runs_the_tool_once_the_user_approves():
    host, _, _ = run(ApproveAll(), {"name_or_path": "x"})

    assert host.calls == [("render_project", {"name_or_path": "x"})]


def test_the_loop_returns_schema_errors_to_the_model_instead_of_calling():
    host, _, loop = run(ApproveAll(), {"preview": True})

    assert host.calls == []
    tool_message = next(m for m in loop._messages if m["role"] == "tool")
    assert "falta o argumento 'name_or_path'" in tool_message["content"]


class ListingHost:
    """Devolve um texto com o caminho de um arquivo, como `list_projects` ou o fim de um render fariam."""

    def __init__(self):
        self.calls = []

    def specs(self):
        return [ToolSpec("probe_media", "p", {"type": "object", "properties": {"paths": {"type": "array"}}})]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return json.dumps({"output": "C:\\saidas\\pronto.mp4"})


def test_a_path_that_a_previous_tool_listed_is_not_treated_as_invented():
    host = ListingHost()
    loop = AgentLoop(
        model=Script(
            [
                Reply("", [ToolCall("probe_media", {"paths": []})]),
                Reply("", [ToolCall("probe_media", {"paths": ["C:/saidas/pronto.mp4"]})]),
                Reply("", [ToolCall("probe_media", {"paths": ["C:/outra/inventada.mp4"]})]),
                Reply("fim"),
            ]
        ),
        tools=host,
        system="s",
        gate=ToolGate(schemas={}, policy=ApproveAll()),
    )

    loop.ask("vê o que tem aí")

    assert [arguments["paths"] for _, arguments in host.calls] == [[], ["C:/saidas/pronto.mp4"]]
    last_tool_message = [m for m in loop._messages if m["role"] == "tool"][-1]
    assert "pergunte ao usuário" in last_tool_message["content"]
