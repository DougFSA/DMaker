"""Referência dos comandos da CLI, gerada da árvore do Typer: comando novo aparece no manual sozinho.

Funciona por duck typing (`.commands`, `.params`, `.help`) porque o Typer recente traz o próprio click
embutido, e os objetos de comando já não são os do pacote `click`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

_VALUE_NAMES = {
    "text": "TEXTO",
    "str": "TEXTO",
    "string": "TEXTO",
    "integer": "NÚMERO",
    "int": "NÚMERO",
    "int range": "NÚMERO",
    "float": "NÚMERO",
    "float range": "NÚMERO",
    "path": "CAMINHO",
    "filename": "CAMINHO",
}


def is_group(command: Any) -> bool:
    return getattr(command, "commands", None) is not None


def visible_commands(group: Any) -> list[tuple[str, Any]]:
    """Os subcomandos de um grupo em ordem alfabética, sem os escondidos."""
    return sorted(
        ((name, sub) for name, sub in group.commands.items() if not getattr(sub, "hidden", False)),
        key=lambda item: item[0],
    )


def iter_leaf_commands(root: Any) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Cada comando que executa algo, com o caminho completo (`("voice", "queue", "add")`)."""

    def walk(node: Any, path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], Any]]:
        for name, sub in visible_commands(node):
            if is_group(sub):
                yield from walk(sub, (*path, name))
            else:
                yield (*path, name), sub

    yield from walk(root, ())


def option_names(command: Any) -> set[str]:
    """Todos os nomes de opção que o comando aceita (`--preview`, `--no-ui`...)."""
    names: set[str] = {"--help"}
    for param in command.params:
        names.update(getattr(param, "opts", ()) or ())
        names.update(getattr(param, "secondary_opts", ()) or ())
    return {name for name in names if name.startswith("-")}


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _first_paragraph(text: str | None) -> str:
    return _clean((text or "").strip().split("\n\n")[0])


def is_argument(param: Any) -> bool:
    return type(param).__name__.endswith("Argument")


def usage(path: tuple[str, ...], command: Any) -> str:
    """`dmaker render SPEC`: o comando com os argumentos que ele pede (entre colchetes, os opcionais)."""
    parts = ["dmaker", *path]
    for param in command.params:
        if not is_argument(param):
            continue
        name = (getattr(param, "metavar", None) or param.name).upper()
        if getattr(param, "nargs", 1) == -1:
            name += "..."
        parts.append(name if param.required else f"[{name}]")
    return " ".join(parts)


def _value_name(param: Any) -> str:
    type_name = getattr(getattr(param, "type", None), "name", "") or ""
    choices = getattr(param.type, "choices", None)
    if choices:
        return "|".join(str(choice) for choice in choices)
    return _VALUE_NAMES.get(type_name, "VALOR")


def _default_note(param: Any) -> str:
    default = getattr(param, "default", None)
    if getattr(param, "is_flag", False):
        return "ligada por padrão" if default is True else ""
    empty = default is None or default is False or default == "" or default == () or default == []
    if empty or callable(default):
        return ""
    return f"padrão {default}"


def option_line(param: Any) -> str:
    """Uma linha por opção: os nomes, o valor esperado, a ajuda e o padrão."""
    opts = list(getattr(param, "opts", ()))
    secondary = list(getattr(param, "secondary_opts", ()))
    names = " / ".join(f"`{name}`" for name in [*opts, *secondary])
    value = "" if getattr(param, "is_flag", False) else f" {_value_name(param)}"
    notes = [note for note in (_default_note(param),) if note]
    if getattr(param, "required", False):
        notes.append("obrigatória")
    if getattr(param, "multiple", False):
        notes.append("pode repetir")
    help_text = _clean(getattr(param, "help", None))
    suffix = f" ({'; '.join(notes)})" if notes else ""
    body = f"{help_text}{suffix}".strip()
    return f"  - {names}{value}: {body}" if body else f"  - {names}{value}"


def command_entry(path: tuple[str, ...], command: Any) -> list[str]:
    lines = [f"- **`{usage(path, command)}`**: {_first_paragraph(command.help)}"]
    for param in command.params:
        if is_argument(param) or getattr(param, "hidden", False) or not getattr(param, "opts", None):
            continue
        lines.append(option_line(param))
    return lines


def cli_reference(root: Any) -> str:
    """Todos os comandos agrupados: os avulsos primeiro, depois um grupo por vez (`voice`, `dub`...)."""
    leaves = list(iter_leaf_commands(root))
    loose = [(path, cmd) for path, cmd in leaves if len(path) == 1]
    out = [
        f"São {len(leaves)} comandos. `dmaker COMANDO --help` mostra o mesmo texto na tela, "
        "com a versão instalada.",
        "",
        "#### Comandos avulsos",
        "",
    ]
    for path, command in loose:
        out.extend(command_entry(path, command))
    groups: dict[tuple[str, ...], list[tuple[tuple[str, ...], Any]]] = {}
    for path, command in leaves:
        if len(path) > 1:
            groups.setdefault(path[:-1], []).append((path, command))
    for group_path in sorted(groups):
        node = root
        for name in group_path:
            node = node.commands[name]
        out.extend(["", f"#### dmaker {' '.join(group_path)}", ""])
        if _first_paragraph(getattr(node, "help", None)):
            out.extend([_first_paragraph(node.help), ""])
        for path, command in groups[group_path]:
            out.extend(command_entry(path, command))
    return "\n".join(out)
