"""Marcadores, âncoras, estrutura das tarefas e exemplos do manual (funções puras, sem disco)."""

from __future__ import annotations

import pytest

from dmaker.manual.examples import (
    ExampleError,
    call_problems,
    cli_problems,
    command_problem,
    parse_calls,
    shell_commands,
)
from dmaker.manual.markers import MarkerError, generated_names, read_generated, replace_generated
from dmaker.manual.outline import parse_manual, parse_sections, structure_problems
from dmaker.manual.slug import SlugCounter, github_slug, plain_title

from .manual_support import SAMPLE_MANUAL, fake_cli_root, fake_tools


def test_replace_generated_swaps_only_the_marked_block_and_is_idempotent():
    once = replace_generated(SAMPLE_MANUAL, "cli", "linha nova")
    assert read_generated(once, "cli") == "linha nova"
    assert read_generated(once, "mcp") == ""  # os outros blocos ficam como estavam
    assert replace_generated(once, "cli", "linha nova") == once
    assert generated_names(SAMPLE_MANUAL) == ["indice", "cli", "mcp", "spec", "infograficos"]


def test_replace_generated_fails_when_the_manual_lacks_the_marker():
    with pytest.raises(MarkerError, match="bloco gerado 'inexistente'"):
        replace_generated(SAMPLE_MANUAL, "inexistente", "x")


def test_slug_matches_github_and_numbers_repeated_titles():
    assert github_slug("Usando com o Claude (Claude Code)") == "usando-com-o-claude-claude-code"
    assert github_slug("Fazer um Reel a partir de uma gravação") == "fazer-um-reel-a-partir-de-uma-gravação"
    assert plain_title("Pela `CLI` e [link](#x)") == "Pela CLI e link"
    counter = SlugCounter()
    assert [counter.unique("Pela CLI"), counter.unique("Pela CLI"), counter.unique("Pela CLI")] == [
        "pela-cli",
        "pela-cli-1",
        "pela-cli-2",
    ]


def test_headings_inside_code_fences_are_not_sections():
    text = "# A\n\n```\n# nao e titulo\n```\n\n## B\n\ncorpo"
    assert [s.title for s in parse_sections(text)] == ["A", "B"]
    assert parse_sections(text)[1].path == ("A", "B")


def test_parse_manual_finds_tasks_with_ids_chapter_and_parts():
    manual = parse_manual(SAMPLE_MANUAL)
    assert [t.id for t in manual.tasks] == ["reel", "dublar"]
    reel = manual.task("reel")
    assert reel.title == "Fazer um Reel" and reel.chapter == "Tarefas de vídeo"
    assert reel.summary == "Transforma uma gravação em um Reel legendado."
    assert set(reel.parts) == {
        "quando_usar", "antes", "ia", "chamadas", "interface", "cli", "conferir", "erros",
    }  # fmt: skip
    assert "Faz um reel desse vídeo" in reel.parts["quando_usar"]
    assert manual.task("nao-existe") is None


def test_structure_problems_flags_what_breaks_the_template():
    assert structure_problems(SAMPLE_MANUAL) == []
    without_cli = SAMPLE_MANUAL.replace("#### Pela CLI", "#### Pela linha de comando", 1)
    assert any("Pela CLI" in p for p in structure_problems(without_cli))
    assert any("Pela linha de comando" in p for p in structure_problems(without_cli))
    swapped = SAMPLE_MANUAL.replace("#### Como conferir", "#### Se der errado", 1)
    assert any("fora da ordem" in p or "Como conferir" in p for p in structure_problems(swapped))
    same_id = SAMPLE_MANUAL.replace("<!-- tarefa: dublar -->", "<!-- tarefa: reel -->")
    assert any("já é de" in p for p in structure_problems(same_id))
    no_summary = SAMPLE_MANUAL.replace("Troca a fala por outro idioma.\n\n", "")
    assert any("frase logo abaixo do título" in p for p in structure_problems(no_summary))


def test_parse_calls_reads_tool_arguments_and_purpose():
    calls = parse_calls(parse_manual(SAMPLE_MANUAL).task("reel"))
    assert [c.tool for c in calls] == ["probe_media", "quick_edit"]
    assert calls[0].arguments == {"paths": ["C:/videos/a.mp4"]} and calls[0].purpose == "ver a duração"
    assert calls[1].purpose == ""


def test_parse_calls_rejects_a_malformed_block():
    task = parse_manual(SAMPLE_MANUAL.replace('"tool": "quick_edit"', '"ferramenta": "quick_edit"')).task(
        "reel"
    )
    with pytest.raises(ExampleError, match="precisa de 'tool'"):
        parse_calls(task)
    broken = parse_manual(SAMPLE_MANUAL.replace('"captions": true}}', '"captions": true}}}')).task("reel")
    with pytest.raises(ExampleError, match="JSON das chamadas é inválido"):
        parse_calls(broken)


def test_call_problems_check_tool_argument_names_and_types_against_the_schema():
    task = parse_manual(SAMPLE_MANUAL).task("reel")
    tools = {tool.name: tool for tool in fake_tools()}
    assert call_problems(task, parse_calls(task), tools) == []

    wrong = parse_manual(
        SAMPLE_MANUAL.replace('"captions": true}', '"captions": "sim", "invento": 1}').replace(
            '"paths": ["C:/videos/a.mp4"]', '"paths": "a.mp4"'
        )
    ).task("reel")
    problems = "\n".join(call_problems(wrong, parse_calls(wrong), tools))
    assert "o argumento 'invento' não existe" in problems
    assert "captions" in problems and "paths" in problems

    missing_tool = {name: tool for name, tool in tools.items() if name != "quick_edit"}
    assert "a ferramenta não existe" in "\n".join(call_problems(task, parse_calls(task), missing_tool))


def test_shell_commands_join_backtick_continuations_and_ignore_other_blocks():
    markdown = (
        "```powershell\n"
        "# comentario\n"
        "dmaker new-from-template a b `\n    --param x=1\n"
        "ollama pull gpt-oss:20b\n"
        "```\n\n```json\n{}\n```\n"
    )
    assert shell_commands(markdown) == ["dmaker new-from-template a b --param x=1"]


def test_command_problem_accepts_real_commands_and_names_what_is_wrong():
    root = fake_cli_root()
    assert command_problem('dmaker quick a.mp4 --captions --hook "Olá, mundo" # comentário', root) is None
    assert command_problem("dmaker dub a.mp4 --to en", root) is None  # o grupo manda o resto para `run`
    assert command_problem("dmaker dub run a.mp4 --to en", root) is None
    assert "não é um comando" in command_problem("dmaker inexistente x", root)
    assert "--inventada" in command_problem("dmaker quick a.mp4 --inventada", root)
    assert "é um grupo" in command_problem("dmaker dub", root)


def test_cli_problems_scan_the_task_parts():
    task = parse_manual(SAMPLE_MANUAL.replace("--captions --hook", "--legendas --hook")).task("reel")
    problems = cli_problems(task, fake_cli_root())
    assert len(problems) == 1 and "--legendas" in problems[0]


def test_command_problem_counts_the_arguments_and_skips_option_values():
    root = fake_cli_root()
    assert command_problem("dmaker quick a.mp4 --hook Olá --captions", root) is None
    assert "recebe 1 argumento" in command_problem(
        "dmaker dub get x.json --to en", root
    )  # subcomando inventado
    assert "precisa de 1 argumento" in command_problem("dmaker quick --captions", root)
    assert command_problem("dmaker quick a.mp4 --hook Olá", root) is None  # o valor de --hook não conta


def test_command_problem_can_accept_a_command_named_without_its_arguments():
    root = fake_cli_root()
    assert "precisa de 1 argumento" in command_problem("dmaker quick", root)
    assert command_problem("dmaker quick", root, require_arguments=False) is None
    assert "recebe 1 argumento" in command_problem("dmaker dub get x.json", root, require_arguments=False)
