"""Rotas /api/looks da interface: o catálogo dos looks e a folha de contato de cada um.

Adaptador fino sobre `pipeline.look_preview`. A folha é gerada na primeira vez que alguém pede e fica em cache; a
galeria pede várias de uma vez, então a geração é uma por vez para não abrir dezenas de ffmpeg juntos. `brand`
(opcional) soma os looks do brand.json da marca, que valem no lugar dos padrões de mesmo nome.
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..domain.brand import load_theme
from ..domain.looks import NO_LOOK, UnknownLookError, available_looks, look_effects
from ..media.ffmpeg import FFmpegError, SubprocessRunner
from ..pipeline.look_preview import LookPreview

_generation_lock = threading.Lock()


def get_look_preview() -> LookPreview:
    return LookPreview(SubprocessRunner(quiet=True))


Preview = Annotated[LookPreview, Depends(get_look_preview)]


def _brand_looks(brand: str | None) -> dict[str, dict]:
    """Looks declarados pela marca; marca desconhecida ou look inválido na marca viram erro de quem pediu."""
    if not brand or brand == "default":
        return {}
    try:
        theme = load_theme(brand)
        available_looks(theme.looks)  # confere cada look da marca (campo inválido levanta ValueError)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return theme.looks


def build_looks_router() -> APIRouter:
    router = APIRouter(prefix="/api/looks", tags=["looks"])

    @router.get("")
    def list_looks(brand: str | None = None) -> dict:
        looks = available_looks(_brand_looks(brand))
        return {
            "off": NO_LOOK,
            "looks": [
                {
                    "name": look.name,
                    "summary": look.summary,
                    "source": look.source,
                    "effects": look_effects(look),
                }
                for look in looks.values()
            ],
        }

    def _serve(generate) -> FileResponse:
        try:
            with _generation_lock:
                path = generate()
        except UnknownLookError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FFmpegError as exc:
            raise HTTPException(
                status_code=500, detail=f"Não foi possível gerar a prévia: {exc.args[0]}"
            ) from exc
        return FileResponse(path, media_type="image/jpeg")

    @router.get("/sheet")
    def overview_sheet(preview: Preview, brand: str | None = None) -> FileResponse:
        brand_looks = _brand_looks(brand)
        return _serve(lambda: preview.overview(brand_looks))

    @router.get("/{name}/sheet")
    def look_sheet(name: str, preview: Preview, brand: str | None = None) -> FileResponse:
        brand_looks = _brand_looks(brand)
        return _serve(lambda: preview.sheet(name, brand_looks))  # nome desconhecido: 404 (UnknownLookError)

    return router
