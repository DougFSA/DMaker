"""Importação de roteiro: txt, md e docx viram capítulos; as marcas de formatação saem do texto."""

from __future__ import annotations

import io
import zipfile

import pytest

from dmaker.voice.manuscript import (
    Chapter,
    chapters_from_docx,
    chapters_from_markdown,
    chapters_from_text,
    parse_manuscript,
    strip_formatting,
    title_from_filename,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(
    paragraphs: list[tuple[str, str | None, bool]], style_names: dict[str, str] | None = None
) -> bytes:
    """.docx mínimo: (texto, id do estilo, item de lista) por parágrafo e a tabela de nomes de estilo."""
    body = []
    for text, style, in_list in paragraphs:
        properties = ""
        if style:
            properties += f'<w:pStyle w:val="{style}"/>'
        if in_list:
            properties += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        runs = "".join(f'<w:r><w:t xml:space="preserve">{part}</w:t></w:r>' for part in text.split("|"))
        body.append(f"<w:p><w:pPr>{properties}</w:pPr>{runs}</w:p>")
    document = f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>'
    styles = ""
    if style_names:
        entries = "".join(
            f'<w:style w:styleId="{sid}"><w:name w:val="{name}"/></w:style>'
            for sid, name in style_names.items()
        )
        styles = f'<w:styles xmlns:w="{W}">{entries}</w:styles>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        if styles:
            archive.writestr("word/styles.xml", styles)
    return buffer.getvalue()


# ---------- texto puro ----------


def test_text_without_markers_is_one_chapter_named_after_the_default_title():
    chapters = chapters_from_text("Primeiro parágrafo.\n\nSegundo parágrafo.", "Meu roteiro")
    assert chapters == [Chapter("Meu roteiro", "Primeiro parágrafo.\n\nSegundo parágrafo.")]


def test_text_chapters_open_with_hash_or_capitulo_or_parte_followed_by_a_number():
    text = (
        "Antes de tudo.\n\n# Começo\nAbertura.\n\nCapítulo 2: O meio\nMeio da história.\n\n"
        "PARTE III\nFim.\n\nParte iniciada sem número não abre capítulo.\n\n"
        "Capítulo 4 mostra que isso é uma frase de corpo e não um título porque passa de cento e vinte "
        "caracteres de comprimento, como qualquer frase corrida normal."
    )
    chapters = chapters_from_text(text)
    assert [c.title for c in chapters] == ["Introdução", "Começo", "Capítulo 2: O meio", "PARTE III"]
    assert chapters[0].text == "Antes de tudo."
    assert "Parte iniciada sem número" in chapters[3].text
    assert "frase de corpo" in chapters[3].text  # a linha longa ficou no texto, não virou capítulo


def test_text_ignores_chapters_without_text_and_accepts_roman_numerals():
    chapters = chapters_from_text("Capítulo I\n\nCapítulo II\nTexto do segundo.")
    assert chapters == [Chapter("Capítulo II", "Texto do segundo.")]


def test_text_with_cp1252_bytes_is_decoded_by_parse_manuscript():
    data = "# Ação\nCoração e emoção.".encode("cp1252")
    assert parse_manuscript(data, "livro.txt") == [Chapter("Ação", "Coração e emoção.")]


# ---------- Markdown ----------


def test_markdown_h1_and_h2_open_chapters_and_deeper_headings_become_sentences():
    text = "# Livro\n\n## Um\nTexto um.\n\n### Detalhe\nMais texto.\n\n## Dois\nTexto dois."
    chapters = chapters_from_markdown(text)
    assert [c.title for c in chapters] == ["Um", "Dois"]
    assert chapters[0].text == "Texto um.\n\nDetalhe.\n\nMais texto."


def test_markdown_formatting_is_removed():
    text = (
        "## Cap\n**Negrito** e *itálico* e __outro__ e `código` e [um link](https://x.com/a_b) "
        "e ![figura](f.png) e snake_case_fica.\n\n- primeiro\n- segundo.\n1. terceiro\n\n> citação\n\n---\n\n"
        "```\nnão narrar isto\n```\n\n| a | b |\n|---|---|\n| c | d |"
    )
    (chapter,) = chapters_from_markdown(text)
    assert chapter.text == (
        "Negrito e itálico e outro e código e um link e e snake_case_fica.\n\n"
        "primeiro. segundo. terceiro.\n\ncitação\n\na, b.\n\nc, d."
    )


def test_markdown_keeps_pronunciation_and_pause_markers_for_the_narration():
    (chapter,) = chapters_from_markdown("# T\nFale [[DMaker|Di Meiker]] [pausa 1.2] agora.")
    assert chapter.text == "Fale [[DMaker|Di Meiker]] [pausa 1.2] agora."


def test_strip_formatting_leaves_plain_text_alone():
    assert strip_formatting("Texto  normal,\ncom   espaços.") == "Texto normal, com espaços."
    assert strip_formatting("5 * 3 * 2 e a_b_c") == "5 * 3 * 2 e a_b_c"


# ---------- Word ----------


def test_docx_heading_styles_by_name_open_chapters():
    data = make_docx(
        [
            ("Meu Livro", "Title", False),
            ("Abertura|, em duas partes.", None, False),
            ("O começo", "Ttulo1", False),
            ("Era uma vez.", None, False),
            ("Subtítulo", "Ttulo3", False),
            ("Primeiro item", None, True),
            ("O fim", "Heading2", False),
            ("Acabou.", None, False),
        ],
        {"Title": "Title", "Ttulo1": "heading 1", "Ttulo3": "heading 3", "Heading2": "Heading 2"},
    )
    chapters = chapters_from_docx(data)
    assert [c.title for c in chapters] == ["Meu Livro", "O começo", "O fim"]
    assert chapters[0].text == "Abertura, em duas partes."
    assert chapters[1].text == "Era uma vez.\n\nSubtítulo\n\nPrimeiro item."
    assert chapters[2].text == "Acabou."


def test_docx_without_a_styles_part_falls_back_to_the_style_id():
    data = make_docx([("Um", "Heading1", False), ("Texto.", None, False)])
    assert chapters_from_docx(data) == [Chapter("Um", "Texto.")]


def test_docx_that_is_not_a_zip_is_reported_in_portuguese():
    with pytest.raises(ValueError, match="Não consegui abrir o .docx"):
        parse_manuscript(b"isso nao e um docx", "roteiro.docx")


# ---------- despacho por extensão ----------


def test_parse_manuscript_picks_the_reader_by_extension_and_names_untitled_scripts_after_the_file():
    assert parse_manuscript(b"Texto simples.", "manual_de_voz.txt") == [
        Chapter("manual de voz", "Texto simples.")
    ]
    assert parse_manuscript(b"# A\ntexto", "x.md")[0].title == "A"
    assert title_from_filename("pasta/meu-livro_final.docx") == "meu livro final"


def test_parse_manuscript_rejects_unknown_formats_and_empty_scripts():
    with pytest.raises(ValueError, match="não suportado"):
        parse_manuscript(b"x", "roteiro.pdf")
    with pytest.raises(ValueError, match="não tem texto"):
        parse_manuscript(b"   \n\n  ", "vazio.txt")


def test_chapter_title_may_be_followed_by_a_dash_or_a_colon():
    text = "Capítulo 1 — O começo\nTexto um.\n\nCapítulo 2 – O fim\nTexto dois.\n\nCapítulo 3: Epílogo\nTexto três."
    assert [c.title for c in chapters_from_text(text)] == [
        "Capítulo 1 — O começo",
        "Capítulo 2 – O fim",
        "Capítulo 3: Epílogo",
    ]
