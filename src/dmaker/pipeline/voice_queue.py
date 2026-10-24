"""Fila persistente de narrações longas: quem entra, em que estado está e até onde foi.

A fila vive em `cache/voice_queue.json` (metadados e medidas de velocidade) e o texto de cada item em
`cache/voice_queue/<id>.json`, para o índice continuar pequeno mesmo com um livro inteiro na fila. Toda
mudança lê o arquivo, altera e grava de volta por inteiro (escreve num temporário e renomeia), então um
processo que cai no meio nunca deixa o índice pela metade. Os diretórios vêm do `config` na hora do uso.
Quem executa os itens é o `QueueWorker` (`voice_worker.py`); aqui só há estado e regras de transição.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .. import config
from ..voice.audiobook import safe_slug
from ..voice.estimate import Sample, append_samples
from ..voice.manuscript import Chapter

INDEX_FILE = "voice_queue.json"
CHAPTERS_DIR = "voice_queue"
OUTPUT_SUBDIR = "narracoes"
FORMAT_VERSION = 1
REPLACE_ATTEMPTS = (
    5  # o Windows recusa renomear sobre um arquivo que outro processo está lendo naquele instante
)
REPLACE_WAIT_SECONDS = 0.05

PENDING = "pending"
RUNNING = "running"
PAUSED = "paused"
CANCELLED = "cancelled"
DONE = "done"
FAILED = "failed"
STATES = (PENDING, RUNNING, PAUSED, CANCELLED, DONE, FAILED)
WAITING_STATES = (PENDING, PAUSED)  # ainda vão rodar; só estes podem ser reordenados
FINISHED_STATES = (DONE, CANCELLED, FAILED)
STATE_LABELS = {
    PENDING: "Pendente",
    RUNNING: "Rodando",
    PAUSED: "Pausado",
    CANCELLED: "Cancelado",
    DONE: "Concluído",
    FAILED: "Falhou",
}
AUDIO_FORMATS = ("wav", "mp3")

# Os leitores e o worker rodam em threads do mesmo processo; este trinco serve a todas as instâncias da fila.
_PROCESS_LOCK = threading.RLock()


class QueueFileError(RuntimeError):
    """O índice da fila existe mas não pôde ser lido (editado à mão, por exemplo)."""


class ItemNotFoundError(KeyError):
    """Nenhum item da fila com esse id."""


@dataclass(frozen=True)
class QueueOptions:
    """Como narrar um item: voz, idioma, ritmo e qualidade (rascunho = 8 passos no OmniVoice)."""

    voice: str | None = None
    language: str | None = None
    speed: float = 1.0
    brand: str | None = None
    draft: bool = False
    audio_format: str = "wav"

    def __post_init__(self) -> None:
        if self.audio_format not in AUDIO_FORMATS:
            raise ValueError(f"Formato {self.audio_format!r} inválido; use wav ou mp3.")


@dataclass
class QueueItem:
    id: str
    title: str
    source_kind: str  # "text" (digitado ou colado) | "file" (roteiro importado)
    source_name: str
    options: QueueOptions
    output_dir: str
    state: str = PENDING
    error: str | None = None
    chapters_total: int = 0
    chapter: int = 0  # capítulo em andamento (1 a chapters_total); 0 antes de começar
    chapter_title: str = ""
    utterance: int = 0  # fala em andamento dentro do capítulo
    utterances: int = 0  # total de falas do capítulo em andamento
    utterances_done: int = 0  # falas prontas no item inteiro, vindas do cache ou recém-sintetizadas
    utterances_total: int = 0
    chars_total: int = 0  # caracteres do roteiro inteiro
    chars_left: int = 0  # caracteres ainda por sintetizar (o que já está no cache não conta)
    note: str = ""  # aviso curto do momento, ex.: "Aguardando outra síntese terminar"
    outputs: list[str] = field(default_factory=list)  # nomes dos arquivos prontos, dentro de `output_dir`
    duration_s: float | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueueItem:
        known = {f.name for f in fields(cls)} - {"options"}
        option_names = {f.name for f in fields(QueueOptions)}
        options = QueueOptions(**{k: v for k, v in (data.get("options") or {}).items() if k in option_names})
        return cls(options=options, **{k: v for k, v in data.items() if k in known})


@dataclass
class _Document:
    items: list[QueueItem] = field(default_factory=list)
    samples: dict[str, list[Sample]] = field(default_factory=dict)  # velocidade medida, por motor e qualidade


def _atomic_write(path: Path, content: str) -> None:
    """Grava num arquivo temporário e renomeia: quem lê vê sempre o arquivo antigo ou o novo, nunca metade."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)


def _read_text(path: Path) -> str:
    """Lê o arquivo; o Windows nega a leitura por um instante se outro processo está trocando o arquivo."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)
    raise AssertionError("inalcançável")  # pragma: no cover


class VoiceQueue:
    def __init__(self, index_path: Path | None = None) -> None:
        self._fixed_path = index_path

    @property
    def index_path(self) -> Path:
        """Lido a cada uso: testes e `DMAKER_HOME` diferentes apontam o config para outra pasta."""
        return self._fixed_path or config.CACHE_DIR / INDEX_FILE

    def chapters_path(self, item_id: str) -> Path:
        return self.index_path.parent / CHAPTERS_DIR / f"{item_id}.json"

    # ---------- leitura e gravação ----------

    def _read(self) -> _Document:
        path = self.index_path
        if not path.exists():
            return _Document()
        try:
            data = json.loads(_read_text(path))
            items = [QueueItem.from_dict(raw) for raw in data.get("items", [])]
            samples = {
                key: [(int(c), float(s)) for c, s in value] for key, value in data.get("samples", {}).items()
            }
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise QueueFileError(f"Não consegui ler a fila de narrações em {path}: {exc}") from exc
        return _Document(items, samples)

    def _write(self, document: _Document) -> None:
        payload = {
            "version": FORMAT_VERSION,
            "items": [item.to_dict() for item in document.items],
            "samples": document.samples,
        }
        _atomic_write(self.index_path, json.dumps(payload, ensure_ascii=False, indent=1))

    def _change(self, apply):
        """Lê a fila, aplica a mudança e grava de volta, sem ninguém entrar no meio (nesta máquina e processo)."""
        with _PROCESS_LOCK:
            document = self._read()
            result = apply(document)
            self._write(document)
            return result

    @staticmethod
    def _find(document: _Document, item_id: str) -> QueueItem:
        for item in document.items:
            if item.id == item_id:
                return item
        raise ItemNotFoundError(f"Não existe item {item_id!r} na fila.")

    # ---------- consulta ----------

    def list(self) -> list[QueueItem]:
        with _PROCESS_LOCK:
            return self._read().items

    def get(self, item_id: str) -> QueueItem:
        with _PROCESS_LOCK:
            return self._find(self._read(), item_id)

    def samples(self, key: str) -> list[Sample]:
        with _PROCESS_LOCK:
            return list(self._read().samples.get(key, []))

    def has_pending(self) -> bool:
        return any(item.state == PENDING for item in self.list())

    def load_chapters(self, item_id: str) -> list[Chapter]:
        data = json.loads(self.chapters_path(item_id).read_text(encoding="utf-8"))
        return [Chapter(entry["title"], entry["text"]) for entry in data]

    # ---------- entrada ----------

    def add(
        self,
        title: str,
        chapters: list[Chapter],
        options: QueueOptions,
        source_kind: str,
        source_name: str = "",
    ) -> QueueItem:
        """Põe um roteiro no fim da fila; o texto dos capítulos fica guardado, então o arquivo original pode sumir."""
        if not chapters:
            raise ValueError("O roteiro não tem capítulos para narrar.")
        item_id = uuid.uuid4().hex[:8]
        final_title = title.strip() or chapters[0].title
        _atomic_write(
            self.chapters_path(item_id),
            json.dumps([{"title": c.title, "text": c.text} for c in chapters], ensure_ascii=False),
        )

        def append(document: _Document) -> QueueItem:
            item = QueueItem(
                id=item_id,
                title=final_title,
                source_kind=source_kind,
                source_name=source_name,
                options=options,
                output_dir=str(self._unique_output_dir(document, final_title)),
                chapters_total=len(chapters),
                chars_total=sum(len(c.text) for c in chapters),
            )
            item.chars_left = item.chars_total
            document.items.append(item)
            return item

        return self._change(append)

    @staticmethod
    def _unique_output_dir(document: _Document, title: str) -> Path:
        """Pasta do item em output/narracoes; títulos iguais ganham sufixo para um não sobrescrever o outro."""
        taken = {item.output_dir for item in document.items}
        root = config.OUTPUT_DIR / OUTPUT_SUBDIR
        slug = safe_slug(title)
        candidate, number = root / slug, 1
        while str(candidate) in taken:
            number += 1
            candidate = root / f"{slug}-{number}"
        return candidate

    # ---------- transições ----------

    def claim_next(self) -> QueueItem | None:
        """Passa o primeiro item pendente para `rodando` e o devolve; None quando não há o que fazer."""

        def claim(document: _Document) -> QueueItem | None:
            for item in document.items:
                if item.state == PENDING:
                    item.state = RUNNING
                    item.error = None
                    item.note = ""
                    item.started_at = item.started_at or time.time()
                    return item
            return None

        return self._change(claim)

    def requeue_interrupted(self) -> int:
        """Itens que estavam `rodando` quando o processo caiu voltam a `pendente`; devolve quantos."""

        def requeue(document: _Document) -> int:
            stuck = [item for item in document.items if item.state == RUNNING]
            for item in stuck:
                item.state = PENDING
                item.note = ""
            return len(stuck)

        return self._change(requeue)

    def update_progress(self, item_id: str, **values: Any) -> bool:
        """Atualiza o andamento de um item que segue `rodando`; False quando alguém o pausou ou cancelou."""

        def apply(document: _Document) -> bool:
            item = self._find(document, item_id)
            if item.state != RUNNING:
                return False
            for key, value in values.items():
                setattr(item, key, value)
            return True

        return self._change(apply)

    def finish(self, item_id: str, outputs: list[str], duration_s: float) -> bool:
        def apply(document: _Document) -> bool:
            item = self._find(document, item_id)
            if item.state != RUNNING:
                return False
            item.state, item.outputs, item.duration_s = DONE, outputs, round(duration_s, 2)
            item.chars_left, item.note, item.finished_at = 0, "", time.time()
            return True

        return self._change(apply)

    def fail(self, item_id: str, error: str) -> bool:
        def apply(document: _Document) -> bool:
            item = self._find(document, item_id)
            if item.state != RUNNING:
                return False
            item.state, item.error, item.note, item.finished_at = FAILED, error, "", time.time()
            return True

        return self._change(apply)

    def _transition(self, item_id: str, allowed: tuple[str, ...], target: str) -> QueueItem:
        def apply(document: _Document) -> QueueItem:
            item = self._find(document, item_id)
            if item.state not in allowed:
                raise ValueError(
                    f"Um item {STATE_LABELS[item.state].lower()} não pode ir para {STATE_LABELS[target].lower()}."
                )
            item.state, item.note = target, ""
            if target == CANCELLED:
                item.finished_at = time.time()
            if target == PENDING:
                item.error, item.finished_at = None, None
            return item

        return self._change(apply)

    def pause(self, item_id: str) -> QueueItem:
        """Pausa um item pendente ou em andamento; o em andamento para na próxima fala e guarda o que já fez."""
        return self._transition(item_id, (PENDING, RUNNING), PAUSED)

    def resume(self, item_id: str) -> QueueItem:
        """Devolve um item pausado à fila, na posição em que estava."""
        return self._transition(item_id, (PAUSED,), PENDING)

    def retry(self, item_id: str) -> QueueItem:
        """Tenta de novo um item que falhou ou foi cancelado; as falas já feitas saem do cache."""
        return self._transition(item_id, (FAILED, CANCELLED), PENDING)

    def cancel(self, item_id: str) -> QueueItem:
        return self._transition(item_id, (PENDING, RUNNING, PAUSED), CANCELLED)

    def move(self, item_id: str, direction: int) -> QueueItem:
        """Sobe (-1) ou desce (+1) um item entre os que ainda vão rodar; no limite da fila não faz nada."""

        def apply(document: _Document) -> QueueItem:
            item = self._find(document, item_id)
            if item.state not in WAITING_STATES:
                raise ValueError("Só dá para reordenar itens pendentes ou pausados.")
            slots = [i for i, other in enumerate(document.items) if other.state in WAITING_STATES]
            position = slots.index(document.items.index(item))
            target = position + (-1 if direction < 0 else 1)
            if 0 <= target < len(slots):
                a, b = slots[position], slots[target]
                document.items[a], document.items[b] = document.items[b], document.items[a]
            return item

        return self._change(apply)

    # ---------- limpeza ----------

    def remove(self, item_id: str) -> None:
        """Tira da fila um item que não está rodando (para o que roda, cancele primeiro)."""

        def apply(document: _Document) -> None:
            item = self._find(document, item_id)
            if item.state == RUNNING:
                raise ValueError("O item está rodando; cancele antes de remover.")
            document.items.remove(item)

        self._change(apply)
        self.chapters_path(item_id).unlink(missing_ok=True)

    def clear_finished(self) -> int:
        """Remove os concluídos e cancelados (os que falharam ficam, para se ler o erro); devolve quantos."""

        def apply(document: _Document) -> list[str]:
            gone = [item.id for item in document.items if item.state in (DONE, CANCELLED)]
            document.items = [item for item in document.items if item.id not in gone]
            return gone

        removed = self._change(apply)
        for item_id in removed:
            self.chapters_path(item_id).unlink(missing_ok=True)
        return len(removed)

    # ---------- velocidade medida ----------

    def record_samples(self, key: str, new: list[Sample]) -> None:
        if not new:
            return

        def apply(document: _Document) -> None:
            document.samples[key] = append_samples(document.samples.get(key, []), new)

        self._change(apply)


class ItemInterrupted(Exception):
    """O item foi pausado ou cancelado enquanto rodava: o executor larga o trabalho e não mexe mais no estado."""
