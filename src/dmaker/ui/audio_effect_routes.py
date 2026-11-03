"""Rota /api/audio-effects da interface: o catálogo dos efeitos de áudio.

Adaptador fino sobre `domain.audio_effects.catalog_payload`, o mesmo que a ferramenta MCP `audio_effects` e o
comando `dmaker audio effects` entregam. A interface monta o painel "Efeitos" (adicionar do catálogo e o
formulário de parâmetros de cada efeito) a partir dele, então um efeito novo aparece lá sem tocar no front.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..domain.audio_effects import catalog_payload


def build_audio_effects_router() -> APIRouter:
    router = APIRouter(prefix="/api/audio-effects", tags=["efeitos de áudio"])

    @router.get("")
    def list_audio_effects(type: str | None = None) -> dict:
        try:
            return catalog_payload(type)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
