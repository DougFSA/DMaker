"""A boca em português: palavras com tempo viram a linha do tempo de visemas (o conjunto Oculus de 15).

Função pura, a fonte única da boca: o motor 2D e o 3D leem esta mesma linha do tempo. As regras de grafema para
visema são as do `modules/lipsync-pt_br.mjs` do TalkingHead (Lucas Boemeke), portadas do JavaScript para Python.

MIT License (a do repositório TalkingHead, https://github.com/met4citizen/TalkingHead)
Copyright (c) 2024 Mika Suominen

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and
this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS
PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import NamedTuple

SILENCE = "sil"
VISEMES = ("sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U")

# Um intervalo menor que isto entre duas palavras é só a respiração da fala corrida: a boca não fecha, segura o
# último visema até a próxima palavra começar. Pausa de verdade (mais longa) fecha a boca.
CONTINUOUS_GAP_SECONDS = 0.12

_LETTER_VISEMES = {
    **dict.fromkeys("aáàâã", "aa"),
    **dict.fromkeys("eéê", "E"),
    **dict.fromkeys("iíy", "I"),
    **dict.fromkeys("oóôõ", "O"),
    **dict.fromkeys("uúüw", "U"),
    **dict.fromkeys("bpm", "PP"),
    **dict.fromkeys("fv", "FF"),
    **dict.fromkeys("dt", "DD"),
    **dict.fromkeys("ckgq", "kk"),
    **dict.fromkeys("jx", "CH"),
    **dict.fromkeys("szç", "SS"),
    **dict.fromkeys("nl", "nn"),
    "r": "RR",
}
_VOWELS = "aáàâãeéêiíoóôõuúüy"
_FRONT_VOWELS = "eéêiíy"

# Duração relativa de cada visema (1 = média), do TalkingHead.
_VISEME_DURATIONS = {
    "aa": 0.95,
    "E": 0.90,
    "I": 0.92,
    "O": 0.96,
    "U": 0.95,
    "PP": 1.08,
    "SS": 1.23,
    "DD": 1.05,
    "FF": 1.00,
    "kk": 1.21,
    "nn": 0.88,
    "RR": 0.88,
    "CH": 1.15,
    "sil": 1.0,
}
_REPEAT_FACTOR = 0.7  # o mesmo visema duas vezes seguidas estende o anterior em vez de abrir outro
_SPECIAL_DURATIONS = {" ": 1.0, ",": 3.0, "-": 0.5}

_UNITS = (
    "zero um dois três quatro cinco seis sete oito nove dez onze doze treze quatorze quinze "
    "dezesseis dezessete dezoito dezenove"
).split()
_TENS = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa")
_HUNDREDS = (
    "",
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
)
_CURRENCIES = {
    "R$": ("real", "reais"),
    "US$": ("dólar", "dólares"),
    "$": ("dólar", "dólares"),
    "€": ("euro", "euros"),
}
_CURRENCY_PATTERN = re.compile(r"(R\$|US\$|\$|€)\s*(\d+(?:[.,]\d+)*)|(\d+(?:[.,]\d+)*)\s*(R\$|US\$|\$|€)")
_SYMBOLS = {
    "%": "por cento",
    "€": "euros",
    "&": "e",
    "+": "mais",
    "$": "dólares",
    "R$": "reais",
    "US$": "dólares",
}
_SYMBOL_PATTERN = re.compile(r"R\$|US\$|[%€&+$]")


class VisemeSpan(NamedTuple):
    """Um visema que vale de `start` a `end` (segundos no áudio da fala)."""

    start: float
    end: float
    viseme: str


def number_to_words(digits: str) -> str:
    """Um inteiro (em texto) por extenso, em português; código com zero à esquerda ou número enorme sai dígito a dígito."""
    if len(digits) > 12 or (len(digits) > 1 and digits[0] == "0"):
        return " ".join(_UNITS[int(d)] for d in digits)
    number = int(digits)
    if number == 0:
        return "zero"

    def below_1000(n: int) -> str:
        if n == 100:
            return "cem"
        parts = []
        hundreds, rest = divmod(n, 100)
        if hundreds:
            parts.append(_HUNDREDS[hundreds])
        if rest < 20:
            if rest:
                parts.append(_UNITS[rest])
        else:
            tens, units = divmod(rest, 10)
            parts.append(f"{_TENS[tens]} e {_UNITS[units]}" if units else _TENS[tens])
        return " e ".join(parts)

    # A conjunção "e" vem antes de um grupo abaixo de 100 ou de uma centena redonda: "mil e vinte", "um milhão e
    # cem", mas "mil duzentos e trinta".
    text = ""
    groups = (
        (number // 10**9, "um bilhão", "bilhões"),
        (number // 10**6 % 1000, "um milhão", "milhões"),
        (number // 10**3 % 1000, "mil", "mil"),
        (number % 1000, "", ""),
    )
    for value, singular, plural in groups:
        if not value:
            continue
        if not plural:
            words = below_1000(value)
        elif value == 1:
            words = singular
        else:
            words = f"{below_1000(value)} {plural}"
        text += (" e " if value < 100 or value % 100 == 0 else " ") + words if text else words
    return text


def preprocess_text(text: str) -> str:
    """Símbolos, moedas e números viram palavras e os caracteres mudos saem, como o TalkingHead faz antes das regras."""

    def currency(match: re.Match[str]) -> str:
        number = match.group(2) or match.group(3)
        singular, plural = _CURRENCIES[match.group(1) or match.group(4)]
        return f" {number} {singular if number == '1' else plural} "

    text = re.sub(r"[#_*'\":;]", "", text)
    text = _CURRENCY_PATTERN.sub(currency, text)
    text = _SYMBOL_PATTERN.sub(lambda m: f" {_SYMBOLS[m.group(0)]} ", text)
    text = re.sub(r"(\d)\.(?=\d{3}(?!\d))", r"\1", text)  # separador de milhar: 1.234 vira 1234
    text = re.sub(r"(\d),(\d)", r"\1 vírgula \2", text)
    text = re.sub(r"\d+", lambda m: number_to_words(m.group(0)), text)
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", text)).strip()


class _Sequence:
    """Os visemas de uma palavra com tempo relativo (unidades do TalkingHead), antes de escalar para segundos."""

    def __init__(self) -> None:
        self.visemes: list[str] = []
        self.times: list[float] = []
        self.durations: list[float] = []
        self.cursor = 0.0

    def push(self, viseme: str) -> None:
        if self.visemes and self.visemes[-1] == viseme:
            extra = _REPEAT_FACTOR * _VISEME_DURATIONS.get(viseme, 1.0)
            self.durations[-1] += extra
            self.cursor += extra
            return
        duration = _VISEME_DURATIONS.get(viseme, 1.0)
        self.visemes.append(viseme)
        self.times.append(self.cursor)
        self.durations.append(duration)
        self.cursor += duration

    @property
    def length(self) -> float:
        """O espaço que os visemas ocupam, sem a pausa que a pontuação do fim da palavra acrescenta."""
        return self.times[-1] + self.durations[-1] if self.visemes else 0.0


def _is_letter(char: str | None) -> bool:
    return char is not None and char.isalpha()


def _is_vowel(char: str | None) -> bool:
    return char is not None and char in _VOWELS


def _is_front(char: str | None) -> bool:
    return char is not None and char in _FRONT_VOWELS


def _at(chars: list[str], index: int) -> str | None:
    return chars[index] if 0 <= index < len(chars) else None


def text_to_visemes(text: str) -> _Sequence:
    """Os visemas do texto já pré-processado, pelas regras de grafema do português brasileiro (dígrafos ch, lh, nh,
    rr, ss, sc, qu, gu; c e g moles; h mudo; "ti"/"di" e "te"/"de" finais; l vocalizado; nasais)."""
    out = _Sequence()
    chars = list(text.lower())

    def is_end(i: int) -> bool:
        return not _is_letter(_at(chars, i))

    def is_final(i: int) -> bool:  # fim da palavra, com ou sem o s do plural
        return is_end(i) or (_at(chars, i) == "s" and is_end(i + 1))

    i = 0
    while i < len(chars):
        c, c1, c2 = chars[i], _at(chars, i + 1), _at(chars, i + 2)
        start_of_word = not _is_letter(_at(chars, i - 1) if i > 0 else None)
        step = _rule(out, chars, i, c, c1, c2, start_of_word, is_end, is_final)
        i += step
    return out


def _rule(out, chars, i, c, c1, c2, start_of_word, is_end, is_final) -> int:  # noqa: PLR0911, PLR0912
    """Aplica a regra que casa em `chars[i]` e devolve quantos caracteres consumiu."""
    # dígrafos
    if c == "c" and c1 == "h":
        out.push("CH")
        return 2
    if c in "ln" and c1 == "h":
        out.push("nn")
        return 2
    if c == "r" and c1 == "r":
        out.push("RR")
        return 2
    if c == "s" and c1 == "s":
        out.push("SS")
        return 2
    if c in "sx" and c1 == "c" and _is_front(c2):
        out.push("SS")
        return 2
    # consoantes com contexto
    if c == "q":
        out.push("kk")
        return 2 if (c1 == "u" and _is_front(c2)) else 1
    if c == "g":
        if c1 == "u" and _is_front(c2):  # gue, gui: o u é mudo
            out.push("kk")
            return 2
        out.push("CH" if _is_front(c1) else "kk")  # gelo x gato
        return 1
    if c == "c":
        out.push("SS" if _is_front(c1) else "kk")  # cedo x casa
        return 1
    if c == "h":
        return 1  # mudo (hoje)
    if c == "x":
        # soa como s antes de consoante (texto) e no "ex" inicial seguido de vogal (exame); senão, ch (caixa)
        after_initial_e = _at(chars, i - 1) in ("e", "ê") and not _is_letter(
            _at(chars, i - 2) if i > 1 else None
        )
        sounds_s = (_is_letter(c1) and not _is_vowel(c1)) or (after_initial_e and _is_vowel(c1))
        out.push("SS" if sounds_s else "CH")
        return 1
    if c in "td":
        # ti, di e te, de finais são africadas (tia, dia, tarde, cidade, de)
        affricate = c1 in ("i", "í") or (c1 == "e" and is_final(i + 2))
        out.push("CH" if affricate else "DD")
        return 1
    if c == "l":
        out.push("nn" if _is_vowel(c1) else "U")  # l em coda se vocaliza (Brasil, alto)
        return 1
    if c in "mn":
        if _is_vowel(c1):  # m/n em coda só nasaliza a vogal (campo, canto)
            out.push("PP" if c == "m" else "nn")
        return 1
    # ditongos nasais e vogais finais
    if c == "ã" and c1 == "o":
        out.push("aa")
        out.push("U")
        return 2
    if c == "a" and c1 == "m" and is_end(i + 2):
        out.push("aa")
        out.push("U")
        return 2
    if c in "eé" and ((c1 == "m" and is_end(i + 2)) or (c1 == "n" and c2 == "s" and is_end(i + 3))):
        out.push("E")
        out.push("I")
        return 2
    if c == "o" and c1 == "u":
        out.push("O")
        return 2
    if c == "e" and is_final(i + 1) and not start_of_word:
        out.push("I")  # e final átono (tarde)
        return 1
    if c == "e" and start_of_word and is_end(i + 1):
        out.push("I")  # a palavra "e"
        return 1
    if c == "o" and is_final(i + 1):
        out.push("U")  # o final átono (carro), a palavra "o"
        return 1
    viseme = _LETTER_VISEMES.get(c)
    if viseme is None and _is_letter(c):  # letra acentuada fora da tabela: vale a letra-base
        viseme = _LETTER_VISEMES.get(unicodedata.normalize("NFD", c)[0])
    if viseme:
        out.push(viseme)
    else:
        out.cursor += _SPECIAL_DURATIONS.get(c, 0.0)
    return 1


def word_visemes(start: float, end: float, text: str) -> list[VisemeSpan]:
    """Os visemas de uma palavra espalhados entre `start` e `end`; cada um segura a boca até o próximo começar."""
    sequence = text_to_visemes(preprocess_text(text))
    if not sequence.visemes or end <= start:
        return []
    scale = (end - start) / sequence.length
    starts = [start + t * scale for t in sequence.times]
    ends = [*starts[1:], end]
    return [VisemeSpan(a, b, viseme) for a, b, viseme in zip(starts, ends, sequence.visemes, strict=True)]


def build_visemes(words: Sequence[tuple[float, float, str]], duration: float) -> list[VisemeSpan]:
    """A linha do tempo de visemas da fala inteira, contínua de 0 a `duration`.

    `words` são `(início, fim, texto)` em segundos, em ordem. Entre palavras, uma pausa (a partir de
    `CONTINUOUS_GAP_SECONDS`) fecha a boca (`sil`); um intervalo curto segura o visema anterior. Visemas vizinhos
    iguais viram um só."""
    spans: list[VisemeSpan] = []
    cursor = 0.0
    for start, end, text in words:
        spoken = word_visemes(max(start, cursor), min(end, duration), text)
        if not spoken:
            continue
        first = spoken[0].start
        if first > cursor:
            if spans and first - cursor < CONTINUOUS_GAP_SECONDS:
                spans[-1] = spans[-1]._replace(end=first)
            else:
                spans.append(VisemeSpan(cursor, first, SILENCE))
        spans.extend(spoken)
        cursor = spoken[-1].end
    if cursor < duration:
        spans.append(VisemeSpan(cursor, duration, SILENCE))
    return _merge_equal(spans)


def _merge_equal(spans: list[VisemeSpan]) -> list[VisemeSpan]:
    merged: list[VisemeSpan] = []
    for span in spans:
        if merged and merged[-1].viseme == span.viseme:
            merged[-1] = merged[-1]._replace(end=span.end)
        else:
            merged.append(span)
    return merged
