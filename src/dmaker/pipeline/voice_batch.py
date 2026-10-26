"""Narra um item da fila: um áudio por capítulo, o áudio completo e as legendas do completo.

O trabalho pesado é do `NarrationService` (com o cache por fala, que faz a retomada não repetir o que já
saiu) e do `FFmpegRunner`; aqui só se organiza o livro: capítulos em ordem, andamento gravado na fila a
cada fala, trava de síntese segurada só durante cada fala e velocidade medida para o tempo estimado.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack, nullcontext
from dataclasses import dataclass
from pathlib import Path

from ..filtergraph.voice import narration_concat_command
from ..media.ffmpeg import FFmpegRunner
from ..text.captions import Cue, to_srt
from ..voice.audiobook import (
    CHAPTER_GAP_SECONDS,
    chapter_filename,
    complete_filename,
    merge_chapter_cues,
)
from ..voice.estimate import Sample, speed_key
from ..voice.library import VoiceLibrary
from ..voice.manuscript import Chapter
from ..voice.synth import DRAFT_STEPS
from .narration import NarrationResult, NarrationService, PlannedUtterance
from .voice_queue import ItemInterrupted, QueueItem, VoiceQueue

# Segura a trava de síntese (a mesma das rotas de voz); recebe um callback para avisar que está esperando.
SynthesisGuard = Callable[[Callable[[str], None]], AbstractContextManager[None]]


def no_guard(_note: Callable[[str], None]) -> AbstractContextManager[None]:
    return nullcontext()


@dataclass(frozen=True)
class ItemOutput:
    files: list[str]  # nomes dentro da pasta do item: capítulos, completo e legenda
    duration: float


@dataclass
class _Totals:
    """Contas do item inteiro, que atravessam os capítulos."""

    utterances_done: int = 0
    chars_left: int = 0


class _ChapterRun:
    """Acompanha as falas de um capítulo: grava o andamento, segura a trava e mede o tempo de cada síntese."""

    def __init__(
        self,
        queue: VoiceQueue,
        item: QueueItem,
        guard: SynthesisGuard,
        clock: Callable[[], float],
        totals: _Totals,
    ) -> None:
        self.queue, self.item, self.guard, self.clock, self.totals = queue, item, guard, clock, totals
        self.samples: list[Sample] = []
        self._held = ExitStack()
        self._started_at = 0.0
        self._plan: list[PlannedUtterance] = []
        self._number, self._title = 0, ""

    def begin(self, number: int, chapter: Chapter, plan: list[PlannedUtterance]) -> None:
        self._plan = plan
        self._number, self._title = number, chapter.title

    def on_utterance(self, index: int, count: int) -> None:
        """Chamado pelo `NarrationService` antes de cada fala: fecha a anterior e prepara a seguinte."""
        if index > 1:
            self._finish(index - 1, measured=True)
        if not self._plan[index - 1].cached:
            self._held.enter_context(self.guard(self._wait_note))
            self._started_at = self.clock()
        self._report(index, count)

    def end(self) -> None:
        """Chamado depois de montar o capítulo: fecha a última fala (sem medi-la, o tempo inclui a montagem)."""
        if self._plan:
            self._finish(len(self._plan), measured=False)

    def release(self) -> None:
        self._held.close()
        self._held = ExitStack()

    def _finish(self, index: int, measured: bool) -> None:
        planned = self._plan[index - 1]
        if not planned.cached:
            if measured:
                self.samples.append((planned.chars, max(0.0, self.clock() - self._started_at)))
            self.totals.chars_left = max(0, self.totals.chars_left - planned.chars)
        self.release()
        self.totals.utterances_done += 1

    def _wait_note(self, message: str) -> None:
        self.queue.update_progress(self.item.id, note=message)

    def _report(self, index: int, count: int) -> None:
        still_running = self.queue.update_progress(
            self.item.id,
            chapter=self._number,
            chapter_title=self._title,
            utterance=index,
            utterances=count,
            utterances_done=self.totals.utterances_done,
            chars_left=self.totals.chars_left,
            note="",
        )
        if not still_running:
            raise ItemInterrupted(self.item.id)


class BatchNarrator:
    """Executa itens da fila (implementa o `Processor` do worker). Tudo que é externo entra por parâmetro."""

    def __init__(
        self,
        queue: VoiceQueue,
        service: NarrationService,
        runner: FFmpegRunner,
        library: VoiceLibrary,
        guard: SynthesisGuard = no_guard,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.queue, self.service, self.runner, self.library = queue, service, runner, library
        self.guard, self.clock = guard, clock

    def process(self, item: QueueItem) -> ItemOutput:
        """Narra os capítulos e monta o completo. Levanta `ItemInterrupted` se o item for pausado ou cancelado."""
        options = item.options
        chapters = self.queue.load_chapters(item.id)
        voice = self.library.get(options.voice) if options.voice else None
        narration = {
            "voice": voice,
            "language": options.language or (voice.language if voice else "pt"),
            "speed": options.speed,
            "steps": DRAFT_STEPS if options.draft else None,
            "brand": options.brand or (voice.brand if voice else None),
        }
        plans = [self.service.plan(chapter.text, **narration) for chapter in chapters]
        totals = _Totals(
            chars_left=sum(u.chars for plan in plans for u in plan if not u.cached),
        )
        started = self.queue.update_progress(
            item.id,
            chapters_total=len(chapters),
            utterances_total=sum(len(plan) for plan in plans),
            utterances_done=0,
            chars_left=totals.chars_left,
        )
        if not started:
            raise ItemInterrupted(item.id)

        output_dir = Path(item.output_dir)
        suffix = options.audio_format
        single = len(chapters) == 1
        speed_name = speed_key(voice.engine if voice else "omnivoice", options.draft)
        run = _ChapterRun(self.queue, item, self.guard, self.clock, totals)
        results: list[tuple[Path, NarrationResult]] = []
        for number, (chapter, plan) in enumerate(zip(chapters, plans, strict=True), 1):
            # um capítulo só dispensa o arquivo por capítulo: o completo já é ele
            name = (
                complete_filename(item.title, suffix)
                if single
                else chapter_filename(number, chapter.title, suffix)
            )
            if not plan:  # capítulo só com símbolos: nada para falar, e não vale derrubar o livro por isso
                continue
            run.begin(number, chapter, plan)
            try:
                result = self.service.render(
                    chapter.text,
                    output_dir / name,
                    on_progress=run.on_utterance,
                    write_srt=single,
                    **narration,
                )
                run.end()
            finally:
                run.release()
                self.queue.record_samples(speed_name, run.samples)
                run.samples = []
            results.append((result.path, result))
        if not results:
            raise ValueError("O roteiro não tem texto para narrar.")
        if single:
            path, result = results[0]
            files = [path.name, *([result.srt_path.name] if result.srt_path else [])]
            return ItemOutput(files, result.duration)
        return self._assemble(item, results, output_dir, suffix)

    def _assemble(
        self, item: QueueItem, results: list[tuple[Path, NarrationResult]], output_dir: Path, suffix: str
    ) -> ItemOutput:
        """Junta os capítulos no áudio completo (1,5 s de silêncio entre eles) e grava a legenda dele."""
        if not self.queue.update_progress(item.id, chapter_title="Montando o áudio completo", note=""):
            raise ItemInterrupted(item.id)
        merged, total = merge_chapter_cues([(r.duration, r.cues) for _, r in results], CHAPTER_GAP_SECONDS)
        last = len(results) - 1
        parts = [
            (path, CHAPTER_GAP_SECONDS if index < last else 0.0) for index, (path, _) in enumerate(results)
        ]
        complete = output_dir / complete_filename(item.title, suffix)
        # a montagem é seca: cada capítulo já saiu com o acabamento broadcast e a marca d'água, e mexer na
        # dinâmica deles agora apagaria a marca (e achataria a voz)
        self.runner.run(
            narration_concat_command(parts, complete, total=total, provenance=self.service.provenance())
        )
        srt = complete.with_suffix(".srt")
        srt.write_text(to_srt([Cue(start, end, text) for start, end, text in merged]), encoding="utf-8")
        return ItemOutput([*(path.name for path, _ in results), complete.name, srt.name], total)
