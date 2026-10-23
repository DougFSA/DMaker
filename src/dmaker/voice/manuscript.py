"""Importação de roteiro: texto, Markdown ou Word viram capítulos prontos para narrar.

Funções puras (texto ou bytes entram, capítulos saem), sem tocar disco e sem dependência fora da
biblioteca padrão: o .docx é lido como o zip de XML que ele é.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

SUPPORTED_SUFFIXES = (".txt", ".md", ".markdown", ".docx")
PREAMBLE_TITLE = "Introdução"  # título do trecho que vem antes do primeiro capítulo marcado
MAX_HEADING_CHARS = 120  # linha maior que isso é frase de corpo, não título ("Capítulo 3 mostra que...")
MAX_DOCX_PART_BYTES = 100 * 1024 * 1024  # barra um .docx que descompacta além do razoável (zip bomb)

_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# "Capítulo 3", "Parte II: o começo". O número é dígito ou numeral romano, e precisa terminar ali.
_SECTION_HEADING = re.compile(
    r"^(?:cap[ií]tulo|parte)\s+(?:\d+|[ivxlc]+)(?=$|[\s.:)\-\u2013\u2014])", re.IGNORECASE
)
_HASH_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_RULE = re.compile(r"^\s*(?:[-*_=]\s*){3,}$")
_TABLE_BORDER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
_SENTENCE_END = (".", "!", "?", "…", ":", ";")

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\[\]]+)\]\((?:[^()]|\([^)]*\))*\)")
_AUTOLINK = re.compile(r"<(?:https?://|mailto:)[^>]*>")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_BOLD_ITALIC = re.compile(r"(?<![\w*])(\*{1,3})(?=\S)(.+?)(?<=\S)\1(?![\w*])")
_UNDERSCORED = re.compile(r"(?<![\w_])(_{1,3})(?=\S)(.+?)(?<=\S)\1(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~")
_CODE_SPAN = re.compile(r"`([^`]*)`")
_BARE_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class Chapter:
    """Um capítulo do roteiro: o título dá nome ao arquivo e o texto é o que a voz narra."""

    title: str
    text: str


@dataclass(frozen=True)
class _Block:
    """Pedaço do documento na ordem em que aparece: um título de capítulo ou um parágrafo."""

    kind: Literal["chapter", "paragraph"]
    text: str


def strip_formatting(text: str) -> str:
    """Tira as marcas de formatação (negrito, itálico, links, código) e deixa só o que se lê em voz alta.

    Link vira o texto dele (o endereço não é narrado) e imagem some; os sublinhados de `snake_case`
    ficam, porque só se removem os que abraçam uma palavra.
    """
    cleaned = _IMAGE.sub("", text)
    cleaned = _LINK.sub(r"\1", cleaned)
    cleaned = _AUTOLINK.sub("", cleaned)
    cleaned = _HTML_TAG.sub("", cleaned)
    cleaned = _CODE_SPAN.sub(r"\1", cleaned)
    cleaned = _STRIKE.sub(r"\1", cleaned)
    cleaned = _BOLD_ITALIC.sub(r"\2", cleaned)
    cleaned = _UNDERSCORED.sub(r"\2", cleaned)
    cleaned = _BARE_URL.sub("", cleaned)
    return " ".join(cleaned.split())


def _as_sentence(text: str) -> str:
    """Garante pontuação no fim: item de lista e título solto viram uma frase com pausa própria."""
    stripped = text.strip()
    if not stripped or stripped.endswith(_SENTENCE_END):
        return stripped
    return f"{stripped}."


def _clean_title(raw: str) -> str:
    return strip_formatting(raw).strip(" #\t")


def _is_section_heading(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) <= MAX_HEADING_CHARS and bool(_SECTION_HEADING.match(stripped))


def _plain_line(line: str) -> str:
    """Tira a marca de citação (`>`) e lê linha de tabela (`| a | b |`) como itens separados por vírgula.

    A barra vertical no meio da frase fica, porque `[[termo|pronúncia]]` a usa.
    """
    if line.startswith(">"):
        line = line.lstrip("> ")
    if line.startswith("|"):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        return _as_sentence(", ".join(cell for cell in cells if cell))
    return line


def _decode(data: bytes) -> str:
    """UTF-8 (com ou sem BOM); se não for, Windows-1252, que é o que o Bloco de Notas antigo grava."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# ---------- texto e Markdown ----------


def _line_blocks(text: str, heading_levels: tuple[int, ...], section_words: bool) -> list[_Block]:
    """Lê o texto linha a linha: títulos viram capítulo, o resto agrupa em parágrafos (linha em branco separa)."""
    blocks: list[_Block] = []
    lines: list[str] = []

    def flush() -> None:
        if lines:
            blocks.append(_Block("paragraph", " ".join(lines)))
            lines.clear()

    in_fence = False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _FENCE.match(raw):
            in_fence = not in_fence  # código não se narra
            continue
        if in_fence:
            continue
        line = raw.strip()
        if not line:
            flush()
            continue
        if _RULE.match(line) or _TABLE_BORDER.match(line):
            flush()
            continue
        heading = _HASH_HEADING.match(line)
        if heading and len(heading.group(1)) in heading_levels:
            flush()
            title = _clean_title(heading.group(2))
            if title:
                blocks.append(_Block("chapter", title))
            continue
        if heading:  # subtítulo que não abre capítulo: vira uma frase própria
            flush()
            blocks.append(_Block("paragraph", _as_sentence(_clean_title(heading.group(2)))))
            continue
        if section_words and _is_section_heading(line):
            flush()
            blocks.append(_Block("chapter", _clean_title(line)))
            continue
        item = _LIST_ITEM.match(raw)
        if item:
            lines.append(_as_sentence(strip_formatting(item.group(1))))
            continue
        lines.append(strip_formatting(_plain_line(line)))
    flush()
    return [block for block in blocks if block.text.strip()]


# ---------- Word ----------


def _heading_style_ids(styles_xml: bytes | None) -> dict[str, bool]:
    """Para cada estilo do documento, se ele é de capítulo (Título 1/2, Heading 1/2 ou Title), pelo nome."""
    if not styles_xml:
        return {}
    marks: dict[str, bool] = {}
    for style in ElementTree.fromstring(styles_xml).iter(f"{_WORD_NS}style"):
        style_id = style.get(f"{_WORD_NS}styleId")
        name = style.find(f"{_WORD_NS}name")
        if style_id and name is not None:
            marks[style_id] = _is_chapter_style(name.get(f"{_WORD_NS}val", ""))
    return marks


def _is_chapter_style(name: str) -> bool:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold().strip()
    return bool(re.fullmatch(r"(?:heading|titulo)\s*[12]?|title", folded))


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_WORD_NS}t":
            parts.append(node.text or "")
        elif node.tag in (f"{_WORD_NS}tab", f"{_WORD_NS}br"):
            parts.append(" ")
    return " ".join("".join(parts).split())


def _docx_blocks(data: bytes) -> list[_Block]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            raise KeyError("word/document.xml")
        sizes = [info.file_size for info in archive.infolist()]
        if any(size > MAX_DOCX_PART_BYTES for size in sizes):
            raise ValueError("O arquivo .docx descompacta para um tamanho absurdo.")
        document = archive.read("word/document.xml")
        styles = archive.read("word/styles.xml") if "word/styles.xml" in names else None
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("Não consegui abrir o .docx: o arquivo está corrompido ou não é do Word.") from exc
    chapter_styles = _heading_style_ids(styles)
    blocks: list[_Block] = []
    for paragraph in ElementTree.fromstring(document).iter(f"{_WORD_NS}p"):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        style = paragraph.find(f"{_WORD_NS}pPr/{_WORD_NS}pStyle")
        style_id = style.get(f"{_WORD_NS}val", "") if style is not None else ""
        if chapter_styles.get(style_id, _is_chapter_style(style_id)):
            blocks.append(_Block("chapter", _clean_title(text)))
            continue
        if paragraph.find(f"{_WORD_NS}pPr/{_WORD_NS}numPr") is not None:
            text = _as_sentence(text)  # item de lista numerada ou com marcadores
        blocks.append(_Block("paragraph", strip_formatting(text)))
    return [block for block in blocks if block.text.strip()]


# ---------- junção em capítulos ----------


def _group_chapters(blocks: list[_Block], default_title: str) -> list[Chapter]:
    """Agrupa os blocos em capítulos; sem nenhum título, o roteiro inteiro é um capítulo só."""
    has_headings = any(block.kind == "chapter" for block in blocks)
    chapters: list[tuple[str, list[str]]] = []
    for block in blocks:
        if block.kind == "chapter":
            chapters.append((block.text, []))
        elif chapters:
            chapters[-1][1].append(block.text)
        else:
            chapters.append((PREAMBLE_TITLE if has_headings else default_title, [block.text]))
    result = [Chapter(title, "\n\n".join(paragraphs)) for title, paragraphs in chapters if paragraphs]
    return result


def chapters_from_text(text: str, default_title: str = "Roteiro") -> list[Chapter]:
    """Roteiro em texto puro: capítulo é a linha que começa com "# " ou com "Capítulo"/"Parte" e um número."""
    return _group_chapters(_line_blocks(text, heading_levels=(1,), section_words=True), default_title)


def chapters_from_markdown(text: str, default_title: str = "Roteiro") -> list[Chapter]:
    """Roteiro em Markdown: os títulos de nível 1 e 2 (# e ##) abrem capítulos."""
    return _group_chapters(_line_blocks(text, heading_levels=(1, 2), section_words=False), default_title)


def chapters_from_docx(data: bytes, default_title: str = "Roteiro") -> list[Chapter]:
    """Roteiro do Word: parágrafos com estilo Título/Heading (1 ou 2) abrem capítulos."""
    return _group_chapters(_docx_blocks(data), default_title)


def parse_manuscript(data: bytes, filename: str) -> list[Chapter]:
    """Capítulos de um arquivo de roteiro, escolhendo o leitor pela extensão; o nome do arquivo vira o título
    do roteiro que não tem capítulos marcados."""
    suffix = Path(filename).suffix.lower()
    default_title = title_from_filename(filename)
    if suffix == ".docx":
        chapters = chapters_from_docx(data, default_title)
    elif suffix in (".md", ".markdown"):
        chapters = chapters_from_markdown(_decode(data), default_title)
    elif suffix == ".txt":
        chapters = chapters_from_text(_decode(data), default_title)
    else:
        raise ValueError(
            f"Formato de roteiro não suportado ({suffix or 'sem extensão'}); use .txt, .md ou .docx."
        )
    if not chapters:
        raise ValueError("O roteiro não tem texto para narrar.")
    return chapters


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    return " ".join(stem.split()) or "Roteiro"
