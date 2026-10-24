"""Quem fala em cada frase e em cada palavra, a partir dos turnos da diarização.

Funções puras, sem áudio nem disco. A frase leva o falante que mais fala dentro dela; a palavra só leva um
falante quando ele é claramente o dono do tempo dela, porque é com as palavras de um falante só que se escolhe
a referência do clone.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..media.diarization import SpeakerTurn
from ..text.captions import Word
from .dub_plan import Timed

NEAREST_TURN_SECONDS = 1.0  # frase sem sobreposição vale o turno mais perto, se estiver a menos que isto
WORD_OWNER_SHARE = 0.5  # a palavra é de quem cobre ao menos esta fração do tempo dela...
WORD_RIVAL_SHARE = 0.25  # ...e ninguém mais cobre mais que esta (senão é fala sobreposta: de ninguém)


def _overlap(start: float, end: float, turn: SpeakerTurn) -> float:
    return max(0.0, min(end, turn.end) - max(start, turn.start))


def overlap_by_speaker(start: float, end: float, turns: Sequence[SpeakerTurn]) -> dict[str, float]:
    """Quanto de `start`..`end` cada falante cobre, na ordem em que aparecem nos turnos."""
    totals: dict[str, float] = {}
    for turn in turns:
        covered = _overlap(start, end, turn)
        if covered > 0:
            totals[turn.speaker] = totals.get(turn.speaker, 0.0) + covered
    return totals


def speaker_at(
    start: float, end: float, turns: Sequence[SpeakerTurn], nearest_within: float = NEAREST_TURN_SECONDS
) -> str | None:
    """O falante com mais tempo dentro de `start`..`end`; sem sobreposição, o do turno mais perto (se perto).

    O diarizador e o Whisper medem o tempo por caminhos diferentes e erram por décimos de segundo, então uma
    frase pode cair numa fresta entre turnos: o vizinho mais próximo é melhor palpite que deixar sem falante.
    """
    covered = overlap_by_speaker(start, end, turns)
    if covered:
        return max(covered, key=lambda speaker: covered[speaker])  # empate: o que aparece primeiro
    best: tuple[float, str] | None = None
    for turn in turns:
        gap = max(turn.start - end, start - turn.end)
        if gap <= nearest_within and (best is None or gap < best[0]):
            best = (gap, turn.speaker)
    return best[1] if best else None


def assign_speakers(segments: Sequence[Timed], turns: Sequence[SpeakerTurn]) -> list[str | None]:
    """O falante de cada trecho, na ordem recebida."""
    return [speaker_at(segment.start, segment.end, turns) for segment in segments]


def word_speaker(word: Word, turns: Sequence[SpeakerTurn]) -> str | None:
    """O dono da palavra, ou None quando ninguém cobre o bastante dela ou dois falam ao mesmo tempo."""
    duration = word.end - word.start
    if duration <= 0:
        return None
    covered = sorted(overlap_by_speaker(word.start, word.end, turns).items(), key=lambda item: -item[1])
    if not covered or covered[0][1] < WORD_OWNER_SHARE * duration:
        return None
    if len(covered) > 1 and covered[1][1] > WORD_RIVAL_SHARE * duration:
        return None
    return covered[0][0]


def label_words(words: Sequence[Word], turns: Sequence[SpeakerTurn]) -> list[str | None]:
    """O dono de cada palavra (veja `word_speaker`), na ordem recebida."""
    return [word_speaker(word, turns) for word in words]


def speaker_names(turns: Sequence[SpeakerTurn]) -> list[str]:
    """Os falantes dos turnos, na ordem em que aparecem."""
    return list(dict.fromkeys(turn.speaker for turn in turns))
