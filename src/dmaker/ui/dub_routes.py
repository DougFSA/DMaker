"""Rotas de dublagem da interface: preparar (transcrever e traduzir), revisar as traduções e gerar o vídeo dublado.

Adaptador fino sobre `pipeline.dubbing`. Reaproveita as dependências do estúdio de voz (`VoiceServices`), que os
testes trocam por dublês. Preparar e gerar ocupam a CPU por minutos, então são jobs com progresso por SSE e um só
roda por vez. O projeto `.dub.json` vive em `output/dublagem`; a página só lê e grava arquivos dali.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from .. import config
from ..domain.dub import (
    PROJECT_SUFFIX,
    DubProject,
    FitMode,
    SpeakerMode,
    load_dub_project,
    save_dub_project,
)
from ..media.ffmpeg import SubprocessRunner
from ..media.probe import probe
from ..pipeline.dub_stems import StemsOptions
from ..pipeline.dubbing import (
    OUTPUT_SUBDIR,
    DubbingService,
    default_dubbing_service,
    default_project_path,
    project_summary,
    report_dict,
    result_dict,
)
from ..pipeline.jobs import Job, JobManager
from ..voice.synth import DRAFT_STEPS
from .speech_routes import file_url, isolation_service, media_file, stage_reporter
from .voice_routes import Services, VoiceServices, audio_url, exclusive_synthesis, existing_voice

MAX_SPEAKERS = 12  # mais pessoas que isto num vídeo curto é erro de digitação, não conversa
MAX_TEXT_CHARS = 2000  # uma fala dublada é uma frase; isto só barra colagem de texto errado
SERVABLE_SUFFIXES = (".srt", ".zip", PROJECT_SUFFIX)  # .zip: as trilhas separadas


class PrepareRequest(BaseModel):
    path: str
    target_language: str = Field(min_length=2, max_length=12)
    source_language: str = Field(default="pt", min_length=2, max_length=12)
    speaker_mode: SpeakerMode | None = None  # None: o padrão do serviço (per_speaker se a diarização existe)
    num_speakers: int | None = Field(default=None, ge=1, le=MAX_SPEAKERS)
    voice: str | None = None
    keep_original_db: float | None = Field(default=None, le=0)
    glossary: list[str] = Field(default_factory=list, max_length=100)
    fit_mode: FitMode = "voz"


class SegmentEdit(BaseModel):
    id: str
    text: str = Field(max_length=MAX_TEXT_CHARS)
    locked: bool = False
    speaker: str | None = None  # None: o falante da fala não muda


class ProjectUpdate(BaseModel):
    project: str
    segments: list[SegmentEdit]
    keep_original_db: float | None = Field(default=None, le=0)
    speaker_mode: SpeakerMode | None = None  # None: o modo do projeto não muda
    voice: str | None = None
    fit_mode: FitMode | None = None  # None mantém o do projeto (clientes antigos não o enviam)


class RenderRequest(BaseModel):
    project: str
    draft: bool = False


class ProjectRef(BaseModel):
    project: str


def dub_folder() -> Path:
    return config.OUTPUT_DIR / OUTPUT_SUBDIR


def dub_file_url(path: Path, download: bool = False) -> str:
    query = {"path": path.resolve().as_posix()}
    if download:
        query["download"] = "true"
    return "/api/dub/file?" + urlencode(query)


def _inside_dub_folder(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(dub_folder().resolve())
    except (OSError, RuntimeError):
        return False


def _project_file(raw: str) -> Path:
    """Projeto de dublagem existente em `output/dublagem`; qualquer outro caminho é recusado."""
    path = Path(raw)
    if not path.name.endswith(PROJECT_SUFFIX) or not _inside_dub_folder(path):
        raise HTTPException(
            status_code=400, detail="Só projetos .dub.json de output/dublagem podem ser abertos."
        )
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Projeto de dublagem não encontrado: {path.name}")
    return path


def _load(path: Path) -> DubProject:
    try:
        return load_dub_project(path)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Projeto de dublagem inválido: {exc}") from exc


def _dubbing_service(job: Job, services: VoiceServices) -> DubbingService:
    return default_dubbing_service(
        services.runner or SubprocessRunner(sink=job.sink()),
        job.log,
        library=services.library,
        transcriber=services.transcriber,
        isolation=isolation_service(job, services),
        synthesizer=services.synthesizer,
        lexicons=services.lexicons,
        translator=services.translator,
        prober=services.prober or probe,
        diarizer=services.diarizer,
    )


def _summary(project: DubProject, path: Path) -> dict:
    return {**project_summary(project, path), "source_url": file_url(Path(project.source))}


def _run_prepare(job: Job, services: VoiceServices, req: PrepareRequest, source: Path, path: Path) -> dict:
    with exclusive_synthesis(job):
        project = _dubbing_service(job, services).prepare(
            source,
            req.target_language,
            req.source_language,
            speaker_mode=req.speaker_mode,
            num_speakers=req.num_speakers,
            voice=req.voice or None,
            keep_original_db=req.keep_original_db,
            glossary=req.glossary,
            project_path=path,
            on_progress=stage_reporter(job),
            fit_mode=req.fit_mode,
        )
    return _summary(project, path)


def _run_retranslate(job: Job, services: VoiceServices, path: Path) -> dict:
    with exclusive_synthesis(job):
        project = _dubbing_service(job, services).retranslate(_load(path), stage_reporter(job))
        save_dub_project(project, path)
    return _summary(project, path)


def _run_render(job: Job, services: VoiceServices, path: Path, draft: bool) -> dict:
    project = _load(path)
    with exclusive_synthesis(job):
        result = _dubbing_service(job, services).render(
            project, on_progress=stage_reporter(job), steps=DRAFT_STEPS if draft else None
        )
    return {
        "output": str(result.path),
        "output_url": audio_url(result.path),
        "download_url": audio_url(result.path) + "&download=true",
        "srt": str(result.srt_path),
        "srt_url": dub_file_url(result.srt_path, download=True),
        "original": project.source,
        "original_url": file_url(Path(project.source)),
        "report": [report_dict(r) for r in result.report],
        **result_dict(result),
    }


def _run_stems(job: Job, services: VoiceServices, path: Path, draft: bool) -> dict:
    project = _load(path)
    with exclusive_synthesis(job):
        stems = _dubbing_service(job, services).export_stems(
            project, StemsOptions(make_zip=True), stage_reporter(job), DRAFT_STEPS if draft else None
        )
    return {
        "folder": str(stems.folder),
        "files": [file.name for file in stems.files],
        "zip": str(stems.zip_path),
        "zip_url": dub_file_url(stems.zip_path, download=True),
        "duration": round(stems.duration, 3),
        "original_voice_db": stems.original_voice_db,
    }


def _apply_update(project: DubProject, update: ProjectUpdate) -> DubProject:
    edited = project
    for item in update.segments:
        try:
            edited = edited.edited(item.id, item.text, item.locked, item.speaker)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    changes = {
        "keep_original_db": update.keep_original_db,
        "speaker_mode": update.speaker_mode or edited.speaker_mode,
        "voice": update.voice or None,
    }
    if update.fit_mode is not None:
        changes["fit_mode"] = update.fit_mode
    return edited.model_copy(update=changes)


def build_dub_router(jobs: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api/dub", tags=["dublagem"])

    @router.get("/projects")
    def projects() -> list[dict]:
        folder = dub_folder()
        files = sorted(folder.glob(f"*{PROJECT_SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"path": str(path), "name": path.name} for path in files] if folder.is_dir() else []

    @router.post("/prepare")
    def prepare(req: PrepareRequest, services: Services) -> dict:
        source = media_file(req.path)
        if req.source_language.split("-")[0] == req.target_language.split("-")[0]:
            raise HTTPException(
                status_code=400, detail="O idioma de destino precisa ser diferente do de origem."
            )
        if req.voice:
            existing_voice(services.library, req.voice)
        path = default_project_path(source, req.target_language)
        job = jobs.start(
            f"dublagem: preparar ({source.name})",
            lambda job: _run_prepare(job, services, req, source, path),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    @router.get("/project")
    def get_project(path: str) -> dict:
        project_path = _project_file(path)
        return _summary(_load(project_path), project_path)

    @router.put("/project")
    def update_project(req: ProjectUpdate, services: Services) -> dict:
        path = _project_file(req.project)
        if req.voice:
            existing_voice(services.library, req.voice)
        try:
            updated = _apply_update(_load(path), req)
            save_dub_project(updated, path)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _summary(updated, path)

    @router.post("/retranslate")
    def retranslate(req: ProjectRef, services: Services) -> dict:
        path = _project_file(req.project)
        _load(path)
        job = jobs.start(
            f"dublagem: traduzir de novo ({path.name})",
            lambda job: _run_retranslate(job, services, path),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    @router.post("/render")
    def render(req: RenderRequest, services: Services) -> dict:
        path = _project_file(req.project)
        project = _load(path)
        if not Path(project.source).is_file():
            raise HTTPException(status_code=404, detail=f"Arquivo de origem não encontrado: {project.source}")
        if not any(s.text.strip() for s in project.segments):
            raise HTTPException(status_code=400, detail="Nenhuma fala está traduzida.")
        job = jobs.start(
            f"dublagem: gerar ({path.name})",
            lambda job: _run_render(job, services, path, req.draft),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    @router.post("/stems")
    def stems(req: RenderRequest, services: Services) -> dict:
        path = _project_file(req.project)
        project = _load(path)
        if not Path(project.source).is_file():
            raise HTTPException(status_code=404, detail=f"Arquivo de origem não encontrado: {project.source}")
        if not any(s.text.strip() for s in project.segments):
            raise HTTPException(status_code=400, detail="Nenhuma fala está traduzida.")
        job = jobs.start(
            f"dublagem: trilhas ({path.name})",
            lambda job: _run_stems(job, services, path, req.draft),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    @router.get("/file")
    def get_file(path: str, download: bool = False) -> FileResponse:
        target = Path(path)
        if target.suffix.lower() not in SERVABLE_SUFFIXES and not target.name.endswith(PROJECT_SUFFIX):
            raise HTTPException(status_code=404, detail="Arquivo não permitido.")
        if not target.is_file() or not _inside_dub_folder(target):
            raise HTTPException(status_code=404, detail="Arquivo não encontrado ou fora de output/dublagem.")
        return FileResponse(target, filename=target.name if download else None)

    return router
