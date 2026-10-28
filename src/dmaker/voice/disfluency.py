"""Vícios de fala e frases repetidas: decide, pelas palavras e pelas pausas, o que sobra para cortar.

Funções puras sobre palavras com tempo. Os tempos precisam estar ajustados à energia do áudio (ver
`voice/cut_plan.refine_words`): o Whisper estica o fim de um "é..." até a palavra seguinte, e uma pausa
que ele não mostra entre duas palavras é justamente o que separa um vício de uma palavra da frase.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from ..text.captions import Word, fold

REASON_FILLER = "filler"
REASON_REPETITION = "repetition"

INF = float("inf")

# 0,25 s de pausa é o mínimo que se ouve como "parou para pensar"; abaixo disso é a respiração normal da frase
ISOLATION_GAP = 0.25
# um "é" falado dura 0,15 a 0,35 s (uma voz sintética lenta chega lá) e um "tipo", ~0,3 a 0,45 s; só bem mais
# que isso é a hesitação arrastada ("ééé", "tiipo"). Na dúvida o "é" fica: cortar o verbo estraga a frase
ELONGATED_SECONDS = {"é": 0.45, "tipo": 0.6}
PHRASE_GAP = 0.3  # pausa que, sozinha, separa duas frases quando o texto não traz pontuação
SENTENCE_END = re.compile(r"[.!?…]$")
REPEAT_LOOKAHEAD = 2  # quantas frases à frente se procura a nova tomada de uma frase
REPEAT_WINDOW = 12.0  # a nova tomada vem logo em seguida; mais longe que isso é outro assunto
MIN_REPEATED_WORDS = 2  # uma palavra só repetida ("então. Então eu vou") é ênfase, não falso começo
MIN_SIMILAR_WORDS = 3  # a comparação por semelhança precisa de frases com um mínimo de conteúdo
SIMILARITY = 0.8  # fração das palavras em comum a partir da qual duas frases são a mesma, dita de novo
NGRAM_SIZES = (4, 3, 2)  # "a gente vai a gente vai": trecho repetido na hora, sem pausa nenhuma

# sons de hesitação que não são palavra; "ah", "um" e "aham" ficam de fora porque têm sentido
HESITATION_SOUNDS = frozenset({"hã", "ham", "hm", "hum", "ahn", "ahm", "uhm", "uh", "eh", "ãh", "ã"})
_STRETCHED_E = re.compile(r"é{2,}")
_REPEATED_LETTER = re.compile(r"(.)\1+")
_NOT_WORD = re.compile(r"[^\w]", re.UNICODE)


def normalize(text: str) -> str:
    """Minúsculas e só letras, mantendo o acento: "é" (verbo ou hesitação) não pode virar "e" (conjunção)."""
    return _NOT_WORD.sub("", text.lower())


def _is_hesitation_sound(token: str) -> bool:
    """ "hã", "hmmm", "ahnn", "ééé": o som sozinho já é o vício, não depende de onde cai na frase."""
    if _STRETCHED_E.fullmatch(token):
        return True
    return _REPEATED_LETTER.sub(r"\1", token) in HESITATION_SOUNDS


def _gap_before(words: Sequence[Word], index: int) -> float:
    """Pausa antes da palavra; o começo da fala conta como pausa (quem começa com "é..." está hesitando)."""
    return INF if index == 0 else words[index].start - words[index - 1].end


def _gap_after(words: Sequence[Word], index: int) -> float:
    """Pausa depois da palavra; o fim da fala conta como pausa."""
    return INF if index == len(words) - 1 else words[index + 1].start - words[index].end


def find_fillers(words: Sequence[Word]) -> set[int]:
    """Índices das palavras que são vício de fala.

    - Sons de hesitação ("hã", "hum", "ééé") sempre.
    - "né" só quando fecha a frase antes de uma pausa: colado nas vizinhas, no meio da frase, é o "não é".
    - "é" e "tipo" só quando isolados por pausa dos dois lados ou arrastados; colados na frase são palavras.
    """
    found: set[int] = set()
    for index, word in enumerate(words):
        token = normalize(word.text)
        if not token:
            continue
        if _is_hesitation_sound(token):
            found.add(index)
        elif token == "né":
            if _gap_after(words, index) >= ISOLATION_GAP:
                found.add(index)
        elif token in ELONGATED_SECONDS:
            elongated = word.end - word.start >= ELONGATED_SECONDS[token]
            isolated = (
                _gap_before(words, index) >= ISOLATION_GAP and _gap_after(words, index) >= ISOLATION_GAP
            )
            if elongated or isolated:
                found.add(index)
    return found


# ---------- frases repetidas e falsos começos ----------


def split_phrases(words: Sequence[Word]) -> list[list[int]]:
    """Índices das palavras agrupados em frases: a pontuação final ou uma pausa de `PHRASE_GAP` separam."""
    phrases: list[list[int]] = []
    for index, word in enumerate(words):
        if phrases and not (
            SENTENCE_END.search(words[index - 1].text.strip())
            or word.start - words[index - 1].end >= PHRASE_GAP
        ):
            phrases[-1].append(index)
        else:
            phrases.append([index])
    return phrases


def _tokens(words: Sequence[Word], indices: Sequence[int], ignore: set[int]) -> list[str]:
    """Palavras da frase para comparar: sem acento nem pontuação, e sem os vícios já marcados."""
    return [t for i in indices if i not in ignore and (t := fold(normalize(words[i].text)))]


def _is_restart(first: Sequence[str], second: Sequence[str]) -> bool:
    """A frase `first` é o começo de `second`; a última palavra pode estar cortada ("fal" de "falar")."""
    size = len(first)
    if size < MIN_REPEATED_WORDS or len(second) < size:
        return False
    return list(first[:-1]) == list(second[: size - 1]) and second[size - 1].startswith(first[-1])


def _is_rephrased(first: Sequence[str], second: Sequence[str]) -> bool:
    """As duas frases são quase as mesmas palavras, ditas de novo com um pequeno ajuste."""
    if min(len(first), len(second)) < MIN_SIMILAR_WORDS:
        return False
    return SequenceMatcher(None, first, second).ratio() >= SIMILARITY


def _repeated_phrase_indices(words: Sequence[Word], ignore: set[int]) -> set[int]:
    """Frases que a pessoa diz de novo logo em seguida: a primeira tomada sai, a última fica."""
    phrases = split_phrases(words)
    tokens = [_tokens(words, phrase, ignore) for phrase in phrases]
    dropped: set[int] = set()
    for k, phrase in enumerate(phrases):
        if len(phrase) == len(ignore & set(phrase)):
            continue  # só tinha vício: já sai pelo outro motivo
        for j in range(k + 1, min(k + 1 + REPEAT_LOOKAHEAD, len(phrases))):
            if words[phrases[j][0]].start - words[phrase[-1]].end > REPEAT_WINDOW:
                break
            if _is_restart(tokens[k], tokens[j]) or _is_rephrased(tokens[k], tokens[j]):
                dropped.update(phrase)
                break
    return dropped


def _repeated_ngram_indices(words: Sequence[Word], ignore: set[int]) -> set[int]:
    """Trecho dito duas vezes seguidas sem pausa ("a gente vai a gente vai"): sai a primeira cópia."""
    dropped: set[int] = set()
    for phrase in split_phrases(words):
        indices = [i for i in phrase if i not in ignore and fold(normalize(words[i].text))]
        tokens = [fold(normalize(words[i].text)) for i in indices]
        for size in NGRAM_SIZES:
            k = 0
            while k + 2 * size <= len(tokens):
                if tokens[k : k + size] == tokens[k + size : k + 2 * size] and not dropped & set(
                    indices[k : k + size]
                ):
                    dropped.update(indices[k : k + size])
                    k += size
                else:
                    k += 1
    return dropped


def find_repetitions(words: Sequence[Word], ignore: set[int] | None = None) -> set[int]:
    """Índices das palavras de frases repetidas e falsos começos, ficando com a última tomada.

    `ignore` são os vícios já marcados: não contam na comparação ("hoje eu vou, é, hoje eu vou" é repetição).
    """
    skipped = ignore or set()
    return _repeated_phrase_indices(words, skipped) | _repeated_ngram_indices(words, skipped)
