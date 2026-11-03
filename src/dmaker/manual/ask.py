"""`dmaker ajuda`: responde uma pergunta em português com os trechos do manual e um modelo local do Ollama.

A busca (BM25) escolhe a tarefa e os trechos; o modelo só redige a resposta em cima deles e cita a seção. Quando
a pergunta cai numa tarefa, o contexto é o arquivo curto de `docs/ia` dela (o passo a passo inteiro, em menos de
1.500 tokens), que dá ao modelo o comando certo sem ele ter de juntar pedaços. O modelo entra pelo protocolo
`ChatModel`, então o teste usa um falso e nada aqui fala com o Ollama diretamente.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..agent.llm import ChatModel
from .outline import Task
from .search import Hit, ManualIndex

SYSTEM_PROMPT = (
    "Você responde dúvidas sobre o DMaker, um editor de vídeos curtos por comando, usando SOMENTE os trechos "
    "do manual que vêm na mensagem do usuário.\n"
    "Regras:\n"
    "- Responda em português do Brasil, direto e curto (no máximo 8 linhas ou passos).\n"
    "- Escreva os comandos e os nomes de ferramentas exatamente como estão nos trechos, entre crases. Copie as "
    "opções sem mudar uma letra.\n"
    "- Comando de terminal começa com `dmaker` e só vale se está escrito assim nos trechos. Nome com sublinhado "
    "(como `dub_get`) é ferramenta MCP, não comando: nunca o escreva como `dmaker dub get`.\n"
    "- Se os trechos não respondem, diga que não achou no manual. Não invente comando, opção nem caminho.\n"
    "- Termine com uma linha no formato: Seção: <caminho da seção do manual em que você se apoiou>.\n"
    "- Não use travessão."
)
TOP_HITS = 5
EXTRA_BLOCKS = 2  # trechos de outras seções que acompanham o arquivo da tarefa
CONTEXT_CHARS = 9000  # ~3 mil tokens de trechos: sobra espaço no contexto de 16k de um modelo local
NO_MODEL_NOTICE = "Não consegui falar com o modelo local; estes são os trechos do manual que mais combinam:"
NOT_FOUND = "Não achei nada no manual sobre isso. Tente outras palavras."

IaDocLoader = Callable[[str], "str | None"]


@dataclass(frozen=True)
class Source:
    """Uma seção do manual consultada: o caminho legível, a âncora e a tarefa a que pertence."""

    section: str
    anchor: str
    task_id: str | None


@dataclass(frozen=True)
class Answer:
    question: str
    text: str
    sources: tuple[Source, ...]
    task_id: str | None  # a tarefa do manual que mais combina com a pergunta, se houver


def thinking_level(model: str) -> str | None:
    """`low` encurta o raciocínio do gpt-oss (que ignora booleano); outros modelos ficam no padrão deles."""
    return "low" if "gpt-oss" in model else None


def task_section(task: Task) -> str:
    return f"{task.chapter} > {task.title}" if task.chapter else task.title


def pick_task(question: str, index: ManualIndex, hits: list[Hit]) -> Task | None:
    """A tarefa que a pergunta pede: a de melhor intenção entre as que aparecem nos melhores trechos."""
    candidates = {hit.chunk.task_id for hit in hits if hit.chunk.task_id}
    if not candidates:
        return None
    for task, _score in index.rank_tasks(question, limit=len(index.manual.tasks)):
        if task.id in candidates:
            return task
    return None


@dataclass(frozen=True)
class Context:
    """O que vai para o modelo: os blocos de texto numerados e as fontes que eles representam."""

    blocks: tuple[tuple[str, str], ...]  # (seção, texto)
    sources: tuple[Source, ...]
    task: Task | None


def build_context(
    question: str, index: ManualIndex, hits: list[Hit], ia_doc: IaDocLoader | None = None
) -> Context:
    """Arquivo da tarefa em primeiro lugar (se houver) e, depois, os melhores trechos de outras seções."""
    task = pick_task(question, index, hits)
    blocks: list[tuple[str, str]] = []
    sources: list[Source] = []
    manual = ia_doc(task.id) if task is not None and ia_doc else None
    if task is not None:
        # a tarefa é sempre a primeira citada
        sources.append(Source(task_section(task), task.anchor, task.id))
    if task is not None and manual:
        blocks.append((task_section(task), manual))
    elif task is not None:
        # sem o arquivo de docs/ia, os trechos da própria tarefa vêm antes
        hits = sorted(hits, key=lambda hit: hit.chunk.task_id != task.id)
    room = EXTRA_BLOCKS if blocks else TOP_HITS
    for hit in hits:
        if room == 0:
            break
        if blocks and task is not None and hit.chunk.task_id == task.id:
            continue  # o arquivo da tarefa já cobre este trecho
        blocks.append((hit.chunk.section, hit.chunk.text))
        room -= 1
        if all(source.section != hit.chunk.section for source in sources):
            sources.append(Source(hit.chunk.section, hit.chunk.anchor, hit.chunk.task_id))
    return Context(tuple(blocks), tuple(sources[:3]), task)


def build_messages(question: str, context: Context) -> list[dict]:
    """Prompt de sistema mais a pergunta com os trechos numerados, cortados no orçamento de contexto."""
    parts: list[str] = []
    used = 0
    for number, (section, text) in enumerate(context.blocks, start=1):
        block = f"[{number}] Seção: {section}\n{text}"
        if used + len(block) > CONTEXT_CHARS and parts:
            break
        parts.append(block)
        used += len(block)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Pergunta: {question}\n\nTrechos do manual:\n\n" + "\n\n".join(parts)},
    ]


def answer_question(
    question: str,
    index: ManualIndex,
    chat: ChatModel,
    ia_doc: IaDocLoader | None = None,
    limit: int = TOP_HITS,
) -> Answer:
    """Busca, pede a resposta ao modelo e devolve o texto com as seções consultadas e a tarefa sugerida."""
    hits = index.search(question, limit=limit)
    if not hits:
        return Answer(question, NOT_FOUND, (), None)
    context = build_context(question, index, hits, ia_doc)
    reply = chat.chat(build_messages(question, context), [])
    return Answer(question, reply.content.strip(), context.sources, context.task.id if context.task else None)


def search_only(
    question: str, index: ManualIndex, ia_doc: IaDocLoader | None = None, limit: int = TOP_HITS
) -> Answer:
    """Sem modelo: devolve o arquivo da tarefa e os trechos que mais combinam, para quem está sem o Ollama."""
    hits = index.search(question, limit=limit)
    if not hits:
        return Answer(question, NOT_FOUND, (), None)
    context = build_context(question, index, hits, ia_doc)
    text = "\n\n".join(f"{section}\n{body}" for section, body in context.blocks)
    task_id = context.task.id if context.task else None
    return Answer(question, f"{NO_MODEL_NOTICE}\n\n{text}", context.sources, task_id)
