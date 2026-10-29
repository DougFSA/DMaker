"""Os comandos do manual: gerar (`build`), conferir se está em dia (`check`) e exportar HTML e PDF.

É aqui, e em `files.py`, que o pacote toca o disco. O navegador entra por injeção (`Browser`), então o teste
exporta sem Chromium.
"""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..media.browser import Browser
from . import files
from .ask import pick_task
from .build import BuildInputs, BuildResult, build_all, stale_files
from .examples import command_problem, extract_commands, parse_calls
from .export import render_html
from .live import agent_tools as live_agent_tools
from .live import build_inputs, cli_root
from .outline import parse_manual
from .search import cached_index

HTML_NAME = "DMaker-manual.html"
PDF_NAME = "DMaker-manual.pdf"
_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![s\w])")


class NotACheckout(RuntimeError):
    """`build` só roda no repositório: numa instalação comum o manual é uma cópia de leitura."""


def planned(inputs: BuildInputs | None = None) -> BuildResult:
    """O que `build` gravaria hoje, calculado em memória a partir do manual que está no disco."""
    return build_all(files.read_manual(), inputs or build_inputs())


def check(inputs: BuildInputs | None = None) -> list[str]:
    """Os arquivos que `build` mudaria; vazio quando o manual e `docs/ia` estão em dia com o código."""
    result = planned(inputs)
    return stale_files(files.read_manual(), files.read_ia_files(), result)


def build(inputs: BuildInputs | None = None) -> list[str]:
    """Regenera os blocos do `MANUAL.md` e a pasta `docs/ia`; devolve os arquivos que mudaram."""
    if not files.is_checkout():
        raise NotACheckout(
            "O manual só é regenerado no repositório do DMaker (existe docs/MANUAL.md na raiz)."
        )
    result = planned(inputs)
    changed = []
    if files.write_text(files.manual_path(), result.manual):
        changed.append("docs/MANUAL.md")
    ia_folder = files.ia_dir()
    for name, text in result.ia_files.items():
        if files.write_text(ia_folder / name, text):
            changed.append(f"docs/ia/{name}")
    for name in sorted(set(files.read_ia_files(ia_folder)) - set(result.ia_files)):
        (ia_folder / name).unlink()
        changed.append(f"docs/ia/{name} (apagado: sem tarefa no manual)")
    return changed


def load_image(source: str) -> tuple[str, bytes] | None:
    """Lê uma imagem citada no manual (caminho relativo a `docs/`); `None` se o arquivo não existe."""
    if re.match(r"^[a-z]+://", source) or source.startswith("data:"):
        return None
    path = (files.docs_dir() / source).resolve()
    if not path.is_file() or not path.is_relative_to(files.docs_dir().resolve()):
        return None
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return mime, path.read_bytes()


def count_pdf_pages(path: Path) -> int:
    """Número de páginas de um PDF, contando os objetos `/Type /Page` (suficiente para o relatório)."""
    return len(_PAGE_OBJECT.findall(path.read_bytes()))


@dataclass(frozen=True)
class ExportReport:
    html_path: Path | None
    pdf_path: Path | None
    pages: int | None
    missing_images: tuple[str, ...]


def default_export_dir() -> Path:
    return config.OUTPUT_DIR / "manual"


def export_manual(
    out_dir: Path | None = None, *, html: bool = True, pdf: bool = True, browser: Browser | None = None
) -> ExportReport:
    """Grava o manual em HTML de página única e/ou PDF. O PDF precisa de um navegador (`Browser`)."""
    folder = out_dir or default_export_dir()
    folder.mkdir(parents=True, exist_ok=True)
    document = render_html(files.read_manual(), title="Manual do DMaker", load_image=load_image)
    html_path = pdf_path = None
    pages = None
    if html:
        html_path = folder / HTML_NAME
        html_path.write_text(document.html, encoding="utf-8", newline="\n")
    if pdf:
        if browser is None:
            from ..media.browser import PlaywrightBrowser

            browser = PlaywrightBrowser()
        pdf_path = folder / PDF_NAME
        browser.html_to_pdf(document.html, pdf_path)
        pages = count_pdf_pages(pdf_path) if pdf_path.exists() else None
    return ExportReport(html_path, pdf_path, pages, document.missing_images)


MAX_RESULTS = 8
RESULT_CHARS = 1200  # cada trecho devolvido à IA é cortado aqui, para a resposta caber num modelo pequeno


def search_manual(question: str, limit: int = 5) -> dict:
    """Os trechos do manual que mais combinam com a pergunta (a ferramenta MCP `search_manual`)."""
    index = cached_index(files.read_manual())
    hits = index.search(question, limit=max(1, min(limit, MAX_RESULTS)))
    results = []
    for hit in hits:
        text = hit.chunk.text
        results.append(
            {
                "section": hit.chunk.section,
                "anchor": hit.chunk.anchor,
                "task": hit.chunk.task_id,
                "score": round(hit.score, 2),
                "text": text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS].rstrip() + " ...",
            }
        )
    task = pick_task(question, index, hits)
    suggestion = (
        {"id": task.id, "title": task.title, "file": f"docs/ia/{task.id}.md"} if task is not None else None
    )
    return {"question": question, "results": results, "suggested_task": suggestion}


@dataclass(frozen=True)
class AgentOffer:
    """A tarefa que o agente local pode executar: o manual dela (de `docs/ia`) e as ferramentas que ele ainda não tem."""

    task_id: str
    title: str
    manual: str
    missing_tools: tuple[str, ...]
    tools: tuple[str, ...] = ()  # todas as ferramentas que as chamadas da tarefa usam

    @property
    def runnable(self) -> bool:
        return not self.missing_tools


def agent_offer(task_id: str, agent_tools: Sequence[str] | None = None) -> AgentOffer | None:
    """Monta a oferta de executar a tarefa pelo agente; `None` se a tarefa ou o arquivo dela não existem."""
    task = parse_manual(files.read_manual()).task(task_id)
    manual = files.read_ia_doc(task_id)
    if task is None or manual is None:
        return None
    available = agent_tools if agent_tools is not None else live_agent_tools()
    used = tuple(dict.fromkeys(call.tool for call in parse_calls(task)))
    missing = tuple(name for name in used if name not in available)
    return AgentOffer(task.id, task.title, manual, missing, used)


def invented_commands(text: str) -> list[str]:
    """Os comandos `dmaker ...` que o texto cita e a CLI não tem: um modelo pequeno mistura ferramenta MCP com comando."""
    root = cli_root()
    return [line for line in extract_commands(text) if command_problem(line, root, require_arguments=False)]
