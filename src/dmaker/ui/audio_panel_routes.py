"""Rotas do painel Áudio da interface nova: a onda de um item por zoom, uma janela do som para tocar e a prova de um efeito.

Adaptador fino sobre `pipeline.audio_panel`. Todas recebem a spec que o editor tem na tela (ainda não salva), porque o
que se vê e se ouve no painel é o projeto em edição: um efeito aplicado há um segundo já conta. O alvo é o mesmo dos
efeitos de áudio (`timeline.2`, `audio.voiceover.0`, `audio.music`...). Nenhuma rota grava o projeto.

- `wave`: os mínimos e máximos das colunas de uma janela (a pirâmide de picos, construída em segundo plano na primeira
  vez e guardada em `cache/waveform`), ou as amostras de verdade no zoom máximo;
- `window`: um trecho do som, como ele soa, em WAV de 16 bits, para tocar sem baixar o áudio inteiro;
- `preview`: o mesmo trecho com um efeito proposto ao fim da cadeia, sem gravar, para a prévia e o antes e depois.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from .. import config
from ..domain.spec import Project
from ..media.ffmpeg import FFmpegError, FFmpegRunner
from ..media.probe import probe
from ..pipeline.analysis_items import TargetError
from ..pipeline.audio_panel import (
    AudioPanelError,
    AudioPanelService,
    HeardPlan,
    PeakTasks,
    PlanCache,
    wave_payload,
)
from .voice_routes import Services, VoiceServices

# quanto a rota espera uma construção de picos terminar antes de responder com o que já há: o áudio curto e o WAV de
# uma hora ficam prontos dentro disto e a primeira resposta já traz a onda; o resto responde com o andamento
DEFAULT_WAIT_S = 2.5
MAX_WAIT_S = 10.0


class PanelBody(BaseModel):
    """O alvo e a spec em edição."""

    spec: dict
    target: str


class WaveBody(PanelBody):
    start: float = Field(0.0, ge=0, allow_inf_nan=False)
    end: float | None = Field(None, ge=0, allow_inf_nan=False)  # vazio: até o fim do áudio
    columns: int = Field(1024, ge=1, le=4096)
    wait: float = Field(DEFAULT_WAIT_S, ge=0, le=MAX_WAIT_S, allow_inf_nan=False)


class WindowBody(PanelBody):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


class PreviewBody(WindowBody):
    effect: dict


def _project(name: str, spec: dict) -> Project:
    data = dict(spec)
    data["name"] = name
    try:
        project = Project.model_validate(data)
    except ValidationError as exc:
        detail = [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise HTTPException(status_code=400, detail=detail) from exc
    project.base_dir = (config.PROJECTS_DIR / name).resolve()
    return project


def build_audio_panel_router() -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/audio-panel", tags=["painel de áudio"])
    plans = PlanCache()
    peaks = PeakTasks()

    def service(services: VoiceServices) -> AudioPanelService:
        return AudioPanelService(services.runner, services.prober or probe)

    def plan_of(project: Project, target: str, svc: AudioPanelService) -> HeardPlan:
        return plans.get(project, target, lambda: svc.plan(project, target))

    def failing(exc: Exception) -> HTTPException:
        if isinstance(exc, FileNotFoundError):
            return HTTPException(status_code=404, detail=str(exc))
        return HTTPException(status_code=400, detail=str(exc))

    @router.post("/wave")
    def wave(name: str, body: WaveBody, services: Services) -> dict:
        project = _project(name, body.spec)
        svc = service(services)
        try:
            plan = plan_of(project, body.target, svc)

            def make(runner: FFmpegRunner) -> AudioPanelService:
                return AudioPanelService(services.runner or runner, svc.prober, svc.offset_finder)

            build = peaks.request(make, plan)
            if build.state == "building" and body.wait > 0:
                build.done.wait(body.wait)
            reader = (
                plans.reader(plan, lambda: svc.reader(plan, create=False))
                if build.state != "failed"
                else None
            )
            end = plan.duration if body.end is None else min(body.end, plan.duration)
            return wave_payload(plan, build, reader, body.start, end, body.columns)
        except (TargetError, AudioPanelError, ValueError, FileNotFoundError, FFmpegError) as exc:
            raise failing(exc) from exc

    @router.post("/window")
    def window(name: str, body: WindowBody, services: Services) -> Response:
        project = _project(name, body.spec)
        svc = service(services)
        try:
            plan = plan_of(project, body.target, svc)
            reader = plans.reader(plan, lambda: svc.reader(plan))
            data, seconds = svc.window_wav(plan, body.start, body.end, reader)
        except (TargetError, AudioPanelError, ValueError, FileNotFoundError, FFmpegError) as exc:
            raise failing(exc) from exc
        return Response(
            data,
            media_type="audio/wav",
            headers={"X-Window-Seconds": f"{seconds:.6f}", "Cache-Control": "no-store"},
        )

    @router.post("/preview")
    def preview(name: str, body: PreviewBody, services: Services) -> Response:
        project = _project(name, body.spec)
        svc = service(services)
        try:
            plan, shift, exact, note = svc.preview(project, body.target, body.effect, body.start, body.end)
            data, seconds = svc.window_wav(plan, body.start - shift, body.end - shift)
        except (TargetError, AudioPanelError, ValueError, FileNotFoundError, FFmpegError) as exc:
            raise failing(exc) from exc
        return Response(
            data,
            media_type="audio/wav",
            headers={
                "X-Window-Seconds": f"{seconds:.6f}",
                "X-Preview-Exact": "1" if exact else "0",
                "X-Preview-Note": quote(note),
                "Cache-Control": "no-store",
            },
        )

    return router


__all__ = ["build_audio_panel_router"]
