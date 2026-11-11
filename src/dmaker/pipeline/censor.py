"""Bipe de censura: acha o intervalo de uma palavra dita num item e dá a ele o par que a edição grava (silêncio no item e
um Tom de 1 kHz sobre o mesmo intervalo).

As palavras com tempo vêm da mesma transcrição que o `speech_words` usa (Whisper, `text.transcribe`): o item é lido como ele
soa (com os efeitos), transcrito, e o tempo de cada palavra volta à linha do tempo do projeto pelo relógio do item. A fonte de
palavras entra por injeção (`WordSource`), então o teste não carrega o modelo.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from ..domain.edits import EditError
from ..domain.spec import Project
from ..media.wavio import write_wav
from ..text.captions import Word, flatten_words
from ..text.transcribe import Transcriber
from ..voice.speech_edit import locate_phrase

# O Tom do bipe: 1 kHz é o bipe de TV, e -12 dBFS de pico o deixa à frente da fala sem estourar o loudnorm
BEEP_FREQUENCY_HZ = 1000.0
BEEP_LEVEL_DB = -12.0
# O áudio transcrito de uma vez: um item mais longo que isto pede uma janela (`search_from`/`search_to`), porque a
# transcrição roda em torno do tempo real e a leitura fica toda em memória
MAX_SEARCH_SECONDS = 900.0


class WordSource(Protocol):
    """Quem diz as palavras ditas num item, com o tempo de cada uma na linha do tempo do projeto."""

    def words(
        self,
        project: Project,
        target: str,
        language: str,
        search_from: float | None,
        search_to: float | None,
    ) -> list[Word]: ...


class SpeechWordSource:
    """As palavras do item pela transcrição local (Whisper). O serviço do painel de áudio e o transcritor entram por injeção; sem
    eles valem o do render e o `WhisperTranscriber`, criados na primeira palavra procurada."""

    def __init__(self, transcriber: Transcriber | None = None, service=None) -> None:
        self.transcriber = transcriber
        self.service = service

    def words(
        self,
        project: Project,
        target: str,
        language: str,
        search_from: float | None,
        search_to: float | None,
    ) -> list[Word]:
        from .audio_panel import AudioPanelService

        service = self.service or AudioPanelService()
        plan = service.plan(project, target)
        if plan.clock is None:
            raise EditError(
                f"{target}: este item não tem lugar certo na linha do tempo (é uma faixa sincronizada pela sessão); "
                "diga o intervalo com `start` e `end` em vez de `word`"
            )
        first, last = self._axis_window(plan, search_from, search_to)
        if last - first > MAX_SEARCH_SECONDS:
            raise EditError(
                f"{target} dura {last - first:.0f} s e a busca de palavra transcreve até {MAX_SEARCH_SECONDS:.0f} s por vez: "
                "diga `search_from` e `search_to` (segundos da linha do tempo) para limitar onde procurar"
            )
        reader = service.reader(plan)
        if reader is None:
            raise EditError(f"{target}: não consegui ler o som do item para procurar a palavra")
        samples = reader.read(first, last - first)
        scratch = Path(tempfile.mkdtemp(prefix="dmaker-palavras-"))
        try:
            wav = write_wav(scratch / "item.wav", samples.mean(axis=1), reader.rate)
            transcriber = self.transcriber or _default_transcriber()
            transcript = transcriber.transcribe(wav, language)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        found = []
        for word in flatten_words(transcript.cues):
            begin, end = plan.to_project(first + word.start), plan.to_project(first + word.end)
            if begin is not None and end is not None:
                found.append(Word(min(begin, end), max(begin, end), word.text, word.probability))
        return found

    @staticmethod
    def _axis_window(plan, search_from: float | None, search_to: float | None) -> tuple[float, float]:
        """O trecho do eixo do item a transcrever: o item inteiro, ou o que a janela (segundos da linha do tempo) cobre."""
        clock = plan.clock
        first, last = plan.origin, plan.origin + plan.duration
        if search_from is not None:
            first = max(first, clock.to_item(search_from) + plan.origin)
        if search_to is not None:
            last = min(last, clock.to_item(search_to) + plan.origin)
        if last <= first:
            raise EditError("a janela de busca (`search_from` a `search_to`) não pega o item")
        return first, last


def _default_transcriber() -> Transcriber:
    from ..text.transcribe import WhisperTranscriber

    return WhisperTranscriber()


def word_interval(words: list[Word], word: str, occurrence: int | None) -> tuple[float, float]:
    """Início e fim da palavra (ou da frase) na transcrição, em segundos da linha do tempo. Mais de uma ocorrência sem
    `occurrence` é erro que lista os tempos, porque bipar a errada esconderia a palavra certa."""
    try:
        return locate_phrase(words, word, occurrence)
    except ValueError as exc:
        raise EditError(str(exc)) from exc
