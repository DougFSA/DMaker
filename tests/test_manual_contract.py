"""O manual de verdade contra o código: tudo o que o código tem aparece nele, e nada nele cita o que não existe.

São os contratos entre arquivos distantes (o texto em `docs/`, a CLI, o servidor MCP e o modelo da spec). Os testes
comparam em memória, sem escrever em `docs/`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dmaker import config
from dmaker.agent.kits import KITS
from dmaker.manual import files, live, service
from dmaker.manual.build import GENERATED_BLOCKS, build_all, stale_files
from dmaker.manual.examples import parse_calls
from dmaker.manual.ia_docs import MAX_TOKENS, estimate_tokens
from dmaker.manual.markers import generated_names
from dmaker.manual.outline import PART_TITLES, TASK_PARTS, parse_manual, structure_problems
from dmaker.manual.reference_cli import iter_leaf_commands

DASHES = ("—", "–")  # travessão e meia-risca: proibidos em texto de tela, no manual e em docs/ia
ROOT = Path(config.ROOT)


@pytest.fixture(scope="module")
def inputs():
    return live.build_inputs()


@pytest.fixture(scope="module")
def manual_text() -> str:
    return files.read_manual()


def test_manual_is_up_to_date_with_the_code(inputs, manual_text):
    """Se um comando, uma ferramenta ou um campo mudou sem `dmaker manual build`, este teste reprova."""
    result = build_all(manual_text, inputs)
    stale = stale_files(manual_text, files.read_ia_files(), result)
    assert not stale, "rode `dmaker manual build` (desatualizados: " + ", ".join(stale) + ")"


def test_manual_has_all_generated_blocks(manual_text):
    assert set(generated_names(manual_text)) == set(GENERATED_BLOCKS)


def test_every_cli_command_option_mcp_tool_and_spec_field_is_in_the_manual(inputs, manual_text):
    for path, command in iter_leaf_commands(inputs.cli_root):
        assert f"`dmaker {' '.join(path)}" in manual_text, (
            f"comando sem documentação: dmaker {' '.join(path)}"
        )
        for param in command.params:
            for option in getattr(param, "opts", ()) or ():
                if option.startswith("--"):
                    assert f"`{option}`" in manual_text, (
                        f"opção sem documentação: dmaker {' '.join(path)} {option}"
                    )
    for tool in inputs.tools:
        assert f"**`{tool.name}`**" in manual_text, f"ferramenta MCP sem documentação: {tool.name}"
    schema = inputs.spec_schema
    models = {
        "Project": schema.get("properties", {}),
        **{n: d.get("properties", {}) for n, d in schema["$defs"].items()},
    }
    for model, properties in models.items():
        assert f"#### {model}\n" in manual_text, f"bloco da spec sem tabela: {model}"
        for field_name in properties:
            assert f"| `{field_name}` |" in manual_text, (
                f"campo da spec sem documentação: {model}.{field_name}"
            )


def test_every_task_follows_the_template_and_shows_the_three_paths(manual_text):
    assert structure_problems(manual_text) == []
    tasks = parse_manual(manual_text).tasks
    assert len(tasks) >= 25
    for task in tasks:
        for title, key in TASK_PARTS:
            assert task.parts.get(key, "").strip(), f"{task.title}: '{title}' vazio"
        for key in ("ia", "interface", "cli"):
            body = task.parts[key]
            assert len(body) > 20 or body.startswith("Não existe"), (
                f"{task.title}: caminho '{key}' sem conteúdo"
            )


def test_the_mandatory_tasks_exist(manual_text):
    ids = {task.id for task in parse_manual(manual_text).tasks}
    assert {
        "reel",
        "narrar",
        "dublar",
        "corrigir-fala",
        "cortar-pausas",
        "multicam",
        "verificar-audio",
    } <= ids
    titles = {task.title for task in parse_manual(manual_text).tasks}
    assert "Fazer o vídeo do casamento com duas câmeras" in titles
    assert "Verificar se um áudio foi gerado pelo DMaker" in titles


def test_where_a_path_does_not_exist_the_task_says_so_clearly(manual_text):
    absent = [
        t
        for t in parse_manual(manual_text).tasks
        for key in ("ia", "interface", "cli")
        if t.parts[key].startswith("Não existe")
    ]
    assert absent, "pelo menos uma tarefa não tem caminho pela interface e deve dizer isso"
    for task in absent:
        assert any(task.parts[k].startswith("Não existe") for k in ("ia", "interface", "cli"))


def test_each_task_has_an_ia_file_within_the_token_limit_and_the_same_template():
    manual = parse_manual(files.read_manual())
    ia_files = files.read_ia_files()
    kit_manuals = {f"agente-{kit.name}.md" for kit in KITS}  # o manual curto de cada kit do agente local
    assert set(ia_files) == {f"{t.id}.md" for t in manual.tasks} | {"llms.txt"} | kit_manuals
    headings = [
        "## Quando usar",
        "## O que perguntar antes",
        "## Ferramentas MCP, na ordem",
        "## Equivalente na CLI",
        "## Como conferir",
        "## Erros comuns",
    ]
    for task in manual.tasks:
        text = ia_files[f"{task.id}.md"]
        assert estimate_tokens(text) <= MAX_TOKENS, f"{task.id}: {estimate_tokens(text)} tokens"
        positions = [text.index(h) for h in headings]
        assert positions == sorted(positions), f"{task.id}: fora do molde"
        assert text.startswith(f"# {task.title}\n")


def test_llms_txt_has_one_line_per_task_with_title_sentence_and_file():
    manual = parse_manual(files.read_manual())
    llms = files.read_ia_files()["llms.txt"]
    assert llms.startswith("# DMaker\n\n> ")
    lines = [line for line in llms.splitlines() if line.startswith("- [")]
    assert len(lines) == len(manual.tasks)
    for task, line in zip(manual.tasks, lines, strict=True):
        assert re.fullmatch(rf"- \[{re.escape(task.title)}\]\({re.escape(task.id)}\.md\): .+", line), line


def test_every_tool_call_example_is_valid_for_the_server_schema(inputs, manual_text):
    tools = {tool.name: tool for tool in inputs.tools}
    from dmaker.manual.examples import call_problems

    for task in parse_manual(manual_text).tasks:
        calls = parse_calls(task)
        assert calls, task.title
        assert call_problems(task, calls, tools) == [], task.title


def test_manual_and_ia_files_have_no_dashes(manual_text):
    blob = manual_text + "".join(files.read_ia_files().values())
    for dash in DASHES:
        assert dash not in blob


def test_manual_keeps_the_chapters_the_readers_look_for(manual_text):
    titles = {section.title for section in parse_manual(manual_text).sections if section.level == 2}
    for chapter in (
        "Quero fazer X, onde está?",
        "O que é o DMaker",
        "Instalação passo a passo no Windows",
        "Conceitos",
        "Usando com o Claude (Claude Code)",
        "Usando com LLM local (Ollama)",
        "Usando pela interface gráfica",
        "Usando pela linha de comando",
        "Marca MedlyCare",
        "O que entrou nesta versão",
        "Referência gerada do código",
        "Solução de problemas",
        "Anexos",
    ):
        assert chapter in titles, chapter
    assert "Glossário" in {s.title for s in parse_manual(manual_text).sections}


def test_manual_documents_what_came_in_this_version(manual_text):
    section = next(s for s in parse_manual(manual_text).sections if s.title == "O que entrou nesta versão")
    for card in ("DMK-23", "DMK-25", "DMK-27", "DMK-29", "DMK-30", "DMK-32", "DMK-33", "DMK-37"):
        assert card in section.body, card


def test_images_referenced_in_the_manual_exist_and_stay_small(manual_text):
    docs = files.checkout_docs_dir()
    references = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", manual_text)
    assert references, "o manual deve ter capturas de tela"
    for reference in references:
        assert (docs / reference).is_file(), f"imagem citada no manual e ausente: {reference}"
    total = sum(f.stat().st_size for f in (docs / "img").rglob("*") if f.is_file())
    assert total < 5_000_000, f"docs/img tem {total / 1e6:.1f} MB; mantenha abaixo de 5 MB"


def test_no_real_media_or_voice_in_docs():
    allowed = {".png", ".jpg", ".jpeg", ".md", ".txt"}
    odd = [p for p in files.checkout_docs_dir().rglob("*") if p.is_file() and p.suffix.lower() not in allowed]
    assert odd == [], f"docs/ só leva imagens e texto (nada de vídeo, áudio ou voz): {odd}"


def test_manual_is_packaged_for_installs_without_the_repository():
    setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "MANUAL.md" in setup_py and '"ia"' in setup_py and "resources" in setup_py and "manual" in setup_py
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "docs/MANUAL.md" in manifest and "docs/ia" in manifest
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"^docs = \[\"playwright", pyproject, re.MULTILINE)
    assert files.packaged_docs_dir() == config.PACKAGE_DIR / "resources" / "manual"


def test_check_in_memory_matches_the_service(inputs):
    assert service.check(inputs) == []


def test_readme_stays_short_and_points_to_the_manual():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) < 120
    assert "docs/MANUAL.md" in readme and "dmaker manual" in readme
    assert all(dash not in readme for dash in DASHES)


def test_part_titles_cover_the_template():
    assert set(PART_TITLES.values()) == {key for _, key in TASK_PARTS}
