"""O manual curto de cada kit do agente local: montado das tarefas do manual, com limite de tokens."""

from __future__ import annotations

import pytest

from dmaker.agent.kits import KITS, Kit
from dmaker.manual import files, live
from dmaker.manual.build import BuildInputs, ManualBuildError, build_all, find_problems
from dmaker.manual.examples import parse_calls
from dmaker.manual.ia_docs import estimate_tokens
from dmaker.manual.kit_manuals import (
    EXAMPLES_PER_KIT,
    KIT_FILE_PREFIX,
    KIT_MAX_TOKENS,
    build_kit_manuals,
    example_requests,
    kit_file_name,
    kit_manual,
    oversize_kits,
)
from dmaker.manual.outline import parse_manual
from dmaker.manual.reference_mcp import ToolDoc

from .manual_support import SAMPLE_MANUAL, fake_cli_root, fake_tools


def sample_kit(**changes) -> Kit:
    base = dict(
        name="editing",
        title="Edição",
        description="Editar e renderizar.",
        tools=("quick_edit", "ferramenta_futura"),
        keywords=("reel",),
        tasks=("reel", "dublar", "nao-existe"),
    )
    base.update(changes)
    return Kit(**base)


@pytest.fixture(scope="module")
def parsed():
    manual = parse_manual(SAMPLE_MANUAL)
    problems, calls = find_problems(
        SAMPLE_MANUAL,
        BuildInputs(cli_root=fake_cli_root(), tools=fake_tools(), spec_schema={}, agent_tools=()),
    )
    assert problems == []
    return manual, calls, {tool.name: tool for tool in fake_tools()}


def test_example_requests_come_from_the_task_quando_usar_part(parsed):
    manual, _, _ = parsed

    assert example_requests(manual.task("reel")) == ["Faz um reel desse vídeo"]
    assert example_requests(manual.task("dublar")) == []


def test_the_kit_manual_lists_only_the_tools_the_server_has_and_the_task_calls(parsed):
    manual, calls, tools = parsed

    text = kit_manual(sample_kit(), {t.id: t for t in manual.tasks}, calls, tools)

    assert text.startswith("# Kit Edição\n")
    assert "`probe_media`" in text and "`quick_edit`" in text and "ferramenta_futura" not in text
    assert '### Pedido: "Faz um reel desse vídeo"' in text
    assert "1. `probe_media`: ver a duração" in text
    assert '`{"src": "C:/videos/a.mp4", "captions": true}`' in text
    assert "Pergunte antes, se faltar:" in text and "O arquivo de vídeo." in text


def test_a_task_without_a_request_example_is_titled_by_the_task(parsed):
    manual, calls, tools = parsed

    text = kit_manual(sample_kit(tasks=("dublar",)), {t.id: t for t in manual.tasks}, calls, tools)

    assert "### Tarefa: Dublar um vídeo" in text


def test_a_kit_never_shows_more_than_three_examples(parsed):
    manual, calls, tools = parsed
    many = {f"t{i}": manual.task("reel") for i in range(6)}
    many_calls = {f"t{i}": calls["reel"] for i in range(6)}
    kit = sample_kit(tasks=tuple(many))

    text = kit_manual(kit, many, many_calls, tools)

    assert text.count("### Pedido:") == EXAMPLES_PER_KIT == 3


def test_a_kit_with_no_tool_on_the_server_says_the_function_does_not_exist_yet(parsed):
    manual, calls, tools = parsed

    text = kit_manual(sample_kit(tools=("so_no_futuro",), tasks=()), {}, calls, {})

    assert "ainda não tem nenhuma ferramenta deste kit" in text and "Sem exemplo para este kit" in text


def test_build_kit_manuals_names_one_file_per_kit(parsed):
    manual, calls, tools = parsed

    built = build_kit_manuals(
        [sample_kit(), sample_kit(name="voice", title="Voz")], manual.tasks, calls, tools
    )

    assert set(built) == {"agente-editing.md", "agente-voice.md"}
    assert kit_file_name(sample_kit()) == f"{KIT_FILE_PREFIX}editing.md"


def test_the_free_html_tools_never_appear_in_the_fixed_kit_manual(parsed):
    """O HTML livre só chega ao modelo com `DMAKER_AGENT_FREE_HTML`: o manual fixo do kit não pode ensiná-lo."""
    manual, calls, tools = parsed
    html_tool = ToolDoc("render_html_frame", "Fotografa uma composição em HTML.", {"type": "object"})
    with_html = {**tools, "render_html_frame": html_tool}

    text = kit_manual(sample_kit(tools=("quick_edit", "render_html_frame")), {}, calls, with_html)

    assert "render_html_frame" not in text and "`quick_edit`" in text


def test_oversize_kits_only_looks_at_kit_files():
    big = "palavra " * 3000

    assert set(oversize_kits({"agente-x.md": big, "reel.md": big, "agente-y.md": "curto"})) == {"agente-x.md"}


def test_build_all_adds_the_kit_manuals_and_is_idempotent():
    inputs = BuildInputs(
        cli_root=fake_cli_root(),
        tools=fake_tools(),
        spec_schema={},
        agent_tools=("probe_media",),
        kits=(sample_kit(),),
    )

    first = build_all(SAMPLE_MANUAL, inputs)
    again = build_all(first.manual, inputs)

    assert "agente-editing.md" in first.ia_files and first.ia_files == again.ia_files


def test_build_fails_when_a_kit_manual_passes_the_token_limit(monkeypatch):
    inputs = BuildInputs(
        cli_root=fake_cli_root(), tools=fake_tools(), spec_schema={}, agent_tools=(), kits=(sample_kit(),)
    )
    monkeypatch.setattr("dmaker.manual.build.oversize_kits", lambda kit_files: {"agente-editing.md": 99})

    with pytest.raises(
        ManualBuildError, match=r"agente-editing.md: ~99 tokens, acima do limite de \d+ de um kit"
    ):
        build_all(SAMPLE_MANUAL, inputs)


# ---------- o manual de verdade ----------


def test_the_real_kit_manuals_exist_and_fit_the_token_limit():
    ia_files = files.read_ia_files()
    for kit in KITS:
        name = kit_file_name(kit)
        assert name in ia_files, f"falta {name}: rode `dmaker manual build`"
        assert estimate_tokens(ia_files[name]) <= KIT_MAX_TOKENS, (
            f"{name}: {estimate_tokens(ia_files[name])} tokens"
        )


def test_every_real_kit_manual_example_is_a_call_the_server_accepts():
    """O manual do kit nasce das mesmas tarefas validadas contra o esquema; aqui só se confere que sobrou exemplo."""
    ia_files = files.read_ia_files()
    for kit in KITS:
        if kit.tasks:
            assert (
                "### Pedido:" in ia_files[kit_file_name(kit)] or "### Tarefa:" in ia_files[kit_file_name(kit)]
            )


def test_the_acceptance_requests_have_the_right_calls_in_the_kit_manuals():
    ia_files = files.read_ia_files()

    assert "`narrate_into_project`" in ia_files["agente-voice.md"]
    assert "`cut_pauses_and_caption`" in ia_files["agente-editing.md"]
    assert "`dub_prepare`" in ia_files["agente-dubbing.md"]
    assert "`quick_edit`" in ia_files["agente-editing.md"]
    assert "`add_infographic`" in ia_files["agente-compositions.md"]
    assert (
        "render_infographic_frame" not in ia_files["agente-compositions.md"]
    )  # devolve imagem: o kit não a oferece


def test_the_kit_manuals_are_in_sync_with_the_task_files_they_come_from():
    inputs = live.build_inputs()
    manual = parse_manual(files.read_manual())
    for task in manual.tasks:
        assert parse_calls(task), task.id
    assert {kit.name for kit in inputs.kits} == {kit.name for kit in KITS}
