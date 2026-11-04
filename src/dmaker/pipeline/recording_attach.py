"""Pôr na spec uma gravação do microfone que já está no disco: a CLI e o MCP usam isto para recuperar a gravação que a
aba deixou aberta, ou para aplicar um punch-in de uma gravação finalizada, sem passar pela interface.

A interface faz o mesmo por conta própria (aplica a operação que o `finish` devolve na spec que tem na tela); aqui a
operação vai pelo `edit_and_record`, então entra no histórico do projeto e `dmaker undo` a desfaz."""

from __future__ import annotations

from pathlib import Path

from .edit_history import edit_and_record
from .edit_outcome import EditReport
from .projects import project_path
from .recordings import RecordingError, RecordingStatus, RecordingStore, edit_for_recording


def store_of(project: str | Path) -> RecordingStore:
    """As gravações da pasta do projeto (nome em `projects/` ou caminho do `spec.json`)."""
    return RecordingStore(project_path(project).parent)


def listing(project: str | Path, unfinished: bool = False) -> list[dict]:
    store = store_of(project)
    return [item.to_dict() for item in (store.unfinished() if unfinished else store.list())]


def attach_recording(
    project: str | Path, identifier: str | None = None, punch: bool = False
) -> tuple[RecordingStatus, EditReport]:
    """Finaliza a gravação (a única aberta, se `identifier` vier vazio) e a põe na linha do tempo: voz nova em geral, ou o
    punch-in que ela guardou ao abrir quando `punch` é verdadeiro. Uma gravação aberta é finalizada com o que chegou."""
    store = store_of(project)
    if identifier is None:
        candidates = store.unfinished()
        if len(candidates) != 1:
            raise RecordingError(
                "diga qual gravação (`id`): há "
                + (f"{len(candidates)} gravações abertas" if candidates else "nenhuma gravação aberta")
            )
        identifier = candidates[0].id
    status = store.finish(identifier)
    report, _ = edit_and_record(project, edit_for_recording(status, recover=not punch))
    return status, report
