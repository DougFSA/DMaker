"""Rotas do corte automático da interface: cortar as pausas, os vícios e as repetições de uma gravação e
desfazer um corte da lista.

Adaptador fino sobre `pipeline.autocut`. A transcrição é lenta na CPU, então cortar é um job com progresso por
SSE (e um só trabalho pesado de voz por vez); desfazer é uma edição rápida, direta. As dependências pesadas
(ffmpeg, Whisper, leitor de mídia) chegam por `VoiceServices`, que os testes trocam por dublês.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from ..media.ffmpeg import SubprocessRunner
from ..media.probe import probe
from ..pipeline.autocut import AutoCutRequest, AutoCutService, undo_cut
from ..pipeline.jobs import Job, JobManager, stage_progress
from ..voice.cut_plan import CutOptions
from .voice_routes import Services, VoiceServices, exclusive_synthesis


class AutoCutBody(BaseModel):
    source: str
    name: str
    intensity: Literal["suave", "normal", "agressiva"] = "normal"
    min_pause: float = Field(0.5, gt=0, le=10)
    breath: float = Field(0.15, ge=0, le=2)
    preset: str = "instagram/reels"
    brand: str | None = None
    captions: bool = True
    language: str = "pt"
    model: str = "small"
    overwrite: bool = False


def _service(job: Job | None, services: VoiceServices) -> AutoCutService:
    runner = services.runner or (SubprocessRunner(sink=job.sink()) if job else SubprocessRunner(quiet=True))
    return AutoCutService(
        runner=runner,
        prober=services.prober or probe,
        transcriber=services.transcriber,
        log=job.log if job else (lambda message: None),
    )


def _run_autocut(job: Job, services: VoiceServices, request: AutoCutRequest) -> dict:
    with exclusive_synthesis(job):
        result = _service(job, services).cut(request, stage_progress(job))
    return {
        "project": result.project.name,
        "spec_path": str(result.spec_path),
        "report": result.report.to_dict(),
        "warnings": result.warnings,
    }


def build_autocut_router(jobs: JobManager) -> APIRouter:
    router = APIRouter(tags=["corte automático"])

    @router.post("/api/autocut")
    def start_autocut(body: AutoCutBody, services: Services) -> dict:
        try:
            request = AutoCutRequest(
                source=Path(body.source),
                name=body.name.strip(),
                options=CutOptions(intensity=body.intensity, min_pause=body.min_pause, breath=body.breath),
                preset=body.preset,
                brand=body.brand or None,
                captions=body.captions,
                language=body.language,
                model=body.model,
                overwrite=body.overwrite,
            )
            _service(None, services).validate(request)  # o erro aparece já, não depois de minutos de job
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, KeyError, ValidationError) as exc:
            raise HTTPException(
                status_code=400, detail=str(exc.args[0] if isinstance(exc, KeyError) else exc)
            ) from exc
        job = jobs.start(
            f"cortar pausas e vícios ({request.name})",
            lambda job: _run_autocut(job, services, request),
            meta={"kind": "autocut", "project": request.name},
        )
        return {"job_id": job.id}

    @router.post("/api/projects/{name}/cuts/{cut_id}/undo")
    def undo(name: str, cut_id: int) -> dict:
        try:
            return undo_cut(name, cut_id).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
