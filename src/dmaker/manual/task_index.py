"""O índice "quero fazer X, onde está?": uma linha por tarefa, com o link e se o agente local já dá conta dela."""

from __future__ import annotations

from collections.abc import Sequence

from .examples import ToolCall
from .outline import Task


def agent_support(calls: Sequence[ToolCall], agent_tools: Sequence[str]) -> str:
    """`sim` quando o agente local enxerga todas as ferramentas da tarefa; senão, quais faltam."""
    missing = [name for name in dict.fromkeys(call.tool for call in calls) if name not in agent_tools]
    if not missing:
        return "sim"
    return "ainda não: " + ", ".join(f"`{name}`" for name in missing)


def first_sentence(text: str) -> str:
    """A frase que resume a tarefa (o parágrafo logo abaixo do título já é uma frase só)."""
    return " ".join(text.split())


def tasks_index(
    tasks: Sequence[Task], calls_by_task: dict[str, list[ToolCall]], agent_tools: Sequence[str]
) -> str:
    """Tabelas por capítulo: tarefa (com link), o que entrega e o suporte do agente local."""
    chapters: dict[str, list[Task]] = {}
    for task in tasks:
        chapters.setdefault(task.chapter, []).append(task)
    out = [
        f"São {len(tasks)} tarefas. A última coluna diz se o agente local (`dmaker agent`) já tem todas as "
        "ferramentas da tarefa; quando não tem, ela fica para o Claude, para a interface ou para a CLI."
    ]
    for chapter, chapter_tasks in chapters.items():
        out.extend(
            ["", f"**{chapter}**", "", "| Quero | O que entrega | Agente local |", "| --- | --- | --- |"]
        )
        for task in chapter_tasks:
            support = agent_support(calls_by_task.get(task.id, []), agent_tools)
            out.append(f"| [{task.title}](#{task.anchor}) | {first_sentence(task.summary)} | {support} |")
    return "\n".join(out)
