"""Roteiro de narração: divide o texto em falas e prepara cada fala para ser lida em voz alta.

Funções puras. Um modelo de voz sai melhor com frases de tamanho natural (uma frase por vez), e a
pausa entre elas vem do roteiro, não do modelo, para o ritmo ficar previsível.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = (
    800  # tamanho de trecho do VoiceStudio: acima disso a fala longa degrada (repete, pula palavra)
)
MIN_SENTENCE_CHARS = 20  # frase mais curta que isso se junta à seguinte (fala solta de uma palavra soa seca)
SENTENCE_PAUSE = 0.35
PARAGRAPH_PAUSE = 0.7
CLAUSE_PAUSE = 0.12  # respiro entre pedaços de uma mesma frase longa

# Abreviações cujo ponto nunca encerra a frase ("Dr. Silva", "R. das Flores").
_STRONG_ABBREVIATIONS = frozenset(
    {"dr", "dra", "drs", "sr", "sra", "srs", "sras", "srta", "prof", "profa", "av", "r", "pça", "cap", "gen"}
    | {"eng", "adv", "des", "min", "ten", "cel", "pe", "mons", "ilmo", "exmo", "ltda", "tel", "cx"}
    | {"ex", "obs", "fig", "p.ex", "pág", "pag", "vol", "cf", "aprox", "ref"}
)
# Abreviações que costumam fechar a frase só se a próxima palavra começar em maiúscula ("... etc. Depois").
_WEAK_ABBREVIATIONS = frozenset({"etc"})

_SENTENCE_END = (".", "!", "?", "…")
_CLOSERS = "\"'”’»)]"
_PAUSE_MARKER = re.compile(r"\[\s*pausa\s+(\d+(?:[.,]\d+)?)\s*(?:s|seg)?\s*\]", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"(?<=[;:,])\s+")


@dataclass(frozen=True)
class Utterance:
    """Uma fala sintetizada de uma vez, seguida de silêncio."""

    text: str
    pause_after: float


def _strip_closers(token: str) -> str:
    return token.rstrip(_CLOSERS)


def _ends_sentence(token: str, next_token: str | None) -> bool:
    bare = _strip_closers(token)
    if not bare.endswith(_SENTENCE_END):
        return False
    if bare.endswith(("!", "?", "…")):
        return True
    word = bare[:-1].lower()
    if word in _STRONG_ABBREVIATIONS:
        return False
    if len(word) == 1 and word.isalpha() and token[0].isupper():
        return False  # inicial de nome ("J. Silva")
    if word in _WEAK_ABBREVIATIONS:
        return next_token is not None and next_token[:1].isupper()
    return True


def split_sentences(paragraph: str) -> list[str]:
    """Divide um parágrafo em frases, respeitando abreviações do português do Brasil."""
    tokens = paragraph.split()
    sentences: list[str] = []
    current: list[str] = []
    for index, token in enumerate(tokens):
        current.append(token)
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if _ends_sentence(token, following):
            sentences.append(" ".join(current))
            current = []
    if current:
        sentences.append(" ".join(current))
    return sentences


def _pack(parts: list[str], max_chars: int) -> list[str]:
    """Junta pedaços vizinhos enquanto couberem em `max_chars`."""
    packed: list[str] = []
    for part in parts:
        if packed and len(packed[-1]) + 1 + len(part) <= max_chars:
            packed[-1] = f"{packed[-1]} {part}"
        else:
            packed.append(part)
    return packed


def _split_by_words(text: str, max_chars: int) -> list[str]:
    """Último recurso para um trecho sem pontuação: quebra em espaços."""
    return _pack(text.split(), max_chars)


def split_long(sentence: str, max_chars: int) -> list[str]:
    """Quebra uma frase maior que `max_chars` em vírgulas e pontos e vírgulas (por fim, em palavras)."""
    if len(sentence) <= max_chars:
        return [sentence]
    pieces: list[str] = []
    for clause in _CLAUSE_BREAK.split(sentence):
        pieces.extend(_split_by_words(clause, max_chars) if len(clause) > max_chars else [clause])
    return _pack(pieces, max_chars)


def _parse_pause(raw: str) -> float:
    return float(raw.replace(",", "."))


def _split_on_markers(text: str) -> list[str | float]:
    """Texto e marcadores `[pausa x]` intercalados; o marcador vira o número de segundos."""
    out: list[str | float] = []
    cursor = 0
    for match in _PAUSE_MARKER.finditer(text):
        out.append(text[cursor : match.start()])
        out.append(_parse_pause(match.group(1)))
        cursor = match.end()
    out.append(text[cursor:])
    return out


def merge_short_sentences(sentences: list[str], min_chars: int = MIN_SENTENCE_CHARS) -> list[str]:
    """Junta cada frase curta à seguinte (a última curta vai para a anterior)."""
    merged: list[str] = []
    carry = ""
    for sentence in sentences:
        current = f"{carry} {sentence}".strip()
        if len(current) < min_chars:
            carry = current
            continue
        merged.append(current)
        carry = ""
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged


def _paragraph_utterances(
    paragraph: str, max_chars: int, sentence_pause: float, paragraph_pause: float, clause_pause: float
) -> list[Utterance]:
    utterances: list[Utterance] = []
    for sentence in merge_short_sentences(split_sentences(paragraph)):
        pieces = split_long(sentence, max_chars)
        for index, piece in enumerate(pieces):
            last_piece = index == len(pieces) - 1
            utterances.append(Utterance(piece, sentence_pause if last_piece else clause_pause))
    if utterances:
        last = utterances[-1]
        utterances[-1] = Utterance(last.text, paragraph_pause)
    return utterances


def parse_script(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    sentence_pause: float = SENTENCE_PAUSE,
    paragraph_pause: float = PARAGRAPH_PAUSE,
    clause_pause: float = CLAUSE_PAUSE,
) -> list[Utterance]:
    """Divide o roteiro em falas com a pausa que vem depois de cada uma.

    Parágrafos (linha em branco) ganham pausa maior; `[pausa 1.2]` fixa a pausa exata do ponto
    onde aparece (substitui a pausa natural da fala anterior); a última fala fica sem pausa. Frases com
    menos de 20 caracteres se juntam à seguinte e trechos passam de `max_chars` só se não houver onde cortar.
    """
    if max_chars < 20:
        raise ValueError("max_chars deve ser pelo menos 20 para caber uma frase")
    utterances: list[Utterance] = []
    for chunk in _split_on_markers(clean_text(text)):
        if isinstance(chunk, float):
            if utterances:
                utterances[-1] = Utterance(utterances[-1].text, chunk)
            continue
        for paragraph in re.split(r"\n\s*\n", chunk):
            flat = " ".join(paragraph.split())
            if flat:
                utterances.extend(
                    _paragraph_utterances(flat, max_chars, sentence_pause, paragraph_pause, clause_pause)
                )
    if utterances:
        utterances[-1] = Utterance(utterances[-1].text, 0.0)
    return utterances


# ---------- normalização para leitura em voz alta ----------

# Caracteres de controle e invisíveis que fazem o modelo alucinar ou ficar mudo (lista do VoiceStudio).
_UNSAFE_CODEPOINTS = {*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), *range(0x7F, 0xA0)} | {
    0x200B,
    0x200E,
    0x200F,
    *range(0x202A, 0x202F),
    *range(0x2060, 0x2065),
    0xFEFF,
    0xFFFD,
}
_UNSAFE_TRANSLATION = dict.fromkeys(_UNSAFE_CODEPOINTS)
_ENTITIES = {
    "&nbsp;": " ",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
    "&hellip;": "…",
    "&mdash;": ",",
    "&ndash;": ",",
}
_ENTITY = re.compile("|".join(re.escape(entity) for entity in _ENTITIES) + r"|&amp;(?![a-zA-Z#])")
# Pontuação repetida mais de 3 vezes ("!!!!!!", ".........") vira silêncio longo ou balbucio: limita a 3.
_PUNCTUATION_RUN = re.compile(r"([!?.,;:~_*#=-])\1{3,}")
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")
_BLANK_LINE_FLOOD = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Limpeza de segurança antes de falar: controles invisíveis, entidades HTML, pontuação repetida."""
    cleaned = text.translate(_UNSAFE_TRANSLATION)
    cleaned = _ENTITY.sub(lambda match: _ENTITIES.get(match.group(0), "&"), cleaned)
    cleaned = _PUNCTUATION_RUN.sub(lambda match: match.group(1) * 3, cleaned)
    cleaned = _HORIZONTAL_SPACE.sub(" ", cleaned)
    return _BLANK_LINE_FLOOD.sub("\n\n", cleaned).strip()


_PT_LANGUAGES = {"pt", "pt-br", "pt_br", "portuguese"}
_THOUSANDS = r"\d{1,3}(?:\.\d{3})+"
_NUMBER = rf"(?:{_THOUSANDS}|\d+)"
_CURRENCY = re.compile(rf"R\$\s*({_NUMBER})(?:,(\d{{1,2}}))?")
_PERCENT = re.compile(rf"({_NUMBER})(?:,(\d+))?\s*%")
_DECIMAL = re.compile(rf"(?<![\w,.])({_NUMBER}),(\d+)(?![\w,])")
_INTEGER = re.compile(rf"(?<![\w,.]){_NUMBER}(?![\w])")


def _cardinal(value: int) -> str:
    from num2words import num2words

    # num2words separa milhares com vírgula ("mil, duzentos"), que na fala vira uma pausa indevida.
    return num2words(value, lang="pt_BR").replace(",", "")


def _to_int(digits: str) -> int:
    return int(digits.replace(".", ""))


def _fraction_words(digits: str) -> str:
    """Parte decimal lida como no dia a dia: zeros à esquerda um a um e o resto como número (até 3 casas)."""
    if len(digits) > 3:
        return " ".join(_cardinal(int(d)) for d in digits)
    zeros = len(digits) - len(digits.lstrip("0"))
    rest = digits.lstrip("0")
    words = ["zero"] * zeros
    if rest:
        words.append(_cardinal(int(rest)))
    return " ".join(words)


def _decimal_words(integer_digits: str, fraction_digits: str) -> str:
    return f"{_cardinal(_to_int(integer_digits))} vírgula {_fraction_words(fraction_digits)}"


def _money_words(reais: int, cents: int) -> str:
    parts: list[str] = []
    if reais or not cents:
        unit = "real" if reais == 1 else ("de reais" if reais and reais % 1_000_000 == 0 else "reais")
        parts.append(f"{_cardinal(reais)} {unit}")
    if cents:
        parts.append(f"{_cardinal(cents)} {'centavo' if cents == 1 else 'centavos'}")
    return " e ".join(parts)


def _currency_sub(match: re.Match[str]) -> str:
    cents_digits = match.group(2) or ""
    cents = int(cents_digits.ljust(2, "0")) if cents_digits else 0
    return _money_words(_to_int(match.group(1)), cents)


def _percent_sub(match: re.Match[str]) -> str:
    if match.group(2):
        return f"{_decimal_words(match.group(1), match.group(2))} por cento"
    return f"{_cardinal(_to_int(match.group(1)))} por cento"


def _decimal_sub(match: re.Match[str]) -> str:
    return _decimal_words(match.group(1), match.group(2))


def _integer_sub(match: re.Match[str]) -> str:
    return _cardinal(_to_int(match.group(0)))


def normalize_for_speech(text: str, language: str = "pt") -> str:
    """Escreve por extenso o que o modelo leria mal: R$, %, decimais com vírgula e números.

    Só o português tem regras próprias; em outros idiomas o texto segue como veio (espaços colapsados).
    Sem o pacote `num2words` (extra `voice`) os números ficam em dígitos.
    """
    collapsed = " ".join(clean_text(text).split())
    if language.lower() not in _PT_LANGUAGES:
        return collapsed
    try:
        import num2words  # noqa: F401
    except ImportError:
        return collapsed
    # Ordem importa: moeda e porcentagem consomem seus números antes das regras genéricas.
    spoken = _CURRENCY.sub(_currency_sub, collapsed)
    spoken = _PERCENT.sub(_percent_sub, spoken)
    spoken = _DECIMAL.sub(_decimal_sub, spoken)
    spoken = _INTEGER.sub(_integer_sub, spoken)
    return " ".join(spoken.split())
