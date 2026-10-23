"""Planejamento da dublagem: partir a fala em frases, medir o espaço de cada uma e decidir como a tradução cabe.

Funções puras, sem áudio nem disco. A segmentação segue a do VoiceStudio (frases por pontuação e pausas, de
cerca de 1 a 12 s); o encaixe é próprio: uma fala dublada pode durar mais que a original, e o que passa do
espaço sai primeiro por avançar na pausa seguinte, depois por pedir ao modelo uma fala mais rápida, depois por
acelerar o áudio pronto (`atempo`), e só então por avisar que a tradução precisa ser mais curta.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from ..text.captions import Word
from .speech_edit import MAX_TEMPO, fit_tempo

MIN_SEGMENT_SECONDS = 1.0  # abaixo disso a clonagem e a síntese ficam instáveis e a legenda some rápido
MAX_SEGMENT_SECONDS = 12.0  # acima disso o roteiro fica difícil de revisar e um erro de duração custa caro
MIN_TAIL_SECONDS = 0.5  # o pedaço que sobra de uma frase longa partida não pode ser só uma palavra
PAUSE_BREAK_SECONDS = 0.6  # silêncio que o falante usa para fechar uma ideia, mesmo sem ponto final
MERGE_GAP_SECONDS = 1.0  # um fragmento curto só se junta ao vizinho se a pausa entre eles for menor que isto

_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")
_CLAUSE_END = re.compile(r"[,;:][\"')\]]*$")


@dataclass(frozen=True)
class Phrase:
    """Uma frase falada: texto e o tempo dela no arquivo."""

    start: float
    end: float
    text: str


class Timed(Protocol):
    start: float
    end: float


def _phrase(words: Sequence[Word]) -> Phrase:
    return Phrase(words[0].start, words[-1].end, " ".join(word.text for word in words))


def _break_score(words: Sequence[Word], at: int) -> tuple[int, float]:
    """Quanto vale partir depois da palavra `at`: pontuação final > vírgula > pausa; a pausa maior desempata."""
    punctuation = (
        2 if _SENTENCE_END.search(words[at].text) else 1 if _CLAUSE_END.search(words[at].text) else 0
    )
    return punctuation, words[at + 1].start - words[at].end


def _split_point(words: Sequence[Word]) -> int:
    """Índice da última palavra do primeiro pedaço de uma frase longa demais.

    Só vale partir deixando pelo menos `MIN_SEGMENT_SECONDS` de um lado e `MIN_TAIL_SECONDS` do outro. Entre os
    pontos válidos vence o de melhor pontuação (e, no empate, o mais tardio, que deixa o primeiro pedaço cheio).
    """
    first_start, last_end = words[0].start, words[-1].end
    valid = [
        at
        for at in range(len(words) - 1)
        if words[at].end - first_start >= MIN_SEGMENT_SECONDS
        and last_end - words[at + 1].start >= MIN_TAIL_SECONDS
    ]
    if not valid:
        return max(0, len(words) - 2)
    return max(valid, key=lambda at: (*_break_score(words, at), at))


def _group_words(words: Sequence[Word]) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for index, word in enumerate(words):
        current.append(word)
        following = words[index + 1] if index + 1 < len(words) else None
        if following is None:
            break
        duration = word.end - current[0].start
        if following.end - current[0].start > MAX_SEGMENT_SECONDS and len(current) > 1:
            cut = _split_point(current)
            groups.append(current[: cut + 1])
            current = current[cut + 1 :]
            continue
        closes = _SENTENCE_END.search(word.text) or following.start - word.end >= PAUSE_BREAK_SECONDS
        if duration >= MIN_SEGMENT_SECONDS and closes:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _merge_short(phrases: list[Phrase]) -> list[Phrase]:
    """Junta cada fragmento curto demais ao vizinho mais próximo (antes de preferência), se a pausa for curta."""
    merged = list(phrases)
    index = 0
    while index < len(merged):
        phrase = merged[index]
        if phrase.end - phrase.start >= MIN_SEGMENT_SECONDS or len(merged) == 1:
            index += 1
            continue
        before = merged[index - 1] if index > 0 else None
        after = merged[index + 1] if index + 1 < len(merged) else None
        gap_before = phrase.start - before.end if before else None
        gap_after = after.start - phrase.end if after else None
        fits_before = (
            before is not None
            and gap_before is not None
            and gap_before < MERGE_GAP_SECONDS
            and phrase.end - before.start <= MAX_SEGMENT_SECONDS
        )
        fits_after = (
            after is not None
            and gap_after is not None
            and gap_after < MERGE_GAP_SECONDS
            and after.end - phrase.start <= MAX_SEGMENT_SECONDS
        )
        if fits_before and (not fits_after or (gap_before or 0.0) <= (gap_after or 0.0)):
            assert before is not None
            merged[index - 1 : index + 1] = [Phrase(before.start, phrase.end, f"{before.text} {phrase.text}")]
            index -= 1
        elif fits_after:
            assert after is not None
            merged[index : index + 2] = [Phrase(phrase.start, after.end, f"{phrase.text} {after.text}")]
        else:
            index += 1
    return merged


def segment_words(words: Sequence[Word]) -> list[Phrase]:
    """Frases de cerca de 1 a 12 s a partir das palavras com tempo (Whisper).

    Uma frase fecha no ponto final (ou `?`, `!`) e na pausa de fôlego; uma frase maior que 12 s é partida na
    vírgula ou na pausa mais natural; fragmentos curtos demais se juntam ao vizinho.
    """
    ordered = sorted(words, key=lambda word: word.start)
    if not ordered:
        return []
    return _merge_short([_phrase(group) for group in _group_words(ordered)])


# ---------- espaço de cada fala ----------

MIN_GAP_SECONDS = (
    0.15  # silêncio mínimo que a fala dublada deixa antes da seguinte, para as frases não colarem
)
MAX_ADVANCE_SECONDS = (
    1.2  # quanto uma fala pode avançar na pausa: mais que isso ela deixa de acompanhar a imagem
)
MIN_SPEECH_SECONDS = 0.3

# O modelo recebe a duração pedida e a respeita; pedir menos que 1/1,25 do natural já soa atropelado. Depois
# da síntese, `atempo` acelera sem mudar o tom, mas passa de 1,15 a fala fica apressada (mesmo limite da
# correção de fala). Juntos, cerca de 1,44x o ritmo natural: o teto do que ainda se entende bem.
MAX_MODEL_SQUEEZE = 1.25
MAX_TOTAL_SQUEEZE = MAX_MODEL_SQUEEZE * MAX_TEMPO
TRUNCATION_TOLERANCE_SECONDS = 0.05  # abaixo disso o excesso é arredondamento, não palavra cortada


@dataclass(frozen=True)
class Slot:
    """O espaço de uma fala: o tempo original e quanto ela pode avançar na pausa seguinte."""

    index: int
    start: float
    end: float
    room: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def capacity(self) -> float:
        return self.duration + self.room


def slot_plan(segments: Sequence[Timed], total: float) -> list[Slot]:
    """Um espaço por fala: a duração original e a folga na pausa até a fala seguinte (ou o fim do arquivo)."""
    slots: list[Slot] = []
    for index, segment in enumerate(segments):
        following_start = segments[index + 1].start if index + 1 < len(segments) else total
        gap = max(0.0, following_start - segment.end)
        room = max(0.0, min(gap - MIN_GAP_SECONDS, MAX_ADVANCE_SECONDS))
        slots.append(Slot(index, segment.start, segment.end, room))
    return slots


# Letras por segundo de uma fala natural em cada idioma. Só a razão entre dois idiomas importa (o ritmo do
# falante vem da própria fala original), e ela diz que o inglês gasta menos letras por segundo que o
# português: uma frase em português com 100 letras vira cerca de 85 em inglês e dura quase o mesmo.
LETTERS_PER_SECOND = {"pt": 14.0, "en": 13.0, "es": 14.0, "fr": 13.5, "de": 13.0, "it": 14.0}
DEFAULT_LETTERS_PER_SECOND = 13.5


def _letters(text: str) -> int:
    return len(re.sub(r"[\W_]+", "", text))


def natural_seconds(
    source_text: str, text: str, source_seconds: float, source_language: str, target_language: str
) -> float:
    """Quanto a tradução leva no ritmo do falante original: proporcional às letras, corrigido pelo idioma."""
    letters = _letters(text)
    if not letters:
        return 0.0
    source_letters = _letters(source_text)
    rate_source = LETTERS_PER_SECOND.get(source_language.split("-")[0], DEFAULT_LETTERS_PER_SECOND)
    rate_target = LETTERS_PER_SECOND.get(target_language.split("-")[0], DEFAULT_LETTERS_PER_SECOND)
    if not source_letters or source_seconds <= 0:
        return max(MIN_SPEECH_SECONDS, letters / rate_target)
    return max(MIN_SPEECH_SECONDS, source_seconds * (letters / source_letters) * (rate_source / rate_target))


FitStatus = Literal["fits", "advances", "squeezed", "overflow"]


@dataclass(frozen=True)
class FitPlan:
    """Como a tradução entra no espaço: a duração pedida ao modelo e o veredito."""

    request_seconds: float
    natural_seconds: float
    capacity: float
    status: FitStatus
    message: str

    @property
    def warns(self) -> bool:
        return self.status == "overflow"


def plan_fit(natural: float, slot: Slot) -> FitPlan:
    """Decide a duração a pedir ao modelo para a fala de `natural` segundos caber em `slot`.

    Ordem: cabe no tempo original; avança na pausa seguinte; o modelo fala mais rápido (até `MAX_MODEL_SQUEEZE`);
    o resto fica para o `atempo` depois da síntese. Passou de `MAX_TOTAL_SQUEEZE`: o fim da fala será cortado e o
    relatório avisa, porque a única saída é encurtar a tradução.
    """
    capacity = slot.capacity
    if natural <= slot.duration:
        return FitPlan(natural, natural, capacity, "fits", "cabe no tempo original")
    if natural <= capacity:
        return FitPlan(
            natural,
            natural,
            capacity,
            "advances",
            f"avança {natural - slot.duration:.1f} s na pausa seguinte",
        )
    squeeze = natural / capacity
    asked = natural / min(squeeze, MAX_MODEL_SQUEEZE)
    if squeeze <= MAX_TOTAL_SQUEEZE:
        return FitPlan(
            asked,
            natural,
            capacity,
            "squeezed",
            f"comprimida {squeeze:.2f}x ({natural:.1f} s em {capacity:.1f} s)",
        )
    return FitPlan(
        asked,
        natural,
        capacity,
        "overflow",
        f"não cabe: leva {natural:.1f} s para {capacity:.1f} s disponíveis; encurte a tradução",
    )


@dataclass(frozen=True)
class Placement:
    """O que fazer com a fala já sintetizada: acelerar e quanto dela toca."""

    tempo: float
    played_seconds: float
    truncated: bool


def place_speech(speech_seconds: float, capacity: float) -> Placement:
    """Acelera a fala pronta (até `MAX_TEMPO`) para caber em `capacity`; o que ainda passar é cortado no fim."""
    tempo = fit_tempo(speech_seconds, capacity)
    after_tempo = speech_seconds / tempo
    truncated = after_tempo > capacity + TRUNCATION_TOLERANCE_SECONDS
    return Placement(tempo, min(after_tempo, capacity) if truncated else after_tempo, truncated)


# ---------- legenda no idioma alvo ----------

SUBTITLE_LINE_CHARS = 42
SUBTITLE_LINES = 2


def subtitle_cues(text: str, start: float, end: float) -> list[tuple[float, float, str]]:
    """Parte a tradução em legendas de até duas linhas, com o tempo repartido pelo tamanho de cada uma."""
    lines = textwrap.wrap(" ".join(text.split()), width=SUBTITLE_LINE_CHARS) or []
    chunks = [lines[at : at + SUBTITLE_LINES] for at in range(0, len(lines), SUBTITLE_LINES)]
    weights = [max(1, _letters(" ".join(chunk))) for chunk in chunks]
    total_weight = sum(weights)
    cues: list[tuple[float, float, str]] = []
    cursor = start
    for chunk, weight in zip(chunks, weights, strict=True):
        finish = cursor + (end - start) * weight / total_weight
        cues.append((cursor, finish, "\n".join(chunk)))
        cursor = finish
    return cues
