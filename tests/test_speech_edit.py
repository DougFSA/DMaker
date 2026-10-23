"""Regravação de fala, parte pura: achar o trecho, estender até o fôlego, planejar a emenda e medir níveis."""

from __future__ import annotations

import numpy as np
import pytest

from dmaker.text.captions import Word
from dmaker.voice.levels import active_rms, frame_rms, gain_to_match_db, quietest_time
from dmaker.voice.reference import choose_reference_span
from dmaker.voice.speech_edit import (
    CROSSFADE_SECONDS,
    compose_text,
    expand_to_breath_group,
    find_phrase_indices,
    fit_tempo,
    isolation_window,
    locate_phrase,
    natural_duration,
    pause_room,
    plan_splice,
    text_between,
)


def speech(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(start, end, text) for text, start, end in items]


# "Hoje é o casamento de João e Maria" com uma pausa de 0,6 s depois de "casamento," e outra depois de "Maria."
SENTENCE = speech(
    ("Hoje", 10.0, 10.3),
    ("é", 10.3, 10.4),
    ("o", 10.4, 10.5),
    ("casamento,", 10.5, 11.1),
    ("de", 11.7, 11.8),
    ("João", 11.8, 12.2),
    ("e", 12.2, 12.3),
    ("Maria.", 12.3, 12.9),
    ("Depois", 14.0, 14.4),
    ("vem", 14.4, 14.6),
    ("a", 14.6, 14.7),
    ("festa", 14.7, 15.2),
)


# ---------- locate_phrase ----------


def test_locate_phrase_ignores_accents_case_and_punctuation():
    assert locate_phrase(SENTENCE, "joao") == (11.8, 12.2)
    assert locate_phrase(SENTENCE, "CASAMENTO de joão") == (10.5, 12.2)
    assert locate_phrase(SENTENCE, "maria") == (12.3, 12.9)


def test_locate_phrase_not_found_suggests_similar_text_in_portuguese():
    with pytest.raises(ValueError) as error:
        locate_phrase(SENTENCE, "casamentos")
    message = str(error.value)
    assert 'Não achei "casamentos"' in message
    assert "Trechos parecidos" in message and "casamento," in message and "10.5 s" in message
    assert "dmaker voice words" in message


def test_locate_phrase_without_a_close_match_still_explains():
    with pytest.raises(ValueError, match="Não achei") as error:
        locate_phrase(SENTENCE, "zzzzzz")
    assert "Trechos parecidos" not in str(error.value)


def test_locate_phrase_ambiguous_lists_the_times_and_occurrence_chooses():
    twice = speech(("a", 1.0, 1.2), ("casa", 1.2, 1.6), ("e", 1.6, 1.7), ("casa", 5.0, 5.4))
    with pytest.raises(ValueError, match=r"aparece 2 vezes \(1\.2 s, 5\.0 s\)"):
        locate_phrase(twice, "casa")
    assert locate_phrase(twice, "casa", occurrence=1) == (1.2, 1.6)
    assert locate_phrase(twice, "casa", occurrence=2) == (5.0, 5.4)
    with pytest.raises(ValueError, match="ocorrência 3 não existe"):
        locate_phrase(twice, "casa", occurrence=3)


def test_locate_phrase_rejects_an_empty_search():
    with pytest.raises(ValueError, match="Informe o texto"):
        locate_phrase(SENTENCE, "  ,. ")


def test_find_phrase_indices_maps_tokens_back_to_words():
    split = speech(("d'água", 0.0, 0.5), ("fria", 0.5, 1.0))
    assert find_phrase_indices(split, "agua fria") == [(0, 1)]


# ---------- grupo de fôlego ----------


def test_expand_stops_at_the_natural_pauses():
    # João (11.8 a 12.2) fica entre a pausa depois de "casamento," e a depois de "Maria."
    start, end = expand_to_breath_group(SENTENCE, 11.8, 12.2)
    assert (start, end) == (11.7, 12.9)


def test_expand_a_phrase_with_no_internal_pause_takes_the_whole_breath_group():
    assert expand_to_breath_group(SENTENCE, 10.5, 11.1) == (10.0, 11.1)


def test_expand_is_limited_by_the_context_cap():
    continuous = [Word(i * 0.5, i * 0.5 + 0.5, f"p{i}") for i in range(30)]
    start, end = expand_to_breath_group(continuous, 7.0, 7.5, max_context=2.0)
    assert (start, end) == (5.0, 9.5)


def test_expand_without_words_in_the_interval_returns_it_unchanged():
    assert expand_to_breath_group(SENTENCE, 13.0, 13.5) == (13.0, 13.5)


def test_pause_room_measures_the_silence_around_the_group():
    assert pause_room(SENTENCE, 11.7, 12.9, 60.0) == pytest.approx((0.6, 1.1))
    assert pause_room(SENTENCE, 10.0, 11.1, 60.0) == pytest.approx((10.0, 0.6))
    assert pause_room(SENTENCE, 14.0, 15.2, 16.0) == pytest.approx((1.1, 0.8))


def test_compose_text_puts_the_new_text_between_the_group_words():
    edit_start, edit_end = locate_phrase(SENTENCE, "joão")
    from dmaker.voice.speech_edit import SpeechEdit

    edit = SpeechEdit(edit_start, edit_end, "Pedro")
    assert compose_text(SENTENCE, edit, 11.7, 12.9) == "de Pedro e Maria."
    assert text_between(SENTENCE, 11.7, 12.9) == "de João e Maria."


# ---------- janela de isolamento ----------


def test_isolation_window_short_files_are_taken_whole():
    assert isolation_window(20.0, 22.0, 70.0) == (0.0, 70.0)


def test_isolation_window_is_aligned_to_the_grid_and_covers_the_edit():
    start, end = isolation_window(3915.0, 3917.0, 7000.0)
    assert start % 15 == 0 and end - start == 60.0
    assert start <= 3915.0 - 6 and end >= 3917.0 + 6


def test_isolation_window_neighbouring_edits_share_the_same_window():
    assert isolation_window(3915.0, 3917.0, 7000.0) == isolation_window(3920.0, 3922.0, 7000.0)


def test_isolation_window_clamps_at_the_edges_of_the_file():
    assert isolation_window(2.0, 3.0, 600.0)[0] == 0.0
    start, end = isolation_window(595.0, 597.0, 600.0)
    assert end == 600.0 and start <= 595.0 - 6


# ---------- duração e plano ----------


def test_natural_duration_keeps_the_original_inside_the_tolerance():
    assert natural_duration(2.0, "de João e Maria", "de Pedro e Maria") == 2.0  # 12 letras contra 12 (mesmo)
    assert natural_duration(2.0, "de João e Maria", "de Joaquim e Maria") == pytest.approx(2.0 * 15 / 12)
    assert natural_duration(2.0, "", "qualquer") == 2.0


def test_plan_keeps_the_duration_when_the_text_has_the_same_size():
    plan = plan_splice(11.7, 12.9, "de João e Maria", "de Pedro e Maria", 0.6, 1.1)
    assert plan.target_duration == pytest.approx(1.2)
    assert plan.speech_start == pytest.approx(11.7)
    assert plan.region_start == pytest.approx(11.7 - 0.3)
    assert plan.region_end == pytest.approx(12.9 + 0.5)  # meia pausa de 1,1 s, no máximo 0,5 s
    assert "mantida" in plan.rule and not plan.squeezed


def test_plan_stretches_into_the_neighbouring_pauses_when_the_text_is_longer():
    plan = plan_splice(11.7, 12.9, "de João e Maria", "de Joaquim e Maria", 0.6, 1.1)
    assert plan.target_duration > 1.2
    assert plan.speech_start < 11.7  # começa antes do grupo original
    assert plan.speech_start >= plan.region_start + CROSSFADE_SECONDS - 1e-9
    assert plan.speech_start + plan.target_duration <= plan.region_end - CROSSFADE_SECONDS + 1e-9
    assert "esticado" in plan.rule and not plan.squeezed


def test_plan_squeezes_when_even_the_pauses_do_not_fit():
    long_text = "de João Carlos Eduardo Albuquerque Montenegro e Maria"
    plan = plan_splice(11.7, 12.9, "de João e Maria", long_text, 0.3, 0.3)
    assert plan.squeezed and "comprimida" in plan.rule
    usable = (plan.region_end - plan.region_start) - 2 * CROSSFADE_SECONDS
    assert plan.target_duration == pytest.approx(usable)
    assert plan.natural_duration > plan.target_duration


def test_plan_shorter_text_is_centered_and_the_rest_becomes_pause():
    plan = plan_splice(11.7, 12.9, "de João e Maria", "de Ana", 0.6, 1.1)
    assert plan.target_duration < 1.2 and "encurtada" in plan.rule
    assert plan.speech_start == pytest.approx(11.7 + (1.2 - plan.target_duration) / 2)


def test_plan_snaps_the_region_edges_and_keeps_the_speech_inside():
    plan = plan_splice(11.7, 12.9, "a b c", "a b c", 0.6, 1.1, snap=lambda seconds: seconds + 0.02)
    assert plan.region_start == pytest.approx(11.7 - 0.3 + 0.02)
    assert plan.region_end == pytest.approx(12.9 + 0.5 + 0.02)
    assert plan.speech_start >= plan.region_start + CROSSFADE_SECONDS


def test_plan_at_the_start_of_the_file_never_goes_negative():
    plan = plan_splice(0.1, 1.0, "oi", "oi", 0.1, 0.5)
    assert plan.region_start >= 0.0


def test_fit_tempo_only_accelerates_what_does_not_fit():
    assert fit_tempo(1.0, 1.0) == 1.0
    assert fit_tempo(1.01, 1.0) == 1.0  # dentro dos 2% de folga
    assert fit_tempo(1.1, 1.0) == pytest.approx(1.1)
    assert fit_tempo(2.0, 1.0) == 1.15  # teto
    assert fit_tempo(0.5, 1.0) == 1.0


# ---------- referência do falante ----------


def run_of_words(start: float, count: int, step: float = 0.5, text: str = "p") -> list[Word]:
    return [Word(start + i * step, start + (i + 1) * step - 0.05, f"{text}{i}", 0.9) for i in range(count)]


def test_reference_span_avoids_the_part_to_fix_and_prefers_about_eight_seconds():
    words = run_of_words(0.0, 40)  # fala contínua de 0 a 20 s
    span = choose_reference_span(words, 8.0, 10.0)
    assert span is not None
    assert span.end <= 8.0 - 0.2 + 1e-9 or span.start >= 10.0 + 0.2 - 1e-9  # fora do trecho, com folga
    assert 3.0 <= span.duration <= 15.0
    assert abs(span.duration - 8.0) <= 1.5


def test_reference_span_never_crosses_a_long_pause():
    words = run_of_words(0.0, 8) + run_of_words(8.0, 8)  # 4 s de fala, pausa de 0,05... vira 1,5 s abaixo
    gap = [
        Word(
            w.start + 1.5 if w.start >= 4.0 else w.start,
            w.end + 1.5 if w.start >= 4.0 else w.end,
            w.text,
            0.9,
        )
        for w in words
    ]
    span = choose_reference_span(gap, 100.0, 101.0)
    assert span is not None
    assert not (span.start < 4.0 < span.end)


def test_reference_span_returns_none_when_only_short_bursts_remain():
    words = run_of_words(0.0, 3) + run_of_words(20.0, 3)  # 1,4 s de fala por bloco
    assert choose_reference_span(words, 50.0, 51.0) is None


def test_reference_span_text_joins_the_words_of_the_span():
    words = run_of_words(0.0, 10)
    span = choose_reference_span(words, 100.0, 101.0)
    assert span is not None and span.text.startswith("p0 p1")


# ---------- níveis ----------


def tone(seconds: float, amplitude: float, rate: int = 16000, hertz: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * hertz * t)).astype(np.float32)


def test_active_rms_ignores_the_pauses():
    rate = 16000
    audio = np.concatenate([tone(1.0, 0.2), np.zeros(rate * 3, dtype=np.float32), tone(1.0, 0.2)])
    assert active_rms(audio, rate) == pytest.approx(0.2 / np.sqrt(2), rel=0.02)
    assert active_rms(np.zeros(rate, dtype=np.float32), rate) == 0.0
    assert frame_rms(np.zeros(5, dtype=np.float32), rate).size == 0


def test_gain_to_match_is_in_decibels_and_limited():
    assert gain_to_match_db(0.1, 0.2) == pytest.approx(6.02, abs=0.01)
    assert gain_to_match_db(0.2, 0.1) == pytest.approx(-6.02, abs=0.01)
    assert gain_to_match_db(0.001, 0.5) == 9.0
    assert gain_to_match_db(0.0, 0.5) == 0.0


def test_quietest_time_finds_the_valley_between_two_sounds():
    rate = 16000
    audio = np.concatenate([tone(0.5, 0.3), np.zeros(int(0.1 * rate), dtype=np.float32), tone(0.5, 0.3)])
    found = quietest_time(audio, rate, center=0.5, radius=0.2)
    assert 0.5 <= found <= 0.6
    assert quietest_time(audio, rate, center=10.0, radius=0.1) == 10.0  # fora do áudio


def test_quietest_time_prefers_the_point_closest_to_the_center_in_silence():
    rate = 16000
    silence = np.zeros(rate, dtype=np.float32)
    assert quietest_time(silence, rate, center=0.5, radius=0.1) == pytest.approx(0.5, abs=0.011)


def test_compose_text_keeps_the_final_punctuation_of_the_replaced_words():
    from dmaker.voice.speech_edit import SpeechEdit

    start, end = locate_phrase(SENTENCE, "casamento")
    assert compose_text(SENTENCE, SpeechEdit(start, end, "enlace"), 10.0, 11.1) == "Hoje é o enlace,"
    assert compose_text(SENTENCE, SpeechEdit(start, end, "enlace!"), 10.0, 11.1) == "Hoje é o enlace!"
    maria = locate_phrase(SENTENCE, "maria")
    assert compose_text(SENTENCE, SpeechEdit(*maria, "Ana"), 11.7, 12.9) == "de João e Ana."
