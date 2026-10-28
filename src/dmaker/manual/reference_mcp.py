"""Referência das ferramentas MCP, gerada do registro do servidor: o manual nunca fica sem uma ferramenta nova."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ`])")
_TYPE_NAMES = {
    "string": "texto",
    "integer": "inteiro",
    "number": "número",
    "boolean": "sim ou não",
    "array": "lista",
    "object": "objeto",
}


@dataclass(frozen=True)
class ToolDoc:
    """O que o manual precisa saber de uma ferramenta: o nome, o que ela faz e o esquema dos argumentos."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """A primeira frase da descrição, que basta para saber para que a ferramenta serve."""
        text = " ".join(self.description.split())
        return _SENTENCE_END.split(text, maxsplit=1)[0] if text else ""


def tool_docs(tools: Iterable[Any]) -> list[ToolDoc]:
    """Converte as ferramentas devolvidas pelo servidor MCP (`list_tools`) no formato do manual."""
    return [
        ToolDoc(name=tool.name, description=tool.description or "", input_schema=dict(tool.input_schema))
        for tool in tools
    ]


def schema_type_label(prop: dict[str, Any]) -> str:
    """Um nome curto, em português, para o tipo de um parâmetro (valores fixos viram a lista deles)."""
    if "enum" in prop:
        return " ou ".join(f'"{value}"' for value in prop["enum"])
    for key in ("anyOf", "oneOf"):
        if key in prop:
            options = [option for option in prop[key] if option.get("type") != "null"]
            labels = [schema_type_label(option) for option in options]
            return " ou ".join(dict.fromkeys(labels)) or "qualquer valor"
    kind = prop.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    label = _TYPE_NAMES.get(kind or "", "qualquer valor")
    if kind == "array" and isinstance(prop.get("items"), dict) and prop["items"].get("type") in _TYPE_NAMES:
        label = f"lista de {_TYPE_NAMES[prop['items']['type']]}"
    return label


def _default_label(prop: dict[str, Any]) -> str:
    if "default" not in prop or prop["default"] is None:
        return ""
    value = prop["default"]
    shown = {True: "sim", False: "não"}.get(value, value) if isinstance(value, bool) else value
    return f", padrão {shown}"


def parameters_line(tool: ToolDoc) -> str:
    """`nome*` (tipo) para cada parâmetro; o asterisco marca os obrigatórios."""
    properties: dict[str, Any] = tool.input_schema.get("properties") or {}
    if not properties:
        return "Sem parâmetros."
    required = set(tool.input_schema.get("required") or [])
    items = []
    for name, prop in properties.items():
        star = "\\*" if name in required else ""
        items.append(f"`{name}`{star} ({schema_type_label(prop)}{_default_label(prop)})")
    return "Parâmetros: " + ", ".join(items) + "."


def mcp_reference(tools: Sequence[ToolDoc]) -> str:
    """Uma entrada por ferramenta, na ordem do servidor: nome, para que serve e os parâmetros."""
    lines = [
        f"São {len(tools)} ferramentas. Um asterisco (\\*) marca o parâmetro obrigatório. "
        "O texto completo de cada uma vem do próprio servidor (`dmaker mcp`).",
        "",
    ]
    for tool in tools:
        lines.append(f"- **`{tool.name}`**: {tool.summary}")
        lines.append(f"  {parameters_line(tool)}")
    return "\n".join(lines)
