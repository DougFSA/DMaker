"""Rotas /api/transitions da interface: o catálogo das transições e a folha de contato de cada uma.

Adaptador fino sobre `pipeline.transition_preview`. A folha é gerada na primeira vez que alguém pede e fica em
cache; a galeria pede várias de uma vez, então a geração é uma por vez para não abrir dezenas de ffmpeg juntos.
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..domain.curves import CURVES
from ..domain.transitions import all_transition_names, catalog
from ..media.ffmpeg import FFmpegError, SubprocessRunner
from ..pipeline.transition_preview import TransitionPreview

_generation_lock = threading.Lock()


def get_transition_preview() -> TransitionPreview:
    return TransitionPreview(SubprocessRunner(quiet=True))


Preview = Annotated[TransitionPreview, Depends(get_transition_preview)]


def build_transitions_router() -> APIRouter:
    router = APIRouter(prefix="/api/transitions", tags=["transições"])

    @router.get("")
    def list_transitions() -> dict:
        return {
            "curves": list(CURVES),
            "transitions": [
                {"name": info.name, "kind": info.kind, "summary": info.summary} for info in catalog()
            ],
        }

    @router.get("/{name}/sheet")
    def transition_sheet(name: str, preview: Preview, curve: str = "linear") -> FileResponse:
        if name not in all_transition_names():
            raise HTTPException(status_code=404, detail=f"Transição desconhecida: {name}")
        if curve not in CURVES:
            raise HTTPException(
                status_code=400, detail=f"Curva desconhecida: {curve}. Use {', '.join(CURVES)}."
            )
        try:
            with _generation_lock:
                path = preview.sheet(name, curve)
        except FFmpegError as exc:
            raise HTTPException(
                status_code=500, detail=f"Não foi possível gerar a prévia: {exc.args[0]}"
            ) from exc
        return FileResponse(path, media_type="image/png")

    return router
