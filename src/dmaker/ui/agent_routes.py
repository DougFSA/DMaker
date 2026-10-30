"""Rotas /api/agent da interface: a conversa com o agente local, salva em disco, com a resposta chegando ao vivo.

Adaptador fino sobre as conversas (`agent_conversations`) e `agent.AgentSession`/`FreeSession`. Cada mensagem do usuário
vira um job (o mesmo `JobManager` e o mesmo SSE de `/api/jobs/{id}/events` dos renders): o agente emite os eventos (kit
escolhido, etapa, trechos da resposta e do raciocínio, ferramenta chamada, andamento, resposta) e a tela os mostra. O
job do turno é cancelável: o Parar fecha a conexão com o modelo, solta a confirmação pendente como "não" e termina o
job como cancelado, guardando a resposta parcial. A confirmação do que é longo ou difícil de desfazer vira um evento
`confirmation_request` e um botão; o job espera a resposta em `/api/agent/confirmations/{id}`. As conversas (criar,
listar, abrir, renomear, mudar modelo e esforço, apagar) vivem em `/api/agent/conversations`. Também mora aqui o
catálogo de modelos (`/api/agent/models`, `/loaded`, `/unload`): o que está instalado, o que está na memória e se cabe.
O motor, as ferramentas, o catálogo, a leitura da memória e o repositório de conversas entram por injeção, então os
testes usam falsos.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..agent import AgentSession, ProgressReportingHost, build_chat, load_settings
from ..agent.attachments import (
    KIND_IMAGE,
    MAX_ATTACHMENTS_PER_MESSAGE,
    AttachedFile,
    AttachmentRecord,
    AttachmentRefused,
    compose_turn,
)
from ..agent.catalog import CatalogError, ModelCatalog, ModelInfo, model_entries
from ..agent.conversations import (
    MODE_OPERATE,
    ConversationFormatError,
    ConversationInUseError,
    ConversationOptions,
    ConversationStore,
    DiskConversationStore,
    configure_chat,
    settings_for_conversation,
)
from ..agent.free_session import FreeSession
from ..agent.kits import KITS, kit_tool_names
from ..agent.llm import StreamingChat, same_model
from ..agent.loop import TurnControl
from ..agent.memory import MemoryProbe, WindowsMemoryProbe
from ..agent.session import server_tool_names
from ..agent.settings import AgentSettings, SettingsError, build_catalog
from ..agent.tools import DEFAULT_WAIT_SECONDS, McpToolHost, ToolHost
from ..pipeline.jobs import Job, JobCancelled, JobManager
from .agent_attachments import AttachmentService, register_attachment_routes
from .agent_conversations import (
    KEEP,
    Conversation,
    ConversationRegistry,
    ModeLockedError,
    SessionFactory,
    with_model,
)
from .agent_turns import CONFIRMATION_TIMEOUT_S, PendingConfirmation, TurnRelay

__all__ = [
    "AGENT_KIND",
    "CONFIRMATION_TIMEOUT_S",
    "PendingConfirmation",
    "TurnRelay",
    "build_agent_router",
    "kit_summaries",
]

AGENT_KIND = "agent"
MAX_MESSAGE_CHARS = 4000
MAX_TITLE_CHARS = 120
Mode = Literal["operate", "free"]


class OptionsBody(BaseModel):
    """As opções avançadas da conversa; o que não vem fica no padrão do ambiente."""

    num_ctx: int | None = Field(default=None, ge=512, le=4_194_304)
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = Field(default=None, ge=0)

    def to_options(self) -> ConversationOptions:
        return ConversationOptions(self.num_ctx, self.temperature, self.seed)


class MessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: str | None = None
    # Valem para a conversa a partir desta mensagem (e ficam gravadas nela); sem `conversation_id`, criam a conversa.
    mode: Mode | None = None
    model: str | None = Field(default=None, min_length=1)
    effort: str | None = None
    options: OptionsBody | None = None
    # Os ids dos anexos já enviados à conversa (`POST /conversations/{id}/attachments`) que seguem nesta mensagem.
    attachments: list[str] = Field(default_factory=list, max_length=MAX_ATTACHMENTS_PER_MESSAGE)


class CreateConversationBody(BaseModel):
    mode: Mode = MODE_OPERATE
    model: str | None = Field(default=None, min_length=1)
    effort: str | None = None
    options: OptionsBody | None = None


class UpdateConversationBody(BaseModel):
    """Só o que veio é alterado. `effort: null` volta ao padrão do modelo; `options: null` volta às opções do ambiente."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_CHARS)
    mode: Mode | None = None  # só enquanto a conversa não teve mensagem
    model: str | None = Field(default=None, min_length=1)
    effort: str | None = None
    options: OptionsBody | None = None


class ConfirmationAnswer(BaseModel):
    approve: bool


class UnloadBody(BaseModel):
    model: str = Field(min_length=1)


Health = Callable[[AgentSettings], dict]
CatalogFactory = Callable[[AgentSettings], ModelCatalog]


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


def default_free_session_factory(relay: TurnRelay, settings: AgentSettings) -> FreeSession:
    """A conversa livre: o mesmo motor, sem ferramentas e sem nada que precise de confirmação."""
    return FreeSession(chat=build_chat(settings), on_event=relay.emit)


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
    catalog_factory: CatalogFactory = build_catalog,
    memory_probe: MemoryProbe | None = None,
    store: ConversationStore | None = None,
    free_session_factory: SessionFactory = default_free_session_factory,
    attachments: AttachmentService | None = None,
) -> APIRouter:
    router = APIRouter(tags=["agente local"])
    registry = ConversationRegistry(store or DiskConversationStore(), session_factory, free_session_factory)
    attachment_service = attachments or AttachmentService()
    catalogs: dict[
        tuple[str, str], ModelCatalog
    ] = {}  # um por servidor: o detalhe de cada modelo fica guardado
    lock = registry.lock  # a mesma trava: começar um turno e descarregar um modelo não podem se cruzar
    probe = memory_probe or WindowsMemoryProbe()

    def settings() -> AgentSettings:
        try:
            return settings_loader()
        except SettingsError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def open_conversation(conversation_id: str, current: AgentSettings) -> Conversation:
        """A conversa viva ou a salva em disco; 404 se não existe."""
        try:
            conversation = registry.get(conversation_id, current)
        except ConversationFormatError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversa desconhecida.")
        return conversation

    def catalog_for(current: AgentSettings) -> ModelCatalog:
        with lock:
            key = (current.engine, current.url)
            if key not in catalogs:
                catalogs[key] = catalog_factory(current)
            return catalogs[key]

    def catalog_failure(exc: CatalogError, current: AgentSettings) -> HTTPException:
        """O servidor fora do ar é 503 (como em `/messages`); a recusa dele mantém o código quando faz sentido."""
        if exc.status is None:
            return HTTPException(
                status_code=503,
                detail=f"O modelo local não está respondendo em {current.url}. Abra o {current.engine_label}.",
            )
        return HTTPException(status_code=exc.status if exc.status in (400, 404) else 502, detail=str(exc))

    def require_model_server(current: AgentSettings, model: str) -> None:
        """O servidor do modelo no ar e o modelo instalado; senão 503 com o que a pessoa precisa fazer."""
        state = health(with_model(current, model))
        if not state["reachable"]:
            raise HTTPException(
                status_code=503,
                detail=f"O modelo local não está respondendo em {current.url}. Abra o {current.engine_label}.",
            )
        if not state["model_installed"]:
            raise HTTPException(
                status_code=503,
                detail=f"O modelo '{model}' não está instalado. Veja `dmaker doctor --offline`.",
            )

    def require_installed_if_known(current: AgentSettings, model: str) -> None:
        """Ao escolher o modelo de uma conversa: recusa o que o servidor diz não ter; servidor fora do ar não impede."""
        state = health(with_model(current, model))
        if state["reachable"] and not state["model_installed"]:
            raise HTTPException(status_code=422, detail=f"O modelo '{model}' não está instalado.")

    def resolve_effort(
        current: AgentSettings,
        model: str,
        effort: str | None,
        explicit: bool,
        new_options: ConversationOptions | None,
    ) -> str | None:
        """O esforço que vale para o modelo escolhido, conferido contra o que ele aceita.

        Um esforço pedido que o modelo não tem é 422. Um esforço herdado (a pessoa só trocou de modelo) que o novo
        modelo não tem volta ao padrão, em vez de enviar ao Ollama um valor que ele recusa. O contexto das opções novas
        também não pode passar do máximo do modelo. Sem catálogo ou sem o modelo na lista, nada é bloqueado.
        """
        if effort is None and not (new_options and new_options.num_ctx):
            return None
        try:
            info = next((m for m in catalog_for(current).models() if same_model(m.name, model)), None)
        except CatalogError:
            return effort
        if info is None:
            return effort
        if (
            new_options
            and new_options.num_ctx
            and info.context_length
            and new_options.num_ctx > info.context_length
        ):
            raise HTTPException(
                status_code=422,
                detail=f"O contexto máximo do modelo {info.name} é {info.context_length} tokens.",
            )
        if effort is None:
            return None
        levels = {level.value: level.label for level in info.effort_levels}
        if effort in levels:
            return effort
        if not explicit:
            return None
        detail = (
            f"O modelo {info.name} não tem o esforço '{effort}'. Escolha entre: {', '.join(levels.values())}."
            if levels
            else f"O modelo {info.name} não tem escolha de esforço."
        )
        raise HTTPException(status_code=422, detail=detail)

    def model_is_cold(current: AgentSettings, conversation: Conversation, num_ctx: int) -> bool:
        """O modelo vai ter de ser carregado antes do primeiro trecho? Só o Ollama sabe dizer.

        Frio é o modelo que não está na memória e também o que está carregado com outro contexto: o Ollama recarrega o
        modelo quando o `num_ctx` pedido muda (uns 60 s a mais na CPU), e a tela não deve chamar isso de "lendo o pedido".
        """
        if not isinstance(conversation.session.chat, StreamingChat):
            return False
        catalog = catalog_for(current)
        if not catalog.can_unload:
            return False
        try:
            running = catalog.loaded()
        except CatalogError:
            return False
        return not any(
            same_model(item.name, conversation.model) and item.context_length in (None, num_ctx)
            for item in running
        )

    def installed_model(current: AgentSettings, model: str) -> tuple[ModelInfo | None, list[ModelInfo]]:
        """O que o servidor diz de um modelo e a lista de todos, ou `(None, [])` se não dá para saber.

        Só o Ollama informa o que cada modelo faz (imagem, ferramentas). Nos outros motores, com o servidor fora do
        ar, com o modelo fora da lista ou com o detalhe dele ilegível, nada se sabe e nada é recusado: o servidor
        responde, e a falha dele chega à pessoa em português (`describe_failure`).
        """
        if current.engine != "ollama":
            return None, []
        try:
            installed = catalog_for(current).models()
        except CatalogError:
            return None, []
        info = next((item for item in installed if same_model(item.name, model)), None)
        if info is None or not info.capabilities_known:
            return None, []
        return info, installed

    def require_tools_when_operating(current: AgentSettings, mode: str, model: str) -> None:
        """Operar o DMaker é usar ferramentas: um modelo que sabidamente não as tem é recusado aqui, sem passar pelo Ollama."""
        if mode != MODE_OPERATE:
            return
        info, _ = installed_model(current, model)
        if info is not None and "tools" not in info.capabilities:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"O modelo {info.name} não usa ferramentas. Para operar o DMaker, escolha um modelo com "
                    "ferramentas; para conversar com ele, use a Conversa livre."
                ),
            )

    def model_sees_images(current: AgentSettings, model: str) -> bool:
        """O modelo lê imagem? Só o que o servidor diz não ter visão conta como "não": sem a informação, a imagem segue."""
        info, _ = installed_model(current, model)
        return info is None or "vision" in info.capabilities

    def vision_refusal(
        current: AgentSettings, model: str, records: Sequence[AttachmentRecord]
    ) -> JSONResponse | None:
        """O 422 de uma mensagem com imagem, numa Conversa livre, para um modelo que não enxerga, com os que enxergam.

        Só a Conversa livre recusa: ali a imagem existe para o modelo olhar. Quem opera o DMaker usa a imagem também como
        arquivo (o caminho vai no texto), então um modelo que não enxerga continua servindo e a imagem segue sem a visão.
        """
        if not any(record.kind == KIND_IMAGE for record in records):
            return None
        info, installed = installed_model(current, model)
        if info is None or "vision" in info.capabilities:
            return None
        seeing = [item.name for item in installed if "vision" in item.capabilities]
        if seeing:
            advice = f"Escolha um destes: {', '.join(seeing)}."
        else:
            advice = "Nenhum modelo instalado aceita imagem; instale um com o selo de imagem no Ollama para usar este anexo."
        message = f"O modelo {info.name} não aceita imagens. {advice}"
        return JSONResponse(
            status_code=422, content={"detail": message, "error": message, "suggested_models": seeing}
        )

    def stop_turn(conversation: Conversation) -> None:
        """O Parar: a confirmação pendente vira "não" e a conexão com o modelo é fechada (o sinal já foi marcado)."""
        conversation.relay.cancel()
        conversation.session.abort()

    def run_turn(
        conversation: Conversation,
        job: Job,
        message: str,
        current: AgentSettings,
        attached: Sequence[AttachedFile] = (),
        sees_images: bool = True,
    ) -> dict:
        conversation.relay.attach(job)
        job.on_cancel(lambda: stop_turn(conversation))
        turn = settings_for_conversation(current, conversation.record)
        try:
            composed = compose_turn(
                attached, turn.num_ctx, conversation.record.mode == MODE_OPERATE, sees_images=sees_images
            )
        except AttachmentRefused as exc:  # a rota já conferiu; isto é a última barreira
            conversation.begin_turn(message)
            conversation.fail(exc)
            raise
        conversation.begin_turn(message, composed.summaries)
        configure_chat(conversation.session.chat, turn)
        control = TurnControl(
            should_stop=lambda: job.cancel_requested,
            num_ctx=turn.num_ctx,
            model_cold=model_is_cold(current, conversation, turn.num_ctx),
        )
        try:
            answer = conversation.session.ask(message, control, composed.attachments)
        except Exception as exc:
            conversation.fail(exc, with_images=bool(composed.attachments.images))
            raise
        conversation.end_turn()
        result = {"answer": answer, "kits": list(conversation.session.current_kits)}
        if conversation.session.interrupted:
            raise JobCancelled("Resposta interrompida.", result={**result, "interrupted": True})
        return result

    # ---------- estado e catálogo de modelos ----------

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

    @router.get("/api/agent/models")
    def models() -> dict:
        current = settings()
        catalog = catalog_for(current)
        try:
            installed = catalog.models()
        except CatalogError as exc:
            raise catalog_failure(exc, current) from exc
        try:
            running = catalog.loaded()
        except (
            CatalogError
        ):  # a lista é o que importa; sem saber o que está carregado, ninguém conta como "cabe"
            running = []
        memory = probe.read()
        return {
            "engine": current.engine,
            "default_model": current.model,
            "memory": memory.to_dict() if memory is not None else None,
            "models": model_entries(installed, running, memory),
        }

    @router.get("/api/agent/loaded")
    def loaded() -> dict:
        current = settings()
        try:
            running = catalog_for(current).loaded()
        except CatalogError as exc:
            raise catalog_failure(exc, current) from exc
        return {"engine": current.engine, "models": [item.to_dict() for item in running]}

    @router.post("/api/agent/unload")
    def unload(body: UnloadBody) -> dict:
        current = settings()
        catalog = catalog_for(current)
        if not catalog.can_unload:
            raise HTTPException(status_code=400, detail="Este motor não descarrega modelos.")
        with lock:  # segurar a trava impede que um turno comece com o modelo no meio de ser descarregado
            if registry.uses_model(lambda name: same_model(name, body.model)):
                raise HTTPException(
                    status_code=409,
                    detail="Uma conversa está usando esse modelo agora. Espere a resposta terminar ou pare-a antes de descarregar.",
                )
            try:
                was_loaded = catalog.unload(body.model)
            except CatalogError as exc:
                raise catalog_failure(exc, current) from exc
        return {"model": body.model, "unloaded": was_loaded}

    # ---------- mensagens e confirmações ----------

    @router.post("/api/agent/messages", response_model=None)
    def send_message(body: MessageBody) -> dict | JSONResponse:
        current = settings()
        conversation = open_conversation(body.conversation_id, current) if body.conversation_id else None
        if body.attachments and conversation is None:
            raise HTTPException(
                status_code=422, detail="Os anexos pertencem a uma conversa: envie também o conversation_id."
            )
        model = body.model or (conversation.model if conversation else current.model)
        mode = body.mode or (conversation.record.mode if conversation else MODE_OPERATE)
        require_model_server(current, model)
        require_tools_when_operating(current, mode, model)
        records = (
            attachment_service.lookup(conversation, body.attachments)
            if conversation is not None and body.attachments
            else []
        )
        if mode != MODE_OPERATE and (refusal := vision_refusal(current, model, records)) is not None:
            return refusal
        # quem opera sem enxergar recebe a imagem só como caminho; a pergunta ao servidor só vale com imagem na mensagem
        sees_images = not any(record.kind == KIND_IMAGE for record in records) or model_sees_images(
            current, model
        )
        options = body.options.to_options() if body.options is not None else None
        explicit_effort = "effort" in body.model_fields_set
        inherited = conversation.record.effort if conversation else None
        model_changed = conversation is not None and not same_model(model, conversation.model)
        effort = inherited
        if explicit_effort or model_changed or (options and options.num_ctx):
            effort = resolve_effort(
                current,
                model,
                (body.effort or None) if explicit_effort else inherited,
                explicit_effort,
                options,
            )
        with lock:
            attached: list[AttachedFile] = []
            if conversation is None:
                conversation = registry.create(current, body.mode or MODE_OPERATE, model, effort, options)
            else:
                if (
                    registry.cached(conversation.id) is not conversation
                ):  # apagada entre abrir e começar o turno
                    raise HTTPException(status_code=404, detail="Conversa desconhecida.")
                if conversation.is_running:
                    raise HTTPException(
                        status_code=409, detail="O agente ainda está respondendo à mensagem anterior."
                    )
                if (
                    records
                ):  # antes de mudar qualquer coisa: um anexo recusado não deixa a conversa pela metade
                    attached = attachment_service.load(conversation, records, mode == MODE_OPERATE)
                if body.mode is not None:
                    try:
                        registry.change_mode(conversation, body.mode, current)
                    except ModeLockedError as exc:
                        raise HTTPException(status_code=409, detail=str(exc)) from exc
                if model_changed or explicit_effort or effort != inherited or options is not None:
                    conversation.update(
                        model=model if model_changed else None,
                        effort=effort if (explicit_effort or effort != inherited) else KEEP,
                        options=options,
                    )
            target = conversation
            sent = tuple(attached)
            if sent:
                target.mark_attachments_sent(item.record.id for item in sent)
            job = jobs.start(
                "agente: " + body.message[:60],
                lambda running_job: run_turn(target, running_job, body.message, current, sent, sees_images),
                meta={"kind": AGENT_KIND, "conversation": target.id, "cancellable": True},
            )
            target.running = job
        return {"job_id": job.id, "conversation_id": target.id}

    @router.post("/api/agent/confirmations/{confirmation_id}")
    def answer_confirmation(confirmation_id: str, body: ConfirmationAnswer, conversation_id: str) -> dict:
        conversation = registry.cached(conversation_id)
        if conversation is None or not conversation.relay.resolve(confirmation_id, body.approve):
            raise HTTPException(status_code=404, detail="Essa confirmação não está mais esperando resposta.")
        return {"approved": body.approve}

    # ---------- conversas salvas ----------

    @router.get("/api/agent/conversations")
    def list_conversations() -> dict:
        return {"conversations": registry.summaries()}

    @router.post("/api/agent/conversations")
    def create_conversation(body: CreateConversationBody) -> dict:
        current = settings()
        model = body.model or current.model
        if body.model:
            require_installed_if_known(current, model)
        require_tools_when_operating(current, body.mode, model)
        options = body.options.to_options() if body.options is not None else None
        effort = resolve_effort(current, model, body.effort or None, True, options)
        return registry.create(current, body.mode, model, effort, options).detail(current.num_ctx)

    @router.get("/api/agent/conversations/{conversation_id}")
    def get_conversation(conversation_id: str) -> dict:
        current = settings()
        return open_conversation(conversation_id, current).detail(current.num_ctx)

    @router.patch("/api/agent/conversations/{conversation_id}")
    def update_conversation(conversation_id: str, body: UpdateConversationBody) -> dict:
        current = settings()
        conversation = open_conversation(conversation_id, current)
        fields = body.model_fields_set
        model = body.model or conversation.model
        model_changed = not same_model(model, conversation.model)
        if model_changed:
            require_installed_if_known(current, model)
        if model_changed or body.mode is not None:
            require_tools_when_operating(current, body.mode or conversation.record.mode, model)
        options = body.options.to_options() if body.options is not None else None
        if "options" in fields and body.options is None:
            options = ConversationOptions()  # `options: null` volta às opções do ambiente
        explicit_effort = "effort" in fields
        inherited = conversation.record.effort
        effort = inherited
        if explicit_effort or model_changed or (options and options.num_ctx):
            effort = resolve_effort(
                current,
                model,
                (body.effort or None) if explicit_effort else inherited,
                explicit_effort,
                options,
            )
        with lock:
            if conversation.is_running and model_changed:
                raise HTTPException(
                    status_code=409, detail="Espere a resposta terminar para trocar o modelo da conversa."
                )
            if body.mode is not None:
                try:
                    registry.change_mode(conversation, body.mode, current)
                except ModeLockedError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
            conversation.update(
                title=body.title or None,
                model=model if model_changed else None,
                effort=effort if (explicit_effort or effort != inherited) else KEEP,
                options=options,
            )
        return conversation.detail(current.num_ctx)

    @router.delete("/api/agent/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str) -> dict:
        with lock:
            live = registry.cached(conversation_id)
            if live is not None and live.is_running:
                raise HTTPException(
                    status_code=409, detail="Pare a resposta do agente antes de apagar a conversa."
                )
            try:
                existed = registry.delete(conversation_id)
            except ConversationInUseError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not existed:
            raise HTTPException(status_code=404, detail="Conversa desconhecida.")
        return {"deleted": conversation_id}

    @router.post("/api/agent/conversations/{conversation_id}/stop")
    def stop_conversation(conversation_id: str) -> dict:
        """O Parar pela conversa (a tela não precisa guardar o job): o mesmo que cancelar o job do turno."""
        conversation = open_conversation(conversation_id, settings())
        running = conversation.running
        if running is None or not conversation.is_running:
            raise HTTPException(status_code=409, detail="Não há resposta em andamento para parar.")
        jobs.cancel(running.id)
        return {"stopping": True, "job_id": running.id}

    register_attachment_routes(router, attachment_service, open_conversation, settings)
    return router
