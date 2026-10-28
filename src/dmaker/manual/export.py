"""Do Markdown do manual para um HTML de página única, com as imagens embutidas e o sumário com âncoras.

O mesmo HTML alimenta o PDF (o navegador imprime a página), então o sumário clicável e as imagens valem nos dois.
É uma função pura: as imagens chegam por um carregador injetado, e nada é lido ou gravado aqui.
"""

from __future__ import annotations

import base64
import html as html_lib
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote

from markdown_it import MarkdownIt

from .slug import SlugCounter, plain_title

TOC_LEVEL = 3  # capítulos e tarefas entram no sumário; os subtítulos de cada tarefa ficam de fora
ImageLoader = Callable[[str], "tuple[str, bytes] | None"]

STYLE = """
:root { color-scheme: light; --ink: #17313a; --muted: #5b6f77; --accent: #0c535a; --soft: #e9f3ef; --line: #cfdcd8; }
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 920px; padding: 24px 20px 64px; color: var(--ink); background: #fff;
  font: 11pt/1.55 "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }
h1 { font-size: 26pt; color: var(--accent); margin: 0 0 8px; }
h2 { font-size: 18pt; color: var(--accent); margin: 40px 0 12px; padding-bottom: 6px; border-bottom: 2px solid var(--soft); }
h3 { font-size: 14pt; margin: 28px 0 8px; }
h4 { font-size: 11.5pt; margin: 18px 0 6px; color: var(--accent); }
h5 { font-size: 11pt; margin: 14px 0 4px; }
p, li { overflow-wrap: anywhere; }
a { color: var(--accent); }
a:not([href]) { color: inherit; text-decoration: none; }
code { font: 0.92em Consolas, "Cascadia Mono", monospace; background: var(--soft); padding: 1px 4px; border-radius: 4px; }
pre { background: #f4f7f6; border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; overflow-x: auto;
  white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0 18px; font-size: 0.93em; table-layout: auto; }
th, td { border: 1px solid var(--line); padding: 5px 8px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
th { background: var(--soft); }
img { max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 6px; }
blockquote { margin: 12px 0; padding: 4px 14px; border-left: 4px solid var(--accent); background: var(--soft); }
nav.toc { background: var(--soft); border-radius: 8px; padding: 14px 20px; margin: 20px 0 8px; }
nav.toc h2 { margin: 0 0 8px; padding: 0; border: 0; font-size: 14pt; break-before: auto; }
nav.toc ul { list-style: none; margin: 0; padding-left: 0; }
nav.toc ul ul { padding-left: 18px; font-size: 0.93em; }
nav.toc li { margin: 2px 0; break-inside: avoid; }
@media print {
  body { max-width: none; padding: 0; font-size: 10pt; }
  h2 { break-before: page; }
  h2, h3, h4 { break-after: avoid; }
  table, img, pre { break-inside: avoid; }
  a { text-decoration: none; }
}
"""


@dataclass(frozen=True)
class HtmlDocument:
    html: str
    missing_images: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _TocEntry:
    level: int
    title: str
    slug: str


def _data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _is_internal(href: str) -> bool:
    return href.startswith(("#", "http://", "https://", "mailto:"))


def _prepare(tokens: list, load_image: ImageLoader) -> tuple[list[_TocEntry], list[str]]:
    """Dá `id` aos títulos, embute as imagens e desfaz os links para arquivos fora do manual."""
    slugs = SlugCounter()
    toc: list[_TocEntry] = []
    missing: list[str] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[index + 1]
            slug = slugs.unique(inline.content)
            token.attrSet("id", slug)
            level = int(token.tag[1])
            if 2 <= level <= TOC_LEVEL:
                toc.append(_TocEntry(level, plain_title(inline.content), slug))
        if token.type != "inline" or not token.children:
            continue
        for child in token.children:
            if child.type == "image":
                src = str(child.attrGet("src") or "")
                loaded = load_image(src)
                if loaded is None:
                    missing.append(src)
                else:
                    child.attrSet("src", _data_uri(*loaded))
            elif child.type == "link_open":
                href = str(child.attrGet("href") or "")
                if not _is_internal(href):
                    # aponta para um arquivo do repositório: no PDF vira só texto
                    child.attrs.pop("href", None)
                elif href.startswith("#"):
                    # o markdown-it codifica os acentos; o id da âncora não
                    child.attrSet("href", unquote(href))
    return toc, missing


def _toc_html(entries: list[_TocEntry]) -> str:
    """Lista de dois níveis: cada capítulo com as suas tarefas embaixo."""
    out = ['<nav class="toc" aria-label="Sumário">', "<h2>Sumário</h2>", "<ul>"]
    open_item = open_sub = False
    for entry in entries:
        link = f'<a href="#{html_lib.escape(entry.slug)}">{html_lib.escape(entry.title)}</a>'
        if entry.level == 2:
            if open_sub:
                out.append("</ul>")
                open_sub = False
            if open_item:
                out.append("</li>")
            out.append(f"<li>{link}")
            open_item = True
        else:
            if not open_sub:
                out.append("<ul>")
                open_sub = True
            out.append(f"<li>{link}</li>")
    if open_sub:
        out.append("</ul>")
    if open_item:
        out.append("</li>")
    out.extend(["</ul>", "</nav>"])
    return "\n".join(out)


def render_html(markdown_text: str, *, title: str, load_image: ImageLoader) -> HtmlDocument:
    """O manual como uma página só: sumário navegável no topo, imagens embutidas e estilo para tela e impressão."""
    parser = MarkdownIt("commonmark", {"html": True}).enable("table")
    tokens = parser.parse(markdown_text)
    toc, missing = _prepare(tokens, load_image)
    body = parser.renderer.render(tokens, parser.options, {})
    first_chapter = body.find("<h2")
    page = body if first_chapter < 0 else body[:first_chapter] + _toc_html(toc) + body[first_chapter:]
    document = (
        '<!doctype html>\n<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html_lib.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n{page}\n</body>\n</html>\n"
    )
    return HtmlDocument(html=document, missing_images=tuple(dict.fromkeys(missing)))
