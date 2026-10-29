"""Monta tudo o que o manual gera do código: os blocos do `MANUAL.md` e os arquivos de `docs/ia`.

É uma função pura: recebe o texto atual do manual e as estruturas do código (árvore da CLI, ferramentas
MCP, esquema da spec) e devolve os textos novos. Quem lê e escreve em disco é `service.py`, e é por isso que o
teste de "manual em dia" consegue comparar tudo em memória.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..agent.kits import Kit
from .examples import ToolCall, call_problems, cli_problems, parse_calls
from .ia_docs import MAX_TOKENS, build_ia_files, oversize
from .kit_manuals import KIT_MAX_TOKENS, build_kit_manuals, oversize_kits
from .markers import replace_generated
from .outline import parse_manual, structure_problems
from .reference_cli import cli_reference
from .reference_infographics import infographics_reference
from .reference_mcp import ToolDoc, mcp_reference
from .reference_spec import spec_reference
from .task_index import tasks_index

GENERATED_BLOCKS = ("indice", "cli", "mcp", "spec", "infograficos")


class ManualBuildError(ValueError):
    """O manual foge do molde ou cita algo que o código não tem; a lista diz o quê."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class BuildInputs:
    """O que o código sabe e o manual precisa mostrar."""

    cli_root: Any
    tools: tuple[ToolDoc, ...]
    spec_schema: dict[str, Any]
    agent_tools: tuple[str, ...]
    field_notes: Mapping[str, str] = field(default_factory=dict)
    kits: tuple[Kit, ...] = ()  # os kits do agente local: cada um ganha o seu `docs/ia/agente-<kit>.md`
    infographics: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class BuildResult:
    manual: str
    ia_files: dict[str, str]


def find_problems(manual_text: str, inputs: BuildInputs) -> tuple[list[str], dict[str, list[ToolCall]]]:
    """Tudo o que está fora do molde ou desatualizado em relação ao código, mais as chamadas já lidas."""
    problems = structure_problems(manual_text)
    tools = {tool.name: tool for tool in inputs.tools}
    calls_by_task: dict[str, list[ToolCall]] = {}
    for task in parse_manual(manual_text).tasks:
        try:
            calls = parse_calls(task)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        calls_by_task[task.id] = calls
        problems.extend(call_problems(task, calls, tools))
        problems.extend(cli_problems(task, inputs.cli_root))
    return problems, calls_by_task


def build_all(manual_text: str, inputs: BuildInputs) -> BuildResult:
    """Regenera os blocos gerados do manual e os arquivos de `docs/ia`; falha se o manual não fecha."""
    problems, calls_by_task = find_problems(manual_text, inputs)
    if problems:
        raise ManualBuildError(problems)
    tasks = parse_manual(manual_text).tasks
    tools = {tool.name: tool for tool in inputs.tools}
    ia_files = build_ia_files(tasks, calls_by_task, tools)
    kit_files = build_kit_manuals(inputs.kits, tasks, calls_by_task, tools)
    too_big = [
        f"docs/ia/{name}: ~{size} tokens, acima do limite de {MAX_TOKENS}."
        for name, size in oversize(ia_files).items()
    ] + [
        f"docs/ia/{name}: ~{size} tokens, acima do limite de {KIT_MAX_TOKENS} de um kit."
        for name, size in oversize_kits(kit_files).items()
    ]
    if too_big:
        raise ManualBuildError(too_big)
    ia_files = {**ia_files, **kit_files}
    text = manual_text
    blocks = {
        "indice": tasks_index(tasks, calls_by_task, inputs.agent_tools),
        "cli": cli_reference(inputs.cli_root),
        "mcp": mcp_reference(inputs.tools),
        "spec": spec_reference(inputs.spec_schema, inputs.field_notes),
        "infograficos": infographics_reference(inputs.infographics),
    }
    for name in GENERATED_BLOCKS:
        text = replace_generated(text, name, blocks[name])
    return BuildResult(manual=text, ia_files=ia_files)


def stale_files(
    manual_now: str, ia_now: Mapping[str, str], result: BuildResult, ia_dir: str = "docs/ia"
) -> list[str]:
    """Os arquivos que `dmaker manual build` mudaria (ou apagaria): vazio quando o manual está em dia."""
    stale = []
    if manual_now != result.manual:
        stale.append("docs/MANUAL.md")
    for name, text in result.ia_files.items():
        if ia_now.get(name) != text:
            stale.append(f"{ia_dir}/{name}")
    stale.extend(
        f"{ia_dir}/{name} (sem tarefa no manual)" for name in sorted(set(ia_now) - set(result.ia_files))
    )
    return stale
