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
    MAX_VIDEO_STRETCH,
    MIN_GAP_SECONDS,
    TRUNCATION_TOLERANCE_SECONDS,
    Slot,
    natural_seconds,
    place_speech,
    plan_fit,
    plan_video_fit,
    plan_voice_fit,
    segment_words,
    slot_plan,
    subtitle_cues,
)
from dmaker.voice.speech_edit import MAX_TEMPO


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


# ---------- desfecho no modo voz (o de sempre) ----------


def test_voice_fit_never_touches_the_picture_and_keeps_the_known_verdicts():
    slot = Slot(0, 0.0, 2.0, 0.5)
    fits = plan_voice_fit(1.8, plan_fit(1.8, slot))
    assert (fits.status, fits.tempo, fits.stretch, fits.max_seconds) == ("fits", 1.0, 1.0, None)
    squeezed = plan_voice_fit(2.9, plan_fit(2.9, slot))
    assert squeezed.status == "squeezed" and squeezed.tempo > 1.0 and squeezed.stretch == 1.0
    assert squeezed.message.startswith("comprimida") or squeezed.message.startswith("acelerada")


def test_voice_fit_cuts_and_warns_when_the_tempo_cannot_save_it():
    slot = Slot(0, 0.0, 2.0, 0.0)
    outcome = plan_voice_fit(4.0, plan_fit(4.0, slot))
    assert outcome.status == "overflow" and outcome.warns and outcome.stretch == 1.0
    assert outcome.max_seconds == pytest.approx(slot.capacity) and "encurte a tradução" in outcome.message


# ---------- desfecho nos modos vídeo e misto ----------

ROOMY = Slot(0, 10.0, 14.0, 1.0)  # 4 s de fala original e 1 s de pausa para avançar: capacidade de 5 s
TIGHT = Slot(0, 10.0, 14.0, 0.0)


@pytest.mark.parametrize("mode", ["video", "misto"])
def test_a_speech_that_fits_is_never_stretched(mode):
    inside = plan_video_fit(3.8, ROOMY, mode)
    assert (inside.status, inside.stretch, inside.tempo, inside.max_seconds) == ("fits", 1.0, 1.0, None)
    assert inside.played_seconds == pytest.approx(3.8)


@pytest.mark.parametrize("mode", ["video", "misto"])
def test_a_speech_that_advances_into_the_pause_is_not_stretched_either(mode):
    advancing = plan_video_fit(4.8, ROOMY, mode)
    assert advancing.status == "advances" and advancing.stretch == 1.0 and "0.8 s" in advancing.message


def test_video_mode_keeps_the_voice_natural_and_stretches_only_what_the_pause_cannot_absorb():
    outcome = plan_video_fit(6.0, ROOMY, "video")
    # a voz toca 6 s: 1 s cabe na pausa seguinte, então a imagem de 4 s precisa durar 5 s
    assert outcome.status == "stretched" and not outcome.warns
    assert outcome.tempo == 1.0 and outcome.stretch == pytest.approx(5.0 / 4.0)
    assert outcome.played_seconds == pytest.approx(6.0) and outcome.max_seconds is None
    assert "1.25x" in outcome.message and "+1.0 s" in outcome.message


def test_video_mode_without_room_stretches_to_the_whole_speech():
    outcome = plan_video_fit(5.0, TIGHT, "video")
    assert outcome.stretch == pytest.approx(1.25) and outcome.tempo == 1.0


def test_video_mode_stretches_exactly_up_to_the_limit_and_warns_beyond_it():
    at_limit = plan_video_fit(4.0 * MAX_VIDEO_STRETCH, TIGHT, "video")
    assert at_limit.status == "stretched" and at_limit.stretch == pytest.approx(MAX_VIDEO_STRETCH)
    beyond = plan_video_fit(4.0 * MAX_VIDEO_STRETCH + 1.0, TIGHT, "video")
    assert beyond.status == "overflow" and beyond.warns and beyond.stretch == MAX_VIDEO_STRETCH
    assert beyond.tempo == 1.0  # nem aí a voz acelera: o fim é cortado e o relatório avisa
    assert beyond.max_seconds == pytest.approx(4.0 * MAX_VIDEO_STRETCH)
    assert "encurte a tradução" in beyond.message and "1.30x" in beyond.message


def test_a_negligible_excess_is_rounding_not_a_reason_to_stretch():
    assert plan_video_fit(5.0 + TRUNCATION_TOLERANCE_SECONDS / 2, ROOMY, "video").stretch == 1.0


def test_mixed_mode_speeds_up_the_voice_first_and_stretches_only_the_rest():
    # 5,75 s numa capacidade de 5 s: 1,15x resolve, sem esticar nada
    only_tempo = plan_video_fit(5.75, ROOMY, "misto")
    assert only_tempo.status == "squeezed" and only_tempo.stretch == 1.0
    assert only_tempo.tempo == pytest.approx(1.15)
    # 6,8 s: a voz acelera ao teto (1,15x -> 5,91 s) e a imagem estica o que a pausa não absorve
    outcome = plan_video_fit(6.8, ROOMY, "misto")
    heard = 6.8 / MAX_TEMPO
    assert outcome.status == "stretched" and outcome.tempo == pytest.approx(MAX_TEMPO)
    assert outcome.played_seconds == pytest.approx(heard)
    assert outcome.stretch == pytest.approx((heard - 1.0) / 4.0)
    assert outcome.message.startswith("acelerada 1.15x e vídeo esticado")


def test_mixed_mode_stretches_less_than_video_mode_for_the_same_speech():
    assert plan_video_fit(7.0, ROOMY, "misto").stretch < plan_video_fit(7.0, ROOMY, "video").stretch


def test_mixed_mode_cuts_beyond_the_limit_without_accelerating_more_than_the_tempo_cap():
    outcome = plan_video_fit(12.0, ROOMY, "misto")
    assert outcome.status == "overflow" and outcome.tempo == pytest.approx(MAX_TEMPO)
    assert outcome.stretch == MAX_VIDEO_STRETCH
    assert outcome.max_seconds == pytest.approx(4.0 * MAX_VIDEO_STRETCH + 1.0)


def test_the_stretch_limit_is_one_point_three():
    assert MAX_VIDEO_STRETCH == 1.3


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
