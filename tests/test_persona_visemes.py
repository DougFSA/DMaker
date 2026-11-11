"""A boca em português: grafema para visema, tempo e pausas (funções puras, sem áudio nem navegador)."""

from __future__ import annotations

import pytest

from dmaker.persona.mouth import MOUTH_SHAPES, VISEME_TO_MOUTH, mouth_timeline
from dmaker.persona.visemes import (
    VISEMES,
    VisemeSpan,
    build_visemes,
    number_to_words,
    preprocess_text,
    text_to_visemes,
    word_visemes,
)


def sequence(text: str) -> list[str]:
    return text_to_visemes(preprocess_text(text)).visemes


def test_digraphs_ch_lh_nh_rr_and_ss_become_one_viseme_each():
    assert sequence("chave") == ["CH", "aa", "FF", "I"]
    assert sequence("filho") == ["FF", "I", "nn", "U"]
    assert sequence("ninho") == ["nn", "I", "nn", "U"]
    assert sequence("carro") == ["kk", "aa", "RR", "U"]
    assert sequence("passo") == ["PP", "aa", "SS", "U"]


def test_ti_and_di_are_affricates_but_ta_and_da_are_not():
    assert sequence("tia")[0] == "CH"
    assert sequence("dia")[0] == "CH"
    assert sequence("tapa")[0] == "DD"
    assert sequence("cidade") == ["SS", "I", "DD", "aa", "CH", "I"]  # o "de" final também africa


def test_nasal_coda_only_nasalizes_the_vowel_and_the_nasal_diphthongs_have_two_visemes():
    assert sequence("campo") == ["kk", "aa", "PP", "U"]  # o m do "mp" não fecha a boca
    assert sequence("não") == ["nn", "aa", "U"]
    assert sequence("bem") == ["PP", "E", "I"]


def test_silent_h_and_the_silent_u_of_que_and_gue():
    assert sequence("hoje") == ["O", "CH", "I"]  # o h não vira visema
    assert sequence("quem") == ["kk", "E", "I"]  # o u de "que" é mudo
    assert sequence("guia") == ["kk", "I", "aa"]


def test_the_vocalized_l_closes_into_u_at_the_end_of_a_syllable():
    assert sequence("Brasil")[-1] == "U"
    assert sequence("lua")[0] == "nn"


def test_numbers_and_symbols_are_read_in_portuguese():
    assert preprocess_text("R$ 10") == "dez reais"
    assert preprocess_text("10 €") == "dez euros"
    assert number_to_words("21") == "vinte e um"
    assert number_to_words("100") == "cem"
    assert number_to_words("1020") == "mil e vinte"
    assert number_to_words("1230") == "mil duzentos e trinta"
    assert number_to_words("2000000") == "dois milhões"
    assert number_to_words("007") == "zero zero sete"
    assert preprocess_text("50%") == "cinquenta por cento"
    assert preprocess_text("1,5") == "um vírgula cinco"


def test_a_word_spreads_its_visemes_over_its_own_time_without_gaps():
    spans = word_visemes(1.0, 1.6, "casa")
    assert spans[0].start == pytest.approx(1.0) and spans[-1].end == pytest.approx(1.6)
    assert all(a.end == pytest.approx(b.start) for a, b in zip(spans, spans[1:], strict=False))
    assert [s.viseme for s in spans] == ["kk", "aa", "SS", "aa"]


def test_the_timeline_is_continuous_from_zero_to_the_duration_and_closes_the_mouth_in_pauses():
    spans = build_visemes([(0.5, 0.9, "olá"), (1.6, 2.0, "tudo")], duration=3.0)
    assert spans[0] == VisemeSpan(0.0, 0.5, "sil")  # antes da primeira palavra
    assert spans[-1].viseme == "sil" and spans[-1].end == pytest.approx(3.0)
    assert all(a.end == pytest.approx(b.start) for a, b in zip(spans, spans[1:], strict=False))
    pause = [s for s in spans if s.viseme == "sil" and s.start >= 0.9 - 1e-6 and s.end <= 1.6 + 1e-6]
    assert pause and pause[0].end - pause[0].start == pytest.approx(0.7)  # a pausa entre as palavras


def test_a_short_gap_between_words_keeps_the_mouth_open_instead_of_closing_it():
    spans = build_visemes([(0.0, 0.4, "um"), (0.46, 0.9, "dia")], duration=1.0)
    assert not any(s.viseme == "sil" and s.start > 0.0 and s.end < 0.9 for s in spans)


def test_equal_neighbours_merge_and_an_empty_speech_is_all_silence():
    spans = build_visemes([], duration=2.0)
    assert spans == [VisemeSpan(0.0, 2.0, "sil")]
    merged = build_visemes([(0.0, 0.5, "aaa")], duration=0.5)
    assert len(merged) == 1 and merged[0].viseme == "aa"


def test_a_word_past_the_duration_is_cut_and_text_with_no_letters_makes_no_viseme():
    spans = build_visemes([(0.0, 5.0, "casa")], duration=1.0)
    assert spans[-1].end == pytest.approx(1.0)
    assert word_visemes(0.0, 1.0, "...") == []


def test_all_fifteen_visemes_map_to_nine_mouth_shapes():
    assert set(VISEME_TO_MOUTH) == set(VISEMES) and len(VISEMES) == 15
    assert set(VISEME_TO_MOUTH.values()) == set(MOUTH_SHAPES) and len(MOUTH_SHAPES) == 9


def test_the_mouth_timeline_merges_visemes_that_share_a_shape():
    spans = [VisemeSpan(0, 1, "DD"), VisemeSpan(1, 2, "nn"), VisemeSpan(2, 3, "aa"), VisemeSpan(3, 4, "sil")]
    assert mouth_timeline(spans) == [(0, 2, "mid"), (2, 3, "open"), (3, 4, "rest")]
