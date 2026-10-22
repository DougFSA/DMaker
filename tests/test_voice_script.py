"""Roteiro de narração: divisão em falas, pausas e normalização para leitura em voz alta."""

from __future__ import annotations

import pytest

from dmaker.voice.script import (
    Utterance,
    clean_text,
    merge_short_sentences,
    normalize_for_speech,
    parse_script,
    split_sentences,
)

needs_num2words = pytest.importorskip("num2words")


def test_splits_sentences_with_pauses_and_no_trailing_pause():
    utterances = parse_script(
        "Olá, tudo bem com você hoje? Hoje vamos falar de vídeo! Vamos lá, começar agora."
    )
    assert [u.text for u in utterances] == [
        "Olá, tudo bem com você hoje?",
        "Hoje vamos falar de vídeo!",
        "Vamos lá, começar agora.",
    ]
    assert [u.pause_after for u in utterances] == [0.35, 0.35, 0.0]


def test_paragraph_break_gets_longer_pause():
    utterances = parse_script(
        "Primeira frase bem completa. Segunda frase também completa.\n\nTerceira parte do texto."
    )
    assert [u.pause_after for u in utterances] == [0.35, 0.7, 0.0]


def test_single_newline_does_not_split_a_sentence():
    assert [u.text for u in parse_script("uma frase\nquebrada na linha.")] == ["uma frase quebrada na linha."]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("O Dr. Silva chegou. A Sra. Lima saiu.", ["O Dr. Silva chegou.", "A Sra. Lima saiu."]),
        (
            "Use cores vivas, ex. azul e verde. Depois exporte.",
            ["Use cores vivas, ex. azul e verde.", "Depois exporte."],
        ),
        ("Compre mesas, cadeiras, etc. Depois pague.", ["Compre mesas, cadeiras, etc.", "Depois pague."]),
        ("Pague etc. e tal.", ["Pague etc. e tal."]),
        ("Fale com J. Almeida hoje.", ["Fale com J. Almeida hoje."]),
        ("Custa R$ 19,90. Aproveite.", ["Custa R$ 19,90.", "Aproveite."]),
        ('Ele disse "vamos". Ela foi.', ['Ele disse "vamos".', "Ela foi."]),
    ],
)
def test_brazilian_abbreviations_do_not_end_sentences(text, expected):
    assert split_sentences(text) == expected


def test_long_sentence_is_split_at_commas_within_limit():
    sentence = ", ".join(f"item número {n} da lista" for n in range(1, 13)) + "."
    utterances = parse_script(sentence, max_chars=80)
    assert len(utterances) > 1
    assert all(len(u.text) <= 80 for u in utterances)
    assert " ".join(u.text for u in utterances) == sentence
    assert utterances[0].pause_after == 0.12  # respiro curto dentro da frase
    assert utterances[-1].pause_after == 0.0


def test_sentence_without_punctuation_falls_back_to_words():
    utterances = parse_script("palavra " * 40, max_chars=50)
    assert all(len(u.text) <= 50 for u in utterances) and len(utterances) > 1


@pytest.mark.parametrize("marker", ["[pausa 1.2]", "[pausa 1,2]", "[Pausa 1.2s]"])
def test_explicit_pause_marker_replaces_natural_pause(marker):
    utterances = parse_script(f"Antes. {marker} Depois.")
    assert utterances == [Utterance("Antes.", 1.2), Utterance("Depois.", 0.0)]


def test_pause_marker_without_previous_speech_is_ignored():
    assert parse_script("[pausa 2] Começo.") == [Utterance("Começo.", 0.0)]


def test_empty_script_has_no_utterances():
    assert parse_script("  \n\n ") == []


def test_max_chars_too_small_is_rejected():
    with pytest.raises(ValueError):
        parse_script("Oi.", max_chars=5)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("R$ 19,90", "dezenove reais e noventa centavos"),
        ("R$ 1,00", "um real"),
        ("R$ 1.500", "mil e quinhentos reais"),
        ("R$ 0,50", "cinquenta centavos"),
        ("R$ 2.000.000", "dois milhões de reais"),
        ("50%", "cinquenta por cento"),
        ("3,5%", "três vírgula cinco por cento"),
        ("2026", "dois mil e vinte e seis"),
        ("3,5", "três vírgula cinco"),
        ("0,05", "zero vírgula zero cinco"),
        ("1.250 pessoas", "mil duzentos e cinquenta pessoas"),
    ],
)
def test_normalize_numbers_money_and_percent(text, expected):
    assert normalize_for_speech(text) == expected


def test_normalize_inside_sentence_and_collapses_spaces():
    spoken = normalize_for_speech("Custa   R$ 19,90  com   50% de desconto em 2026.")
    assert spoken == (
        "Custa dezenove reais e noventa centavos com cinquenta por cento de desconto "
        "em dois mil e vinte e seis."
    )


def test_normalize_other_language_only_collapses_spaces():
    assert normalize_for_speech("It costs   50%", language="en") == "It costs 50%"


def test_short_sentences_join_the_next_one():
    assert parse_script("Sim. Claro que podemos começar agora mesmo. Ok.") == [
        Utterance("Sim. Claro que podemos começar agora mesmo. Ok.", 0.0)
    ]


def test_merge_short_sentences_keeps_long_ones_apart():
    assert merge_short_sentences(["Esta frase tem tamanho bom.", "Outra frase com tamanho bom."]) == [
        "Esta frase tem tamanho bom.",
        "Outra frase com tamanho bom.",
    ]
    assert merge_short_sentences(["Oi.", "Tudo bem com você hoje?"]) == ["Oi. Tudo bem com você hoje?"]
    assert merge_short_sentences(["Esta frase tem tamanho bom.", "Ok."]) == [
        "Esta frase tem tamanho bom. Ok."
    ]
    assert merge_short_sentences(["Oi."]) == ["Oi."]


def test_default_chunk_limit_follows_voicestudio_800_chars():
    sentence = ", ".join(f"item número {n} da lista" for n in range(1, 30)) + "."
    assert 220 < len(sentence) < 800
    assert len(parse_script(sentence)) == 1


def test_clean_text_removes_invisible_controls_entities_and_punctuation_floods():
    dirty = "Olá\u200b mundo&nbsp;&amp; tudo&quot;bem&quot;!!!!!!! E....... \x07fim"
    assert clean_text(dirty) == 'Olá mundo & tudo"bem"!!! E... fim'
    assert clean_text("a\n\n\n\n\nb") == "a\n\nb"
    assert clean_text(clean_text(dirty)) == clean_text(dirty)


def test_parse_script_cleans_the_text_before_splitting():
    assert parse_script("Uma frase de teste completa\u200b!!!!!!") == [
        Utterance("Uma frase de teste completa!!!", 0.0)
    ]
