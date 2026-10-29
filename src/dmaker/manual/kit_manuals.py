"""O manual curto de cada kit do agente local, montado das mesmas tarefas do manual (e não escrito à parte).

O agente não carrega a skill nem o guia: cada pedido vê só o manual do kit que a triagem escolheu. Ele nasce
das tarefas do kit (`Kit.tasks`): para cada uma, um pedido de exemplo e as chamadas certas, tirados do mesmo
`MANUAL.md` que gera `docs/ia`. Assim skill, guia e agente nunca divergem, e o limite de tokens pega o kit que
crescer demais. Função pura: recebe tarefas, chamadas e ferramentas; devolve texto.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from ..agent.kits import Kit, kit_tool_names
from .examples import ToolCall
from .ia_docs import estimate_tokens, plain_links
from .outline import Task
from .reference_mcp import ToolDoc

KIT_MAX_TOKENS = 2000  # junto das ferramentas e das regras, o prompt de um kit ainda cabe em 16k de contexto
EXAMPLES_PER_KIT = 3  # "dois ou três exemplos de pedido": mais que isso gasta contexto sem ensinar nada novo
KIT_FILE_PREFIX = "agente-"

_REQUEST_LINE = re.compile(r'^-\s+"(.+)"\s*$', re.MULTILINE)


def kit_file_name(kit: Kit) -> str:
    return f"{KIT_FILE_PREFIX}{kit.name}.md"


def example_requests(task: Task) -> list[str]:
    """Os pedidos de exemplo que a tarefa lista em 'Quando usar' (frases entre aspas)."""
    return _REQUEST_LINE.findall(task.parts.get("quando_usar", ""))


def _call_lines(position: int, call: ToolCall, available: Mapping[str, ToolDoc]) -> list[str]:
    tool = available.get(call.tool)
    purpose = call.purpose or (tool.summary if tool else "")
    head = f"{position}. `{call.tool}`" + (f": {purpose}" if purpose else "")
    return [head, f"   Argumentos: `{json.dumps(call.arguments, ensure_ascii=False)}`"]


def _example(task: Task, calls: Sequence[ToolCall], available: Mapping[str, ToolDoc]) -> list[str]:
    requests = example_requests(task)
    title = f'Pedido: "{requests[0]}"' if requests else f"Tarefa: {task.title}"
    lines = [f"### {title}", ""]
    for position, call in enumerate(calls, start=1):
        lines.extend(_call_lines(position, call, available))
    ask_first = plain_links(task.parts.get("antes", "")).strip()
    if ask_first:
        lines.extend(["", "Pergunte antes, se faltar:", ask_first])
    lines.append("")
    return lines


def kit_manual(
    kit: Kit,
    tasks: Mapping[str, Task],
    calls_by_task: Mapping[str, Sequence[ToolCall]],
    tools: Mapping[str, ToolDoc],
) -> str:
    """O manual de um kit: as ferramentas que ele tem neste servidor e até três pedidos com as chamadas certas."""
    names = kit_tool_names(kit, available=tools)
    lines = [f"# Kit {kit.title}", "", kit.description, "", "## Ferramentas deste kit", ""]
    if names:
        # só os nomes: a descrição e os argumentos de cada uma já chegam ao modelo junto da ferramenta
        lines.append(", ".join(f"`{name}`" for name in names) + ".")
    else:
        lines.append(
            "Este servidor ainda não tem nenhuma ferramenta deste kit: diga ao usuário que a função não existe."
        )
    lines.extend(["", "## Pedidos e as chamadas certas", ""])
    shown = 0
    for task_id in kit.tasks:
        task = tasks.get(task_id)
        if task is None or shown == EXAMPLES_PER_KIT:
            continue
        calls = [call for call in calls_by_task.get(task_id, ()) if call.tool in names]
        if not calls:
            continue
        lines.extend(_example(task, calls, tools))
        shown += 1
    if shown == 0:
        lines.append("Sem exemplo para este kit ainda: use a descrição das ferramentas.")
    return "\n".join(lines).rstrip() + "\n"


def build_kit_manuals(
    kits: Sequence[Kit],
    tasks: Sequence[Task],
    calls_by_task: Mapping[str, Sequence[ToolCall]],
    tools: Mapping[str, ToolDoc],
) -> dict[str, str]:
    """`{nome do arquivo: texto}` de `docs/ia/agente-<kit>.md`, um por kit."""
    by_id = {task.id: task for task in tasks}
    return {kit_file_name(kit): kit_manual(kit, by_id, calls_by_task, tools) for kit in kits}


def oversize_kits(files: Mapping[str, str], limit: int = KIT_MAX_TOKENS) -> dict[str, int]:
    """Os manuais de kit que passam do limite de tokens, com o tamanho estimado de cada um."""
    return {
        name: estimate_tokens(text)
        for name, text in files.items()
        if name.startswith(KIT_FILE_PREFIX) and estimate_tokens(text) > limit
    }
