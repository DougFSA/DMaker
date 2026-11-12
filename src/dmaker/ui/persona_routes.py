"""Rotas das personas da interface: cadastro (listar, criar, editar, apagar) e a prévia da persona falando.

Adaptador fino sobre `pipeline.personas` (o mesmo serviço da CLI e do MCP) e `pipeline.persona_preview`. A biblioteca
chega por `get_persona_library`, que os testes trocam com `app.dependency_overrides`. A prévia é um job: o desenho e a
síntese levam segundos a minutos, com o progresso pelo SSE de jobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..persona.engine import PersonaEngineError, engine_for, engine_kinds
from ..persona.library import PersonaLibrary, PersonaNotFoundError
from ..pipeline import personas as service
from ..pipeline.jobs import JobManager
from ..pipeline.persona_preview import MAX_PHRASE_CHARS, render_persona_preview


def get_persona_library() -> PersonaLibrary:
    return PersonaLibrary()


Library = Annotated[PersonaLibrary, Depends(get_persona_library)]


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "2d"
    voice: str | None = None
    appearance: dict[str, Any] = Field(default_factory=dict)
    expressions: list[str] = Field(default_factory=list)
    gestures: list[str] = Field(default_factory=list)


class PersonaChanges(BaseModel):
    """Só os campos enviados mudam (a aparência mescla com a atual)."""

    name: str | None = None
    voice: str | None = None
    appearance: dict[str, Any] | None = None
    expressions: list[str] | None = None
    gestures: list[str] | None = None


class UseRequest(BaseModel):
    project: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)
    placement: str = "segment"  # "segment" (tela cheia) ou "overlay" (no canto)
    start: float = Field(0.0, ge=0)


class PreviewRequest(BaseModel):
    phrase: str = Field(default="", max_length=MAX_PHRASE_CHARS)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PersonaNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _engines() -> list[dict[str, Any]]:
    """Cada tipo de persona com o que ele aceita e, se não está pronto, por quê (a tela mostra a mensagem do motor)."""
    result = []
    for kind in engine_kinds():
        engine = engine_for(kind)
        result.append(
            {
                "kind": kind,
                "expressions": list(engine.expressions),
                "gestures": list(engine.gestures),
                "unavailable": engine.unavailable_reason(),
            }
        )
    return result


def build_persona_router(jobs: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api/personas", tags=["personas"])

    @router.get("")
    def list_personas(library: Library) -> dict:
        return {"personas": service.list_personas(library), "engines": _engines()}

    @router.get("/{persona_id}")
    def get_persona(persona_id: str, library: Library) -> dict:
        try:
            return service.get_persona(persona_id, library)
        except (PersonaNotFoundError, ValueError) as exc:
            raise _http(exc) from exc

    @router.post("")
    def create_persona(body: PersonaCreate, library: Library) -> dict:
        try:
            return service.create_persona(
                body.name,
                body.kind,
                body.voice,
                body.appearance,
                body.expressions,
                body.gestures,
                library=library,
            )
        except (PersonaEngineError, ValueError) as exc:
            raise _http(exc) from exc

    @router.put("/{persona_id}")
    def edit_persona(persona_id: str, body: PersonaChanges, library: Library) -> dict:
        changes = body.model_dump(exclude_unset=True)
        try:
            return service.edit_persona(persona_id, changes, library)
        except (PersonaNotFoundError, PersonaEngineError, ValueError) as exc:
            raise _http(exc) from exc

    @router.delete("/{persona_id}")
    def remove_persona(persona_id: str, library: Library, confirm: bool = False) -> dict:
        if not confirm:  # apagar não tem volta: a tela mostra o aviso e só então manda a confirmação
            raise HTTPException(status_code=409, detail="Confirme para apagar a persona.")
        try:
            service.remove_persona(persona_id, library)
        except (PersonaNotFoundError, ValueError) as exc:
            raise _http(exc) from exc
        return {"removed": persona_id}

    @router.post("/{persona_id}/use")
    def use(persona_id: str, body: UseRequest, library: Library) -> dict:
        """Põe a persona num projeto (trecho de tela cheia ou sobreposição no canto), como o infográfico entra."""
        from ..pipeline.projects import load_project, save_project

        try:
            project = load_project(body.project)
            updated = service.use_persona(project, persona_id, body.text, body.placement, body.start, library)
            save_project(updated)
        except (PersonaNotFoundError, PersonaEngineError, ValueError, FileNotFoundError, KeyError) as exc:
            raise _http(exc) from exc
        return {"project": body.project, "placement": body.placement}

    @router.post("/{persona_id}/preview")
    def preview(persona_id: str, body: PreviewRequest, library: Library) -> dict:
        try:
            persona = library.get(persona_id)
            reason = engine_for(persona.kind).unavailable_reason()
        except (PersonaNotFoundError, PersonaEngineError) as exc:
            raise _http(exc) from exc
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        from ..media.ffmpeg import SubprocessRunner

        def work(job) -> dict:
            result = render_persona_preview(
                persona_id,
                body.phrase,
                library=library,
                runner=SubprocessRunner(sink=job.sink()),
                log=job.log,
            )
            return {
                "output": str(result.output),
                "output_url": f"/api/file?path={Path(result.output).resolve().as_posix()}",
                "duration_s": round(result.duration, 2),
                "warnings": result.warnings,
            }

        job = jobs.start(
            f"prévia da persona {persona.name}", work, meta={"kind": "persona", "persona": persona_id}
        )
        return {"job_id": job.id}

    return router
