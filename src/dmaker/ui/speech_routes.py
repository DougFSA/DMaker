"""Rotas de áudio da interface: isolar a voz de um arquivo, corrigir uma fala e trocar a voz da gravação.

Adaptador fino sobre `pipeline.isolation`, `pipeline.speech_fix` e `pipeline.voice_conversion`. Reaproveita as dependências do estúdio de
voz (`VoiceServices`), que os testes trocam por dublês. Separar voz, transcrever e sintetizar ocupam a CPU
toda, então tudo é job com progresso por SSE e um só roda por vez.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import config
from ..filtergraph.speech_edit import corrected_suffix
from ..media.ffmpeg import SubprocessRunner
from ..media.probe import probe
from ..media.separation import Stems
from ..pipeline.isolation import IsolationService, default_isolation_service
from ..pipeline.jobs import Job, JobManager
from ..pipeline.speech_fix import FixRequest, default_speech_fix_service
from ..pipeline.voice_conversion import ConversionRequest, default_voice_conversion_service
from ..voice.speech_edit import MIN_PAUSE_SECONDS
from ..voice.synth import DRAFT_STEPS
from .voice_routes import Services, VoiceServices, audio_url, exclusive_synthesis, existing_voice

MAX_UPLOAD_BYTES = (
    4 * 1024**3
)  # um vídeo de celular de alguns minutos; isto só barra o que claramente não é mídia
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 2000  # uma correção troca uma palavra ou frase, não um roteiro (isso é a narração)
ISOLATION_SUBDIR = "isolamento"
CORRECTION_SUBDIR = "correcao"


class _MediaRequest(BaseModel):
    path: str
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)


class IsolateRequest(_MediaRequest):
    format: Literal["wav", "mp3"] = "wav"


class WordsRequest(_MediaRequest):
    language: str = "pt"


class ConvertVoiceRequest(_MediaRequest):
    voice: str


class FixSpeechRequest(_MediaRequest):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    find: str | None = None
    occurrence: int | None = Field(default=None, ge=1)
    search_from: float | None = Field(default=None, ge=0)
    search_to: float | None = Field(default=None, ge=0)
    voice: str | None = None
    expand: bool = True
    save_voice: str | None = None
    language: str = "pt"
    brand: str | None = None
    draft: bool = False


def file_url(path: Path) -> str:
    """Endereço para tocar o arquivo original (qualquer mídia que `/api/file` aceita)."""
    return "/api/file?" + urlencode({"path": path.resolve().as_posix()})


def media_file(raw: str) -> Path:
    path = Path(raw)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Arquivo não encontrado: {raw}")
    return path


def _upload_name(upload: UploadFile) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(upload.filename or "arquivo").stem).strip("-.")[:60]
    suffix = re.sub(r"[^a-z0-9.]", "", Path(upload.filename or "").suffix.lower())[:6] or ".bin"
    return f"{stem or 'arquivo'}{suffix}"


def _save_media_upload(upload: UploadFile) -> Path:
    """Grava o arquivo enviado em cache/uploads (o ffmpeg lê por caminho), recusando o que passa do limite."""
    folder = config.CACHE_DIR / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / f".{hashlib.sha1(str(id(upload)).encode()).hexdigest()[:8]}.part"
    digest = hashlib.sha256()
    written = 0
    with partial.open("wb") as handle:
        while chunk := upload.file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                handle.close()
                partial.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Arquivo grande demais.")
            digest.update(chunk)
            handle.write(chunk)
    if not written:
        partial.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    # o conteúdo entra no nome: enviar o mesmo arquivo de novo reaproveita o caminho (e os caches por caminho)
    destination = folder / f"{digest.hexdigest()[:10]}-{_upload_name(upload)}"
    partial.replace(destination)
    return destination


def stage_reporter(job: Job):
    """Etapa e fração do serviço viram progresso do job e evento SSE."""

    def report(label: str, fraction: float) -> None:
        percent = round(fraction * 100)
        job.progress = {"label": label, "done": percent, "total": 100, "percent": percent}
        job.emit("progress", **job.progress)

    return report


def _block_reporter(job: Job):
    """Blocos do Demucs (feito, total) viram progresso do job e evento SSE."""

    def report(done: int, total: int) -> None:
        percent = int(100 * done / max(total, 1))
        job.progress = {"label": f"bloco {done} de {total}", "done": done, "total": total, "percent": percent}
        job.emit("progress", **job.progress)

    return report


def isolation_service(job: Job, services: VoiceServices) -> IsolationService:
    runner = services.runner or SubprocessRunner(sink=job.sink())
    return services.isolation or default_isolation_service(runner, job.log)


def _fix_service(job: Job, services: VoiceServices):
    return default_speech_fix_service(
        services.runner or SubprocessRunner(sink=job.sink()),
        job.log,
        library=services.library,
        transcriber=services.transcriber,
        isolation=isolation_service(job, services),
        synthesizer=services.synthesizer,
        lexicons=services.lexicons,
        prober=services.prober or probe,
    )


def _run_isolation(job: Job, services: VoiceServices, req: IsolateRequest) -> dict:
    with exclusive_synthesis(job):
        stems: Stems = isolation_service(job, services).export(
            Path(req.path),
            config.OUTPUT_DIR / ISOLATION_SUBDIR,
            req.format,
            req.start,
            req.end,
            on_progress=_block_reporter(job),
        )
    return {
        "voice": str(stems.vocals),
        "background": str(stems.background),
        "voice_url": audio_url(stems.vocals),
        "background_url": audio_url(stems.background),
    }


def _run_words(job: Job, services: VoiceServices, req: WordsRequest) -> dict:
    with exclusive_synthesis(job):
        words = _fix_service(job, services).transcribe_words(Path(req.path), req.start, req.end, req.language)
    return {
        "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "text": w.text} for w in words],
        "pause_seconds": MIN_PAUSE_SECONDS,
    }


def _run_fix(job: Job, services: VoiceServices, request: FixRequest) -> dict:
    with exclusive_synthesis(job):
        result = _fix_service(job, services).fix(request, stage_reporter(job))
    return {
        "output": str(result.path),
        "audio_url": audio_url(result.path),
        "original": str(request.src),
        "original_url": file_url(request.src),
        "region": [round(result.region_start, 2), round(result.region_end, 2)],
        "old_text": result.old_text,
        "new_text": result.new_text,
        "spoken": result.spoken_context,
        "rule": result.rule,
        "squeezed": result.squeezed,
        "voice": result.voice,
    }


def _conversion_service(job: Job, services: VoiceServices):
    return default_voice_conversion_service(
        services.runner or SubprocessRunner(sink=job.sink()),
        job.log,
        library=services.library,
        isolation=isolation_service(job, services),
        synthesizer=services.synthesizer,
        converter=services.converter,
        prober=services.prober or probe,
    )


def _run_conversion(job: Job, services: VoiceServices, request: ConversionRequest) -> dict:
    with exclusive_synthesis(job):
        result = _conversion_service(job, services).convert(request, stage_reporter(job))
    return {
        "output": str(result.path),
        "audio_url": audio_url(result.path),
        "original": str(request.src),
        "original_url": file_url(request.src),
        "voice": result.voice,
        "seconds": round(result.seconds, 2),
        "blocks": result.blocks,
        "gain_db": round(result.gain_db, 2),
        "excerpt": request.start is not None or request.end is not None,
    }


def _output_path(req: FixSpeechRequest, services: VoiceServices) -> Path:
    """Arquivo da correção: o trecho e o texto entram no nome, para tentativas diferentes não se sobrescreverem."""
    source = Path(req.path)
    digest = hashlib.sha1(
        json.dumps([req.find, req.occurrence, req.start, req.end, req.text, req.voice, req.expand]).encode()
    ).hexdigest()[:8]
    try:
        has_video = (services.prober or probe)(source).has_video
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Não consegui ler {source.name} como vídeo ou áudio."
        ) from exc
    suffix = corrected_suffix(source.suffix, has_video)
    return config.OUTPUT_DIR / CORRECTION_SUBDIR / f"{source.stem}.corrigido-{digest}{suffix}"


def build_speech_router(jobs: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api/speech", tags=["fala"])

    @router.post("/upload")
    def upload(file: Annotated[UploadFile, File()]) -> dict:
        path = _save_media_upload(file)
        return {"path": path.as_posix(), "name": path.name}

    @router.post("/isolate")
    def isolate(req: IsolateRequest, services: Services) -> dict:
        source = media_file(req.path)
        if req.start is not None and req.end is not None and req.end <= req.start:
            raise HTTPException(status_code=400, detail="O fim precisa ser maior que o início.")
        job = jobs.start(
            f"isolar voz ({source.name})",
            lambda job: _run_isolation(job, services, req),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    @router.post("/words")
    def words(req: WordsRequest, services: Services) -> dict:
        source = media_file(req.path)
        job = jobs.start(
            f"palavras de {source.name}",
            lambda job: _run_words(job, services, req),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    @router.post("/fix")
    def fix(req: FixSpeechRequest, services: Services) -> dict:
        source = media_file(req.path)
        if req.voice:
            existing_voice(services.library, req.voice)
        try:
            request = FixRequest(
                src=source,
                text=req.text,
                find=req.find or None,
                occurrence=req.occurrence,
                start=req.start,
                end=req.end,
                search_from=req.search_from,
                search_to=req.search_to,
                voice=req.voice or None,
                expand=req.expand,
                save_voice=req.save_voice or None,
                language=req.language,
                brand=req.brand or None,
                steps=DRAFT_STEPS if req.draft else None,
                out=_output_path(req, services),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job = jobs.start(
            f"corrigir fala ({source.name})",
            lambda job: _run_fix(job, services, request),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    @router.post("/convert")
    def convert(req: ConvertVoiceRequest, services: Services) -> dict:
        source = media_file(req.path)
        existing_voice(services.library, req.voice)
        try:
            request = ConversionRequest(src=source, voice=req.voice, start=req.start, end=req.end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job = jobs.start(
            f"trocar voz ({source.name})",
            lambda job: _run_conversion(job, services, request),
            meta={"kind": "voice"},
        )
        return {"job_id": job.id}

    return router
