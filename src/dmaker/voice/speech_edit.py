"""Regravar um trecho de fala: achar o trecho pelas palavras e planejar a emenda. Funções puras, sem áudio.

A emenda troca uma região do original (as palavras erradas mais as pausas vizinhas) por uma fala nova. Os
tempos vêm das palavras da transcrição; o plano diz onde cortar, quanto a fala nova pode durar e onde ela
começa, sem tocar em disco nem no ffmpeg.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..text.captions import Word, fold

CROSSFADE_SECONDS = 0.03  # 30 ms: o menor fade que não estala numa emenda e ainda some dentro de uma pausa
MIN_PAUSE_SECONDS = 0.25  # silêncio a partir do qual o falante tomou fôlego: ali termina um grupo de fala
MAX_CONTEXT_SECONDS = (
    3.0  # quanto da frase vizinha entra de cada lado; mais que isso encarece a síntese à toa
)
MAX_BORROW_SECONDS = 0.5  # quanto de cada pausa vizinha a fala nova pode ocupar
STRETCH_TOLERANCE = 0.10  # até 10% de diferença no tamanho do texto mantém a duração original
MIN_SPEECH_SECONDS = 0.3
SNAP_RADIUS_SECONDS = 0.06  # quanto a emenda pode andar para cair no ponto mais quieto
WINDOW_SECONDS = 60.0  # janela isolada em volta do trecho: a voz do falante e o fundo da região
WINDOW_GRID_SECONDS = (
    15.0  # início da janela alinhado a esta grade, para dois reparos vizinhos dividirem o cache
)
WINDOW_MARGIN_SECONDS = 6.0  # a janela cobre o trecho com esta folga de cada lado (ganho e referência)
MAX_SUGGESTIONS = 3


@dataclass(frozen=True)
class SpeechEdit:
    """Trocar o que foi dito entre `start` e `end` (segundos no arquivo) por `text`."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SplicePlan:
    """Onde cortar e como encaixar a fala nova. Tempos em segundos no arquivo original."""

    region_start: float  # até aqui vale o original (mais o fade)
    region_end: float  # daqui em diante vale o original de novo
    speech_start: float  # onde a fala nova começa
    target_duration: float  # duração pedida ao sintetizador
    natural_duration: float  # quanto o texto novo levaria no ritmo do original
    crossfade: float
    rule: str  # a decisão de duração, em português, para o relatório

    @property
    def usable_end(self) -> float:
        return self.region_end - self.crossfade

    @property
    def squeezed(self) -> bool:
        """A fala natural não coube na região e foi comprimida."""
        return self.natural_duration > self.target_duration + 1e-6


# ---------- achar o trecho ----------


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", fold(text))


def _flat_tokens(words: list[Word]) -> list[tuple[str, int]]:
    """Cada palavra do texto sem acento nem caixa, com o índice da palavra de onde veio."""
    return [(token, index) for index, word in enumerate(words) for token in _tokens(word.text)]


def find_phrase_indices(words: list[Word], find: str) -> list[tuple[int, int]]:
    """Todas as ocorrências de `find` (sem acento, sem caixa, sem pontuação) como (primeira, última palavra)."""
    wanted = _tokens(find)
    if not wanted:
        raise ValueError("Informe o texto a procurar.")
    flat = _flat_tokens(words)
    tokens = [token for token, _ in flat]
    size = len(wanted)
    return [
        (flat[at][1], flat[at + size - 1][1])
        for at in range(len(tokens) - size + 1)
        if tokens[at : at + size] == wanted
    ]


def _suggestions(words: list[Word], find: str) -> list[str]:
    """Trechos da transcrição parecidos com `find`, no formato `"texto" (12.3 s)`."""
    size = len(_tokens(find))
    spans = [
        (" ".join(w.text for w in words[at : at + size]), words[at].start)
        for at in range(len(words) - size + 1)
    ]
    folded = {" ".join(_tokens(text)): (text, start) for text, start in spans}
    close = difflib.get_close_matches(" ".join(_tokens(find)), list(folded), n=MAX_SUGGESTIONS, cutoff=0.5)
    return [f'"{folded[key][0]}" ({folded[key][1]:.1f} s)' for key in close]


def locate_phrase(words: list[Word], find: str, occurrence: int | None = None) -> tuple[float, float]:
    """Início e fim (s) da frase `find` na transcrição, sem diferenciar acento, caixa nem pontuação.

    Com mais de uma ocorrência, `occurrence` (1, 2...) escolhe; sem ele a ambiguidade é um erro que lista
    os tempos, porque regravar a ocorrência errada estragaria o vídeo sem aviso.
    """
    matches = find_phrase_indices(words, find)
    if not matches:
        hint = _suggestions(words, find)
        close = f" Trechos parecidos: {'; '.join(hint)}." if hint else ""
        raise ValueError(
            f'Não achei "{find}" na transcrição.{close} Veja as palavras com `dmaker voice words`.'
        )
    if occurrence is None and len(matches) > 1:
        times = ", ".join(f"{words[first].start:.1f} s" for first, _ in matches)
        raise ValueError(
            f'"{find}" aparece {len(matches)} vezes ({times}). Diga qual (ocorrência 1 a {len(matches)}) '
            "ou use --start e --end."
        )
    position = (occurrence or 1) - 1
    if not 0 <= position < len(matches):
        raise ValueError(f'"{find}" aparece {len(matches)} vez(es); a ocorrência {occurrence} não existe.')
    first, last = matches[position]
    return words[first].start, words[last].end


def _midpoint(word: Word) -> float:
    return (word.start + word.end) / 2


def words_between(words: list[Word], start: float, end: float) -> list[Word]:
    """Palavras cujo meio cai em [start, end]."""
    return [word for word in words if start <= _midpoint(word) <= end]


def text_between(words: list[Word], start: float, end: float) -> str:
    return " ".join(word.text for word in words_between(words, start, end))


# ---------- grupo de fôlego ----------


def expand_to_breath_group(
    words: list[Word],
    start: float,
    end: float,
    min_pause: float = MIN_PAUSE_SECONDS,
    max_context: float = MAX_CONTEXT_SECONDS,
) -> tuple[float, float]:
    """Estende [start, end] até as pausas naturais em volta, para a frase regravada ter prosódia de frase.

    Uma palavra solta sintetizada fora de contexto soa recortada; com as palavras vizinhas até o próximo
    fôlego (pausa >= `min_pause`), a entonação encaixa. Cada lado traz no máximo `max_context` segundos.
    Sem palavras no intervalo, devolve o intervalo como veio.
    """
    inside = [index for index, word in enumerate(words) if start <= _midpoint(word) <= end]
    if not inside:
        return start, end
    first, last = inside[0], inside[-1]
    earliest = words[first].start - max_context
    while (
        first > 0
        and words[first].start - words[first - 1].end < min_pause
        and words[first - 1].start >= earliest
    ):
        first -= 1
    latest = words[last].end + max_context
    while (
        last < len(words) - 1
        and words[last + 1].start - words[last].end < min_pause
        and words[last + 1].end <= latest
    ):
        last += 1
    return words[first].start, words[last].end


def pause_room(words: list[Word], start: float, end: float, total_duration: float) -> tuple[float, float]:
    """Silêncio livre antes de `start` e depois de `end`, até a palavra vizinha (ou a ponta do arquivo)."""
    before = [word.end for word in words if _midpoint(word) < start]
    after = [word.start for word in words if _midpoint(word) > end]
    room_before = start - (max(before) if before else 0.0)
    room_after = (min(after) if after else total_duration) - end
    return max(0.0, room_before), max(0.0, room_after)


_TRAILING_PUNCTUATION = re.compile(r"[.,;:!?…]+$")


def _with_original_punctuation(replaced: list[Word], new_text: str) -> str:
    """O texto novo com a pontuação final do trecho trocado, se ele não trouxe a sua.

    "santo." trocado por "Santíssima Trindade" sem o ponto faria o modelo emendar a frase seguinte sem a
    pausa e a queda de entonação que o falante fez ali.
    """
    text = new_text.strip()
    if not replaced or _TRAILING_PUNCTUATION.search(text):
        return text
    kept = _TRAILING_PUNCTUATION.search(replaced[-1].text)
    return text + (kept.group(0) if kept else "")


def compose_text(words: list[Word], edit: SpeechEdit, group_start: float, group_end: float) -> str:
    """Texto a sintetizar: as palavras do grupo antes e depois do trecho, com o texto novo no lugar dele."""
    group = words_between(words, group_start, group_end)
    before = [w.text for w in group if _midpoint(w) < edit.start]
    after = [w.text for w in group if _midpoint(w) > edit.end]
    replacement = _with_original_punctuation(words_between(words, edit.start, edit.end), edit.text)
    return " ".join([*before, replacement, *after])


# ---------- janela de isolamento ----------


def isolation_window(
    start: float,
    end: float,
    duration: float,
    span: float = WINDOW_SECONDS,
    grid: float = WINDOW_GRID_SECONDS,
    margin: float = WINDOW_MARGIN_SECONDS,
) -> tuple[float, float]:
    """Janela do arquivo a isolar em volta do trecho: arquivos curtos inteiros, longos em `span` segundos.

    O início cai numa grade de `grid` segundos, de modo que dois reparos próximos reaproveitam os mesmos
    stems (separar custa vários minutos de CPU). A janela sempre cobre o trecho com `margin` de folga.
    """
    if duration <= span + grid:
        return 0.0, duration
    middle = (start + end) / 2
    window_start = max(0.0, math.floor((middle - span / 2) / grid) * grid)
    while window_start + span < end + margin:
        window_start += grid
    while window_start > max(0.0, start - margin):
        window_start -= grid
    window_start = max(0.0, window_start)
    window_end = window_start + span
    if window_end > duration - grid:
        window_end = duration
    return window_start, min(window_end, duration)


# ---------- plano da emenda ----------


def _letters(text: str) -> int:
    return len(re.sub(r"\W+", "", text))


def natural_duration(group_seconds: float, old_text: str, new_text: str) -> float:
    """Quanto o texto novo leva no ritmo do original: proporcional ao número de letras.

    Diferença de até `STRETCH_TOLERANCE` conta como igual (o ritmo oscila mais que isso), o que mantém a
    duração original e evita pedir ao sintetizador uma fala quase igual à de antes, só que mais lenta.
    """
    old_letters, new_letters = _letters(old_text), _letters(new_text)
    if not old_letters or not new_letters:
        return group_seconds
    ratio = new_letters / old_letters
    return group_seconds if abs(ratio - 1.0) <= STRETCH_TOLERANCE else group_seconds * ratio


def plan_splice(
    group_start: float,
    group_end: float,
    old_text: str,
    new_text: str,
    room_before: float,
    room_after: float,
    snap: Callable[[float], float] | None = None,
    crossfade: float = CROSSFADE_SECONDS,
) -> SplicePlan:
    """Região a trocar, onde a fala nova começa e quanto ela pode durar.

    A região vai de meia pausa antes do grupo até meia pausa depois (as emendas caem no meio do silêncio,
    onde um erro de tempo da transcrição não corta palavra). A fala nova pode ocupar a região toda menos o
    fade de cada ponta: texto mais longo estica o trecho para dentro das pausas vizinhas; se nem assim
    couber, a fala é comprimida. O comprimento total do arquivo nunca muda, então o vídeo segue em sincronia.
    `snap` (opcional) leva cada ponta da região ao ponto mais quieto ali perto.
    """
    snap = snap or (lambda seconds: seconds)
    pre_roll = max(crossfade, min(room_before / 2, MAX_BORROW_SECONDS))
    post_roll = max(crossfade, min(room_after / 2, MAX_BORROW_SECONDS))
    region_start = max(0.0, snap(group_start - pre_roll))
    region_end = snap(group_end + post_roll)

    usable_start, usable_end = region_start + crossfade, region_end - crossfade
    usable = max(MIN_SPEECH_SECONDS, usable_end - usable_start)
    old_seconds = group_end - group_start
    natural = max(MIN_SPEECH_SECONDS, natural_duration(old_seconds, old_text, new_text))
    target = min(natural, usable)

    # centrada onde o grupo original estava: o que sobra ou falta reparte-se pelos dois lados
    centered = group_start - (target - old_seconds) / 2
    speech_start = max(usable_start, min(centered, usable_end - target))
    return SplicePlan(
        region_start=region_start,
        region_end=region_end,
        speech_start=speech_start,
        target_duration=target,
        natural_duration=natural,
        crossfade=crossfade,
        rule=_rule(old_seconds, natural, target),
    )


def _rule(old_seconds: float, natural: float, target: float) -> str:
    if natural > target + 1e-6:
        return (
            f"texto longo demais: a fala natural levaria {natural:.1f} s e só cabem {target:.1f} s "
            f"(trecho original: {old_seconds:.1f} s); a fala foi comprimida"
        )
    if abs(target - old_seconds) < 1e-6:
        return f"duração do trecho original mantida ({old_seconds:.1f} s)"
    if target > old_seconds:
        return f"texto mais longo: trecho esticado de {old_seconds:.1f} s para {target:.1f} s usando as pausas vizinhas"
    return f"texto mais curto: fala encurtada de {old_seconds:.1f} s para {target:.1f} s; o resto vira pausa"


MAX_TEMPO = 1.15  # acima disso a fala acelerada soa apressada; é melhor comprimir na síntese
TEMPO_SLACK = 0.02  # até 2% além do espaço não vale um atempo


def fit_tempo(speech_seconds: float, available_seconds: float, max_tempo: float = MAX_TEMPO) -> float:
    """Fator de aceleração (sem mudar o tom) para a fala caber no espaço; 1.0 quando já cabe.

    O OmniVoice já gera na duração pedida; isto corrige o motor que ignora a duração (Kokoro) ou erra por
    pouco (o aparo das pontas). O que passa de `max_tempo` é cortado na emenda, com fade.
    """
    if available_seconds <= 0 or speech_seconds <= available_seconds * (1.0 + TEMPO_SLACK):
        return 1.0
    return min(max_tempo, speech_seconds / available_seconds)
