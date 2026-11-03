"""Rotas da exportação de áudio da interface: os formatos, a exportação (inteira, por região, por trilha ou só um
trecho) e a importação de áudio bruto.

Adaptador fino sobre `pipeline.audio_service` e `pipeline.audio_import`: a interface escolhe, o serviço renderiza.
A exportação roda como um job (progresso por SSE), como o render de vídeo.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from ..domain.audio_presets import AudioFormatError, EncodingChoices, list_audio_presets
from ..domain.loudness import LOUDNESS_TARGETS
from ..media.ffmpeg import FFmpegError, SubprocessRunner
from ..pipeline.audio_import import RawImportError, import_raw_audio
from ..pipeline.audio_service import export_audio_project, export_request, planned_outputs, result_dict
from ..pipeline.jobs import Job, JobManager
from ..pipeline.projects import load_project


class AudioExportRequest(BaseModel):
    """O pedido de exportação de áudio. Os campos de cada modo só valem nele (ver `domain/audio_export.py`)."""

    preset: str | None = None  # audio/mp3...; omitido, vale o do projeto se for de áudio
    mode: str = "mix"
    group: str | None = None
    pauses: bool = False
    numbered: bool = False
    start: float | str | None = None
    end: float | str | None = None
    tracks: list[str] = Field(default_factory=list)
    loudness: str | float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    bitrate_k: int | None = None
    bitrate_mode: str | None = None
    quality: float | None = None
    overwrite: bool = False  # a interface confirma antes; sem isto, arquivo que já existe devolve 409
    out_dir: str | None = None


class RawImportRequest(BaseModel):
    src: str
    encoding: str = "s16"
    byte_order: str = "little"
    channels: int = 1
    sample_rate: int = 44100
    offset_bytes: int = 0
    percent: float = 100.0
    start: float = 0.0
    volume: float = 1.0
    wav_name: str | None = None
    overwrite: bool = False


def audio_catalog() -> dict:
    """Os formatos de áudio e os alvos de loudness, como a interface os mostra."""
    return {
        "audio_presets": [
            {
                "id": a.id,
                "name": a.name,
                "extension": a.extension,
                "lossless": a.lossless,
                "sample_rate": a.sample_rate,
                "channels": a.channels,
                "bit_depths": list(a.bit_depths),
                "bit_depth": a.bit_depth,
                "bitrate_modes": list(a.bitrate_modes),
                "bitrate_mode": a.bitrate_mode,
                "bitrate_k": a.bitrate_k,
                "quality": a.quality,
                "quality_range": list(a.quality_range),
                "allowed_sample_rates": list(a.sample_rates),
                "default_label": a.default_label,
                "notes": a.notes,
            }
            for a in list_audio_presets()
        ],
        "loudness_targets": LOUDNESS_TARGETS,
    }


def _error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def build_audio_router(jobs: JobManager) -> APIRouter:
    router = APIRouter()

    @router.get("/api/audio/catalog")
    def catalog() -> dict:
        return audio_catalog()

    @router.post("/api/projects/{name}/audio-export")
    def audio_export(name: str, req: AudioExportRequest) -> dict:
        try:
            request = export_request(
                req.mode,
                group=req.group,
                pauses=req.pauses,
                numbered=req.numbered,
                start=req.start,
                end=req.end,
                tracks=req.tracks,
            )
            choices = EncodingChoices(
                req.sample_rate,
                req.channels,
                req.bit_depth,
                req.bitrate_mode,
                req.bitrate_k,
                req.quality,  # type: ignore[arg-type]
            )
            project = load_project(name)
            targets = planned_outputs(
                name, request, preset=req.preset, out_dir=req.out_dir, loader=lambda _: project
            )
        except FileNotFoundError as exc:
            raise _error(404, str(exc)) from exc
        except (AudioFormatError, KeyError, ValueError, ValidationError) as exc:
            raise _error(400, str(exc)) from exc
        existing = [str(path) for path in targets if path.exists()]
        if existing and not req.overwrite:
            # a interface pergunta e manda de novo com `overwrite`; o arquivo nunca é trocado sem esse sim
            raise HTTPException(
                status_code=409,
                detail={"message": "Já existe um arquivo com esse nome.", "existing": existing},
            )

        def work(job: Job) -> dict:
            result = export_audio_project(
                name,
                request,
                preset=req.preset,
                out_dir=req.out_dir,
                loudness=req.loudness,
                choices=None if choices.empty else choices,
                runner=SubprocessRunner(sink=job.sink()),
                log=job.log,
            )
            return result_dict(result)

        job = jobs.start(f"{name}: áudio ({req.mode})", work, meta={"project": name})
        return {"job_id": job.id}

    @router.post("/api/projects/{name}/audio-import-raw")
    def audio_import_raw(name: str, req: RawImportRequest) -> dict:
        try:
            imported = import_raw_audio(
                name,
                Path(req.src),
                encoding=req.encoding,
                byte_order=req.byte_order,
                channels=req.channels,
                sample_rate=req.sample_rate,
                offset_bytes=req.offset_bytes,
                percent=req.percent,
                start=req.start,
                volume=req.volume,
                name=req.wav_name,
                overwrite=req.overwrite,
                runner=SubprocessRunner(quiet=True),
            )
        except RawImportError as exc:
            status = 409 if "já existe" in str(exc) else 400
            raise _error(status, str(exc)) from exc
        except (FFmpegError, FileNotFoundError, ValueError) as exc:
            raise _error(400, str(exc)) from exc
        return {
            "wav": str(imported.wav),
            "voiceover_src": imported.source,
            "duration_s": round(imported.duration, 3),
            "project_created": imported.created_project,
        }

    return router
