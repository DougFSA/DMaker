"""O relé de um turno do agente: leva os eventos da sessão ao job da mensagem atual e a confirmação ao botão.

A sessão (e a conversa) vive entre as mensagens, mas o job é novo a cada uma; por isso a sessão fala com o relé, e o
relé é que aponta para o job do momento. A confirmação do que é longo ou difícil de desfazer vira um evento
`confirmation_request` e um botão; o turno espera a resposta, e o Parar a solta como "não".
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..agent import ConfirmationRequest
from ..pipeline.jobs import Job

CONFIRMATION_TIMEOUT_S = 900.0  # quinze minutos sem resposta contam como "não"


@dataclass
class PendingConfirmation:
    request: ConfirmationRequest
    answered: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class TurnRelay:
    """Liga uma conversa ao job da mensagem atual: leva os eventos do agente ao job e a confirmação ao botão."""

    def __init__(self, confirmation_timeout: float = CONFIRMATION_TIMEOUT_S) -> None:
        self.job: Job | None = None
        self.confirmation_timeout = confirmation_timeout
        # quem mais quer ver os eventos do turno (a conversa salva monta a transcrição a partir deles)
        self.tap: Callable[[str, dict[str, Any]], None] | None = None
        self._pending: dict[str, PendingConfirmation] = {}
        self._lock = threading.Lock()
        self._stopped = False

    def attach(self, job: Job) -> None:
        """Começa o turno do job: um Parar do turno anterior não vale para este."""
        with self._lock:
            self.job = job
            self._stopped = False

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        # A conversa salva vem primeiro: quem vê o evento na tela já encontra o passo guardado se recarregar a página.
        if self.tap is not None:
            try:
                self.tap(kind, data)
            except Exception:  # noqa: BLE001 - a transcrição nunca pode derrubar o turno que ela só registra
                pass
        if self.job is not None:
            self.job.emit(kind, **data)

    def progress(self, tool: str, snapshot: dict) -> None:
        """O andamento de uma ferramenta longa (render, transcrição) vira o progresso do job do agente."""
        info = snapshot.get("progress") or {}
        self.emit("tool_progress", {"name": tool, "status": snapshot.get("status"), "progress": info})
        if self.job is not None and info:
            self.job.progress = {**info, "label": f"{tool}: {info.get('label', '')}".strip(": ")}
            self.job.emit("progress", **self.job.progress)

    def confirm(self, request: ConfirmationRequest) -> bool:
        pending = PendingConfirmation(request)
        confirmation_id = uuid.uuid4().hex[:10]
        with self._lock:
            if self._stopped:  # a pessoa já mandou parar: nem pergunta, e a resposta é "não"
                return False
            self._pending[confirmation_id] = pending
        self.emit(
            "confirmation_request",
            {"id": confirmation_id, "tool": request.tool, "question": request.question, "type": request.kind},
        )
        pending.answered.wait(timeout=self.confirmation_timeout)
        with self._lock:
            self._pending.pop(confirmation_id, None)
        self.emit("confirmation_answered", {"id": confirmation_id, "approved": pending.approved})
        return pending.approved

    def resolve(self, confirmation_id: str, approve: bool) -> bool:
        """Responde a uma confirmação pendente; `False` se ela não existe (já respondida ou expirada)."""
        with self._lock:
            pending = self._pending.get(confirmation_id)
        if pending is None:
            return False
        pending.approved = approve
        pending.answered.set()
        return True

    def cancel(self) -> None:
        """O Parar: solta toda confirmação pendente como "não" e recusa as que viriam depois, até o próximo turno."""
        with self._lock:
            self._stopped = True
            pending = list(self._pending.values())
        for item in pending:
            item.approved = False
            item.answered.set()

    @property
    def waiting(self) -> int:
        with self._lock:
            return len(self._pending)
