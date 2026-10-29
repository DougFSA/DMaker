"""Palavras para a busca: minúsculas, sem acento, sem palavras vazias e com um radical simples do português.

Sem modelo de embeddings: a busca casa palavras. O radical existe para "dublar", "dublagem" e "dublo" caírem na
mesma raiz, que é o que uma pergunta em linguagem corrida precisa. É grosseiro de propósito (alguns radicais
saem estranhos), mas o mesmo radical vale para o manual e para a pergunta, e isso é o que importa.
"""

from __future__ import annotations

import re

from .slug import strip_accents

# Palavras de ligação e de pergunta que não distinguem uma seção da outra. "fazer", "criar" e "gerar" ficam de
# fora da lista de propósito: elas dizem o que a pessoa quer.
STOPWORDS = frozenset(
    """
    a o as os um uma uns umas de do da dos das em no na nos nas ao aos à às por para pra com sem sob sobre
    e ou mas que se como qual quais quando onde quem porque por que eu me meu minha meus minhas seu sua seus suas
    nosso nossa voce voces ele ela eles elas isso isto esse essa esses essas este esta estes estas aquele aquela
    ser sou e eh foi era sao esta estao estou ter tem tenho temos haver ha
    posso pode podem poder preciso precisa quero quer queria gostaria saber sei ver vejo ir vou vai
    ja ainda tambem so apenas muito muita mais menos bem aqui ali la entao assim nao nem
    """.split()
)

_SUFFIXES = tuple(
    sorted(
        """
        issimos issimas issimo issima amentos imentos amento imento adoras adores adora ador acoes ucoes acao ucao
        idades idade mente istas ista ismos ismo aveis avel iveis ivel agens agem ancias ancia encias encia
        ando endo indo aram eram iram ados adas ado ada idos idas ido ida antes ante osos osas oso osa
        oes aes ar er ir ou ei em as os es ao s a o e
        """.split(),
        key=len,
        reverse=True,
    )
)
MIN_STEM = 3

_COMPOUND = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)+")
_WORD = re.compile(r"[a-z0-9]+")


def stem(word: str) -> str:
    """O radical da palavra; número e palavra curta passam como estão."""
    if len(word) <= MIN_STEM or not word.isalpha():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    """Os termos de um texto para indexar ou buscar.

    Um identificador como `render_project` ou `no-ui` vira o termo inteiro (assim a pergunta que o cita acha
    a ferramenta) e também as partes (`render`, `project`).
    """
    plain = strip_accents(text.lower())
    terms: list[str] = [match.group(0) for match in _COMPOUND.finditer(plain)]
    for match in _WORD.finditer(plain):
        word = match.group(0)
        if word in STOPWORDS or len(word) < 2 and not word.isdigit():
            continue
        terms.append(stem(word))
    return terms
