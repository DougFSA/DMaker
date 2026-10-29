"""Infográficos prontos como serviço: listar os modelos, ver um quadro com os valores pedidos e pôr um no projeto.

É o que `dmaker infographics`, as ferramentas MCP `list_infographics` e `add_infographic` e a tela "Infográficos"
da interface chamam: adaptadores finos sobre as mesmas funções, para os três falarem a mesma língua. A conferência
dos valores é a do esquema (`domain/infographic_schema.py`) e o quadro sai do mesmo renderizador do
`render_html_frame` (`pipeline/html_frame.py`): o que se vê aqui é o que o vídeo vai mostrar.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..domain.edits import add_overlay
from ..domain.infographic_schema import InfographicSchema, validate_params
from ..domain.infographics import (
    Infographic,
    InfographicError,
    find_infographic,
    load_infographics,
    resolve_infographic,
)
from ..domain.spec import HtmlOverlay, Project
from ..media.html_render import HtmlRenderer
from .html_frame import HtmlFrame, render_html_frame

PREVIEW_AT_RATIO = 0.6  # a prévia mostra o modelo já desenhado: perto de dois terços da duração sugerida


def describe_infographics(folder: Path | None = None) -> list[dict[str, Any]]:
    """Cada modelo com nome, descrição e o esquema dos parâmetros, para a IA e a interface montarem o pedido sem
    abrir o HTML."""
    return [model.schema.to_dict() for model in load_infographics(folder).values()]


def coerce_assignments(schema: InfographicSchema, assignments: Sequence[str]) -> dict[str, Any]:
    """`["ate=10000", "sombra=false"]` vira `{"ate": 10000, "sombra": False}` pelo tipo de cada parâmetro do
    esquema (a linha de comando só tem texto). Chave que o esquema não conhece passa como texto, e a conferência
    dos valores a aponta depois."""
    values: dict[str, Any] = {}
    for item in assignments:
        key, separator, raw = item.partition("=")
        if not separator or not key.strip():
            raise InfographicError(f"parâmetro mal escrito: {item!r} (use nome=valor, como ate=10000)")
        key = key.strip()
        param = schema.params.get(key)
        kind = param.type if param else "text"
        if kind in ("number", "integer"):
            try:
                number = float(raw.replace(",", "."))
            except ValueError:
                values[key] = raw  # a conferência do esquema diz que não é um número
                continue
            values[key] = int(number) if number.is_integer() else number
        elif kind == "bool":
            lowered = raw.strip().lower()
            values[key] = (
                True
                if lowered in ("1", "true", "sim", "verdadeiro")
                else False
                if lowered in ("0", "false", "nao", "não", "falso")
                else raw
            )
        else:
            values[key] = raw
    return values


def _checked(model: Infographic, params: dict[str, Any]) -> None:
    issues = validate_params(model.schema, params)
    if issues:
        raise InfographicError(f"{model.name}: " + "; ".join(issue.message for issue in issues))


def infographic_frame(
    name: str,
    out: Path,
    *,
    params: dict[str, Any] | None = None,
    at: float | None = None,
    size: tuple[int, int] | None = None,
    scale: float = 1.0,
    brand: str | None = None,
    background: str | None = None,
    project: Project | None = None,
    renderer: HtmlRenderer | None = None,
    folder: Path | None = None,
) -> HtmlFrame:
    """O quadro de um modelo com os valores pedidos, em PNG. Sem `at` mostra o modelo já desenhado, sem `size` usa o
    tamanho natural dele. O que o esquema não aceita levanta `InfographicError` antes de abrir o navegador."""
    model = find_infographic(name, folder)
    _checked(model, params or {})
    resolved = resolve_infographic(HtmlOverlay(infographic=name, data=params or {}), project, folder)
    schema = model.schema
    return render_html_frame(
        model.folder,
        out,
        at=schema.duration * PREVIEW_AT_RATIO if at is None else at,
        size=size or schema.size,
        duration=schema.duration,
        scale=scale,
        data=resolved.data,
        files={name: Path(path) for name, path in resolved.files.items()},
        brand=brand,
        background=background,
        renderer=renderer,
    )


def add_infographic(
    project: Project,
    name: str,
    params: dict[str, Any] | None = None,
    *,
    start: float = 0.0,
    end: float | None = None,
    region: str | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    layer: str = "front",
    folder: Path | None = None,
) -> Project:
    """O projeto com o infográfico `name` acrescentado às sobreposições. Parâmetro fora do esquema, modelo que não
    existe e região que o projeto não declara falham aqui, com a mensagem do campo. Sem lugar dito (`region`,
    `x`/`y`, `width`/`height`) o modelo entra na área própria dele. `end` vazio vai até o fim do vídeo."""
    model = find_infographic(name, folder)
    _checked(model, params or {})
    overlay: dict[str, Any] = {
        "type": "html",
        "infographic": name,
        "data": dict(params or {}),
        "start": start,
        "layer": layer,
    }
    for key, value in (
        ("end", end),
        ("region", region),
        ("x", x),
        ("y", y),
        ("width", width),
        ("height", height),
    ):
        if value is not None:
            overlay[key] = value
    return add_overlay(project, overlay)
