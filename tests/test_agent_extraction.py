"""O que o pedido já diz: extração pura dos dados do pedido, sem disco e sem modelo."""

from __future__ import annotations

import pytest

from dmaker.agent.extraction import (
    TimeSpan,
    extract_facts,
    find_files,
    find_projects,
    find_quoted,
    find_spans,
    parse_time,
    render_facts,
    slug,
)

PROJECTS = ["meu-video", "aula-01", "aula", "Casamento Ana"]


# ---------- projetos ----------


def test_an_existing_project_named_in_the_request_is_found_ignoring_case_and_accents():
    assert find_projects("Valida o projeto meu-video", PROJECTS) == ("meu-video",)
    assert find_projects("gera uma prévia do MEU-VIDEO", PROJECTS) == ("meu-video",)
    assert find_projects("abre o casamento ana", PROJECTS) == ("Casamento Ana",)


def test_a_project_name_inside_another_word_or_name_does_not_count():
    assert find_projects("renderiza o aula-01", PROJECTS) == ("aula-01",)  # não é "aula"
    assert find_projects("o meu-video-final ficou bom", ["meu-video"]) == ()
    assert find_projects("preciso de um vídeo de aula", PROJECTS) == ("aula",)  # palavra inteira


def test_no_project_means_no_project():
    assert find_projects("Quais templates existem?", PROJECTS) == ()
    assert find_projects("qualquer coisa", []) == ()


# ---------- arquivos ----------


def test_files_are_the_drive_paths_and_bare_media_names_with_the_trailing_punctuation_removed():
    request = "Faz um reel de C:/videos/aula.mp4, e usa a capa logo.png e D:\\musica\\trilha.mp3."

    assert find_files(request) == ("C:/videos/aula.mp4", "D:\\musica\\trilha.mp3", "logo.png")


def test_a_bare_name_already_inside_a_path_is_not_listed_twice():
    assert find_files("o arquivo C:/a/video.mp4 é este") == ("C:/a/video.mp4",)


def test_text_without_files_has_no_files():
    assert find_files("Põe um contador de 0 a 95 mg em cima") == ()


# ---------- tempo ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0:12", 12.0),
        ("1:05", 65.0),
        ("10", 10.0),
        ("1,5", 1.5),
    ],
)
def test_parse_time_reads_clocks_and_plain_numbers(text, expected):
    assert parse_time(text) == expected


def test_minutes_are_converted_when_the_unit_says_so():
    assert parse_time("2", "minutos") == 120.0


@pytest.mark.parametrize(
    ("request_text", "span"),
    [
        ("Corta de 0:12 a 0:20", TimeSpan("range", 12, 20)),
        ("Põe entre 10 e 14 s no projeto", TimeSpan("range", 10, 14)),
        ("dos 1 aos 6 segundos", TimeSpan("range", 1, 6)),
        ("só os primeiros 30 s", TimeSpan("first", 30)),
        ("tira os últimos 5 segundos", TimeSpan("last", 5)),
        ("a partir de 2 min", TimeSpan("from", 120)),
    ],
)
def test_time_spans_in_portuguese(request_text, span):
    assert find_spans(request_text) == (span,)


def test_a_pair_of_numbers_that_is_not_time_is_not_a_span():
    assert find_spans("contador de 0 a 95 mg") == ()
    assert find_spans("de 10 a 20 pessoas") == ()


def test_span_labels_are_readable():
    assert TimeSpan("range", 12, 20).label() == "de 12 s a 20 s"
    assert TimeSpan("first", 30).label() == "os primeiros 30 s"
    assert TimeSpan("last", 5).label() == "os últimos 5 s"
    assert TimeSpan("from", 90).label() == "a partir de 90 s"


# ---------- aspas ----------


def test_quoted_text_in_all_the_quote_styles_without_apostrophes_of_words():
    request = "Troca \"Medi\" por “Medly” e a palavra 'oi' por olá nas águas d'água"

    assert find_quoted(request) == ("Medi", "Medly", "oi")


# ---------- o conjunto ----------


def test_the_acceptance_style_request_with_a_file_and_no_time_says_to_use_the_whole_file():
    facts = extract_facts("Separa a voz da música neste áudio: C:/m/audio.wav", PROJECTS)

    assert facts.files == ("C:/m/audio.wav",) and facts.spans == ()
    assert "Sem trecho de tempo citado: use o arquivo inteiro." in facts.notes
    assert facts.suggested_name == "audio"


def test_a_request_naming_an_existing_project_does_not_suggest_a_new_name():
    facts = extract_facts("Valida o projeto meu-video", PROJECTS)

    assert facts.projects == ("meu-video",) and facts.suggested_name is None and facts.files == ()


def test_language_date_and_couple_are_found():
    facts = extract_facts(
        "Dubla para inglês. Casamento de Ana & Carlos, data 15.08.2026, câmeras em C:/altar e C:/lateral"
    )

    assert facts.languages == (("inglês", "en"),)
    assert facts.dates == ("15.08.2026",) and facts.couples == ("Ana & Carlos",)
    assert facts.files == ("C:/altar", "C:/lateral")


def test_render_facts_is_a_short_block_with_one_line_per_fact():
    block = render_facts(extract_facts("Põe entre 10 e 14 s o contador no projeto meu-video, 'oi'", PROJECTS))

    lines = block.splitlines()
    assert lines[0] == "O que o pedido já diz (use estes dados, não pergunte de novo):"
    assert "- Projeto que já existe: meu-video (use este nome)." in lines
    assert "- Trecho de tempo: de 10 s a 14 s." in lines
    assert '- Entre aspas: "oi"' in lines


def test_a_request_with_nothing_to_extract_adds_no_block():
    assert render_facts(extract_facts("Quais templates de vídeo existem?", PROJECTS)) == ""
    assert extract_facts("Quais templates existem?").empty


def test_the_block_has_no_dashes_in_the_screen_text():
    block = render_facts(extract_facts("Dubla para inglês C:/a/b.mp4 entre 1 e 5 s", PROJECTS))

    assert "—" not in block and "–" not in block


def test_slug_makes_project_names_like_the_dmaker_ones():
    assert slug("Minha Gravação Final.mp4") == "minha-gravacao-final-mp4"
    assert slug("video") == "video"
