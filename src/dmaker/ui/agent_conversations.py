"""As conversas vivas do agente: a sessão, o registro salvo em disco e a transcrição que cresce com os eventos.

`Conversation` junta o que uma conversa tem em memória (a sessão do modelo, o relé do turno, a transcrição) ao registro
que vai para o disco; `ConversationRegistry` guarda as vivas, abre as salvas (depois de reiniciar o DMaker) e cria as
novas. As rotas só falam com o registro. A sessão é fabricada por injeção, um modo por fábrica, então os testes não
precisam de Ollama.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..agent.conversations import (
    MODE_FREE,
    MODE_OPERATE,
    ConversationOptions,
    ConversationRecord,
    ConversationStore,
    new_record,
    settings_for_conversation,
    title_from_message,
)
from ..agent.history import repair_history
from ..agent.session import ConversationSession
from ..agent.settings import AgentSettings
from ..agent.transcript import TranscriptBuilder, utc_now
from ..pipeline.jobs import Job
from .agent_turns import TurnRelay

SessionFactory = Callable[[TurnRelay, AgentSettings], ConversationSession]

# Os eventos depois dos quais a conversa vai para o disco: o que acabou de acontecer vale ser guardado se o DMaker fechar.
SAVE_EVENTS = frozenset(
    {
        "tool_blocked",
        "tool_result",
        "confirmation_request",
        "confirmation_answered",
        "answer",
        "history_trimmed",
    }
)


class ModeLockedError(Exception):
    """O modo da conversa não muda depois da primeira mensagem."""


class _Keep:
    """O valor de "não mexer" num campo que também aceita `None` (tirar a escolha e voltar ao padrão)."""


KEEP = _Keep()


class Conversation:
    """Uma conversa viva. O registro (`record`) é o que vai a disco; a sessão é o que fala com o modelo."""

    def __init__(
        self,
        record: ConversationRecord,
        relay: TurnRelay,
        session: ConversationSession,
        store: ConversationStore,
    ) -> None:
        self.record = record
        self.relay = relay
        self.session = session
        self.store = store
        self.transcript = TranscriptBuilder(record.transcript)
        self.running: Job | None = None
        self.lock = threading.RLock()  # os eventos chegam da thread do turno e as rotas leem de outra
        self._save_warned = False
        relay.tap = self.on_event

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def model(self) -> str:
        """O modelo desta conversa: descarregá-lo no meio da resposta derrubaria o turno."""
        return self.record.model

    @property
    def is_running(self) -> bool:
        return self.running is not None and self.running.status == "running"

    def _save(self, touch: bool = True) -> None:
        """Grava a conversa. Disco cheio ou arquivo travado não derrubam o turno: viram um aviso, uma vez."""
        with self.lock:
            self.record.history = self.session.history
            self.record.kits = list(self.session.current_kits)
            self.record.transcript = self.transcript.snapshot()
            if touch:
                self.record.updated_at = utc_now()
            try:
                self.store.save(self.record)
            except OSError as exc:
                if not self._save_warned:
                    self._save_warned = True
                    self.transcript.add_notice(
                        "warning", "save_failed", f"Não consegui salvar a conversa: {exc}"
                    )

    def save(self, touch: bool = True) -> None:
        self._save(touch)

    def on_event(self, kind: str, data: dict[str, Any]) -> None:
        """Cada evento do turno entra na transcrição; os que marcam um passo concluído também salvam."""
        with self.lock:
            self.transcript.apply(kind, data)
            if kind in SAVE_EVENTS:
                self._save()

    def begin_turn(self, text: str) -> None:
        with self.lock:
            self.transcript.add_user(text)
            if not self.record.title:
                self.record.title = title_from_message(text)
            self._save()

    def fail(self, exc: BaseException) -> None:
        """O turno acabou em erro: a pessoa lê o motivo na conversa, e o que já aconteceu fica salvo."""
        with self.lock:
            self.transcript.add_notice("error", "error", str(exc) or exc.__class__.__name__)
            self._save()

    def end_turn(self) -> None:
        self._save()

    def update(
        self,
        title: str | None = None,
        model: str | None = None,
        effort: str | None | _Keep = KEEP,
        options: ConversationOptions | None = None,
    ) -> None:
        """Muda o que a pessoa pode mudar a qualquer momento; vale a partir da mensagem seguinte."""
        with self.lock:
            if title is not None:
                self.record.title = title
            if model is not None:
                self.record.model = model
            if not isinstance(effort, _Keep):
                self.record.effort = effort or None
            if options is not None:
                self.record.options = options
            self._save(touch=False)

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.record.id,
                "title": self.record.display_title,
                "created_at": self.record.created_at,
                "updated_at": self.record.updated_at,
                "mode": self.record.mode,
                "model": self.record.model,
                "effort": self.record.effort,
                "messages": self.record.message_count,
                "running": self.is_running,
            }

    def detail(self) -> dict[str, Any]:
        """A conversa inteira para a tela: o resumo, as opções e a transcrição (o histórico do modelo fica no servidor)."""
        with self.lock:
            return {
                **self.summary(),
                "options": self.record.options.to_dict(),
                "kits": list(self.session.current_kits),
                "mode_locked": self.record.message_count > 0,
                "running_job_id": self.running.id if self.is_running and self.running else None,
                "transcript": self.transcript.snapshot(),
            }


class ConversationRegistry:
    """As conversas vivas, mais o acesso às salvas: abrir pelo id, criar, listar e apagar."""

    def __init__(
        self, store: ConversationStore, session_factory: SessionFactory, free_session_factory: SessionFactory
    ) -> None:
        self.store = store
        self._factories = {MODE_OPERATE: session_factory, MODE_FREE: free_session_factory}
        self._live: dict[str, Conversation] = {}
        self.lock = threading.RLock()

    def _build_session(
        self, relay: TurnRelay, record: ConversationRecord, base: AgentSettings
    ) -> ConversationSession:
        return self._factories[record.mode](relay, settings_for_conversation(base, record))

    def create(
        self,
        base: AgentSettings,
        mode: str,
        model: str,
        effort: str | None = None,
        options: ConversationOptions | None = None,
    ) -> Conversation:
        with self.lock:
            record = new_record(self.store.new_id(), mode, model, effort, options)
            relay = TurnRelay()
            conversation = Conversation(record, relay, self._build_session(relay, record, base), self.store)
            conversation.save(touch=False)
            self._live[record.id] = conversation
            return conversation

    def cached(self, conversation_id: str) -> Conversation | None:
        with self.lock:
            return self._live.get(conversation_id)

    def get(self, conversation_id: str, base: AgentSettings) -> Conversation | None:
        """A conversa viva ou, se foi salva antes de o DMaker reiniciar, a que está no disco (`None` se não existe).

        Uma conversa lida do disco não tem turno em andamento: a confirmação que esperava um clique conta como "não" e
        a ferramenta que rodava como interrompida (`TranscriptBuilder.settle`), e o histórico volta ao modelo inteiro.
        """
        with self.lock:
            live = self._live.get(conversation_id)
            if live is not None:
                return live
            record = self.store.load(conversation_id)  # `ConversationFormatError` para um arquivo ilegível
            if record is None:
                return None
            record.history = repair_history(record.history)
            relay = TurnRelay()
            session = self._build_session(relay, record, base)
            session.load_history(record.history, record.kits)
            conversation = Conversation(record, relay, session, self.store)
            if conversation.transcript.settle():
                conversation.save(touch=False)
            self._live[record.id] = conversation
            return conversation

    def change_mode(self, conversation: Conversation, mode: str, base: AgentSettings) -> None:
        """Troca o modo de uma conversa que ainda não teve mensagem; depois da primeira, o modo está travado."""
        with self.lock, conversation.lock:
            if mode == conversation.record.mode:
                return
            if conversation.record.message_count > 0 or conversation.is_running:
                raise ModeLockedError("O modo da conversa não muda depois da primeira mensagem.")
            conversation.record.mode = mode
            conversation.session = self._build_session(conversation.relay, conversation.record, base)
            conversation.save(touch=False)

    def summaries(self) -> list[dict[str, Any]]:
        """A lista lateral, a mais recente primeiro; as conversas vivas dizem se estão respondendo agora."""
        with self.lock:
            running = {cid for cid, live in self._live.items() if live.is_running}
        return [{**summary.to_dict(), "running": summary.id in running} for summary in self.store.list()]

    def delete(self, conversation_id: str) -> bool:
        """Apaga do disco e da memória; `False` se não existia. Quem chama já conferiu que ela não está respondendo."""
        with self.lock:
            existed = self.store.delete(conversation_id)  # `ConversationInUseError` deixa tudo como estava
            return self._live.pop(conversation_id, None) is not None or existed

    def uses_model(self, matches: Callable[[str], bool]) -> bool:
        """Alguma conversa respondendo agora usa um modelo que `matches` reconhece?"""
        with self.lock:
            return any(live.is_running and matches(live.model) for live in self._live.values())


def with_model(settings: AgentSettings, model: str) -> AgentSettings:
    """As configurações do ambiente trocando só o modelo: a checagem de "modelo instalado" é do modelo da conversa."""
    return replace(settings, model=model)
