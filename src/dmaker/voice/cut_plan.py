"""Plano de cortes de uma gravação falada: onde tirar pausas, vícios e frases repetidas. Funções puras.

Recebe as palavras do Whisper e o áudio, e devolve os trechos que ficam e a lista do que saiu (início, fim,
motivo). O Whisper erra o tempo das palavras por dezenas de milissegundos, e depois de uma pausa chega a
errar por meio segundo, então a energia do áudio manda: os tempos das palavras são ajustados ao som de
verdade e cada borda de corte cai no vale de energia mais próximo, sem passar por dentro de uma palavra.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

import numpy as np

from ..text.captions import Word
from .disfluency import REASON_FILLER, REASON_REPETITION, find_fillers, find_repetitions
from .levels import FRAME_SECONDS, active_frames, frame_rms, quietest_time

Intensity = Literal["suave", "normal", "agressiva"]
INTENSITIES: tuple[str, ...] = ("suave", "normal", "agressiva")

REASON_SILENCE = "silence"
REASON_LABELS = {
    REASON_SILENCE: "pausa",
    REASON_FILLER: "vício de fala",
    REASON_REPETITION: "frase repetida",
}
# se um corte junta motivos, vale o de maior peso: quem revisa precisa ver primeiro o que mexeu no conteúdo
REASON_WEIGHT = {REASON_SILENCE: 0, REASON_FILLER: 1, REASON_REPETITION: 2}

# a pausa natural entre frases fica em ~0,3 s (o respiro de cada lado); acima de meio segundo já soa parado
DEFAULT_MIN_PAUSE = 0.5
DEFAULT_BREATH = 0.15
# o Whisper deixa o som de fora do fim da palavra por até ~0,3 s; esticar mais que isso invadiria a seguinte
STRETCH_LIMIT = 0.4
# cortes menores que isso picotam o ritmo sem ganho que se perceba
MIN_CUT = 0.15
# o vale é procurado perto da borda ideal: mais longe que 50 ms já seria outro ponto da fala
SNAP_RADIUS = 0.05
# numa pausa, respiração e ruído de sala (mais de 12 dB abaixo da fala) saem junto; som em nível de fala que o
# Whisper não escutou (mais de 50 ms, 5 quadros) é fala perdida, e aí a pausa não é cortada
SPEECH_LEVEL_DB = 12.0
MAX_SPEECH_FRAMES = 5
# o mezanino tem quadros inteiros; clipes com duração em múltiplos do quadro (30 fps vale para 60 também)
# não acumulam arredondamento e as legendas continuam alinhadas ao fim do vídeo
DEFAULT_FRAME_GRID = 1 / 30


@dataclass(frozen=True)
class CutOptions:
    """O que o usuário regula: quanto cortar (intensidade), o limite de pausa e o respiro que sobra."""

    intensity: Intensity = "normal"
    min_pause: float = DEFAULT_MIN_PAUSE  # pausa acima disso (s) vira corte
    breath: float = DEFAULT_BREATH  # silêncio mantido antes e depois de cada fala (s)
    frame_grid: float | None = DEFAULT_FRAME_GRID  # duração dos clipes em múltiplos disto; None desliga

    def __post_init__(self) -> None:
        if self.intensity not in INTENSITIES:
            raise ValueError(f"intensidade inválida: {self.intensity!r}. Use {', '.join(INTENSITIES)}")
        if self.min_pause <= 0:
            raise ValueError("o limite de pausa precisa ser maior que zero")
        if self.breath < 0:
            raise ValueError("o respiro não pode ser negativo")


@dataclass(frozen=True)
class Cut:
    start: float  # segundos no arquivo original
    end: float
    reason: str  # silence | filler | repetition
    text: str = ""  # as palavras removidas (vazio em pausa)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class CutPlan:
    keep: list[tuple[float, float]]  # trechos que ficam, em ordem
    cuts: list[Cut] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)  # com os tempos ajustados à energia

    @property
    def removed_seconds(self) -> float:
        return sum(cut.duration for cut in self.cuts)


# ---------- tempos das palavras ajustados à energia ----------


def refine_words(words: Sequence[Word], active: np.ndarray) -> list[Word]:
    """Encolhe cada palavra ao som que há dentro dela e a estica até o som que o Whisper deixou de fora.

    `active` marca os quadros de 10 ms com fala. Uma palavra sem som nenhum fica como veio.
    """
    count = len(active)
    refined = list(words)
    reaches_start = [False] * len(refined)
    reaches_end = [False] * len(refined)
    for i, word in enumerate(words):
        first = min(max(int(word.start / FRAME_SECONDS), 0), count)
        last = min(max(math.ceil(word.end / FRAME_SECONDS), first), count)
        hits = np.flatnonzero(active[first:last])
        if hits.size == 0:
            continue
        refined[i] = replace(
            word,
            start=max(word.start, (first + int(hits[0])) * FRAME_SECONDS),
            end=min(word.end, (first + int(hits[-1]) + 1) * FRAME_SECONDS),
        )
        reaches_start[i] = int(hits[0]) == 0
        reaches_end[i] = int(hits[-1]) == last - first - 1

    # som que continua além do fim registrado (a palavra acaba depois do que o Whisper disse)
    for i, word in enumerate(refined):
        if not reaches_end[i]:
            continue
        limit = min(word.end + STRETCH_LIMIT, refined[i + 1].start if i + 1 < len(refined) else math.inf)
        frame = math.ceil(word.end / FRAME_SECONDS - 1e-9)
        while frame < count and (frame + 1) * FRAME_SECONDS <= limit + 1e-9 and active[frame]:
            frame += 1
        refined[i] = replace(word, end=max(word.end, frame * FRAME_SECONDS))

    # e o mesmo para o começo, de trás para a frente para respeitar o fim da palavra anterior
    for i in range(len(refined) - 1, -1, -1):
        word = refined[i]
        if not reaches_start[i]:
            continue
        limit = max(word.start - STRETCH_LIMIT, refined[i - 1].end if i > 0 else 0.0)
        frame = int(word.start / FRAME_SECONDS + 1e-9)
        while frame > 0 and (frame - 1) * FRAME_SECONDS >= limit - 1e-9 and active[frame - 1]:
            frame -= 1
        refined[i] = replace(word, start=min(word.start, frame * FRAME_SECONDS))

    for i in range(len(refined) - 1):  # nenhuma palavra termina depois de a seguinte começar
        if refined[i].end > refined[i + 1].start:
            refined[i] = replace(refined[i], end=max(refined[i].start, refined[i + 1].start))
    return refined


def _has_sound(word: Word, active: np.ndarray) -> bool:
    first = min(max(int(word.start / FRAME_SECONDS), 0), len(active))
    last = min(max(math.ceil(word.end / FRAME_SECONDS), first), len(active))
    return bool(active[first:last].any())


# ---------- o que cortar ----------


def drop_reasons(words: Sequence[Word], intensity: Intensity) -> dict[int, str]:
    """Índice da palavra -> motivo, conforme a intensidade: suave não corta palavra, normal tira os vícios e
    agressiva tira também as frases repetidas."""
    reasons: dict[int, str] = {}
    if intensity == "suave":
        return reasons
    fillers = find_fillers(words)
    reasons.update({index: REASON_FILLER for index in fillers})
    if intensity == "agressiva":
        reasons.update({index: REASON_REPETITION for index in find_repetitions(words, ignore=fillers)})
    return reasons


@dataclass(frozen=True)
class _Audio:
    """O áudio da gravação e o que se mede dele de uma vez: quadros com fala e duração."""

    samples: np.ndarray
    rate: int
    active: np.ndarray  # quadros com fala ou qualquer som acima do limiar de pausa
    speech: np.ndarray  # quadros em nível de fala de verdade

    @property
    def duration(self) -> float:
        return len(self.samples) / self.rate


def _valley(audio: _Audio, low: float, high: float, near: float) -> float:
    """O instante mais quieto entre `low` e `high`; sem espaço para procurar, o ponto mais perto de `near`."""
    if high - low < 2 * FRAME_SECONDS:
        return max(low, min(near, high))
    found = quietest_time(audio.samples, audio.rate, (low + high) / 2, (high - low) / 2)
    return max(low, min(found, high))


def _cut_between(
    refined: Sequence[Word],
    dropped: list[int],
    left: int | None,
    right: int | None,
    reasons: dict[int, str],
    audio: _Audio,
    options: CutOptions,
) -> Cut | None:
    """O corte entre a última palavra que fica (`left`) e a primeira seguinte que fica (`right`), com as
    palavras cortadas no meio (`dropped`). `None` quando não há o que cortar ali."""
    duration = audio.duration
    low = 0.0 if left is None else refined[left].end
    high = duration if right is None else refined[right].start
    removed = [refined[i] for i in dropped]
    if removed:
        reason = max((reasons[i] for i in dropped), key=REASON_WEIGHT.__getitem__)
        start = 0.0 if left is None else max(low, min(low + options.breath, removed[0].start))
        end = duration if right is None else min(high, max(high - options.breath, removed[-1].end))
    else:
        reason = REASON_SILENCE
        if high - low <= options.min_pause:
            return None
        start = 0.0 if left is None else low + options.breath
        end = duration if right is None else high - options.breath
    if end - start < MIN_CUT:
        return None

    if left is not None:  # a borda cai no vale, sem passar da palavra cortada nem entrar na que fica
        ceiling = min(start + SNAP_RADIUS, end - MIN_CUT)
        if removed:
            ceiling = min(ceiling, removed[0].start)
        start = _valley(audio, max(low, start - SNAP_RADIUS), ceiling, start)
    if right is not None:
        floor = max(end - SNAP_RADIUS, start + MIN_CUT)
        if removed:
            floor = max(floor, removed[-1].end)
        end = _valley(audio, floor, min(high, end + SNAP_RADIUS), end)
    if end - start < MIN_CUT:
        return None
    if not removed:
        first, last = int(start / FRAME_SECONDS), math.ceil(end / FRAME_SECONDS)
        if int(np.count_nonzero(audio.speech[first:last])) > MAX_SPEECH_FRAMES:
            return None  # há som nessa pausa que o Whisper não escutou: não é silêncio
    text = " ".join(word.text for word in removed)
    return Cut(round(start, 3), round(end, 3), reason, text)


def _snap_to_frame_grid(cuts: list[Cut], levels: np.ndarray, grid: float) -> list[Cut]:
    """Move o começo de cada corte para que o trecho que fica antes dele dure um múltiplo da grade, no
    ponto mais quieto dos dois possíveis."""

    def loudness(time: float, original: float) -> tuple[float, float]:
        frame = min(int(time / FRAME_SECONDS), len(levels) - 1)
        return float(levels[frame]), abs(time - original)

    adjusted: list[Cut] = []
    cursor = 0.0
    for cut in cuts:
        steps = max(1, math.floor((cut.start - cursor) / grid))
        candidates = [cursor + steps * grid, cursor + (steps + 1) * grid]
        candidates = [t for t in candidates if t <= cut.end - MIN_CUT]
        if candidates:
            best = min(candidates, key=lambda t, c=cut: loudness(t, c.start))
            cut = replace(cut, start=round(best, 3))
        adjusted.append(cut)
        cursor = cut.end
    return adjusted


def plan_cuts(
    words: Sequence[Word], samples: np.ndarray, sample_rate: int, options: CutOptions | None = None
) -> CutPlan:
    """Os trechos que ficam e os cortes (início, fim, motivo) de uma gravação falada.

    `samples` é o áudio mono da gravação inteira. Sem palavras ou sem fala no áudio, nada é cortado.
    """
    options = options or CutOptions()
    duration = len(samples) / sample_rate
    whole = CutPlan([(0.0, duration)], [], list(words))
    levels = frame_rms(samples, sample_rate)
    active = active_frames(levels)
    if active is None or not words:
        return whole
    speech = levels >= float(np.percentile(levels, 95)) * 10.0 ** (-SPEECH_LEVEL_DB / 20.0)
    audio = _Audio(samples, sample_rate, active, speech)

    # o Whisper às vezes "escuta" uma palavra no silêncio; sem som não há o que proteger nem cortar
    sounding = [i for i, word in enumerate(words) if _has_sound(word, active)]
    refined = refine_words([words[i] for i in sounding], active)
    everything = list(words)
    for index, word in zip(sounding, refined, strict=True):
        everything[index] = word
    reasons = drop_reasons(refined, options.intensity)
    kept = [i for i in range(len(refined)) if i not in reasons]
    if not kept:
        return replace(whole, words=everything)

    # trechos de fala seguidos (índices das palavras que ficam) e o que se corta entre eles
    runs: list[list[int]] = [[kept[0]]]
    between: list[list[int]] = [list(range(0, kept[0]))]
    for previous, current in zip(kept, kept[1:], strict=False):
        pause = refined[current].start - refined[previous].end
        if current - previous > 1 or pause > options.min_pause:
            runs.append([current])
            between.append(list(range(previous + 1, current)))
        else:
            runs[-1].append(current)
    between.append(list(range(kept[-1] + 1, len(refined))))

    cuts: list[Cut] = []
    for k, dropped in enumerate(between):
        left = runs[k - 1][-1] if k > 0 else None
        right = runs[k][0] if k < len(runs) else None
        cut = _cut_between(refined, dropped, left, right, reasons, audio, options)
        if cut is not None:
            cuts.append(cut)
    if options.frame_grid:
        cuts = _snap_to_frame_grid(cuts, levels, options.frame_grid)

    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for cut in cuts:
        if cut.start > cursor:
            keep.append((round(cursor, 3), cut.start))
        cursor = cut.end
    if duration > cursor:
        keep.append((round(cursor, 3), round(duration, 3)))
    return CutPlan(keep, cuts, everything)
