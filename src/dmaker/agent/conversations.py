"""Conversas salvas do agente local: o registro de cada uma e o repositório em disco.

Uma conversa é um JSON (`<id>.json`) em `config.CONVERSATIONS_DIR`, com a pasta dos anexos ao lado (`<id>/`). Guarda o
que é preciso para continuar depois de reiniciar o DMaker: o modo, o modelo, o esforço e as opções, os kits em uso, o
histórico que o modelo lê e a transcrição que a tela desenha. Mora fora de `cache/` porque é dado da pessoa, não algo
que se possa descartar. O repositório é um protocolo: as rotas só o conhecem por ele, e os testes usam uma pasta
temporária (a pasta é lida de `config` na hora do uso, nunca fixada na importação).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from .. import config
from .catalog import think_value
from .settings import AgentSettings
from .transcript import utc_now

SCHEMA_VERSION = 1
MODE_OPERATE = "operate"  # "Operar o DMaker": o modelo usa as ferramentas do editor
MODE_FREE = "free"  # "Conversa livre": o modelo só conversa, sem ferramenta nenhuma
MODES = (MODE_OPERATE, MODE_FREE)
DEFAULT_TITLE = "Nova conversa"
TITLE_LIMIT = 60

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SAVE_ATTEMPTS = (
    4  # o Windows recusa trocar um arquivo que um antivírus ou o Explorer está lendo; costuma durar instantes
)
_SAVE_RETRY_S = 0.05


class ConversationFormatError(ValueError):
    """O arquivo da conversa existe, mas não é uma conversa legível."""


class ConversationInUseError(RuntimeError):
    """Não deu para apagar a conversa porque um arquivo dela está aberto em outro programa (o Windows não deixa)."""


@dataclass
class ConversationOptions:
    """As opções avançadas da conversa; `None` é o padrão do ambiente (variáveis `DMAKER_AGENT_*`)."""

    num_ctx: int | None = None
    temperature: float | None = None
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"num_ctx": self.num_ctx, "temperature": self.temperature, "seed": self.seed}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ConversationOptions:
        data = data or {}
        return cls(data.get("num_ctx"), data.get("temperature"), data.get("seed"))


@dataclass
class ConversationRecord:
    """Tudo que se guarda de uma conversa."""

    id: str
    mode: str
    model: str
    created_at: str
    updated_at: str
    title: str = ""  # vazio até a primeira mensagem dar o título
    effort: str | None = None
    options: ConversationOptions = field(default_factory=ConversationOptions)
    kits: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)  # o que o modelo lê, sem o prompt de sistema
    transcript: list[dict[str, Any]] = field(default_factory=list)  # o que a tela desenha

    @property
    def display_title(self) -> str:
        return self.title or DEFAULT_TITLE

    @property
    def message_count(self) -> int:
        return sum(1 for entry in self.transcript if entry.get("kind") == "user")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
            "model": self.model,
            "effort": self.effort,
            "options": self.options.to_dict(),
            "kits": list(self.kits),
            "history": self.history,
            "transcript": self.transcript,
        }

    @classmethod
    def from_json_dict(cls, data: Any) -> ConversationRecord:
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or data.get("mode") not in MODES:
            raise ConversationFormatError("O arquivo não tem o formato de uma conversa do DMaker.")
        if data.get("version", SCHEMA_VERSION) > SCHEMA_VERSION:
            raise ConversationFormatError("A conversa foi salva por uma versão mais nova do DMaker.")
        return cls(
            id=data["id"],
            mode=data["mode"],
            model=str(data.get("model") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            title=str(data.get("title") or ""),
            effort=data.get("effort") or None,
            options=ConversationOptions.from_dict(data.get("options")),
            kits=[str(kit) for kit in data.get("kits") or []],
            history=list(data.get("history") or []),
            transcript=list(data.get("transcript") or []),
        )


@dataclass(frozen=True)
class ConversationSummary:
    """Uma linha da lista lateral: o suficiente para mostrar e ordenar sem abrir a conversa."""

    id: str
    title: str
    created_at: str
    updated_at: str
    mode: str
    model: str
    effort: str | None
    messages: int  # quantas mensagens a pessoa mandou

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
            "model": self.model,
            "effort": self.effort,
            "messages": self.messages,
        }


class ConversationStore(Protocol):
    def new_id(self) -> str: ...

    def save(self, record: ConversationRecord) -> None: ...

    def load(self, conversation_id: str) -> ConversationRecord | None:
        """A conversa, ou `None` se não existe. Um arquivo ilegível levanta `ConversationFormatError`."""
        ...

    def list(self) -> list[ConversationSummary]:
        """Todas as conversas legíveis, a mais recente primeiro."""
        ...

    def delete(self, conversation_id: str) -> bool:
        """Apaga a conversa e a pasta dos anexos; `False` se não existia. Levanta `ConversationInUseError`."""
        ...

    def attachments_dir(self, conversation_id: str) -> Path:
        """A pasta dos anexos da conversa (não é criada aqui)."""
        ...


def new_record(
    conversation_id: str,
    mode: str,
    model: str,
    effort: str | None = None,
    options: ConversationOptions | None = None,
) -> ConversationRecord:
    now = utc_now()
    return ConversationRecord(
        id=conversation_id,
        mode=mode,
        model=model,
        created_at=now,
        updated_at=now,
        effort=effort,
        options=options or ConversationOptions(),
    )


def title_from_message(text: str, limit: int = TITLE_LIMIT) -> str:
    """O título que nasce da primeira mensagem: a primeira linha, em até `limit` caracteres, cortada numa palavra."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    line = " ".join(first.split())
    if not line:
        return DEFAULT_TITLE
    if len(line) <= limit:
        return line
    cut = line[: limit - 1]
    head, space, _ = cut.rpartition(" ")
    if space and len(head) >= limit // 2:
        cut = head
    return cut.rstrip(" ,;:.-") + "…"


def settings_for_conversation(base: AgentSettings, record: ConversationRecord) -> AgentSettings:
    """As configurações que valem para a próxima mensagem: as do ambiente, com o que a conversa escolheu por cima."""
    options = record.options
    return replace(
        base,
        model=record.model or base.model,
        think=think_value(record.effort) if record.effort else base.think,
        num_ctx=options.num_ctx or base.num_ctx,
        temperature=options.temperature if options.temperature is not None else base.temperature,
        seed=options.seed if options.seed is not None else base.seed,
    )


def configure_chat(chat: object, settings: AgentSettings) -> None:
    """Aplica ao cliente do modelo o que a conversa escolheu (modelo, esforço, contexto, temperatura, semente).

    O cliente é mutável de propósito (ver `OllamaChat`): vale a partir da próxima chamada. O que o motor não tem (o
    `think` e o `num_ctx` do servidor compatível com a OpenAI) simplesmente não existe no cliente e fica de fora.
    """
    for name, value in (
        ("model", settings.model),
        ("think", settings.think),
        ("num_ctx", settings.num_ctx),
        ("temperature", settings.temperature),
        ("seed", settings.seed),
    ):
        if hasattr(chat, name):
            setattr(chat, name, value)


def _remove_tree(folder: Path) -> list[Path]:
    """Apaga a pasta e devolve os arquivos que não deu para apagar (em uso por outro programa)."""
    locked: list[Path] = []

    def note(function: object, path: str, error: object) -> None:
        locked.append(Path(path))

    # `onexc` substituiu `onerror` no Python 3.12; as duas recebem o caminho que falhou como segundo argumento
    options: dict[str, Any] = {"onexc": note} if sys.version_info >= (3, 12) else {"onerror": note}
    shutil.rmtree(folder, **options)
    return locked


def _read_summary(path: Path) -> ConversationSummary:
    record = ConversationRecord.from_json_dict(json.loads(path.read_text(encoding="utf-8")))
    return ConversationSummary(
        record.id,
        record.display_title,
        record.created_at,
        record.updated_at,
        record.mode,
        record.model,
        record.effort,
        record.message_count,
    )


class DiskConversationStore:
    """O repositório em disco: um JSON por conversa, gravado por inteiro de forma atômica (`.part` e `replace`)."""

    def __init__(self, root: Callable[[], Path] | None = None) -> None:
        self._root = root or (lambda: config.CONVERSATIONS_DIR)
        self._lock = threading.Lock()
        # (data de modificação, tamanho) -> resumo: a lista só relê o arquivo que mudou
        self._summaries: dict[Path, tuple[tuple[int, int], ConversationSummary]] = {}

    def root(self) -> Path:
        return self._root()

    def _file(self, conversation_id: str) -> Path | None:
        return self.root() / f"{conversation_id}.json" if _ID.fullmatch(conversation_id) else None

    def new_id(self) -> str:
        while True:
            candidate = uuid.uuid4().hex[:10]
            if not (self.root() / f"{candidate}.json").exists():
                return candidate

    def attachments_dir(self, conversation_id: str) -> Path:
        if not _ID.fullmatch(conversation_id):
            raise ValueError(f"Identificador de conversa inválido: {conversation_id!r}")
        return self.root() / conversation_id

    def save(self, record: ConversationRecord) -> None:
        path = self._file(record.id)
        if path is None:
            raise ValueError(f"Identificador de conversa inválido: {record.id!r}")
        payload = json.dumps(record.to_json_dict(), ensure_ascii=False, indent=2)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix(".json.part")
            part.write_text(payload, encoding="utf-8")
            for attempt in range(_SAVE_ATTEMPTS):
                try:
                    os.replace(part, path)
                    return
                except PermissionError:
                    if attempt == _SAVE_ATTEMPTS - 1:
                        raise
                    time.sleep(_SAVE_RETRY_S)

    def load(self, conversation_id: str) -> ConversationRecord | None:
        path = self._file(conversation_id)
        if path is None or not path.exists():
            return None
        try:
            return ConversationRecord.from_json_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:  # JSON quebrado, arquivo cortado ou formato desconhecido
            raise ConversationFormatError(
                f"A conversa {conversation_id} está ilegível ({path.name}): {exc}"
            ) from exc

    def list(self) -> list[ConversationSummary]:
        folder = self.root()
        if not folder.is_dir():
            return []
        found: list[ConversationSummary] = []
        with self._lock:
            seen: set[Path] = set()
            for path in folder.glob("*.json"):
                try:
                    stat = path.stat()
                    key = (stat.st_mtime_ns, stat.st_size)
                    cached = self._summaries.get(path)
                    if cached is None or cached[0] != key:
                        cached = (key, _read_summary(path))
                        self._summaries[path] = cached
                except (ValueError, OSError):
                    continue  # um arquivo ilegível não esconde as outras conversas
                seen.add(path)
                found.append(cached[1])
            for gone in set(self._summaries) - seen:
                del self._summaries[gone]
        return sorted(found, key=lambda summary: (summary.updated_at, summary.id), reverse=True)

    def delete(self, conversation_id: str) -> bool:
        path = self._file(conversation_id)
        if path is None:
            return False
        folder = self.attachments_dir(conversation_id)
        with self._lock:
            existed = path.exists() or folder.exists()
            if folder.exists():
                locked = _remove_tree(folder)
                if locked:
                    raise ConversationInUseError(in_use_message(locked[0]))
            try:
                path.unlink(missing_ok=True)
            except PermissionError as exc:
                raise ConversationInUseError(in_use_message(path)) from exc
            self._summaries.pop(path, None)
        return existed


def in_use_message(path: Path) -> str:
    """A explicação para a pessoa quando o Windows não deixa apagar um arquivo da conversa."""
    return (
        f"Não consegui apagar a conversa porque o arquivo '{path.name}' está aberto em outro programa. "
        "Feche-o e tente apagar de novo."
    )
