"""Lê o `MANUAL.md` como uma árvore de títulos e reconhece as tarefas pelo molde fixo.

Uma tarefa é um título de nível 3 com um subtítulo "Quando usar". Os subtítulos que vêm depois seguem um
molde (`TASK_PARTS`), e é essa regularidade que deixa o gerador montar o arquivo de `docs/ia` sem que ninguém
o escreva à parte. Função pura: recebe o texto e devolve estruturas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .slug import SlugCounter, plain_title

# Subtítulo (nível 4) de cada parte de uma tarefa, na ordem em que aparecem, e a chave que o gerador usa.
TASK_PARTS: tuple[tuple[str, str], ...] = (
    ("Quando usar", "quando_usar"),
    ("Antes de começar", "antes"),
    ("Pela IA", "ia"),
    ("Chamadas das ferramentas", "chamadas"),
    ("Pela interface", "interface"),
    ("Pela CLI", "cli"),
    ("Como conferir", "conferir"),
    ("Se der errado", "erros"),
)
PART_TITLES = {title: key for title, key in TASK_PARTS}
TASK_LEVEL = 3
PART_LEVEL = 4

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TASK_ID = re.compile(r"<!--\s*tarefa:\s*([\w-]+)\s*-->")


@dataclass(frozen=True)
class Section:
    """Um título do manual e o texto que vem logo abaixo dele, até o próximo título de qualquer nível."""

    level: int
    title: str
    path: tuple[str, ...]  # títulos do capítulo até este, para citar a seção
    anchor: str
    line: int  # posição (0-based) da linha do título
    end: int  # primeira linha depois do texto direto desta seção
    body: str


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    chapter: str
    anchor: str
    summary: str  # o parágrafo logo abaixo do título: o que a tarefa entrega, em uma frase
    parts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Manual:
    sections: tuple[Section, ...]
    tasks: tuple[Task, ...]

    def task(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)


def parse_sections(text: str) -> list[Section]:
    """Todos os títulos (fora dos blocos de código) com o texto direto de cada um."""
    lines = text.splitlines()
    found: list[tuple[int, int, str]] = []  # (linha, nível, título)
    in_fence = False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING.match(line)
        if match:
            found.append((index, len(match.group(1)), match.group(2)))

    slugs = SlugCounter()
    stack: list[tuple[int, str]] = []
    sections: list[Section] = []
    for position, (index, level, raw_title) in enumerate(found):
        title = plain_title(raw_title)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = found[position + 1][0] if position + 1 < len(found) else len(lines)
        body = "\n".join(lines[index + 1 : end]).strip("\n")
        sections.append(
            Section(
                level=level,
                title=title,
                path=tuple(name for _, name in stack),
                anchor=slugs.unique(raw_title),
                line=index,
                end=end,
                body=body,
            )
        )
    return sections


def _chapter_of(section: Section) -> str:
    return section.path[1] if len(section.path) > 1 else ""


def parse_manual(text: str) -> Manual:
    """As seções e as tarefas do manual (as tarefas na ordem em que aparecem)."""
    sections = parse_sections(text)
    tasks: list[Task] = []
    for position, section in enumerate(sections):
        if section.level != TASK_LEVEL:
            continue
        children: list[Section] = []
        for later in sections[position + 1 :]:
            if later.level <= TASK_LEVEL:
                break
            if later.level == PART_LEVEL:
                children.append(later)
        if not any(child.title == TASK_PARTS[0][0] for child in children):
            continue
        id_match = _TASK_ID.search(section.body)
        task_id = id_match.group(1) if id_match else section.anchor
        summary = _TASK_ID.sub("", section.body).strip()
        parts = {PART_TITLES[child.title]: child.body for child in children if child.title in PART_TITLES}
        tasks.append(
            Task(
                id=task_id,
                title=section.title,
                chapter=_chapter_of(section),
                anchor=section.anchor,
                summary=summary,
                parts=parts,
            )
        )
    return Manual(sections=tuple(sections), tasks=tuple(tasks))


def task_part_titles(text: str, task: Task) -> list[str]:
    """Os subtítulos (nível 4) de uma tarefa, na ordem do arquivo, para conferir o molde."""
    sections = parse_sections(text)
    for position, section in enumerate(sections):
        if section.level == TASK_LEVEL and section.anchor == task.anchor:
            titles = []
            for later in sections[position + 1 :]:
                if later.level <= TASK_LEVEL:
                    break
                if later.level == PART_LEVEL:
                    titles.append(later.title)
            return titles
    return []


def structure_problems(text: str) -> list[str]:
    """O que foge do molde: parte faltando, fora de ordem, vazia, subtítulo desconhecido ou id repetido."""
    manual = parse_manual(text)
    expected = [title for title, _ in TASK_PARTS]
    problems: list[str] = []
    seen_ids: dict[str, str] = {}
    for task in manual.tasks:
        if task.id in seen_ids:
            problems.append(f"{task.title}: o id '{task.id}' já é de '{seen_ids[task.id]}'.")
        seen_ids[task.id] = task.title
        if not task.summary:
            problems.append(
                f"{task.title}: falta a frase logo abaixo do título dizendo o que a tarefa entrega."
            )
        titles = task_part_titles(text, task)
        for title in expected:
            if title not in titles:
                problems.append(f"{task.title}: falta o subtítulo '{title}'.")
        for title in titles:
            if title not in expected:
                problems.append(f"{task.title}: o subtítulo '{title}' não é do molde das tarefas.")
        present = [title for title in titles if title in expected]
        if present != [title for title in expected if title in present]:
            problems.append(f"{task.title}: os subtítulos estão fora da ordem do molde.")
        for title, key in TASK_PARTS:
            if key in task.parts and not task.parts[key].strip():
                problems.append(f"{task.title}: o subtítulo '{title}' está vazio.")
    return problems
