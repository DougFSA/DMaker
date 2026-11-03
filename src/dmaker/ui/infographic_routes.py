"""Rotas /api/infographics da interface: o catálogo dos infográficos prontos e um quadro de cada um.

Adaptador fino sobre `pipeline.infographics`, o mesmo serviço do `render_infographic_frame` do MCP e do
`dmaker infographics frame`. O quadro é gerado na primeira vez que alguém pede e fica em cache pelo conteúdo (o
modelo, os valores, o instante, o tamanho e a marca); a geração é uma por vez, porque cada uma abre o Chromium.
`GET .../preview` mostra o modelo com os valores de exemplo (a galeria), `POST .../frame` mostra os valores que
quem usa o formulário digitou.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import config
from ..domain.brand import load_theme
from ..domain.infographic_schema import SchemaError
from ..domain.infographics import Infographic, InfographicError, find_infographic
from ..media.browser import BrowserUnavailable
from ..media.html_render import HtmlRenderError, PlaywrightHtmlRenderer
from ..pipeline.html_layer import content_digest
from ..pipeline.infographics import describe_infographics, infographic_frame

_generation_lock = threading.Lock()
DEFAULT_BACKGROUND = (
    "#0F172A"  # o fundo escuro do modelo "explicativo": o transparente se vê melhor sobre ele
)


class FrameRequest(BaseModel):
    """O que o formulário manda: os valores digitados, o instante, o tamanho da página e a marca."""

    params: dict[str, Any] = Field(default_factory=dict)
    at: float | None = Field(None, ge=0)
    size: tuple[int, int] | None = None
    brand: str | None = None
    background: str | None = None


def example_params(model: Infographic) -> dict[str, Any]:
    """Os valores de exemplo do modelo; um arquivo de exemplo é relativo à pasta do modelo."""
    values = dict(model.schema.example)
    for name, param in model.schema.params.items():
        value = values.get(name)
        if param.type == "path" and isinstance(value, str) and not Path(value).is_absolute():
            values[name] = str(model.folder / value)
    return values


def _cache_key(model: Infographic, request: FrameRequest) -> str:
    theme = load_theme(request.brand)
    payload = {
        "folder": content_digest(model.folder),
        "name": model.name,
        "params": request.params,
        "at": request.at,
        "size": request.size,
        "brand": [theme.key, sorted(theme.colors.items()), theme.font_family, theme.rounded_box_radius],
        "background": request.background,
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def build_infographics_router() -> APIRouter:
    router = APIRouter(prefix="/api/infographics", tags=["infográficos"])

    def _model(name: str) -> Infographic:
        try:
            return find_infographic(name)
        except InfographicError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _frame(model: Infographic, request: FrameRequest) -> FileResponse:
        cache_dir = config.CACHE_DIR / "infographics"
        target = cache_dir / f"{_cache_key(model, request)}.png"
        if not target.exists():
            try:
                with _generation_lock:
                    renderer = PlaywrightHtmlRenderer()
                    reason = renderer.unavailable_reason()
                    if reason:
                        raise BrowserUnavailable(reason)
                    infographic_frame(
                        model.name,
                        target,
                        params=request.params,
                        at=request.at,
                        size=request.size,
                        brand=request.brand,
                        background=request.background or DEFAULT_BACKGROUND,
                        renderer=renderer,
                    )
            except InfographicError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except BrowserUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except (HtmlRenderError, FileNotFoundError, ValueError) as exc:
                raise HTTPException(
                    status_code=500, detail=f"Não foi possível gerar o quadro: {exc}"
                ) from exc
        return FileResponse(target, media_type="image/png")

    @router.get("")
    def list_models() -> dict:
        try:
            return {"infographics": describe_infographics()}
        except SchemaError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/{name}/preview")
    def preview(name: str, brand: str | None = None) -> FileResponse:
        model = _model(name)
        if brand and brand != "default":
            try:
                load_theme(brand)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _frame(model, FrameRequest(params=example_params(model), brand=brand))

    @router.post("/{name}/frame")
    def frame(name: str, request: FrameRequest) -> FileResponse:
        model = _model(name)
        if request.brand and request.brand != "default":
            try:
                load_theme(request.brand)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _frame(model, request)

    return router
