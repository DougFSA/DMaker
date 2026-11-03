"""Rotas /api/voices/queue da interface: a fila de narrações longas (audiobook, vários roteiros de uma vez).

Adaptador fino sobre `pipeline.voice_queue_service`. O worker que executa a fila roda numa thread deste
processo (ligada por `serve()`), segurando a mesma trava de síntese das outras rotas de voz. O andamento
sai por SSE em /api/voices/queue/events: o servidor olha a fila uma vez por segundo e só manda o que mudou,
o que também pega o progresso de um worker que esteja em outro processo (`dmaker voice queue run`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..pipeline.voice_queue import ItemNotFoundError, QueueFileError, QueueItem, QueueOptions, VoiceQueue
from ..pipeline.voice_queue_service import MAX_FILE_BYTES, MAX_TEXT_CHARS, VoiceQueueService, build_worker
from ..pipeline.voice_worker import QueueWorker
from .voice_routes import hold_synthesis

EVENTS_INTERVAL_S = 1.0
EVENTS_KEEPALIVE_S = 15.0


class QueueRuntime:
    """O serviço da fila e o worker deste processo, criados só quando alguém precisa (a importação não toca disco)."""

    def __init__(self) -> None:
        self._service: VoiceQueueService | None = None
        self.worker: QueueWorker | None = None

    def service(self) -> VoiceQueueService:
        if self._service is None:
            self._service = VoiceQueueService(VoiceQueue(), on_change=self.wake)
        return self._service

    def start_worker(self) -> None:
        """Liga o worker da fila neste processo; chamado por `dmaker ui`, nunca pela importação nem pelos testes."""
        if self.worker is None:
            self.worker = build_worker(self.service().queue, guard=hold_synthesis)
        self.worker.start()

    def wake(self) -> None:
        if self.worker is not None:
            self.worker.wake()

    @property
    def worker_running(self) -> bool:
        return self.worker is not None and self.worker.running


runtime = QueueRuntime()


def get_queue_service() -> VoiceQueueService:
    return runtime.service()


Queue = Annotated[VoiceQueueService, Depends(get_queue_service)]


class QueueTextRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    title: str | None = None
    voice: str | None = None
    language: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    brand: str | None = None
    draft: bool = False
    format: Literal["wav", "mp3"] = "wav"


class MoveRequest(BaseModel):
    direction: Literal[-1, 1]


def _options(
    voice: str | None, language: str | None, speed: float, brand: str | None, draft: bool, audio_format: str
) -> QueueOptions:
    return QueueOptions(
        voice=voice or None,
        language=language or None,
        speed=speed,
        brand=brand or None,
        draft=draft,
        audio_format=audio_format,
    )


def queue_event_stream(
    service: VoiceQueueService,
    interval: float = EVENTS_INTERVAL_S,
    keepalive: float = EVENTS_KEEPALIVE_S,
    sleep: Callable[[float], None] = time.sleep,
    snapshot: Callable[[], dict] | None = None,
) -> Iterator[str]:
    """Quadros SSE da fila: a fila inteira quando muda e um comentário de vida a cada `keepalive` segundos.

    `snapshot` devolve a foto a mandar; sem ele vale `service.view()`. A rota passa a foto com o aviso de
    executor ativo, que a tela precisa também no fluxo e não só na primeira leitura.
    """
    take = snapshot or service.view
    last: str | None = None
    quiet = 0.0
    while True:
        payload = json.dumps(take(), ensure_ascii=False)
        if payload != last:
            last, quiet = payload, 0.0
            yield f"data: {payload}\n\n"
        else:
            quiet += interval
            if quiet >= keepalive:
                quiet = 0.0
                yield ": keep-alive\n\n"
        sleep(interval)


def _view(service: VoiceQueueService) -> dict:
    return {**service.view(), "worker": runtime.worker_running}


def _lookup(service: VoiceQueueService, item_id: str) -> QueueItem:
    try:
        return service.queue.get(item_id)
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc


def _guarded(action: Callable[[], object]) -> None:
    """Transição pedida pela tela: regra de estado violada vira 400 com a frase pronta, item sumido vira 404."""
    try:
        action()
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_queue_router() -> APIRouter:
    router = APIRouter(prefix="/api/voices/queue", tags=["fila de voz"])

    @router.get("")
    def list_queue(service: Queue) -> dict:
        try:
            return _view(service)
        except QueueFileError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/events")
    def queue_events(service: Queue) -> StreamingResponse:
        return StreamingResponse(
            queue_event_stream(service, snapshot=lambda: _view(service)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @router.post("")
    def add_text(req: QueueTextRequest, service: Queue) -> dict:
        options = _options(req.voice, req.language, req.speed, req.brand, req.draft, req.format)
        try:
            item = service.add_text(req.text, options, req.title or None)
        except ValueError as exc:  # inclui voz inexistente (VoiceNotFoundError)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": item.id, **_view(service)}

    @router.post("/upload")
    def add_file(
        service: Queue,
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form()] = None,
        voice: Annotated[str | None, Form()] = None,
        language: Annotated[str | None, Form()] = None,
        speed: Annotated[float, Form(ge=0.5, le=2.0)] = 1.0,
        brand: Annotated[str | None, Form()] = None,
        draft: Annotated[bool, Form()] = False,
        format: Annotated[Literal["wav", "mp3"], Form()] = "wav",
    ) -> dict:
        data = file.file.read(MAX_FILE_BYTES + 1)
        try:
            item = service.add_file(
                data,
                file.filename or "roteiro.txt",
                _options(voice, language, speed, brand, draft, format),
                title,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": item.id, **_view(service)}

    @router.post("/clear-finished")
    def clear_finished(service: Queue) -> dict:
        removed = service.queue.clear_finished()
        return {"removed": removed, **_view(service)}

    @router.post("/{item_id}/pause")
    def pause(item_id: str, service: Queue) -> dict:
        _guarded(lambda: service.queue.pause(item_id))
        return _view(service)

    @router.post("/{item_id}/resume")
    def resume(item_id: str, service: Queue) -> dict:
        _guarded(lambda: service.queue.resume(item_id))
        service.on_change()
        return _view(service)

    @router.post("/{item_id}/retry")
    def retry(item_id: str, service: Queue) -> dict:
        _guarded(lambda: service.queue.retry(item_id))
        service.on_change()
        return _view(service)

    @router.post("/{item_id}/cancel")
    def cancel(item_id: str, service: Queue) -> dict:
        _guarded(lambda: service.queue.cancel(item_id))
        return _view(service)

    @router.post("/{item_id}/move")
    def move(item_id: str, req: MoveRequest, service: Queue) -> dict:
        _guarded(lambda: service.queue.move(item_id, req.direction))
        return _view(service)

    @router.delete("/{item_id}")
    def remove(item_id: str, service: Queue) -> dict:
        _guarded(lambda: service.queue.remove(item_id))
        return _view(service)

    @router.get("/{item_id}/files/{name}")
    def item_file(item_id: str, name: str, service: Queue, download: bool = False) -> FileResponse:
        item = _lookup(service, item_id)
        if (
            name not in item.outputs
        ):  # só os arquivos que a fila gerou para este item, nunca um caminho qualquer
            raise HTTPException(status_code=404, detail="Arquivo não encontrado neste item.")
        path = Path(item.output_dir) / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="O arquivo não está mais na pasta de saída.")
        return FileResponse(path, filename=name if download else None)

    return router
