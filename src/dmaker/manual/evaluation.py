"""A bateria de perguntas do manual: o formato do arquivo de dados e a correção de uma resposta.

O arquivo (`tests/data/manual_perguntas.json`) diz, para cada pergunta, em que seção a resposta certa se apoia
e quais termos ela precisa conter. A correção é determinística e sem modelo, então testa-se sozinha; quem roda
a bateria de verdade (com o Ollama) é o teste lento atrás de `DMAKER_MANUAL_EVAL=1`. Outros chamados estendem o
mesmo arquivo com perguntas para o agente local.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from .ask import Answer
from .examples import extract_commands
from .slug import strip_accents


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    sections: tuple[str, ...]  # trechos de título: basta a resposta citar um deles
    terms: tuple[str, ...]  # cada termo tem de aparecer na resposta; "a|b" aceita qualquer das duas grafias


@dataclass(frozen=True)
class Grade:
    ok: bool
    section_ok: bool  # a seção esperada está entre as consultadas
    section_in_text: bool  # o próprio modelo citou a seção no texto
    missing_terms: tuple[str, ...]
    invalid_commands: tuple[str, ...] = ()  # comandos `dmaker ...` da resposta que a CLI não tem


def normalize(text: str) -> str:
    return " ".join(strip_accents(text).lower().split())


def load_battery(raw: str) -> list[Question]:
    """Lê o JSON da bateria; erro claro se uma pergunta está sem seção ou sem termos."""
    data = json.loads(raw)
    questions = []
    for item in data["perguntas"]:
        if not item.get("secoes") or not item.get("termos"):
            raise ValueError(f"A pergunta '{item.get('id')}' precisa de 'secoes' e de 'termos'.")
        questions.append(Question(item["id"], item["pergunta"], tuple(item["secoes"]), tuple(item["termos"])))
    return questions


def _contains(haystack: str, needle: str) -> bool:
    return normalize(needle) in normalize(haystack)


def grade(
    answer: Answer, question: Question, command_problem: Callable[[str], str | None] | None = None
) -> Grade:
    """Acerta quando a seção esperada foi consultada e todos os termos aparecem no texto da resposta.

    `command_problem` (opcional) confere cada comando `dmaker` escrito na resposta contra a CLI de verdade; os que
    não existem vão em `invalid_commands`, para medir quanto o modelo inventa (não derruba o acerto).
    """
    consulted = " ; ".join(source.section for source in answer.sources)
    section_ok = any(_contains(consulted, wanted) for wanted in question.sections)
    in_text = any(_contains(answer.text, wanted) for wanted in question.sections)
    missing = tuple(
        term for term in question.terms if not any(_contains(answer.text, alt) for alt in term.split("|"))
    )
    invalid = ()
    if command_problem is not None:
        invalid = tuple(line for line in extract_commands(answer.text) if command_problem(line))
    return Grade(
        ok=section_ok and not missing,
        section_ok=section_ok,
        section_in_text=in_text,
        missing_terms=missing,
        invalid_commands=invalid,
    )
