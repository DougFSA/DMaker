"""Texto dos documentos que a pessoa anexa à conversa com o agente: .txt, .md, .srt, .docx e .pdf viram texto puro.

Cada formato é um extrator registrado por extensão em `EXTRACTORS`: aceitar um formato novo é escrever uma função e
registrá-la, sem `if` espalhado. Tudo aqui é puro (bytes e nome entram, texto sai); o disco e o limite de contexto ficam
com quem chama. Só o PDF usa um pacote de fora (`pypdf`, do extra `agente`), importado na hora de ler um PDF.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from ..voice.manuscript import decode_text, docx_paragraphs
from .captions import parse_srt

# Quanto de texto extraído se guarda no máximo: um livro inteiro cabe, e um PDF enorme não trava a leitura.
MAX_EXTRACTED_CHARS = 2_000_000
PDF_INSTALL_HINT = (
    'Ler PDF precisa do pacote pypdf. Instale com: pip install -e ".[agente]" '
    "(ou copie o texto para um arquivo .txt ou .docx)."
)
# Quanto da folga final vale procurar uma fronteira (fim de parágrafo, de frase ou de palavra) ao cortar um texto.
CUT_LOOKBACK_RATIO = 0.10
_NUL = "\x00"
_BLANK_RUNS = re.compile(r"\n{3,}")
# Onde um corte é bem-vindo, do melhor ao pior, e quantos caracteres do marcador ficam no texto (o ponto final fica).
_BOUNDARIES = (
    ("\n\n", 0),
    (". ", 1),
    ("! ", 1),
    ("? ", 1),
    (".\n", 1),
    ("!\n", 1),
    ("?\n", 1),
    ("\n", 0),
    (" ", 0),
)


class DocumentError(ValueError):
    """O arquivo não pôde virar texto (formato desconhecido, arquivo corrompido ou sem nenhum texto)."""


Extractor = Callable[[bytes], str]


def extract_plain(data: bytes) -> str:
    """Texto puro e Markdown vão como estão: o modelo lê Markdown sem precisar de ajuda."""
    return decode_text(data)


def extract_srt(data: bytes) -> str:
    """As falas de uma legenda em texto corrido, sem numeração nem tempos (o modelo quer o que foi dito)."""
    cues = parse_srt(decode_text(data))
    if not cues:
        raise DocumentError("Não encontrei falas neste arquivo .srt.")
    return " ".join(cue.text.strip() for cue in cues if cue.text.strip())


def extract_docx(data: bytes) -> str:
    """O texto do Word: um parágrafo por bloco, títulos com `#` e itens de lista com `-`."""
    blocks = []
    for paragraph in docx_paragraphs(data):
        if paragraph.is_heading:
            blocks.append(f"# {paragraph.text}")
        elif paragraph.is_list_item:
            blocks.append(f"- {paragraph.text}")
        else:
            blocks.append(paragraph.text)
    return "\n\n".join(blocks)


def extract_pdf(data: bytes) -> str:
    """O texto selecionável de um PDF, página por página. Digitalização (só imagem) não tem texto: o DMaker não faz OCR."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentError(PDF_INSTALL_HINT) from exc
    pages: list[str] = []
    total = 0
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("O PDF está protegido por senha: o DMaker não consegue lê-lo.")
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
                total += len(text)
            if total > MAX_EXTRACTED_CHARS:
                break
    except DocumentError:
        raise
    except Exception as exc:  # noqa: BLE001 - o pypdf levanta tipos variados diante de um PDF quebrado
        raise DocumentError("Não consegui abrir o PDF: o arquivo está corrompido ou protegido.") from exc
    if not pages:
        raise DocumentError(
            "Este PDF não tem texto selecionável (talvez seja uma digitalização); o DMaker ainda não faz OCR."
        )
    return "\n\n".join(pages)


EXTRACTORS: dict[str, Extractor] = {
    ".txt": extract_plain,
    ".md": extract_plain,
    ".markdown": extract_plain,
    ".srt": extract_srt,
    ".docx": extract_docx,
    ".pdf": extract_pdf,
}


def tidy_text(text: str) -> str:
    """Quebras de linha do Windows viram `\\n`, o caractere nulo some e sobra no máximo uma linha em branco seguida."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").replace(_NUL, "")
    return _BLANK_RUNS.sub("\n\n", cleaned).strip()


def extract_text(data: bytes, filename: str, extractors: Mapping[str, Extractor] = EXTRACTORS) -> str:
    """O texto do arquivo, escolhendo o extrator pela extensão; levanta `DocumentError` com a razão em português."""
    suffix = Path(filename).suffix.lower()
    extractor = extractors.get(suffix)
    if extractor is None:
        accepted = ", ".join(sorted(extractors))
        raise DocumentError(
            f"Não sei ler arquivos {suffix or 'sem extensão'} como texto (aceitos: {accepted})."
        )
    try:
        text = tidy_text(extractor(data))
    except DocumentError:
        raise
    except ValueError as exc:  # o leitor de Word e o de legenda explicam o problema em português
        raise DocumentError(str(exc)) from exc
    if not text:
        raise DocumentError("O arquivo não tem texto para enviar ao modelo.")
    return text


def cut_text(text: str, limit: int) -> tuple[str, bool]:
    """O começo de `text` com até `limit` caracteres, cortado numa fronteira natural; diz se cortou.

    Procura, nos últimos 10% antes do limite, o fim de um parágrafo, de uma frase ou ao menos de uma palavra, para o
    modelo não receber meia palavra. Sem fronteira por perto, corta no limite.
    """
    if limit <= 0:
        return "", bool(text)
    if len(text) <= limit:
        return text, False
    floor = limit - max(1, int(limit * CUT_LOOKBACK_RATIO))
    window = text[floor : limit + 1]
    for marker, kept in _BOUNDARIES:
        position = window.rfind(marker)
        if position != -1:
            return text[: floor + position + kept].rstrip(), True
    return text[:limit], True
