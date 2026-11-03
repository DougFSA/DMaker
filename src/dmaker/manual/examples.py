"""Os exemplos do manual (chamadas MCP em JSON e comandos da CLI) e a conferência deles contra o código.

Um exemplo que cita uma ferramenta, um argumento, um comando ou uma opção que não existe mais é um erro de
manual que só se descobriria seguindo o passo a passo. Aqui ele vira lista de problemas, para um teste reprovar.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from .outline import Task
from .reference_cli import is_argument, is_group, option_names
from .reference_mcp import ToolDoc

_JSON_FENCE = re.compile(r"```json[^\n]*\n(.*?)```", re.DOTALL)
_SHELL_FENCE = re.compile(r"```(?:powershell|bash|console|shell)[^\n]*\n(.*?)```", re.DOTALL)
_TOKEN = re.compile(r"""(?:[^\s"']|"[^"]*"|'[^']*')+""")


class ExampleError(ValueError):
    """O bloco de chamadas de uma tarefa não segue o formato."""


@dataclass(frozen=True)
class ToolCall:
    """Uma chamada de exemplo: a ferramenta, os argumentos e, em uma frase, para que ela serve no passo."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    purpose: str = ""


def parse_calls(task: Task) -> list[ToolCall]:
    """As chamadas do bloco `json` de "Chamadas das ferramentas" (lista de `{tool, arguments, para}`)."""
    body = task.parts.get("chamadas", "")
    match = _JSON_FENCE.search(body)
    if not match:
        raise ExampleError(f"{task.title}: 'Chamadas das ferramentas' não tem um bloco ```json.")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ExampleError(f"{task.title}: o JSON das chamadas é inválido ({exc}).") from exc
    if not isinstance(data, list) or not data:
        raise ExampleError(f"{task.title}: as chamadas devem ser uma lista com pelo menos uma ferramenta.")
    calls = []
    for position, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("tool"), str):
            raise ExampleError(f"{task.title}: a chamada {position} precisa de 'tool' (texto).")
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ExampleError(f"{task.title}: 'arguments' da chamada {position} deve ser um objeto.")
        unknown = set(item) - {"tool", "arguments", "para"}
        if unknown:
            raise ExampleError(f"{task.title}: chave desconhecida na chamada {position}: {sorted(unknown)}.")
        calls.append(ToolCall(item["tool"], arguments, str(item.get("para", ""))))
    return calls


def call_problems(task: Task, calls: list[ToolCall], tools: Mapping[str, ToolDoc]) -> list[str]:
    """Cada chamada precisa citar uma ferramenta que existe, com argumentos que o esquema dela aceita."""
    problems = []
    for position, call in enumerate(calls, start=1):
        tool = tools.get(call.tool)
        label = f"{task.title}, chamada {position} ({call.tool})"
        if tool is None:
            problems.append(f"{label}: a ferramenta não existe no servidor MCP.")
            continue
        schema = tool.input_schema
        allowed = set((schema.get("properties") or {}).keys())
        for name in call.arguments:
            if name not in allowed:
                problems.append(f"{label}: o argumento '{name}' não existe (aceitos: {sorted(allowed)}).")
        for error in Draft202012Validator(schema).iter_errors(call.arguments):
            where = ".".join(str(part) for part in error.path) or "argumentos"
            problems.append(f"{label}: {where}: {error.message}")
    return problems


_COMMAND = re.compile(r"dmaker[ \t]+[^\n`]+")


def extract_commands(text: str) -> list[str]:
    """Os comandos `dmaker ...` que a resposta escreve (em bloco de código ou entre crases), sem repetição."""
    found = (match.group(0).strip().rstrip(".,;:)") for match in _COMMAND.finditer(text))
    return list(dict.fromkeys(found))


def shell_commands(markdown: str) -> list[str]:
    """Os comandos `dmaker ...` dos blocos de código, com as continuações de linha (crase) já unidas."""
    commands = []
    for block in _SHELL_FENCE.findall(markdown):
        joined = re.sub(r"[ \t]*`[ \t]*\n\s*", " ", block)
        for raw in joined.splitlines():
            line = raw.strip().lstrip("> ").strip()
            if line.startswith("dmaker "):
                commands.append(line)
    return commands


def _tokens(line: str) -> list[str]:
    tokens = []
    for token in _TOKEN.findall(line):
        if token.startswith("#"):
            break
        tokens.append(token)
    return tokens


def command_problem(line: str, root: Any, require_arguments: bool = True) -> str | None:
    """`None` se o comando e as opções existem na CLI; senão, o que está errado.

    `require_arguments=False` aceita o comando citado sem os argumentos (numa frase, "rode `dmaker validate`"), mas
    ainda recusa argumento a mais, que é o sinal de um subcomando inventado.
    """
    tokens = _tokens(line)
    node = root
    path: list[str] = []
    index = 1  # tokens[0] é "dmaker"
    while is_group(node) and index < len(tokens):
        token = tokens[index]
        if token in node.commands:
            node = node.commands[token]
            path.append(token)
            index += 1
        elif token.startswith("-"):
            break
        elif "run" in node.commands:  # `dmaker dub ARQUIVO`: o grupo manda o que não é comando para `run`
            node = node.commands["run"]
            path.append("run")
        else:
            return f"'{token}' não é um comando de 'dmaker {' '.join(path)}'.".replace("  ", " ")
    if is_group(node):
        return f"'dmaker {' '.join(path)}' é um grupo: falta o subcomando."
    known = option_names(node)
    for token in tokens[index:]:
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            if name not in known:
                return f"a opção {name} não existe em 'dmaker {' '.join(path)}'."
    return _arguments_problem(node, tokens[index:], path, require_arguments)


def _arguments_problem(node: Any, rest: list[str], path: list[str], require_all: bool) -> str | None:
    """Confere quantos argumentos (não opções) o comando recebe: de mais é o erro típico de um subcomando inventado."""
    by_name = {}
    for param in node.params:
        for name in (*(getattr(param, "opts", ()) or ()), *(getattr(param, "secondary_opts", ()) or ())):
            by_name[name] = param
    positionals = 0
    position = 0
    while position < len(rest):
        token = rest[position]
        if token.startswith("--"):
            param = by_name.get(token.split("=", 1)[0])
            takes_value = param is not None and not getattr(param, "is_flag", False) and "=" not in token
            position += 2 if takes_value else 1
            continue
        positionals += 1
        position += 1
    arguments = [param for param in node.params if is_argument(param)]
    most = None if any(getattr(param, "nargs", 1) == -1 for param in arguments) else len(arguments)
    least = sum(1 for param in arguments if param.required)
    label = f"dmaker {' '.join(path)}"
    if most is not None and positionals > most:
        return f"'{label}' recebe {most} argumento(s) e o exemplo passa {positionals}."
    if require_all and positionals < least:
        return f"'{label}' precisa de {least} argumento(s) e o exemplo passa {positionals}."
    return None


def cli_problems(task: Task, root: Any) -> list[str]:
    """Todos os comandos `dmaker` escritos nas partes da tarefa que existem na CLI."""
    problems = []
    for key in ("ia", "cli", "conferir", "erros", "antes", "interface"):
        for line in shell_commands(task.parts.get(key, "")):
            problem = command_problem(line, root)
            if problem:
                problems.append(f"{task.title}: `{line}`: {problem}")
    return problems
