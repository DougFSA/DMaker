"""Templates de projeto: specs de exemplo com placeholders que viram um `Project` a partir de poucos
parâmetros, em vez de a IA reescrever o JSON inteiro na mão.

Formato de um template (`templates/*.json`): um JSON de spec normal, mais duas chaves de metadados no
topo, removidas do resultado renderizado:

- `"description"`: frase curta dizendo para que serve o template.
- `"params"`: `{nome: {"description", "default" (opcional), "type" (opcional, inferido do default),
  "required" (opcional, inferido: obrigatório quando não há default)}}`. Tipos: text, path, paths
  (lista de caminhos), number, bool, list.

Placeholders no resto do JSON:

- `"{{nome}}"` sozinho numa string: vira o valor com o tipo original (número, lista, bool...).
- `"{{nome}}"` dentro de um texto maior (`"Oi {{nome}}"`): interpolação de texto (`str(valor)`).
- `{"$for": "lista", "as": "item", "item": {...}}` como item de um array: expande um item para cada
  elemento de `lista` (que precisa ser um parâmetro do tipo lista), com `{{item}}` e `{{item_index}}`
  (índice a partir de 0) disponíveis dentro de `"item"`. Serve para trechos repetidos em quantidade
  variável (imagens, clipes).
- `"$if": "{{nome}}"` num objeto (item de array ou valor de uma chave): o objeto some do resultado se o
  valor não for verdadeiro. Como o índice de `$for` começa em 0 (falso em Python), `"$if": "{{item_index}}"`
  é um jeito direto de pular a transição do primeiro item de uma lista.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config

_VALID_TYPES = {"text", "path", "paths", "number", "bool", "list"}
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class TemplateError(ValueError):
    """Template não encontrado, ou parâmetros faltando/errados para renderizá-lo."""


@dataclass
class TemplateParam:
    name: str
    description: str = ""
    default: Any = None
    type: str = "text"
    required: bool = False


@dataclass
class Template:
    name: str
    description: str
    path: Path
    params: dict[str, TemplateParam] = field(default_factory=dict)
    body: dict = field(default_factory=dict)


def _infer_type(default: Any) -> str:
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, (int, float)):
        return "number"
    if isinstance(default, list):
        return "list"
    return "text"


def _parse_param(name: str, raw: dict) -> TemplateParam:
    raw = raw or {}
    has_default = "default" in raw
    default = raw.get("default")
    param_type = raw.get("type") or (_infer_type(default) if has_default else "text")
    if param_type not in _VALID_TYPES:
        raise TemplateError(
            f'tipo desconhecido no parâmetro "{name}": {param_type!r} (use {", ".join(sorted(_VALID_TYPES))})'
        )
    required = raw.get("required", not has_default)
    return TemplateParam(
        name=name,
        description=raw.get("description", ""),
        default=default if has_default else None,
        type=param_type,
        required=required,
    )


def load_template(path: Path | str) -> Template:
    """Lê um template do disco, separando os metadados (`params`, `description`) do corpo da spec."""
    import json

    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    params_raw = data.pop("params", {})
    description = data.pop("description", "")
    params = {name: _parse_param(name, raw) for name, raw in params_raw.items()}
    return Template(name=path.stem, description=description, path=path, params=params, body=data)


def list_templates(folder: Path | None = None) -> list[Template]:
    folder = Path(folder) if folder else config.TEMPLATES_DIR
    return [load_template(p) for p in sorted(folder.glob("*.json"))]


def find_template(name: str, folder: Path | None = None) -> Template:
    """Procura pelo nome do arquivo (sem .json) ou pelo campo `name` da spec dentro do template."""
    templates = list_templates(folder)
    for t in templates:
        if t.name == name:
            return t
    for t in templates:
        if t.body.get("name") == name:
            return t
    available = ", ".join(t.name for t in templates)
    raise TemplateError(f'template "{name}" não encontrado (disponíveis: {available})')


def _check_type(name: str, param_type: str, value: Any) -> None:
    if value is None:
        return
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    checks = {
        "text": isinstance(value, str),
        "path": isinstance(value, str),
        "paths": isinstance(value, list) and all(isinstance(v, str) for v in value),
        "number": is_number,
        "bool": isinstance(value, bool),
        "list": isinstance(value, list),
    }
    if not checks[param_type]:
        raise TemplateError(f'parâmetro "{name}" precisa ser do tipo "{param_type}" (recebido {value!r})')


_DROP = object()  # marca um objeto removido do resultado por "$if"


def _lookup(name: str, context: dict[str, Any]) -> Any:
    if name not in context:
        raise TemplateError(f'placeholder desconhecido: "{{{{{name}}}}}"')
    return context[name]


def _substitute(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _substitute_str(value, context)
    if isinstance(value, dict):
        return _substitute_dict(value, context)
    if isinstance(value, list):
        return _substitute_list(value, context)
    return value


def _substitute_str(text: str, context: dict[str, Any]) -> Any:
    full = _PLACEHOLDER_RE.fullmatch(text)
    if full:
        return _lookup(full.group(1), context)
    return _PLACEHOLDER_RE.sub(lambda m: str(_lookup(m.group(1), context)), text)


def _substitute_dict(d: dict, context: dict[str, Any]) -> Any:
    if "$if" in d:
        if not _substitute(d["$if"], context):
            return _DROP
        d = {k: v for k, v in d.items() if k != "$if"}
    out = {}
    for k, v in d.items():
        sub = _substitute(v, context)
        if sub is not _DROP:
            out[k] = sub
    return out


def _substitute_list(items: list, context: dict[str, Any]) -> list:
    out = []
    for item in items:
        if isinstance(item, dict) and "$for" in item:
            out.extend(_expand_for(item, context))
            continue
        sub = _substitute(item, context)
        if sub is not _DROP:
            out.append(sub)
    return out


def _expand_for(spec: dict, context: dict[str, Any]) -> list:
    source_name = spec["$for"]
    as_name = spec.get("as", source_name)
    item_template = spec["item"]
    values = _lookup(source_name, context)
    if not isinstance(values, list):
        raise TemplateError(f'"$for" espera uma lista no parâmetro "{source_name}"')
    out = []
    for i, v in enumerate(values):
        item_context = {**context, as_name: v, f"{as_name}_index": i}
        rendered = _substitute(item_template, item_context)
        if rendered is not _DROP:
            out.append(rendered)
    return out


def render_template(template: Template, params: dict[str, Any] | None = None) -> dict:
    """Aplica `params` ao template: valida obrigatórios e tipos, aplica defaults, expande `$for`/`$if`
    e substitui os placeholders. Devolve a spec pronta (sem `params`/`description`)."""
    params = params or {}
    unknown = sorted(set(params) - set(template.params))
    if unknown:
        raise TemplateError(f'template "{template.name}" não tem os parâmetros: {", ".join(unknown)}')
    missing = sorted(name for name, p in template.params.items() if p.required and name not in params)
    if missing:
        raise TemplateError(
            f'faltam parâmetros obrigatórios para o template "{template.name}": {", ".join(missing)}'
        )
    context: dict[str, Any] = {}
    for name, p in template.params.items():
        value = params[name] if name in params else p.default
        _check_type(name, p.type, value)
        context[name] = value
    return _substitute(template.body, context)


def template_summary(template: Template) -> str:
    """Texto curto com nome, descrição e parâmetros do template, barato para a IA ler antes de usá-lo."""
    header = template.name
    if template.description:
        header += f": {template.description}"
    lines = [header]
    for name in sorted(template.params):
        p = template.params[name]
        status = "obrigatório" if p.required else f"padrão={p.default!r}"
        desc = f" - {p.description}" if p.description else ""
        lines.append(f"  {name} ({p.type}, {status}){desc}")
    return "\n".join(lines)
