"""Planejamento da dublagem: frases, espaço de cada fala, regra de velocidade e legenda. Tudo puro."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from dmaker.text.captions import Word
from dmaker.voice.dub_plan import (
    MAX_ADVANCE_SECONDS,
    MAX_MODEL_SQUEEZE,
    MAX_SEGMENT_SECONDS,
    MAX_TOTAL_SQUEEZE,
    MIN_GAP_SECONDS,
    Slot,
    natural_seconds,
    place_speech,
    plan_fit,
    segment_words,
    slot_plan,
    subtitle_cues,
)


def spoken(text: str, start: float, per_word: float = 0.4, gap: float = 0.05) -> list[Word]:
    """Palavras igualmente espaçadas a partir de `start` (a pontuação fica colada na palavra, como no Whisper)."""
    words, cursor = [], start
    for token in text.split():
        words.append(Word(cursor, cursor + per_word, token, 0.9))
        cursor += per_word + gap
    return words


@dataclass
class Span:
    start: float
    end: float


# ---------- segmentação ----------


def test_sentence_end_closes_a_phrase():
    words = spoken("Olá pessoal, hoje vamos falar. Depois vem o resto da conversa.", 1.0)
    phrases = segment_words(words)
    assert [p.text for p in phrases] == [
        "Olá pessoal, hoje vamos falar.",
        "Depois vem o resto da conversa.",
    ]
    assert phrases[0].start == pytest.approx(1.0)
    assert phrases[0].end == pytest.approx(words[4].end)


def test_a_breath_pause_closes_a_phrase_without_punctuation():
    first = spoken("a gente se casou ontem", 0.0)
    second = spoken("e foi lindo demais", first[-1].end + 0.8)
    phrases = segment_words(first + second)
    assert [p.text for p in phrases] == ["a gente se casou ontem", "e foi lindo demais"]


def test_a_short_pause_does_not_split():
    first = spoken("a gente se casou ontem", 0.0)
    second = spoken("e foi lindo demais", first[-1].end + 0.2)
    assert len(segment_words(first + second)) == 1


def test_a_long_run_is_split_at_the_latest_comma_and_stays_under_the_maximum():
    tokens = [f"p{i}" for i in range(1, 31)]
    tokens[11] += ","  # vírgula na 12ª palavra
    tokens[19] += ","  # e na 20ª: a mais tardia deixa o primeiro pedaço mais cheio
    phrases = segment_words(spoken(" ".join(tokens), 0.0, per_word=0.5))
    assert len(phrases) >= 2
    assert phrases[0].text.endswith("p20,")
    assert all(p.end - p.start <= MAX_SEGMENT_SECONDS + 1e-6 for p in phrases)
    assert " ".join(p.text for p in phrases) == " ".join(tokens)


def test_phrases_never_overlap_and_keep_every_word_in_order():
    words = spoken(
        "Primeira frase aqui. Segunda frase mais comprida que a primeira, com vírgula. Terceira.", 0.0
    )
    phrases = segment_words(words)
    assert " ".join(p.text for p in phrases) == " ".join(w.text for w in words)
    assert all(a.end <= b.start for a, b in zip(phrases, phrases[1:], strict=False))


def test_a_fragment_shorter_than_the_minimum_joins_the_neighbour():
    words = spoken("Isto é uma frase completa e longa.", 0.0) + spoken("Sim.", 3.6, per_word=0.3)
    phrases = segment_words(words)
    assert len(phrases) == 1 and phrases[0].text.endswith("Sim.")


def test_a_fragment_far_from_any_neighbour_stays_alone():
    words = spoken("Isto é uma frase completa e longa.", 0.0) + spoken("Sim.", 9.0, per_word=0.3)
    assert [p.text for p in segment_words(words)][-1] == "Sim."


def test_no_words_no_phrases_and_unsorted_words_are_ordered():
    assert segment_words([]) == []
    words = spoken("Uma frase fora de ordem aqui.", 0.0)
    assert segment_words(list(reversed(words)))[0].text == "Uma frase fora de ordem aqui."


# ---------- espaço de cada fala ----------


def test_slot_room_is_the_pause_minus_a_breathing_gap():
    slots = slot_plan([Span(0.0, 2.0), Span(3.0, 5.0)], total=20.0)
    assert slots[0].room == pytest.approx(1.0 - MIN_GAP_SECONDS)
    assert slots[0].capacity == pytest.approx(2.0 + 1.0 - MIN_GAP_SECONDS)
    # a última pode avançar até o fim do arquivo, mas nunca além do máximo
    assert slots[1].room == pytest.approx(MAX_ADVANCE_SECONDS)


def test_slot_room_is_never_negative_when_phrases_are_glued():
    slots = slot_plan([Span(0.0, 2.0), Span(2.05, 4.0)], total=4.0)
    assert slots[0].room == 0.0 and slots[1].room == 0.0


# ---------- duração natural ----------


def test_natural_seconds_scales_with_letters_and_the_language_rate():
    same_text = natural_seconds("abcdefghij", "abcdefghij", 2.0, "pt", "pt")
    assert same_text == pytest.approx(2.0)
    longer = natural_seconds("abcdefghij", "abcdefghijabcdefghij", 2.0, "pt", "pt")
    assert longer == pytest.approx(4.0)
    # o inglês gasta menos letras por segundo: as mesmas letras levam mais tempo
    assert natural_seconds("abcdefghij", "abcdefghij", 2.0, "pt", "en") > 2.0


def test_natural_seconds_handles_empty_text_and_missing_source():
    assert natural_seconds("olá", "", 2.0, "pt", "en") == 0.0
    assert natural_seconds("", "hello there my friend", 2.0, "pt", "en") > 0.3


# ---------- regra de velocidade ----------


def test_fits_when_the_translation_is_not_longer_than_the_original():
    plan = plan_fit(1.8, Slot(0, 0.0, 2.0, 0.5))
    assert plan.status == "fits" and plan.request_seconds == pytest.approx(1.8) and not plan.warns


def test_advances_into_the_pause_before_squeezing():
    plan = plan_fit(2.4, Slot(0, 0.0, 2.0, 0.5))
    assert plan.status == "advances" and plan.request_seconds == pytest.approx(2.4)
    assert "0.4 s" in plan.message


def test_squeezed_asks_the_model_for_a_faster_speech_up_to_its_limit():
    slot = Slot(0, 0.0, 2.0, 0.0)
    plan = plan_fit(2.4, slot)  # 1,2x o espaço: dentro do limite do modelo
    assert plan.status == "squeezed" and plan.request_seconds == pytest.approx(2.0)
    beyond_model = plan_fit(2.6, slot)  # 1,3x: o modelo faz 1,25x, o resto fica para o atempo
    assert beyond_model.status == "squeezed"
    assert beyond_model.request_seconds == pytest.approx(2.6 / MAX_MODEL_SQUEEZE)


def test_overflow_warns_when_not_even_both_squeezes_fit():
    slot = Slot(0, 0.0, 2.0, 0.0)
    plan = plan_fit(2.0 * MAX_TOTAL_SQUEEZE * 1.1, slot)
    assert plan.status == "overflow" and plan.warns and "encurte a tradução" in plan.message
    assert plan.request_seconds == pytest.approx(plan.natural_seconds / MAX_MODEL_SQUEEZE)


def test_place_speech_keeps_a_fitting_speech_untouched():
    placement = place_speech(1.9, 2.0)
    assert (
        placement.tempo == 1.0 and not placement.truncated and placement.played_seconds == pytest.approx(1.9)
    )


def test_place_speech_speeds_up_a_slightly_long_speech():
    placement = place_speech(2.2, 2.0)
    assert placement.tempo == pytest.approx(1.1) and not placement.truncated
    assert placement.played_seconds == pytest.approx(2.0)


def test_place_speech_truncates_what_even_the_tempo_cannot_fit():
    placement = place_speech(3.0, 2.0)
    assert placement.tempo == pytest.approx(1.15) and placement.truncated
    assert placement.played_seconds == pytest.approx(2.0)


# ---------- legenda ----------


def test_short_text_is_one_cue_over_the_whole_span():
    assert subtitle_cues("Hello there, my friend.", 4.0, 6.0) == [(4.0, 6.0, "Hello there, my friend.")]


def test_long_text_is_split_in_two_line_cues_that_tile_the_span():
    text = (
        "This is a much longer sentence that certainly will not fit in a single subtitle line on the screen."
    )
    cues = subtitle_cues(text, 10.0, 16.0)
    assert len(cues) >= 2
    assert cues[0][0] == 10.0 and cues[-1][1] == pytest.approx(16.0)
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(cues, cues[1:], strict=False))
    assert all(len(line) <= 42 for _, _, chunk in cues for line in chunk.split("\n"))
    assert all(chunk.count("\n") <= 1 for _, _, chunk in cues)
    assert " ".join(chunk.replace("\n", " ") for _, _, chunk in cues) == text


def test_empty_text_has_no_cues():
    assert subtitle_cues("   ", 0.0, 2.0) == []
