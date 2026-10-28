"""Busca no manual por palavras (BM25): devolve os trechos que respondem a uma pergunta, com a seção de cada um.

Funciona sem internet e sem modelo de embeddings. O manual é cortado em trechos pequenos, cada um com o
caminho dos títulos até ele; o título pesa mais que o corpo porque o nome de uma tarefa é o que uma pergunta
costuma repetir. Os trechos da referência gerada (comandos, ferramentas, campos) valem menos: servem para
quem pergunta por um nome exato, mas não podem esconder a tarefa que ensina o caminho.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .bm25 import Bm25
from .markers import end_marker, start_marker
from .outline import Manual, Section, Task, parse_manual
from .tokens import tokenize

CHUNK_LIMIT = 1400  # caracteres por trecho de texto corrido
ENTRY_LIMIT = 700  # caracteres por trecho de referência (agrupa algumas entradas seguidas)
TITLE_WEIGHT = 3  # quantas vezes o caminho dos títulos conta no índice
REFERENCE_WEIGHT = 0.6  # a referência gerada vale menos que o texto que ensina a tarefa
REFERENCE_BLOCKS = ("cli", "mcp", "spec")

KIND_TASK = "tarefa"
KIND_TEXT = "texto"
KIND_REFERENCE = "referencia"


@dataclass(frozen=True)
class Chunk:
    """Um trecho do manual: o caminho dos títulos, a âncora da seção e o texto."""

    path: tuple[str, ...]
    anchor: str
    kind: str
    task_id: str | None
    text: str

    @property
    def section(self) -> str:
        """O caminho legível da seção, para citar: `Tarefas de voz > Dublar um vídeo > Pela CLI`."""
        return " > ".join(self.path[1:] if len(self.path) > 1 else self.path)


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def _generated_ranges(text: str) -> dict[str, tuple[int, int]]:
    """Linhas (início, fim) de cada bloco gerado."""
    lines = text.splitlines()
    ranges: dict[str, tuple[int, int]] = {}
    for name in (*REFERENCE_BLOCKS, "indice"):
        begin = next((i for i, line in enumerate(lines) if line.strip() == start_marker(name)), None)
        finish = next((i for i, line in enumerate(lines) if line.strip() == end_marker(name)), None)
        if begin is not None and finish is not None:
            ranges[name] = (begin, finish)
    return ranges


def _split_paragraphs(body: str, limit: int) -> list[str]:
    """Corta em parágrafos e, se um parágrafo sozinho passa do limite, em linhas; nunca no meio de uma linha."""
    pieces: list[str] = []
    current = ""
    for block in re.split(r"\n\s*\n", body):
        block = block.strip("\n")
        if not block:
            continue
        if len(block) > limit:
            if current:
                pieces.append(current)
                current = ""
            for line in block.splitlines():
                if current and len(current) + len(line) + 1 > limit:
                    pieces.append(current)
                    current = ""
                current = f"{current}\n{line}" if current else line
            continue
        if current and len(current) + len(block) + 2 > limit:
            pieces.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    if current:
        pieces.append(current)
    return pieces


def _split_entries(body: str, limit: int) -> list[str]:
    """Para a referência: cada entrada (`- **comando**` e suas linhas recuadas) fica inteira num trecho."""
    entries: list[str] = []
    for line in body.splitlines():
        if line.startswith("- **") or not entries:
            entries.append(line)
        else:
            entries[-1] += "\n" + line
    pieces: list[str] = []
    current = ""
    for entry in entries:
        if current and len(current) + len(entry) + 1 > limit:
            pieces.append(current)
            current = ""
        current = f"{current}\n{entry}" if current else entry
    if current:
        pieces.append(current)
    return pieces


def _without_index_block(body: str) -> str:
    """Tira o índice gerado de dentro do texto de um capítulo: ele repete todos os títulos e casaria com tudo."""
    return re.sub(
        rf"{re.escape(start_marker('indice'))}.*?{re.escape(end_marker('indice'))}", "", body, flags=re.DOTALL
    )


def _chunks_of(section: Section, kind: str, task_id: str | None) -> list[Chunk]:
    body = _without_index_block(section.body)
    if not body.strip():
        return []
    if kind == KIND_REFERENCE and "- **" in body:
        pieces = _split_entries(body, ENTRY_LIMIT)
    else:
        pieces = _split_paragraphs(body, CHUNK_LIMIT)
    return [Chunk(section.path, section.anchor, kind, task_id, piece) for piece in pieces]


def split_chunks(text: str, manual: Manual | None = None) -> list[Chunk]:
    """Os trechos de busca do manual inteiro, sem o índice de tarefas (que só repete os títulos)."""
    manual = manual or parse_manual(text)
    ranges = _generated_ranges(text)
    task_by_title = {task.anchor: task for task in manual.tasks}
    current_task = None
    chunks: list[Chunk] = []
    for section in manual.sections:
        if section.level <= 3:
            current_task = task_by_title.get(section.anchor) if section.level == 3 else None
        if "indice" in ranges and ranges["indice"][0] < section.line < ranges["indice"][1]:
            continue
        in_reference = any(
            begin < section.line < finish
            for name, (begin, finish) in ranges.items()
            if name in REFERENCE_BLOCKS
        )
        if in_reference:
            kind, task_id = KIND_REFERENCE, None
        elif current_task is not None:
            kind, task_id = KIND_TASK, current_task.id
        else:
            kind, task_id = KIND_TEXT, None
        chunks.extend(_chunks_of(section, kind, task_id))
    return chunks


def task_intent_terms(task: Task) -> list[str]:
    """Os termos que dizem para que a tarefa serve: o título, a frase de resumo, quando usar e o que perguntar."""
    return (
        tokenize(task.title) * TITLE_WEIGHT
        + tokenize(task.summary) * 2
        + tokenize(task.parts.get("quando_usar", ""))
        + tokenize(task.parts.get("antes", ""))
    )


class ManualIndex:
    """O manual pronto para perguntas: os trechos e o índice BM25 deles, mais um índice de tarefas.

    O índice de tarefas casa a pergunta só com a intenção de cada uma (título, resumo e frases de pedido). Ele
    resolve o empate entre tarefas parecidas ("palavra errada na legenda" e "palavra errada sem regravar"),
    que no índice de trechos disputam por causa das mesmas palavras nos títulos.
    """

    def __init__(self, chunks: list[Chunk], manual: Manual) -> None:
        self.chunks = chunks
        self.manual = manual
        documents = [tokenize(" ".join(chunk.path)) * TITLE_WEIGHT + tokenize(chunk.text) for chunk in chunks]
        self._bm25 = Bm25(documents)
        self._tasks_bm25 = Bm25([task_intent_terms(task) for task in manual.tasks])

    def rank_tasks(self, question: str, limit: int = 3) -> list[tuple[Task, float]]:
        """As tarefas cuja intenção mais combina com a pergunta (nota maior que zero), da melhor para a pior."""
        query = tokenize(question)
        if not query or not self.manual.tasks:
            return []
        scores = self._tasks_bm25.scores(query)
        ranked = sorted(zip(self.manual.tasks, scores, strict=True), key=lambda item: item[1], reverse=True)
        return [(task, score) for task, score in ranked[:limit] if score > 0]

    @classmethod
    def from_text(cls, text: str) -> ManualIndex:
        manual = parse_manual(text)
        return cls(split_chunks(text, manual), manual)

    def search(self, question: str, limit: int = 5, max_reference: int = 2) -> list[Hit]:
        """Os `limit` melhores trechos para a pergunta, com no máximo `max_reference` da referência gerada."""
        query = tokenize(question)
        if not query or not self.chunks:
            return []
        scores = self._bm25.scores(query)
        ranked = sorted(
            (
                Hit(chunk, score * (REFERENCE_WEIGHT if chunk.kind == KIND_REFERENCE else 1.0))
                for chunk, score in zip(self.chunks, scores, strict=True)
                if score > 0
            ),
            key=lambda hit: hit.score,
            reverse=True,
        )
        chosen: list[Hit] = []
        references = 0
        for hit in ranked:
            if hit.chunk.kind == KIND_REFERENCE:
                if references >= max_reference:
                    continue
                references += 1
            chosen.append(hit)
            if len(chosen) == limit:
                break
        return chosen


@lru_cache(maxsize=2)
def cached_index(text: str) -> ManualIndex:
    """O índice do manual com este texto; a ferramenta MCP responde várias perguntas sem reindexar."""
    return ManualIndex.from_text(text)
