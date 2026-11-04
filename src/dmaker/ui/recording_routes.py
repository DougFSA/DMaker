"""Rotas da gravação pelo microfone: abrir, receber os pedaços de um segundo, finalizar e recuperar o que a aba deixou.

Adaptador fino sobre `pipeline.recordings`. O navegador captura o som (`getUserMedia` + AudioWorklet, PCM sem compressão) e
manda um pedaço por segundo numerado; cada um é gravado na hora em `<projeto>/recordings/<id>/`, então fechar a aba no
meio não perde nada. O `finish` devolve a operação do `edit_project` que põe a gravação na linha do tempo (voz nova ou
punch-in), para a interface aplicar na spec que ela tem na tela: nenhuma rota aqui grava o `spec.json`.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import config
from ..pipeline.recordings import (
    RecordingError,
    RecordingNotFound,
    RecordingStatus,
    RecordingStore,
    edit_for_recording,
)

PROJECT_NAME = re.compile(r"^[^\\/:*?\"<>|]+$")  # um nome de pasta de projeto: sem separador nem ".."


class PunchRange(BaseModel):
    target: str = Field(min_length=1)  # a voz que o punch-in regrava (audio.voiceover.N)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


class OpenRecording(BaseModel):
    rate: int
    channels: int = 1
    start: float = Field(
        0.0, allow_inf_nan=False
    )  # onde o primeiro quadro cai na linha do tempo, com a latência já compensada
    label: str = ""
    device: str = ""
    punch: PunchRange | None = None


class FinishRecording(BaseModel):
    start: float | None = Field(
        None, allow_inf_nan=False
    )  # corrige o instante, se a interface o refinou depois de abrir
    label: str | None = None
    punch: PunchRange | None = None  # o alvo do punch-in no momento de finalizar (o índice pode ter mudado)


def _store(name: str) -> RecordingStore:
    if not PROJECT_NAME.match(name) or name in (".", "..") or ".." in name:
        raise HTTPException(status_code=400, detail="Nome de projeto inválido.")
    folder = config.PROJECTS_DIR / name
    if not (folder / "spec.json").is_file():
        raise HTTPException(status_code=404, detail=f"Projeto não encontrado: {name}")
    return RecordingStore(folder)


def _fail(exc: RecordingError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, RecordingNotFound) else 400, detail=str(exc))


def _payload(status: RecordingStatus, with_edit: bool = False) -> dict[str, Any]:
    data = status.to_dict()
    if with_edit:
        data["op"] = edit_for_recording(status)
        data["recover_op"] = edit_for_recording(status, recover=True)
    return data


def build_recording_router() -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/recordings", tags=["gravação"])

    @router.post("")
    def open_recording(name: str, body: OpenRecording) -> dict:
        try:
            status = _store(name).create(
                body.rate,
                body.channels,
                body.start,
                body.label,
                body.punch.model_dump() if body.punch else None,
                body.device,
            )
        except RecordingError as exc:
            raise _fail(exc) from exc
        return _payload(status)

    @router.get("")
    def list_recordings(name: str, unfinished: bool = False) -> dict:
        store = _store(name)
        found = store.unfinished() if unfinished else store.list()
        return {"recordings": [item.to_dict() for item in found]}

    @router.get("/{recording_id}")
    def get_recording(name: str, recording_id: str) -> dict:
        try:
            return _payload(_store(name).status(recording_id))
        except RecordingError as exc:
            raise _fail(exc) from exc

    @router.put("/{recording_id}/chunks/{seq}")
    async def put_chunk(name: str, recording_id: str, seq: int, request: Request) -> dict:
        store = _store(name)
        data = await request.body()
        try:
            return store.put_chunk(recording_id, seq, data).to_dict()
        except RecordingError as exc:
            raise _fail(exc) from exc

    @router.post("/{recording_id}/finish")
    def finish_recording(name: str, recording_id: str, body: FinishRecording | None = None) -> dict:
        body = body or FinishRecording()
        store = _store(name)
        try:
            status = store.finish(
                recording_id, body.start, body.label, body.punch.model_dump() if body.punch else None
            )
            return _payload(status, with_edit=True)
        except RecordingError as exc:
            raise _fail(exc) from exc

    @router.delete("/{recording_id}")
    def discard_recording(name: str, recording_id: str) -> dict:
        try:
            _store(name).discard(recording_id)
        except RecordingError as exc:
            raise _fail(exc) from exc
        return {"discarded": recording_id}

    return router
