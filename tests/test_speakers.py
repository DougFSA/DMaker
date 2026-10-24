"""Quem fala em cada frase e palavra, e a referência de voz de cada falante: contas puras."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dmaker.media.diarization import SpeakerTurn
from dmaker.text.captions import Word
from dmaker.voice.reference import choose_speaker_reference
from dmaker.voice.speakers import (
    assign_speakers,
    label_words,
    overlap_by_speaker,
    speaker_at,
    speaker_names,
    word_speaker,
)

ANA, BIA = "Falante 1", "Falante 2"
TURNS = [
    SpeakerTurn(0.0, 6.0, ANA),
    SpeakerTurn(6.0, 12.0, BIA),
    SpeakerTurn(12.0, 20.0, ANA),
]


def span(start: float, end: float) -> SimpleNamespace:
    return SimpleNamespace(start=start, end=end)


# ---------- frase ----------


def test_a_phrase_takes_the_speaker_with_the_most_time_inside_it():
    assert speaker_at(1.0, 5.0, TURNS) == ANA
    assert speaker_at(5.0, 11.0, TURNS) == BIA  # 1 s da Ana contra 5 s da Bia
    assert speaker_at(4.0, 8.0, TURNS) == ANA  # empate de 2 s a 2 s: quem apareceu primeiro


def test_overlap_by_speaker_adds_up_separate_turns_of_the_same_person():
    assert overlap_by_speaker(5.0, 14.0, TURNS) == {ANA: pytest.approx(3.0), BIA: pytest.approx(6.0)}


def test_a_phrase_in_a_gap_takes_the_nearest_turn_if_it_is_close_enough():
    turns = [SpeakerTurn(0.0, 4.0, ANA), SpeakerTurn(6.0, 10.0, BIA)]
    assert speaker_at(4.2, 5.0, turns) == ANA  # a 0,2 s da Ana, a 1 s da Bia
    assert speaker_at(5.2, 5.9, turns) == BIA
    assert speaker_at(12.0, 13.0, turns) is None  # longe de todos: sem palpite
    assert speaker_at(1.0, 2.0, []) is None


def test_assign_speakers_labels_every_segment_in_order():
    segments = [span(1, 5), span(7, 11), span(13, 19)]
    assert assign_speakers(segments, TURNS) == [ANA, BIA, ANA]


def test_speaker_names_keep_the_order_of_appearance():
    assert speaker_names(TURNS) == [ANA, BIA]


# ---------- palavra ----------


def word(start: float, end: float, text: str = "x") -> Word:
    return Word(start, end, text, 0.9)


def test_a_word_belongs_to_the_speaker_who_clearly_covers_it():
    assert word_speaker(word(2.0, 2.5), TURNS) == ANA


def test_a_word_crossing_two_speakers_or_outside_every_turn_belongs_to_nobody():
    assert word_speaker(word(5.8, 6.2), TURNS) is None  # metade de cada
    assert word_speaker(word(5.9, 6.2), TURNS) is None  # a Bia cobre 2/3, mas a Ana ainda cobre 1/3: dúvida
    assert word_speaker(word(5.95, 6.5), TURNS) == BIA  # só 0,05 s da Ana em 0,55 s: a Bia é a dona
    assert word_speaker(word(30.0, 30.5), TURNS) is None
    assert word_speaker(word(3.0, 3.0), TURNS) is None  # duração zero


def test_label_words_follow_the_order_of_the_words():
    words = [word(1, 1.5), word(7, 7.5), word(13, 13.5)]
    assert label_words(words, TURNS) == [ANA, BIA, ANA]


# ---------- referência de voz do falante ----------


def run(texts: list[str], start: float, per_word: float = 0.5, gap: float = 0.02) -> list[Word]:
    words, cursor = [], start
    for text in texts:
        words.append(Word(cursor, cursor + per_word, text, 0.9))
        cursor += per_word + gap
    return words


def test_the_reference_is_the_longest_stretch_of_only_that_speaker():
    ana_short = run(list("abcdefg"), 0.5)  # 3,6 s
    bia = run(list("hijklmn"), 6.5)
    ana_long = run(list("opqrstuvwxy"), 12.5)  # 5,7 s
    words = [*ana_short, *bia, *ana_long]
    owners = label_words(words, TURNS)
    best = choose_speaker_reference(words, owners, ANA)
    assert best is not None and (best.start, best.text.split()[0]) == (12.5, "o")
    assert best.duration >= 3.0


def test_another_speaker_in_the_middle_splits_the_stretch():
    words = [*run(list("abcd"), 0.0), *run(["e"], 2.1, per_word=0.4), *run(list("fghi"), 2.6)]
    owners = [ANA, ANA, ANA, ANA, BIA, ANA, ANA, ANA, ANA]
    # sem a interjeição da Bia seriam 4,2 s seguidos da Ana; com ela, dois blocos de 2 s, nenhum chega a 3 s
    assert choose_speaker_reference(words, owners, ANA) is None
    assert choose_speaker_reference(words, [ANA] * 9, ANA) is not None


def test_overlapping_speech_words_do_not_count_for_anyone():
    words = run(list("abcdefgh"), 0.0)
    owners = [ANA, ANA, ANA, None, None, ANA, ANA, ANA]
    assert choose_speaker_reference(words, owners, ANA) is None  # blocos de 1,5 s e 1,5 s


def test_a_long_stretch_is_capped_at_fifteen_seconds_and_a_pause_breaks_it():
    long_run = run([f"p{i}" for i in range(40)], 0.0)  # 20,8 s contínuos
    best = choose_speaker_reference(long_run, [ANA] * 40, ANA)
    assert best is not None and 14.0 <= best.duration <= 15.0
    with_pause = [*run(list("abcde"), 0.0), *run(list("fghij"), 5.0)]  # pausa de 2,5 s no meio: 2,6 s cada
    assert choose_speaker_reference(with_pause, [ANA] * 10, ANA) is None


def test_a_speaker_with_no_words_has_no_reference():
    words = run(list("abcdefg"), 0.0)
    assert choose_speaker_reference(words, [ANA] * 7, BIA) is None
