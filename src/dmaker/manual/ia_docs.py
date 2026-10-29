"""A versão do manual para modelo local pequeno: um arquivo curto por tarefa e o índice `llms.txt`.

Nada aqui é escrito à parte: cada arquivo é montado das partes da tarefa no `MANUAL.md` (quando usar, o que
perguntar, as chamadas, a CLI, como conferir, erros) e dos esquemas das ferramentas do servidor. Um modelo de
16k a 32k de contexto carrega o arquivo da tarefa inteiro e ainda tem espaço para trabalhar, por isso o limite.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from .examples import ToolCall
from .outline import Task
from .reference_mcp import ToolDoc

MAX_TOKENS = 1500  # por arquivo: cabe no prompt de um modelo de 16k junto com o resto da conversa

LLMS_TITLE = "DMaker"
LLMS_SUMMARY = (
    "Editor de vídeos curtos por comando, com narração, dublagem e correção de fala locais. "
    "Cada arquivo abaixo ensina uma tarefa: quando usar, o que perguntar antes, as ferramentas MCP na ordem "
    "com um exemplo de argumentos, o equivalente na CLI, como conferir e os erros comuns."
)

_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")
_WORD = re.compile(r"[^\W_]+")
_SYMBOL = re.compile(r"[^\w\s]|_")


def estimate_tokens(text: str) -> int:
    """Uma estimativa que não precisa do tokenizador do modelo: palavras valem 1,5 e cada símbolo vale 1.

    Em português, os vocabulários BPE (Llama, Qwen, gpt-oss) partem uma palavra em 1 a 2 pedaços, em média
    perto de 1,5; pontuação, chaves e aspas do JSON costumam valer 1 cada (às vezes juntam, então a conta sobra).
    Errar para mais é o certo aqui: o limite protege o contexto do modelo.
    """
    return round(len(_WORD.findall(text)) * 1.5 + len(_SYMBOL.findall(text)))


def plain_links(markdown: str) -> str:
    """Troca `[texto](destino)` pelo texto e some com as imagens: dentro de `docs/ia` os destinos não existem."""

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if match.group(0).startswith("!"):
            return ""
        return label if not target.startswith("http") else f"{label} ({target})"

    return _LINK.sub(replace, markdown)


def _tool_line(position: int, call: ToolCall, tools: Mapping[str, ToolDoc]) -> list[str]:
    tool = tools.get(call.tool)
    what = tool.summary if tool else ""
    head = f"{position}. `{call.tool}`"
    if call.purpose:
        head += f": {call.purpose}"
    elif what:
        head += f": {what}"
    arguments = json.dumps(call.arguments, ensure_ascii=False)
    return [head, f"   Argumentos de exemplo: `{arguments}`"]


def _section(title: str, body: str) -> list[str]:
    # a imagem removida deixa uma linha em branco a mais
    text = re.sub(r"\n{3,}", "\n\n", plain_links(body.strip())).strip()
    return [f"## {title}", "", text, ""]


def ia_doc(task: Task, calls: Sequence[ToolCall], tools: Mapping[str, ToolDoc]) -> str:
    """O arquivo de uma tarefa, sempre no mesmo molde, para o modelo achar cada coisa no mesmo lugar."""
    lines = [
        f"# {task.title}",
        "",
        f"Tarefa `{task.id}` do manual do DMaker. {plain_links(task.summary)}",
        "",
        *_section("Quando usar", task.parts["quando_usar"]),
        *_section("O que perguntar antes", task.parts["antes"]),
        "## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)",
        "",
    ]
    for position, call in enumerate(calls, start=1):
        lines.extend(_tool_line(position, call, tools))
    lines.extend(["", *_section("Equivalente na CLI", task.parts["cli"])])
    lines.extend(_section("Como conferir", task.parts["conferir"]))
    lines.extend(_section("Erros comuns", task.parts["erros"]))
    return "\n".join(lines).rstrip() + "\n"


def llms_txt(tasks: Sequence[Task]) -> str:
    """O índice no formato llms.txt: um título, uma frase de resumo e uma linha por tarefa com o arquivo."""
    chapters: dict[str, list[Task]] = {}
    for task in tasks:
        chapters.setdefault(task.chapter, []).append(task)
    lines = [f"# {LLMS_TITLE}", "", f"> {LLMS_SUMMARY}", ""]
    for chapter, chapter_tasks in chapters.items():
        lines.extend([f"## {chapter}", ""])
        for task in chapter_tasks:
            lines.append(f"- [{task.title}]({task.id}.md): {' '.join(plain_links(task.summary).split())}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_ia_files(
    tasks: Sequence[Task], calls_by_task: Mapping[str, list[ToolCall]], tools: Mapping[str, ToolDoc]
) -> dict[str, str]:
    """`{nome do arquivo: texto}` de `docs/ia`: um arquivo por tarefa mais o `llms.txt`."""
    files = {f"{task.id}.md": ia_doc(task, calls_by_task[task.id], tools) for task in tasks}
    files["llms.txt"] = llms_txt(tasks)
    return files


def oversize(files: Mapping[str, str], limit: int = MAX_TOKENS) -> dict[str, int]:
    """Os arquivos de tarefa que passam do limite de tokens, com o tamanho estimado de cada um."""
    return {
        name: estimate_tokens(text)
        for name, text in files.items()
        if name.endswith(".md") and estimate_tokens(text) > limit
    }
