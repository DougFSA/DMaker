"""Esquema de parâmetros de um infográfico pronto: o que cada composição aceita e a conferência dos valores.

Cada pasta de `templates/html/<nome>/` traz um `esquema.json` ao lado do `index.html`, com o nome, o rótulo e o
tipo de cada parâmetro, o padrão e os limites. É a fonte única de três consumidores: o formulário da interface, a
IA (que sabe o que pode mudar sem ler o HTML) e a validação do projeto, que aponta o valor fora do esquema antes
do render. Tudo aqui é puro: recebe dados, devolve dados, não toca disco.

Formato do arquivo (chaves em inglês, textos em português, como os modelos de projeto em `templates/*.json`):

    {
      "title": "Contador",                    # nome para mostrar
      "description": "uma frase do que faz",
      "size": [900, 360],                     # tamanho natural da página, em px na base 1080
      "area": {"x": 0.5, "y": 0.27, "width": 0.8, "height": 0.2},   # onde entra quando ninguém diz (frações)
      "duration": 4,                          # duração sugerida na tela, em segundos
      "example": {"ate": 10000},              # parâmetros de um exemplo que funciona
      "caption_anchor": {...},                # opcional: o modelo pode ser preso a uma palavra da legenda
      "params": {
        "ate": {"type": "number", "label": "Termina em", "required": true, "min": -1000000, "max": 1000000},
        "tipo": {"type": "choice", "label": "Tipo", "default": "circulo", "options": ["circulo", "risco"]}
      }
    }

Tipos de parâmetro: `number`, `integer`, `text` (`max_length`), `choice` (`options`), `bool`, `color` (`#RRGGBB` ou
o nome de uma cor da marca) e `path` (arquivo, conferido pelo projeto). `caption_anchor` diz quais parâmetros
guardam a palavra, a ocorrência, a permanência e a folga, para o resolvedor que prende o modelo à legenda
(`pipeline/infographic_anchor.py`) não precisar saber nada de nenhum modelo em particular.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

PARAM_TYPES = ("number", "integer", "text", "choice", "bool", "color", "path")

# nomes de cor que um parâmetro `color` aceita além do hex: as chaves de cor da marca (`theme.colors`)
BRAND_COLOR_NAMES = ("primary", "accent", "icon", "mint", "text", "muted", "white", "bg", "bg_dark")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ANCHOR_KEYS = ("word", "occurrence", "hold", "margin")


class SchemaError(ValueError):
    """O `esquema.json` de um infográfico está mal escrito (erro de quem escreve o modelo, não de quem o usa)."""


def _json_number(value: float | None) -> float | int | None:
    """Um limite sem o `.0` inútil (1000000000, não 1000000000.0) quando ele é inteiro."""
    if value is not None and float(value).is_integer():
        return int(value)
    return value


@dataclass(frozen=True)
class ParamSchema:
    """Um parâmetro: o nome (a chave em `data`), o tipo, o rótulo da interface e os limites."""

    name: str
    type: str
    label: str
    description: str = ""
    default: Any = None
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[str, ...] = ()
    max_length: int | None = None
    example: Any = None

    def to_dict(self) -> dict[str, Any]:
        """A forma JSON que a interface e as ferramentas MCP recebem (sem os campos vazios)."""
        data: dict[str, Any] = {"name": self.name, "type": self.type, "label": self.label}
        if self.description:
            data["description"] = self.description
        data["required"] = self.required
        for key, value in (
            ("default", self.default),
            ("min", _json_number(self.minimum)),
            ("max", _json_number(self.maximum)),
            ("max_length", self.max_length),
            ("example", self.example),
        ):
            if value is not None:
                data[key] = value
        if self.options:
            data["options"] = list(self.options)
        return data


@dataclass(frozen=True)
class CaptionAnchorKeys:
    """Quais parâmetros do modelo dizem a palavra da legenda, a ocorrência, a permanência e a folga em volta."""

    word: str
    occurrence: str
    hold: str
    margin: str


@dataclass(frozen=True)
class InfographicSchema:
    name: str
    title: str
    description: str
    params: dict[str, ParamSchema]
    size: tuple[int, int] = (900, 400)
    area: dict[str, float] = field(default_factory=dict)
    duration: float = 4.0
    example: dict[str, Any] = field(default_factory=dict)
    caption_anchor: CaptionAnchorKeys | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "size": list(self.size),
            "area": dict(self.area),
            "duration": self.duration,
            "example": dict(self.example),
            "anchors_to_caption": self.caption_anchor is not None,
            "params": [param.to_dict() for param in self.params.values()],
        }


@dataclass(frozen=True)
class ParamIssue:
    """Um valor fora do esquema. `param` é a chave em `data` e `detail` o que está errado, sem repetir a chave
    (o projeto a põe depois do caminho do campo: `overlays[0].data.ate: precisa ser um número`)."""

    param: str
    detail: str

    @property
    def message(self) -> str:
        """A frase inteira, com a chave na frente, para quem mostra o erro sozinho (CLI, ferramenta MCP)."""
        return f"`{self.param}` {self.detail}"


# ---------- leitura do esquema ----------


def _number(value: Any, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SchemaError(f"{where}: esperava um número, veio {value!r}")
    return float(value)


def _parse_param(owner: str, name: str, raw: Any) -> ParamSchema:
    where = f"{owner}: parâmetro {name!r}"
    if not isinstance(raw, dict):
        raise SchemaError(f"{where}: esperava um objeto com type e label")
    kind = raw.get("type")
    if kind not in PARAM_TYPES:
        raise SchemaError(f"{where}: tipo desconhecido {kind!r} (use {', '.join(PARAM_TYPES)})")
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        raise SchemaError(f"{where}: falta o rótulo em português (`label`)")
    options = tuple(raw.get("options") or ())
    if kind == "choice" and (not options or not all(isinstance(item, str) for item in options)):
        raise SchemaError(f"{where}: `choice` precisa de `options`, uma lista de textos")
    minimum, maximum = _number(raw.get("min"), where), _number(raw.get("max"), where)
    if kind in ("number", "integer") and (minimum is None or maximum is None):
        raise SchemaError(f"{where}: `{kind}` precisa de `min` e `max` (todo valor tem um limite)")
    max_length = raw.get("max_length")
    if kind == "text" and (not isinstance(max_length, int) or max_length < 1):
        raise SchemaError(f"{where}: `text` precisa de `max_length` (um número de caracteres)")
    required = bool(raw.get("required", False))
    default = raw.get("default")
    if required and default is not None:
        raise SchemaError(f"{where}: um parâmetro obrigatório não tem padrão")
    param = ParamSchema(
        name=name,
        type=kind,
        label=label.strip(),
        description=str(raw.get("description", "")).strip(),
        default=default,
        required=required,
        minimum=minimum,
        maximum=maximum,
        options=options,
        max_length=max_length if kind == "text" else None,
        example=raw.get("example"),
    )
    if default is not None:
        issue = _check_value(param, default)
        if issue:
            raise SchemaError(f"{where}: o padrão não passa no próprio esquema ({issue})")
    return param


def _parse_anchor(owner: str, raw: Any, params: Mapping[str, ParamSchema]) -> CaptionAnchorKeys:
    if not isinstance(raw, dict) or set(raw) != set(_ANCHOR_KEYS):
        raise SchemaError(f"{owner}: `caption_anchor` precisa de {', '.join(_ANCHOR_KEYS)}")
    for key, param_name in raw.items():
        if param_name not in params:
            raise SchemaError(
                f"{owner}: `caption_anchor.{key}` aponta para {param_name!r}, que não é um parâmetro"
            )
        if key != "word" and params[param_name].default is None:
            raise SchemaError(
                f"{owner}: o parâmetro {param_name!r} (`caption_anchor.{key}`) precisa de um padrão"
            )
    return CaptionAnchorKeys(**raw)


def parse_schema(name: str, raw: Any) -> InfographicSchema:
    """O esquema de um infográfico a partir do JSON lido. Levanta `SchemaError` dizendo o que está errado."""
    if not isinstance(raw, dict):
        raise SchemaError(f"{name}: o esquema precisa ser um objeto JSON")
    for key in ("title", "description", "params"):
        if key not in raw:
            raise SchemaError(f"{name}: falta `{key}` no esquema")
    params_raw = raw["params"]
    if not isinstance(params_raw, dict) or not params_raw:
        raise SchemaError(f"{name}: `params` precisa ser um objeto com pelo menos um parâmetro")
    params = {key: _parse_param(name, key, value) for key, value in params_raw.items()}
    size = raw.get("size", [900, 400])
    if not (
        isinstance(size, list)
        and len(size) == 2
        and all(isinstance(side, int) and 16 <= side <= 8192 for side in size)
    ):
        raise SchemaError(f"{name}: `size` precisa ser [largura, altura] em px, de 16 a 8192")
    area = raw.get("area", {})
    if area and (
        set(area) != {"x", "y", "width", "height"}
        or not all(isinstance(v, int | float) and 0 < v <= 1 for v in area.values())
    ):
        raise SchemaError(f"{name}: `area` precisa de x, y, width e height, frações entre 0 e 1")
    duration = _number(raw.get("duration", 4.0), f"{name}: duration")
    if duration is None or duration <= 0:
        raise SchemaError(f"{name}: `duration` precisa ser maior que zero")
    schema = InfographicSchema(
        name=name,
        title=str(raw["title"]),
        description=str(raw["description"]),
        params=params,
        size=(size[0], size[1]),
        area={key: float(value) for key, value in area.items()},
        duration=duration,
        example=dict(raw.get("example") or {}),
        caption_anchor=(
            _parse_anchor(name, raw["caption_anchor"], params) if raw.get("caption_anchor") else None
        ),
    )
    issues = validate_params(schema, schema.example)
    if issues:
        raise SchemaError(f"{name}: o `example` não passa no próprio esquema ({issues[0].message})")
    return schema


# ---------- conferência dos valores ----------


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _shown(value: Any) -> str:
    return f"o texto {value!r}" if isinstance(value, str) else f"{value!r}"


def _check_value(param: ParamSchema, value: Any, color_names: Collection[str] | None = None) -> str | None:
    """O que está errado com `value` para este parâmetro (sem repetir a chave), ou None se está certo."""
    if param.type in ("number", "integer"):
        if not _is_number(value):
            return f"precisa ser um número (veio {_shown(value)})"
        if param.type == "integer" and float(value) != int(value):
            return f"precisa ser um número inteiro (veio {value})"
        if value < (param.minimum if param.minimum is not None else -math.inf):
            return f"não pode ser menor que {_plain(param.minimum)} (veio {_plain(value)})"
        if value > (param.maximum if param.maximum is not None else math.inf):
            return f"não pode passar de {_plain(param.maximum)} (veio {_plain(value)})"
    elif param.type == "text":
        if not isinstance(value, str):
            return f"precisa ser um texto (veio {_shown(value)})"
        if param.max_length is not None and len(value) > param.max_length:
            return f"tem {len(value)} caracteres e o limite é {param.max_length}"
    elif param.type == "choice":
        if value not in param.options:
            return f"precisa ser um destes: {', '.join(param.options)} (veio {_shown(value)})"
    elif param.type == "bool":
        if not isinstance(value, bool):
            return f"precisa ser verdadeiro ou falso (veio {_shown(value)})"
    elif param.type == "color":
        known = BRAND_COLOR_NAMES if color_names is None else tuple(color_names)
        if not isinstance(value, str) or not (HEX_COLOR.match(value) or value in known):
            return (
                f"precisa ser uma cor #RRGGBB ou uma cor da marca ({', '.join(known)}); veio {_shown(value)}"
            )
    elif param.type == "path":
        if not isinstance(value, str) or not value.strip():
            return f"precisa ser o caminho de um arquivo (veio {_shown(value)})"
    return None


def _plain(number: float | None) -> str:
    """Número sem o `.0` inútil (`1000000`, não `1000000.0`)."""
    if number is None:
        return ""
    return f"{number:.15g}"


def validate_params(
    schema: InfographicSchema, data: Mapping[str, Any], color_names: Collection[str] | None = None
) -> list[ParamIssue]:
    """Tudo o que está fora do esquema em `data`: chave desconhecida, obrigatório que falta, tipo, limite e opção.
    `color_names` são as cores da marca do projeto (sem ele, vale a lista padrão)."""
    issues: list[ParamIssue] = []
    for key in data:
        if key not in schema.params:
            close = difflib.get_close_matches(str(key), schema.params, n=1)
            hint = f" (quis dizer `{close[0]}`?)" if close else ""
            known = ", ".join(schema.params)
            issues.append(
                ParamIssue(
                    str(key), f"não é um parâmetro do modelo {schema.name}{hint}; os parâmetros são: {known}"
                )
            )
    for name, param in schema.params.items():
        if name not in data or data[name] is None:
            if param.required:
                issues.append(ParamIssue(name, f"é obrigatório no modelo {schema.name} ({param.label})"))
            continue
        message = _check_value(param, data[name], color_names)
        if message:
            issues.append(ParamIssue(name, message))
    return issues


def with_defaults(schema: InfographicSchema, data: Mapping[str, Any]) -> dict[str, Any]:
    """`data` com o padrão do esquema nos parâmetros que faltam (o que o pedido disse sempre vale)."""
    merged: dict[str, Any] = {
        name: param.default for name, param in schema.params.items() if param.default is not None
    }
    merged.update({key: value for key, value in data.items() if value is not None})
    return merged
