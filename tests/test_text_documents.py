"""Texto dos documentos anexados: cada formato vira texto puro, o corte respeita fronteiras e a recusa explica o porquê."""

from __future__ import annotations

import pytest

from dmaker.text.documents import (
    EXTRACTORS,
    PDF_INSTALL_HINT,
    DocumentError,
    cut_text,
    extract_text,
    tidy_text,
)
from dmaker.voice.manuscript import docx_paragraphs

from .pdf_samples import make_pdf
from .test_voice_manuscript import make_docx

SRT = """1
00:00:01,000 --> 00:00:03,000
Bom dia a todos.

2
00:00:03,500 --> 00:00:05,000
<i>Hoje</i> vamos
falar de vídeo.
"""


def test_plain_text_and_markdown_come_through_as_they_are():
    assert extract_text("Olá, mundo.\n".encode(), "nota.txt") == "Olá, mundo."
    assert extract_text("# Título\n\nCorpo.".encode(), "nota.md") == "# Título\n\nCorpo."


def test_a_text_file_saved_in_windows_1252_is_read_without_garbling_the_accents():
    assert extract_text("coração".encode("cp1252"), "velho.txt") == "coração"


def test_an_srt_becomes_the_spoken_words_without_numbers_or_times():
    text = extract_text(SRT.encode(), "legenda.srt")

    assert text == "Bom dia a todos. Hoje vamos falar de vídeo."


def test_a_file_that_is_not_a_subtitle_is_refused_in_portuguese():
    with pytest.raises(DocumentError, match="Não encontrei falas"):
        extract_text(b"isto nao e uma legenda", "legenda.srt")


def test_a_docx_keeps_the_structure_titles_lists_and_paragraphs():
    data = make_docx(
        [
            ("Relatório", "Heading1", False),
            ("Primeiro parágrafo.", None, False),
            ("item um", None, True),
            ("item dois", None, True),
        ],
        {"Heading1": "heading 1"},
    )

    assert extract_text(data, "relatorio.docx") == (
        "# Relatório\n\nPrimeiro parágrafo.\n\n- item um\n\n- item dois"
    )


def test_the_public_docx_reader_is_the_one_the_manuscript_import_uses():
    data = make_docx([("Capítulo um", "Heading1", False), ("Texto.", None, False)], {"Heading1": "heading 1"})

    paragraphs = docx_paragraphs(data)

    assert [(p.text, p.is_heading, p.is_list_item) for p in paragraphs] == [
        ("Capítulo um", True, False),
        ("Texto.", False, False),
    ]


def test_a_docx_that_is_not_a_zip_is_refused_with_the_manuscript_message():
    with pytest.raises(DocumentError, match="Não consegui abrir o .docx"):
        extract_text(b"isso nao e um docx", "x.docx")


def test_a_docx_whose_xml_is_broken_is_refused_not_crashed():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><w:body>")
    with pytest.raises(DocumentError, match="corrompido"):
        extract_text(buffer.getvalue(), "quebrado.docx")


def test_a_file_without_text_is_refused():
    with pytest.raises(DocumentError, match="não tem texto"):
        extract_text(b"  \n\n \r\n", "vazio.txt")


def test_a_pdf_is_read_page_by_page():
    pytest.importorskip("pypdf")

    text = extract_text(make_pdf("Primeira pagina: ARARA-AZUL-742", "Segunda pagina."), "contrato.pdf")

    assert text == "Primeira pagina: ARARA-AZUL-742\n\nSegunda pagina."


def test_a_pdf_without_selectable_text_says_it_is_probably_a_scan():
    pytest.importorskip("pypdf")

    with pytest.raises(DocumentError, match="não tem texto selecionável"):
        extract_text(make_pdf(""), "scan.pdf")


def test_a_broken_pdf_is_refused_not_crashed():
    pytest.importorskip("pypdf")

    with pytest.raises(DocumentError, match="Não consegui abrir o PDF"):
        extract_text(b"%PDF-1.4 isto nao termina", "quebrado.pdf")


def test_a_password_protected_pdf_is_refused_with_the_reason():
    pypdf = pytest.importorskip("pypdf")
    import io

    writer = pypdf.PdfWriter()
    writer.append(pypdf.PdfReader(io.BytesIO(make_pdf("segredo"))))
    writer.encrypt("senha", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(DocumentError, match="senha|Não consegui abrir"):
        extract_text(buffer.getvalue(), "trancado.pdf")


def test_without_pypdf_the_pdf_says_which_extra_to_install(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pypdf", None)  # import de um módulo `None` levanta ImportError

    with pytest.raises(DocumentError) as raised:
        extract_text(make_pdf("x"), "contrato.pdf")

    assert str(raised.value) == PDF_INSTALL_HINT and '".[agente]"' in PDF_INSTALL_HINT


def test_an_unknown_extension_lists_what_is_accepted():
    with pytest.raises(DocumentError, match=r"\.exe") as raised:
        extract_text(b"MZ", "programa.exe")

    assert ".docx" in str(raised.value)


def test_a_new_format_enters_by_registering_an_extractor_not_by_touching_the_function():
    registry = {**EXTRACTORS, ".fake": lambda data: data.decode().upper()}

    assert extract_text(b"abc", "x.fake", registry) == "ABC"
    assert ".pdf" in EXTRACTORS


def test_tidy_text_unifies_line_breaks_drops_nul_and_collapses_blank_runs():
    assert tidy_text("a\r\nb\rc\x00d\n\n\n\n\ne  ") == "a\nb\ncd\n\ne"


# ---------- corte ----------


def test_a_text_that_fits_is_not_cut():
    assert cut_text("curto", 100) == ("curto", False)


def test_a_cut_prefers_the_end_of_a_paragraph_near_the_limit():
    text = "A" * 80 + "\n\n" + "B" * 40

    cut, truncated = cut_text(text, 90)

    assert truncated and cut == "A" * 80


def test_a_cut_falls_back_to_the_end_of_a_sentence_then_a_word():
    sentence = "A" * 93 + ". " + "B" * 60
    words = "palavras soltas sem ponto algum até passar do limite escolhido por aqui"

    assert cut_text(sentence, 100) == ("A" * 93 + ".", True)
    cut, truncated = cut_text(words, 32)
    assert truncated and cut == "palavras soltas sem ponto algum"
    assert words[len(cut)] == " "  # cortou entre palavras, não no meio de uma


def test_a_cut_without_any_boundary_cuts_at_the_limit():
    assert cut_text("x" * 100, 40) == ("x" * 40, True)


def test_a_zero_limit_keeps_nothing_but_reports_the_cut():
    assert cut_text("algo", 0) == ("", True)
    assert cut_text("", 0) == ("", False)
