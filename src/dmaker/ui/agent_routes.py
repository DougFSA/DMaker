"""Rotas /api/agent da interface: a conversa com o agente local, com o progresso das ferramentas ao vivo.

Adaptador fino sobre `agent.AgentSession`. Cada mensagem do usuário vira um job (o mesmo `JobManager` e o mesmo
SSE de `/api/jobs/{id}/events` dos renders): o agente emite os eventos (kit escolhido, ferramenta chamada, andamento,
resposta) e a tela os mostra. A confirmação do que é longo ou difícil de desfazer vira um evento
`confirmation_request` e um botão; o job espera a resposta em `/api/agent/confirmations/{id}`. O motor e as
ferramentas entram por injeção, então os testes usam um modelo falso.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent import AgentSession, ConfirmationRequest, ProgressReportingHost, build_chat, load_settings
from ..agent.kits import KITS, kit_tool_names
from ..agent.session import server_tool_names
from ..agent.settings import AgentSettings, SettingsError
from ..agent.tools import DEFAULT_WAIT_SECONDS, McpToolHost, ToolHost
from ..pipeline.jobs import Job, JobManager

AGENT_KIND = "agent"
CONFIRMATION_TIMEOUT_S = 900.0  # quinze minutos sem resposta contam como "não"
MAX_MESSAGE_CHARS = 4000


class MessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: str | None = None


class ConfirmationAnswer(BaseModel):
    approve: bool


@dataclass
class PendingConfirmation:
    request: ConfirmationRequest
    answered: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class TurnRelay:
    """Liga uma conversa ao job da mensagem atual: leva os eventos do agente ao job e a confirmação ao botão.

    A sessão vive entre as mensagens, mas o job é novo a cada uma; por isso a sessão fala com o relé, e o relé
    é que aponta para o job do momento.
    """

    def __init__(self, confirmation_timeout: float = CONFIRMATION_TIMEOUT_S) -> None:
        self.job: Job | None = None
        self.confirmation_timeout = confirmation_timeout
        self._pending: dict[str, PendingConfirmation] = {}
        self._lock = threading.Lock()

    def attach(self, job: Job) -> None:
        self.job = job

    def emit(self, kind: str, data: dict[str, Any]) -> None:
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

    @property
    def waiting(self) -> int:
        with self._lock:
            return len(self._pending)


@dataclass
class Conversation:
    id: str
    relay: TurnRelay
    session: AgentSession
    running: Job | None = None


SessionFactory = Callable[[TurnRelay, AgentSettings], AgentSession]
Health = Callable[[AgentSettings], dict]


def running_mcp_jobs() -> list[dict]:
    """O que o servidor MCP em processo está executando agora (a barra de andamento da ferramenta longa)."""
    from .. import mcp_server

    return [snapshot for snapshot in mcp_server.jobs.list() if snapshot["status"] == "running"]


def default_session_factory(relay: TurnRelay, settings: AgentSettings) -> AgentSession:
    """A sessão de verdade: o motor configurado, o servidor MCP em processo e o progresso das ferramentas ao vivo."""
    from ..pipeline.recipes import project_exists

    defaults = {
        "wait_seconds": DEFAULT_WAIT_SECONDS,
        "show_ui": False,
    }  # o render aparece aqui, não numa aba nova

    def make_host(tool_names: list[str]) -> ToolHost:
        inner = McpToolHost(allowed=tool_names, argument_defaults=defaults)
        return ProgressReportingHost(inner, relay.progress, running_mcp_jobs)

    return AgentSession(
        chat=build_chat(settings),
        host_factory=make_host,
        available=server_tool_names(),
        policy=relay,
        on_event=relay.emit,
        free_html=settings.free_html,
        project_exists=project_exists,
    )


def default_health(settings: AgentSettings) -> dict:
    chat = build_chat(settings)
    alive = chat.is_alive()
    return {"reachable": alive, "model_installed": chat.has_model() if alive else False}


def kit_summaries(available: set[str] | None = None) -> list[dict]:
    names = server_tool_names() if available is None else available
    return [
        {
            "name": kit.name,
            "title": kit.title,
            "description": kit.description,
            "tools": len(kit_tool_names(kit, names)),
        }
        for kit in KITS
    ]


def build_agent_router(
    jobs: JobManager,
    session_factory: SessionFactory = default_session_factory,
    health: Health = default_health,
    settings_loader: Callable[[], AgentSettings] = load_settings,
) -> APIRouter:
    router = APIRouter(tags=["agente local"])
    conversations: dict[str, Conversation] = {}
    lock = threading.Lock()

    def settings() -> AgentSettings:
        try:
            return settings_loader()
        except SettingsError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def conversation_for(conversation_id: str | None, current: AgentSettings) -> Conversation:
        with lock:
            if conversation_id and conversation_id in conversations:
                return conversations[conversation_id]
            relay = TurnRelay()
            created = Conversation(uuid.uuid4().hex[:10], relay, session_factory(relay, current))
            conversations[created.id] = created
            return created

    @router.get("/api/agent/status")
    def status() -> dict:
        current = settings()
        state = health(current)
        return {
            "engine": current.engine,
            "engine_label": current.engine_label,
            "model": current.model,
            "url": current.url,
            "free_html": current.free_html,
            "kits": kit_summaries(),
            **state,
        }

    @router.post("/api/agent/messages")
    def send_message(body: MessageBody) -> dict:
        current = settings()
        state = health(current)
        if not state["reachable"]:
            raise HTTPException(
                status_code=503,
                detail=f"O modelo local não está respondendo em {current.url}. Abra o {current.engine_label}.",
            )
        if not state["model_installed"]:
            raise HTTPException(
                status_code=503,
                detail=f"O modelo '{current.model}' não está instalado. Veja `dmaker doctor --offline`.",
            )
        conversation = conversation_for(body.conversation_id, current)
        with lock:
            if conversation.running is not None and conversation.running.status == "running":
                raise HTTPException(
                    status_code=409, detail="O agente ainda está respondendo à mensagem anterior."
                )

            def work(job: Job) -> dict:
                conversation.relay.attach(job)
                answer = conversation.session.ask(body.message)
                return {"answer": answer, "kits": list(conversation.session.current_kits)}

            job = jobs.start(
                "agente: " + body.message[:60],
                work,
                meta={"kind": AGENT_KIND, "conversation": conversation.id},
            )
            conversation.running = job
        return {"job_id": job.id, "conversation_id": conversation.id}

    @router.post("/api/agent/confirmations/{confirmation_id}")
    def answer_confirmation(confirmation_id: str, body: ConfirmationAnswer, conversation_id: str) -> dict:
        conversation = conversations.get(conversation_id)
        if conversation is None or not conversation.relay.resolve(confirmation_id, body.approve):
            raise HTTPException(status_code=404, detail="Essa confirmação não está mais esperando resposta.")
        return {"approved": body.approve}

    @router.delete("/api/agent/conversations/{conversation_id}")
    def reset_conversation(conversation_id: str) -> dict:
        with lock:
            conversation = conversations.get(conversation_id)
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversa desconhecida.")
            if conversation.running is not None and conversation.running.status == "running":
                raise HTTPException(
                    status_code=409, detail="Espere o agente terminar a resposta para limpar."
                )
            conversation.session.reset()
        return {"reset": conversation_id}

    return router
