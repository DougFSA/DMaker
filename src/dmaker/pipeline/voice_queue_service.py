"""Serviço da fila de narrações: entrada (texto ou roteiro importado), visão para a tela e montagem do worker.

É o que a interface, a CLI e o MCP usam, para os três adaptadores ficarem finos e mostrarem os mesmos números.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..voice.estimate import (
    default_seconds_per_char,
    format_duration,
    remaining_seconds,
    seconds_per_char,
    speed_key,
)
from ..voice.library import VoiceLibrary
from ..voice.manuscript import (
    Chapter,
    chapters_from_text,
    parse_manuscript,
    strip_formatting,
    title_from_filename,
)
from .voice_batch import BatchNarrator, SynthesisGuard, no_guard
from .voice_queue import (
    DONE,
    PENDING,
    RUNNING,
    STATE_LABELS,
    QueueItem,
    QueueOptions,
    VoiceQueue,
)
from .voice_worker import QueueWorker

MAX_TEXT_CHARS = 2_000_000  # ~40 horas de fala: muito além de um audiobook, só barra o arquivo errado
MAX_FILE_BYTES = 20 * 1024 * 1024
TITLE_WORDS = 6  # roteiro colado sem título ganha o começo do texto como nome


def default_title(text: str) -> str:
    words = text.split()[:TITLE_WORDS]
    return " ".join(words).strip(" .,;:!?") or "Narração"


class VoiceQueueService:
    def __init__(
        self,
        queue: VoiceQueue | None = None,
        library: VoiceLibrary | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.queue = queue or VoiceQueue()
        self.library = library or VoiceLibrary()
        self.on_change = on_change or (lambda: None)  # acorda o worker quando entra item novo

    # ---------- entrada ----------

    def _checked(self, options: QueueOptions) -> QueueOptions:
        if options.voice:
            self.library.get(options.voice)  # falha já no pedido, e não horas depois na fila
        return options

    def _enqueue(
        self, title: str, chapters: list[Chapter], options: QueueOptions, kind: str, name: str
    ) -> QueueItem:
        if sum(len(c.text) for c in chapters) > MAX_TEXT_CHARS:
            raise ValueError("O roteiro passa de dois milhões de caracteres; divida em mais de um item.")
        item = self.queue.add(title, chapters, self._checked(options), kind, name)
        self.on_change()
        return item

    def add_text(self, text: str, options: QueueOptions, title: str | None = None) -> QueueItem:
        """Texto digitado ou colado; capítulos marcados com "# " ou "Capítulo N" viram arquivos separados."""
        if not text.strip():
            raise ValueError("Escreva o texto da narração.")
        chapters = chapters_from_text(text, default_title=title or default_title(strip_formatting(text)))
        if not chapters:
            raise ValueError("O texto não tem nada para narrar.")
        return self._enqueue(title or chapters[0].title, chapters, options, "text", "")

    def add_file(
        self, data: bytes, filename: str, options: QueueOptions, title: str | None = None
    ) -> QueueItem:
        """Roteiro importado de um arquivo .txt, .md ou .docx, um capítulo por título."""
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("O arquivo de roteiro é grande demais (limite de 20 MB).")
        chapters = parse_manuscript(data, filename)
        fallback = chapters[0].title if len(chapters) == 1 else title_from_filename(filename)
        return self._enqueue(title or fallback, chapters, options, "file", Path(filename).name)

    def add_path(self, path: Path, options: QueueOptions, title: str | None = None) -> QueueItem:
        return self.add_file(path.read_bytes(), path.name, options, title)

    # ---------- visão ----------

    def _per_char(self, item: QueueItem, cache: dict[str, float]) -> float:
        options = item.options
        engine = "omnivoice"
        if options.voice:
            try:
                engine = self.library.get(options.voice).engine
            except (
                ValueError
            ):  # a voz foi apagada depois de entrar na fila: o item vai falhar, mas o tempo não quebra a tela
                pass
        key = speed_key(engine, options.draft)
        if key not in cache:
            cache[key] = seconds_per_char(
                self.queue.samples(key), default_seconds_per_char(engine, options.draft)
            )
        return cache[key]

    @staticmethod
    def _percent(item: QueueItem) -> int:
        if item.state == DONE:
            return 100
        if not item.utterances_total:
            return 0
        return min(99, int(100 * item.utterances_done / item.utterances_total))

    def item_view(self, item: QueueItem, per_char: float) -> dict[str, Any]:
        eta = remaining_seconds(item.chars_left, per_char) if item.state in (PENDING, RUNNING) else None
        return {
            "id": item.id,
            "title": item.title,
            "state": item.state,
            "state_label": STATE_LABELS[item.state],
            "error": item.error,
            "note": item.note,
            "source": {"kind": item.source_kind, "name": item.source_name},
            "options": {
                "voice": item.options.voice,
                "language": item.options.language,
                "speed": item.options.speed,
                "brand": item.options.brand,
                "draft": item.options.draft,
                "format": item.options.audio_format,
            },
            "chapter": item.chapter,
            "chapters_total": item.chapters_total,
            "chapter_title": item.chapter_title,
            "utterance": item.utterance,
            "utterances": item.utterances,
            "utterances_done": item.utterances_done,
            "utterances_total": item.utterances_total,
            "percent": self._percent(item),
            "chars_left": item.chars_left,
            "eta_seconds": None if eta is None else round(eta),
            "eta_label": None if eta is None else format_duration(eta),
            "duration_s": item.duration_s,
            "output_dir": item.output_dir,
            "files": [
                {"name": name, "url": file_url(item.id, name), "audio": not name.endswith(".srt")}
                for name in item.outputs
            ],
            "created_at": item.created_at,
            "started_at": item.started_at,
            "finished_at": item.finished_at,
        }

    def view(self) -> dict[str, Any]:
        """Fila inteira para a tela: itens na ordem de execução e o tempo estimado para esvaziá-la."""
        cache: dict[str, float] = {}
        items = self.queue.list()
        views = [self.item_view(item, self._per_char(item, cache)) for item in items]
        waiting = [v["eta_seconds"] for v in views if v["eta_seconds"] is not None]
        total = sum(waiting)
        return {
            "items": views,
            "eta_seconds": total if waiting else None,
            "eta_label": format_duration(total) if waiting else None,
            "running": any(item.state == RUNNING for item in items),
        }


def file_url(item_id: str, name: str) -> str:
    return f"/api/voices/queue/{item_id}/files/{quote(name)}"


# ---------- montagem do worker com as dependências reais ----------


def build_worker(
    queue: VoiceQueue,
    guard: SynthesisGuard = no_guard,
    log: Callable[[str], None] | None = None,
) -> QueueWorker:
    """Worker com o sintetizador compartilhado do processo, o ffmpeg e a biblioteca de vozes reais.

    O sintetizador só é criado (e os modelos só carregam) quando o primeiro item chega.
    """

    def make_processor() -> BatchNarrator:
        from ..media.ffmpeg import SubprocessRunner
        from ..voice.lexicon_store import LexiconStore
        from .narration import NarrationService
        from .voices import shared_synthesizer

        runner = SubprocessRunner(quiet=True)
        service = NarrationService(shared_synthesizer(), runner, lexicons=LexiconStore().for_brand)
        return BatchNarrator(queue, service, runner, VoiceLibrary(), guard)

    return QueueWorker(queue, make_processor, log=log)
