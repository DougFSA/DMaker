"""API local da interface gráfica (FastAPI). Adaptador fino sobre os serviços do pipeline.

Só escuta em 127.0.0.1. Progresso dos renders sai por SSE em /api/jobs/{id}/events.
"""

from __future__ import annotations

import json
import queue
import string
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .. import __version__, config
from ..domain.brand import available_brands, load_theme
from ..domain.presets import get_preset, list_presets
from ..domain.spec import Project
from ..media.probe import AUDIO_EXTS, IMAGE_EXTS
from ..pipeline.jobs import Job, JobManager

STATIC_DIR = Path(__file__).parent / "static"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS | AUDIO_EXTS

app = FastAPI(title="DMaker", version=__version__)
jobs = JobManager()


# ---------- modelos de entrada ----------


class NewProject(BaseModel):
    name: str
    preset: str = "instagram/reels"
    brand: str | None = None
    sources: list[str] = Field(default_factory=list)
    captions: bool = True
    logo: bool = False


class RenderRequest(BaseModel):
    preview: bool = False
    preset: str | None = None
    force: bool = False
    guides: bool = False
    no_captions: bool = False
    segments: str | None = None  # "12-20": render parcial


class SyncRequest(BaseModel):
    master: str
    others: list[str]
    master_stream: int = 0
    stream: int = 0


class ExportRequest(BaseModel):
    presets: list[str]


class ProbeRequest(BaseModel):
    paths: list[str]


class SheetRequest(BaseModel):
    video: str
    cols: int = 3
    rows: int = 3
    width: int = 320


class FrameRequest(BaseModel):
    video: str
    t: float
    width: int = 540


class CaptionsUpdate(BaseModel):
    cues: list[dict]


class TimelineRequest(BaseModel):
    spec: dict | None = None


class EditRequest(BaseModel):
    spec: dict
    op: dict


# ---------- utilidades ----------


def _error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def _validation_detail(exc: ValidationError) -> list[dict]:
    return [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]


def _file_url(path: Path | str | None) -> str | None:
    return f"/api/file?path={Path(path).resolve().as_posix()}" if path else None


def _output_entry(path: Path) -> dict:
    st = path.stat()
    thumb = path.with_suffix(".jpg")
    stem = path.stem
    project_name, _, rest = stem.partition("__")
    preset_id, _, suffix = rest.partition("__")
    return {
        "path": str(path),
        "url": _file_url(path),
        "name": path.name,
        "project": project_name,
        "preset": preset_id.replace("-", "/", 1) if preset_id else None,
        "kind": "preview" if suffix == "preview" else "final",
        "size_mb": round(st.st_size / 1e6, 2),
        "mtime": st.st_mtime,
        "thumbnail": _file_url(thumb) if thumb.exists() else None,
    }


def _project_outputs(name: str) -> list[dict]:
    if not config.OUTPUT_DIR.exists():
        return []
    files = sorted(config.OUTPUT_DIR.glob(f"{name}__*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_output_entry(p) for p in files]


def _summary_dict(summary: Any) -> dict:
    return {
        "name": summary.name,
        "preset": summary.preset.id,
        "resolution": f"{summary.preset.width}x{summary.preset.height}",
        "theme": summary.theme.name,
        "total_s": round(summary.total, 2),
        "segments": [
            {"index": s.index, "type": s.type, "duration_s": round(s.duration, 2), "label": s.label}
            for s in summary.segments
        ],
        "warnings": summary.warnings,
    }


def _proxy_entry(status: Any) -> dict:
    return {
        "src": str(status.src),
        "proxy": str(status.proxy),
        "ready": status.ready,
        "url": _file_url(status.proxy) if status.ready else None,
    }


def _result_dict(result: Any) -> dict:
    return {
        "output": str(result.output),
        "output_url": _file_url(result.output),
        "thumbnail": str(result.thumbnail) if result.thumbnail else None,
        "thumbnail_url": _file_url(result.thumbnail),
        "duration_s": round(result.duration, 2),
        "size_mb": round(result.size_bytes / 1e6, 2),
        "preset": result.preset.id,
        "resolution": f"{result.preset.width}x{result.preset.height}",
        "captions_file": str(result.captions_file) if result.captions_file else None,
        "warnings": result.warnings,
    }


def _run_render(job: Job, name: str, req: RenderRequest, preset: str | None = None) -> dict:
    from ..media.ffmpeg import SubprocessRunner
    from ..pipeline import RenderOptions, RenderPipeline
    from ..pipeline.projects import load_project, parse_segments

    project = load_project(name)
    options = RenderOptions(
        preview=req.preview,
        preset=preset or req.preset,
        force=req.force,
        guides=req.guides or None,
        no_captions=req.no_captions,
        quiet=True,
        segments=parse_segments(req.segments),
    )
    pipeline = RenderPipeline(project, options, runner=SubprocessRunner(sink=job.sink()), log=job.log)
    return _result_dict(pipeline.run())


# ---------- estado geral ----------


@app.get("/api/state")
def state() -> dict:
    return {
        "version": __version__,
        "root": str(config.ROOT),
        "output_dir": str(config.OUTPUT_DIR),
        "projects_dir": str(config.PROJECTS_DIR),
        "ffmpeg": str(config.find_tool("ffmpeg") or ""),
        "presets": [
            {
                "id": p.id,
                "platform": p.platform,
                "name": p.name,
                "width": p.width,
                "height": p.height,
                "fps": p.fps,
                "max_duration_s": p.max_duration,
                "notes": p.notes,
            }
            for p in list_presets()
        ],
        "brands": [
            {"key": b, "name": load_theme(b).name, "colors": load_theme(b).colors} for b in available_brands()
        ],
        "projects": list_projects(),
    }


@app.get("/api/schema")
def schema() -> dict:
    return Project.model_json_schema()


# ---------- projetos ----------


@app.get("/api/projects")
def list_projects() -> list[dict]:
    out = []
    for spec in sorted(config.PROJECTS_DIR.glob("*/spec.json")):
        try:
            data = json.loads(spec.read_text(encoding="utf-8"))
            out.append(
                {
                    "name": spec.parent.name,
                    "spec_path": str(spec),
                    "preset": data.get("output", {}).get("preset"),
                    "brand": data.get("brand"),
                    "segments": len(data.get("timeline", [])),
                    "mtime": spec.stat().st_mtime,
                }
            )
        except (OSError, json.JSONDecodeError):
            out.append({"name": spec.parent.name, "spec_path": str(spec), "error": "spec ilegível"})
    return out


@app.post("/api/projects")
def create_project(req: NewProject) -> dict:
    from ..pipeline.projects import save_project, scaffold_project

    try:
        project = scaffold_project(
            req.name, req.preset, [Path(s) for s in req.sources], req.brand, req.captions, req.logo
        )
    except (FileNotFoundError, KeyError, ValidationError) as exc:
        raise _error(400, str(exc)) from exc
    path = save_project(project)
    return {
        "name": project.name,
        "spec_path": str(path),
        "spec": json.loads(project.model_dump_json(exclude_none=True)),
    }


@app.get("/api/projects/{name}")
def get_project(name: str) -> dict:
    from ..pipeline.projects import load_project, project_path

    try:
        project = load_project(name)
    except FileNotFoundError as exc:
        raise _error(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    folder = project_path(name).parent
    return {
        "name": project.name,
        "spec_path": str(project_path(name)),
        "spec": json.loads(project.model_dump_json(exclude_none=True)),
        "captions_exists": (folder / "captions.auto.json").exists(),
        "outputs": _project_outputs(name),
    }


@app.put("/api/projects/{name}")
def save_spec(name: str, spec: dict) -> dict:
    from ..pipeline.projects import save_project

    spec = dict(spec)
    spec["name"] = name
    try:
        project = Project.model_validate(spec)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    path = save_project(project)
    return {"ok": True, "spec_path": str(path)}


@app.post("/api/projects/{name}/validate")
def validate_project(name: str) -> dict:
    from ..pipeline.projects import load_project, summarize

    try:
        return _summary_dict(summarize(load_project(name)))
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise _error(400, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/projects/{name}/render")
def render_project(name: str, req: RenderRequest) -> dict:
    if req.preset:
        try:
            get_preset(req.preset)
        except KeyError as exc:
            raise _error(400, str(exc)) from exc
    job = jobs.start(
        f"{name}: {'preview' if req.preview else 'render ' + (req.preset or 'final')}",
        lambda job: _run_render(job, name, req),
    )
    return {"job_id": job.id}


@app.post("/api/projects/{name}/export")
def export_project(name: str, req: ExportRequest) -> dict:
    for p in req.presets:
        try:
            get_preset(p)
        except KeyError as exc:
            raise _error(400, str(exc)) from exc

    def work(job: Job) -> list[dict]:
        return [_run_render(job, name, RenderRequest(), preset=p) for p in req.presets]

    job = jobs.start(f"{name}: export {', '.join(req.presets)}", work)
    return {"job_id": job.id}


@app.get("/api/projects/{name}/captions")
def get_captions(name: str) -> dict:
    from ..pipeline.projects import project_path

    store = project_path(name).parent / "captions.auto.json"
    if not store.exists():
        raise _error(404, "sem legendas automáticas ainda")
    return json.loads(store.read_text(encoding="utf-8"))


@app.put("/api/projects/{name}/captions")
def put_captions(name: str, update: CaptionsUpdate) -> dict:
    from ..pipeline.projects import project_path
    from ..text.captions import from_json, to_json, to_srt

    store = project_path(name).parent / "captions.auto.json"
    if not store.exists():
        raise _error(404, "sem legendas automáticas ainda")
    data = json.loads(store.read_text(encoding="utf-8"))
    cues = from_json(json.dumps({"cues": update.cues}))
    payload = json.loads(to_json(cues, data.get("language", "pt")))
    payload.update({k: v for k, v in data.items() if k not in ("cues", "language")})
    store.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    store.with_suffix(".srt").write_text(to_srt(cues), encoding="utf-8")
    return {"ok": True, "cues": len(cues)}


# ---------- edição multitrilha ----------


def _project_from_body(name: str, spec: dict) -> Project:
    spec = dict(spec)
    spec["name"] = name
    try:
        project = Project.model_validate(spec)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_validation_detail(exc)) from exc
    project.base_dir = (config.PROJECTS_DIR / name).resolve()
    return project


@app.post("/api/projects/{name}/timeline")
def project_timeline(name: str, req: TimelineRequest) -> dict:
    from ..pipeline.layout import project_layout
    from ..pipeline.projects import load_project
    from ..pipeline.timeline_view import build_timeline_view

    if req.spec is not None:
        project = _project_from_body(name, req.spec)
    else:
        try:
            project = load_project(name)
        except FileNotFoundError as exc:
            raise _error(404, str(exc)) from exc
    layout = project_layout(project)
    return build_timeline_view(project, layout).to_dict()


@app.post("/api/projects/{name}/edit")
def project_edit(name: str, req: EditRequest) -> dict:
    from ..domain.edits import EditError
    from ..pipeline.edits import apply_edit
    from ..pipeline.layout import project_layout
    from ..pipeline.timeline_view import build_timeline_view

    project = _project_from_body(name, req.spec)
    try:
        new_project = apply_edit(project, req.op)
    except EditError as exc:
        raise _error(400, str(exc)) from exc
    layout = project_layout(new_project)
    view = build_timeline_view(new_project, layout)
    return {
        "spec": json.loads(new_project.model_dump_json(exclude_none=True)),
        "timeline": view.to_dict(),
    }


@app.get("/api/projects/{name}/theme")
def project_theme(name: str) -> dict:
    from ..pipeline.projects import load_project

    try:
        project = load_project(name)
    except FileNotFoundError as exc:
        raise _error(404, str(exc)) from exc
    theme = load_theme(project.brand, project.theme)
    return {
        "colors": theme.colors,
        "font": theme.font_family,
        "logos": {kind: _file_url(path) for kind, path in theme.logos.items()},
        "no_dash": theme.no_dash,
    }


@app.get("/api/card-preview")
def card_preview(
    title: str,
    brand: str | None = None,
    preset: str = "instagram/reels",
    subtitle: str | None = None,
    variant: str | None = None,
    logo: bool = True,
    background: str | None = None,
    width: int = 540,
) -> FileResponse:
    """PNG de um cartão a partir só dos campos (sem depender de projeto salvo em disco), para a
    prévia ao vivo da linha do tempo poder mostrar edições ainda não salvas. Cacheado por hash dos
    parâmetros em cache/cards; `brand` vazio usa o tema padrão."""
    import hashlib

    from ..visuals.cards import render_card, save_card

    try:
        theme = load_theme(brand or None)
    except FileNotFoundError as exc:
        raise _error(404, str(exc)) from exc
    try:
        preset_obj = get_preset(preset).preview(width)
    except KeyError as exc:
        raise _error(404, str(exc)) from exc
    key = "|".join(
        [
            title,
            subtitle or "",
            variant or "",
            str(logo),
            background or "",
            brand or "default",
            preset,
            str(width),
        ]
    )
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    out = config.CACHE_DIR / "cards" / f"{digest}.png"
    if not out.exists():
        img = render_card(
            theme,
            preset_obj.width,
            preset_obj.height,
            title,
            subtitle,
            variant,
            logo,
            background,
            preset_obj.safe,
        )
        save_card(img, out)
    return FileResponse(out)


# ---------- jobs ----------


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return sorted(jobs.list(), key=lambda j: j["job_id"])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise _error(404, "job desconhecido")
    return {**job.snapshot(), "result": job.result, "events": job.events[-200:]}


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str) -> StreamingResponse:
    job = jobs.get(job_id)
    if job is None:
        raise _error(404, "job desconhecido")

    def stream():
        q = job.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                if event.get("kind") == "end":
                    break
        finally:
            job.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---------- mídia e conferência ----------


def _allowed_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        path.relative_to(config.ROOT)
        return True
    except ValueError:
        return path.suffix.lower() in MEDIA_EXTS


@app.get("/api/file")
def get_file(path: str) -> FileResponse:
    p = Path(path)
    if not _allowed_file(p):
        raise _error(404, "arquivo não encontrado ou não permitido")
    return FileResponse(p)


@app.post("/api/probe")
def probe_media(req: ProbeRequest) -> list[dict]:
    from ..media.probe import probe

    out = []
    for raw in req.paths:
        p = Path(raw)
        try:
            i = probe(p)
            out.append(
                {
                    "path": str(p),
                    "url": _file_url(p),
                    "kind": "image" if i.is_image else ("video" if i.has_video else "audio"),
                    "width": i.width,
                    "height": i.height,
                    "duration_s": round(i.duration, 3),
                    "fps": i.fps,
                    "has_audio": i.has_audio,
                    "orientation": i.orientation,
                }
            )
        except Exception as exc:  # noqa: BLE001 - erro por arquivo
            out.append({"path": str(p), "error": str(exc)})
    return out


@app.get("/api/projects/{name}/proxies")
def get_proxies(name: str) -> list[dict]:
    """Status dos proxies 540p (prévia ao vivo) de cada fonte de vídeo do projeto."""
    from ..media.ffmpeg import SubprocessRunner
    from ..pipeline.projects import load_project
    from ..pipeline.proxies import ProxyBuilder

    try:
        project = load_project(name)
    except FileNotFoundError as exc:
        raise _error(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    status = ProxyBuilder(SubprocessRunner(quiet=True)).status(project)
    return [_proxy_entry(s) for s in status]


@app.post("/api/projects/{name}/proxies")
def build_proxies(name: str) -> dict:
    """Gera em segundo plano os proxies que ainda faltam para a prévia ao vivo."""
    from ..media.ffmpeg import SubprocessRunner
    from ..pipeline.projects import load_project
    from ..pipeline.proxies import ProxyBuilder

    try:
        project = load_project(name)
    except FileNotFoundError as exc:
        raise _error(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    status = ProxyBuilder(SubprocessRunner(quiet=True)).status(project)
    if all(s.ready for s in status):
        return {"job": None, "proxies": [_proxy_entry(s) for s in status]}

    def work(job: Job) -> list[dict]:
        builder = ProxyBuilder(SubprocessRunner(sink=job.sink()), log=job.log)
        return [_proxy_entry(s) for s in builder.build(project)]

    job = jobs.start(f"{name}: proxies de prévia", work)
    return {"job": job.snapshot(), "proxies": [_proxy_entry(s) for s in status]}


@app.get("/api/browse")
def browse(path: str | None = None) -> dict:
    """Navegador de arquivos para escolher fontes (só pastas e mídia)."""
    if not path:
        drives = [f"{d}:/" for d in string.ascii_uppercase if Path(f"{d}:/").exists()]
        return {"path": "", "parent": None, "dirs": drives, "files": []}
    p = Path(path)
    if not p.is_dir():
        raise _error(404, "pasta não encontrada")
    dirs, files = [], []
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            if child.name.startswith(".") or child.name.startswith("$"):
                continue
            if child.is_dir():
                dirs.append(child.as_posix())
            elif child.suffix.lower() in MEDIA_EXTS:
                files.append(
                    {
                        "path": child.as_posix(),
                        "name": child.name,
                        "size_mb": round(child.stat().st_size / 1e6, 2),
                    }
                )
    except PermissionError as exc:
        raise _error(403, str(exc)) from exc
    parent = p.parent.as_posix() if p.parent != p else None
    return {"path": p.as_posix(), "parent": parent, "dirs": dirs, "files": files}


@app.post("/api/sync")
def sync_sources(req: SyncRequest) -> list[dict]:
    """Deslocamento de cada fonte em relação à principal, pelo áudio."""
    from ..media.audiosync import sync_offset
    from ..media.ffmpeg import FFmpegError, SubprocessRunner

    runner = SubprocessRunner(quiet=True)
    out = []
    for other in req.others:
        try:
            r = sync_offset(
                runner,
                Path(req.master),
                Path(other),
                config.CACHE_DIR / "audio" / "sync",
                req.master_stream,
                req.stream,
            )
        except FFmpegError as exc:
            raise _error(400, str(exc)) from exc
        out.append({"path": other, "offset_s": r.offset, "confidence": r.confidence, "reliable": r.reliable})
    return out


@app.post("/api/qa/sheet")
def qa_sheet(req: SheetRequest) -> dict:
    from ..pipeline.qa import contact_sheet

    src = Path(req.video)
    if not src.exists():
        raise _error(404, "vídeo não encontrado")
    out = contact_sheet(src, src.with_name(f"{src.stem}_sheet.png"), req.cols, req.rows, req.width)
    return {"image": str(out), "url": _file_url(out)}


@app.post("/api/qa/frame")
def qa_frame(req: FrameRequest) -> dict:
    from ..pipeline.qa import frame_at

    src = Path(req.video)
    if not src.exists():
        raise _error(404, "vídeo não encontrado")
    out = frame_at(
        src, req.t, src.parent / f"{src.stem}_frames" / f"{src.stem}_{req.t:06.2f}s.jpg", req.width
    )
    return {"image": str(out), "url": _file_url(out), "t": req.t}


@app.get("/api/outputs")
def list_outputs() -> list[dict]:
    if not config.OUTPUT_DIR.exists():
        return []
    files = sorted(config.OUTPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_output_entry(p) for p in files]


# ---------- frontend ----------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    config.ensure_dirs()
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
