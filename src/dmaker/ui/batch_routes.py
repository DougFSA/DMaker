"""Rotas /api/batches da interface: lote de vídeos a partir de uma planilha (validar, rodar, pausar, retomar).

Adaptador fino sobre `pipeline.batch`. O lote roda como um job (o andamento por vídeo chega pelo SSE de
jobs) e o estado de cada linha vem do arquivo do lote, que a tela relê enquanto o job anda. Um lote por vez:
os renders disputam a mesma CPU.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from ..domain.batch_sheet import SheetError
from ..domain.templates import TemplateError
from ..pipeline.batch import BatchError, BatchExistsError, BatchInvalidError, BatchService, run_in_job
from ..pipeline.batch_state import BatchFileError, BatchNotFoundError
from ..pipeline.jobs import Job, JobManager

BATCH_KIND = "batch"

# erro de entrada (planilha, modelo, arquivo, pedido) vira 400 com a frase pronta para a tela
INPUT_ERRORS = (SheetError, TemplateError, BatchError, FileNotFoundError, ValidationError)


def get_batch_service() -> BatchService:
    return BatchService()


Batches = Annotated[BatchService, Depends(get_batch_service)]


class ValidateBody(BaseModel):
    template: str
    sheet: str
    name_column: str | None = None


class StartBody(ValidateBody):
    name: str | None = None
    skip_invalid: bool = False
    preview: bool = False
    preset: str | None = None


class ResumeBody(BaseModel):
    rows: list[int] | None = None
    force: bool = False


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc.args[0] if isinstance(exc, KeyError) else exc))


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc.args[0]))


def build_batch_router(jobs: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api/batches", tags=["lote"])

    def running_job(name: str | None = None) -> Job | None:
        return jobs.find_running(
            lambda job: job.meta.get("kind") == BATCH_KIND and (name is None or job.meta.get("batch") == name)
        )

    def ensure_idle(service: BatchService, name: str | None = None) -> None:
        """Um lote por vez: dois renders ao mesmo tempo disputam a CPU e atrasam os dois."""
        if running_job() is not None or (name is not None and service.active(name)):
            raise HTTPException(
                status_code=409, detail="Já há um lote rodando; espere ele terminar ou pause-o."
            )

    def start_job(service: BatchService, name: str, rows: list[int] | None, force: bool) -> Job:
        ensure_idle(service, name)
        return jobs.start(
            f"lote {name}",
            lambda job: run_in_job(service, name, job, rows, force),
            meta={"kind": BATCH_KIND, "batch": name, "cancellable": True},
        )

    def view(service: BatchService, name: str) -> dict:
        report = service.report(name)
        job = running_job(name)
        return {**report.to_dict(), "text": report.to_text(), "job_id": job.id if job else None}

    @router.get("")
    def list_batches(service: Batches) -> dict:
        return {"batches": [{**report.to_dict(), "rows": len(report.rows)} for report in service.reports()]}

    @router.post("/validate")
    def validate(body: ValidateBody, service: Batches) -> dict:
        try:
            validation = service.validate(body.template, body.sheet, body.name_column)
        except INPUT_ERRORS as exc:
            raise _bad_request(exc) from exc
        return {**validation.to_dict(), "text": validation.to_text()}

    @router.post("")
    def start(body: StartBody, service: Batches) -> dict:
        ensure_idle(service)
        try:
            batch = service.create(
                body.template,
                body.sheet,
                name=body.name,
                name_column=body.name_column,
                preview=body.preview,
                preset=body.preset,
                skip_invalid=body.skip_invalid,
            )
        except BatchInvalidError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BatchExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except INPUT_ERRORS as exc:
            raise _bad_request(exc) from exc
        job = start_job(service, batch.name, None, False)
        return {"name": batch.name, "job_id": job.id}

    @router.get("/{name}")
    def get_batch(name: str, service: Batches) -> dict:
        try:
            return view(service, name)
        except BatchNotFoundError as exc:
            raise _not_found(exc) from exc
        except BatchFileError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/{name}/resume")
    def resume(name: str, body: ResumeBody, service: Batches) -> dict:
        try:
            service.report(name)
        except BatchNotFoundError as exc:
            raise _not_found(exc) from exc
        job = start_job(service, name, body.rows, body.force)
        return {"name": name, "job_id": job.id}

    @router.post("/{name}/pause")
    def pause(name: str, service: Batches) -> dict:
        try:
            service.pause(name)
        except BatchNotFoundError as exc:
            raise _not_found(exc) from exc
        return {"name": name, "pause_requested": True}

    @router.delete("/{name}")
    def remove(name: str, service: Batches) -> dict:
        try:
            service.report(name)
        except BatchNotFoundError as exc:
            raise _not_found(exc) from exc
        if service.active(name):
            raise HTTPException(status_code=409, detail="O lote está rodando; pause-o antes de remover.")
        service.store.remove(name)
        return {"removed": name}

    return router
