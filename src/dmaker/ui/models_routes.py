"""Rotas dos modelos de IA da interface: ver o que está baixado, baixar (job com progresso), apagar e limpar sobras.

Adaptador fino sobre `pipeline.models_service`. Apagar exige `confirm: true` no corpo: a interface mostra o
aviso (vindo de `GET /{id}/removal`) e só então manda a confirmação.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..pipeline.jobs import JobManager
from ..pipeline.models_service import (
    ConfirmationRequired,
    ModelBusy,
    ModelError,
    ModelService,
    UnknownModel,
    job_progress_reporter,
    shared_service,
)


def get_model_service() -> ModelService:
    return shared_service()


Service = Annotated[ModelService, Depends(get_model_service)]


class RemoveRequest(BaseModel):
    confirm: bool = False


class PruneRequest(BaseModel):
    confirm: bool = False
    paths: list[str] | None = None  # as sobras que a pessoa viu na lista; sem isso vale tudo o que for sobra


def _http(exc: ModelError) -> HTTPException:
    if isinstance(exc, UnknownModel):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ModelBusy | ConfirmationRequired):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def build_models_router(jobs: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api/models", tags=["modelos"])

    @router.get("")
    def inventory(service: Service) -> dict:
        return service.inventory().to_dict()

    @router.get("/{model_id}/removal")
    def removal_plan(model_id: str, service: Service) -> dict:
        try:
            return service.plan_removal(model_id).to_dict()
        except ModelError as exc:
            raise _http(exc) from exc

    @router.post("/{model_id}/download")
    def download(model_id: str, service: Service) -> dict:
        try:
            spec = service.spec(model_id)
        except ModelError as exc:
            raise _http(exc) from exc
        running = jobs.find_running(lambda job: job.meta.get("model") == model_id)
        if running:  # clicar duas vezes acompanha o download que já existe
            return {"job_id": running.id}
        job = jobs.start(
            f"baixar modelo ({spec.name})",
            lambda job: service.download(model_id, job_progress_reporter(job, spec.name)).to_dict(),
            meta={"kind": "models", "model": model_id},
        )
        return {"job_id": job.id}

    @router.post("/{model_id}/remove")
    def remove(model_id: str, body: RemoveRequest, service: Service) -> dict:
        try:
            return {"removed": service.remove(model_id, confirm=body.confirm).to_dict()}
        except ModelError as exc:
            raise _http(exc) from exc

    @router.post("/prune")
    def prune(body: PruneRequest, service: Service) -> dict:
        try:
            return {"removed": service.prune(confirm=body.confirm, only=body.paths).to_dict()}
        except ModelError as exc:
            raise _http(exc) from exc

    return router
