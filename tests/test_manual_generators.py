"""Os geradores de referência (CLI, ferramentas MCP, campos da spec), o índice, o `docs/ia` e a montagem."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from dmaker.manual.build import BuildInputs, ManualBuildError, build_all, stale_files
from dmaker.manual.examples import parse_calls
from dmaker.manual.ia_docs import MAX_TOKENS, estimate_tokens, ia_doc, llms_txt, oversize, plain_links
from dmaker.manual.outline import parse_manual
from dmaker.manual.reference_cli import cli_reference, iter_leaf_commands, option_names, usage
from dmaker.manual.reference_mcp import ToolDoc, mcp_reference, parameters_line, schema_type_label
from dmaker.manual.reference_spec import spec_reference, type_label
from dmaker.manual.task_index import agent_support, tasks_index

from .manual_support import SAMPLE_MANUAL, fake_cli_root, fake_tools


def _inputs(extra_command: bool = False, tools=None, schema=None) -> BuildInputs:
    return BuildInputs(
        cli_root=fake_cli_root(extra=extra_command),
        tools=tuple(tools if tools is not None else fake_tools()),
        spec_schema=schema or {"properties": {"name": {"type": "string"}}, "required": ["name"]},
        agent_tools=("probe_media",),
        field_notes={"Project.name": "Nome do projeto."},
    )


def test_cli_reference_lists_every_command_with_usage_options_and_defaults():
    text = cli_reference(fake_cli_root())
    assert "São 2 comandos" in text
    assert "- **`dmaker quick SRC`**: Edição rápida de um vídeo." in text
    assert "  - `--captions` / `--no-captions`: Legendas automáticas." in text
    assert "  - `--hook` TEXTO: Texto de gancho." in text
    assert "#### dmaker dub" in text and "- **`dmaker dub run FILE`**: Dubla tudo." in text
    assert "  - `--to` TEXTO: Idioma alvo. (obrigatória)" in text
    assert "\u2014" not in text and "\u2013" not in text


def test_cli_reference_picks_up_a_new_command_automatically():
    """O manual reprova um comando sem documentação: ele aparece na referência no instante em que existe."""
    assert "comando-falso" not in cli_reference(fake_cli_root())
    assert "**`dmaker comando-falso NOME`**" in cli_reference(fake_cli_root(extra=True))


def test_cli_helpers_expose_paths_usage_and_option_names():
    root = fake_cli_root()
    paths = [path for path, _ in iter_leaf_commands(root)]
    assert paths == [("dub", "run"), ("quick",)]
    quick = root.commands["quick"]
    assert usage(("quick",), quick) == "dmaker quick SRC"
    assert {"--captions", "--no-captions", "--hook", "--help"} <= option_names(quick)


def test_mcp_reference_summarizes_each_tool_and_marks_required_parameters():
    text = mcp_reference(fake_tools())
    assert "São 2 ferramentas" in text
    assert "- **`probe_media`**: Duração e tamanho de arquivos." in text  # só a primeira frase
    assert "Segunda frase" not in text
    assert "Parâmetros: `paths`\\* (lista de texto)." in text
    assert "`captions` (sim ou não, padrão não)" in text and "`end` (número)" in text


def test_schema_type_labels_in_portuguese():
    assert schema_type_label({"type": "string"}) == "texto"
    assert schema_type_label({"enum": ["a", "b"]}) == '"a" ou "b"'
    assert schema_type_label({"anyOf": [{"type": "integer"}, {"type": "null"}]}) == "inteiro"
    assert parameters_line(ToolDoc("x", "", {})) == "Sem parâmetros."


class _Inner(BaseModel):
    volume: float = Field(1.0, ge=0, le=4)
    mode: str = "a"


class _Outer(BaseModel):
    name: str
    inner: _Inner = _Inner()
    tags: list[str] = []
    novo_campo_sem_nota: bool = False


def test_spec_reference_has_one_table_per_block_and_every_field():
    schema = _Outer.model_json_schema()
    schema["properties"]["inner"]["$ref"] = schema["properties"]["inner"].get("$ref", "#/$defs/_Inner")
    text = spec_reference(schema, {"Project.name": "Nome.", "*.volume": "Volume do áudio."})
    assert "São 2 blocos e 6 campos" in text
    for name in ("name", "inner", "tags", "novo_campo_sem_nota", "volume", "mode"):
        assert f"| `{name}` |" in text
    assert "| `volume` | número, de 0 a 4 | 1.0 | Volume do áudio. |" in text
    assert "| `name` | texto | obrigatório | Nome. |" in text
    assert "| `novo_campo_sem_nota` | sim ou não | não |  |" in text  # sem nota continua aparecendo
    assert "Usado em `Project.inner`" in text.replace("_Outer", "Project") or "Usado em" in text


def test_spec_type_label_handles_unions_ranges_and_maps():
    assert type_label({"$ref": "#/$defs/Output"}) == "`Output`"
    assert type_label({"type": "number", "exclusiveMinimum": 0, "maximum": 8}) == "número, maior que 0, até 8"
    assert type_label({"type": "object", "additionalProperties": {"type": "string"}}) == "mapa de texto"
    assert type_label({"enum": ["x", "y"]}) == '`"x"` ou `"y"`'


def test_agent_support_names_the_tools_the_local_agent_still_lacks():
    manual = parse_manual(SAMPLE_MANUAL)
    calls = parse_calls(manual.task("reel"))
    assert agent_support(calls, ["probe_media", "quick_edit"]) == "sim"
    assert agent_support(calls, ["probe_media"]) == "ainda não: `quick_edit`"
    index = tasks_index(manual.tasks, {"reel": calls, "dublar": []}, ["probe_media"])
    assert "[Fazer um Reel](#fazer-um-reel)" in index and "**Tarefas de vídeo**" in index
    assert "| ainda não: `quick_edit` |" in index


def test_ia_doc_follows_the_same_template_for_every_task():
    manual = parse_manual(SAMPLE_MANUAL)
    tools = {tool.name: tool for tool in fake_tools()}
    task = manual.task("reel")
    text = ia_doc(task, parse_calls(task), tools)
    order = [
        "# Fazer um Reel",
        "## Quando usar",
        "## O que perguntar antes",
        "## Ferramentas MCP, na ordem",
        "## Equivalente na CLI",
        "## Como conferir",
        "## Erros comuns",
    ]
    positions = [text.index(heading) for heading in order]
    assert positions == sorted(positions)
    assert (
        '1. `probe_media`: ver a duração\n   Argumentos de exemplo: `{"paths": ["C:/videos/a.mp4"]}`' in text
    )
    assert "2. `quick_edit`: Edição rápida de um vídeo." in text  # sem 'para', usa a descrição da ferramenta
    assert "dmaker quick a.mp4 --captions" in text
    assert "Novo projeto" not in text  # "Pela interface" não vai para a IA


def test_plain_links_drop_links_and_images():
    assert plain_links("veja [a tarefa](#x) e ![foto](img/a.png) e [site](https://a.com)") == (
        "veja a tarefa e  e site (https://a.com)"
    )


def test_llms_txt_lists_every_task_with_title_sentence_and_file():
    manual = parse_manual(SAMPLE_MANUAL)
    text = llms_txt(manual.tasks)
    assert text.startswith("# DMaker\n\n> ")
    assert "## Tarefas de vídeo" in text
    assert "- [Fazer um Reel](reel.md): Transforma uma gravação em um Reel legendado." in text
    assert "- [Dublar um vídeo](dublar.md): Troca a fala por outro idioma." in text


def test_token_estimate_counts_words_and_symbols_and_the_limit_flags_big_files():
    assert estimate_tokens("") == 0
    assert estimate_tokens("duas palavras") == 3  # 2 palavras x 1,5
    assert estimate_tokens('{"a": 1}') == 8  # 2 palavras (a, 1) x 1,5 + 5 símbolos
    assert oversize({"a.md": "palavra " * 2000, "b.md": "curto", "llms.txt": "palavra " * 5000}) == {
        "a.md": estimate_tokens("palavra " * 2000)
    }
    assert MAX_TOKENS == 1500


def test_build_all_regenerates_blocks_and_ia_files_and_is_idempotent():
    result = build_all(SAMPLE_MANUAL, _inputs())
    assert set(result.ia_files) == {"reel.md", "dublar.md", "llms.txt"}
    assert "- **`dmaker quick SRC`**" in result.manual and "**`probe_media`**" in result.manual
    assert "| `name` |" in result.manual
    again = build_all(result.manual, _inputs())
    assert again.manual == result.manual and again.ia_files == result.ia_files
    assert stale_files(result.manual, result.ia_files, again) == []


def test_a_new_command_makes_the_manual_stale_until_it_is_regenerated():
    """O critério do chamado: mudar o código sem regenerar reprova (e o comando novo entra na referência)."""
    built = build_all(SAMPLE_MANUAL, _inputs())
    with_new_command = build_all(built.manual, _inputs(extra_command=True))
    stale = stale_files(built.manual, built.ia_files, with_new_command)
    assert stale == ["docs/MANUAL.md"]
    assert "comando-falso" in with_new_command.manual and "comando-falso" not in built.manual


def test_a_new_tool_or_field_makes_the_manual_stale_too():
    built = build_all(SAMPLE_MANUAL, _inputs())
    new_tool = ToolDoc("ferramenta_nova", "Faz algo novo.", {"type": "object", "properties": {}})
    with_tool = build_all(built.manual, _inputs(tools=[*fake_tools(), new_tool]))
    assert stale_files(built.manual, built.ia_files, with_tool) == ["docs/MANUAL.md"]
    assert "ferramenta_nova" in with_tool.manual
    schema = {
        "properties": {"name": {"type": "string"}, "campo_novo": {"type": "integer"}},
        "required": ["name"],
    }
    with_field = build_all(built.manual, _inputs(schema=schema))
    assert stale_files(built.manual, built.ia_files, with_field) == ["docs/MANUAL.md"]
    assert "campo_novo" in with_field.manual


def test_a_changed_cli_option_inside_a_task_makes_the_ia_file_stale():
    """Mudar um comando no código sem regenerar docs/ia reprova: o exemplo da tarefa passa a citar o que não existe."""
    built = build_all(SAMPLE_MANUAL, _inputs())
    renamed = SAMPLE_MANUAL.replace("--captions --hook", "--legendas --hook")
    with pytest.raises(ManualBuildError, match="--legendas"):
        build_all(renamed, _inputs())
    # e um arquivo de docs/ia que ficou para trás (ou que não tem mais tarefa) também é apontado
    edited = {**built.ia_files, "reel.md": built.ia_files["reel.md"] + "\nlinha à mão\n", "velha.md": "x"}
    assert stale_files(built.manual, edited, built) == [
        "docs/ia/reel.md",
        "docs/ia/velha.md (sem tarefa no manual)",
    ]


def test_build_fails_with_the_list_of_problems_when_a_call_does_not_fit_the_schema():
    bad = SAMPLE_MANUAL.replace('"paths": ["C:/videos/a.mp4"]', '"caminhos": ["C:/videos/a.mp4"]')
    with pytest.raises(ManualBuildError) as error:
        build_all(bad, _inputs())
    assert any("caminhos" in problem for problem in error.value.problems)


def test_build_refuses_an_ia_file_over_the_token_limit():
    huge = SAMPLE_MANUAL.replace("Você tem um vídeo falado e quer um Reel.", "palavra " * 3000)
    with pytest.raises(ManualBuildError, match="acima do limite"):
        build_all(huge, _inputs())


def test_generated_text_never_carries_a_dash():
    built = build_all(SAMPLE_MANUAL, _inputs())
    blob = built.manual + json.dumps(built.ia_files, ensure_ascii=False)
    assert "\u2014" not in blob and "\u2013" not in blob
