"""Rotas dos analisadores de áudio da interface: o catálogo e a análise de um item do projeto.

Adaptador fino sobre `analysis.analyzer_catalog` e `pipeline.audio_analysis`, os mesmos que a ferramenta MCP
`audio_analyze` e o comando `dmaker audio analyze` usam. A interface usa a análise para desenhar o gráfico do espectro
(frequência × dB, com o cursor que mostra a frequência, a nota e o nível). A rota só LÊ: ela não grava marcadores nem
arquivos, que são decisão de quem pede pela CLI ou pelo MCP.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from ..analysis import analyzer_catalog
from ..media.ffmpeg import FFmpegError, SubprocessRunner
from ..pipeline.audio_analysis import AnalysisRequest, AudioAnalysisService
from ..pipeline.projects import load_project

# Quantos pontos a curva do gráfico leva: a tela tem poucos pixels de largura, e o pico de cada grupo é guardado
CURVE_POINTS = 1024


class AudioAnalysisBody(BaseModel):
    """O pedido de análise: o analisador, o item (o mesmo alvo dos efeitos, ou `output`) e o trecho dele."""

    analyzer: str = "spectrum"
    target: str | None = None
    start: float | str | None = None
    end: float | str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    points: int = Field(CURVE_POINTS, ge=64, le=8192)


def build_audio_analysis_router() -> APIRouter:
    router = APIRouter(tags=["análise de áudio"])

    @router.get("/api/audio-analyzers")
    def list_audio_analyzers(type: str | None = None) -> dict:
        try:
            return analyzer_catalog(type)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/projects/{name}/audio-analysis")
    def analyze_audio(name: str, body: AudioAnalysisBody) -> dict:
        try:
            project = load_project(name)
            request = AnalysisRequest(
                body.analyzer, body.params, target=body.target, start=body.start, end=body.end, mark=False
            )
            outcome = AudioAnalysisService(SubprocessRunner(quiet=True)).analyze(project, request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, ValidationError, FFmpegError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return outcome.to_dict(limit=body.points)

    return router
