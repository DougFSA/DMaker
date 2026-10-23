"""Nomes dos arquivos do audiobook, legendas do completo e tempo estimado da fila (tudo função pura)."""

from __future__ import annotations

import pytest

from dmaker.voice.audiobook import (
    CHAPTER_GAP_SECONDS,
    chapter_filename,
    complete_filename,
    merge_chapter_cues,
    safe_slug,
)
from dmaker.voice.estimate import (
    MAX_SAMPLES,
    append_samples,
    default_seconds_per_char,
    format_duration,
    remaining_seconds,
    seconds_per_char,
    speed_key,
)


def test_slugs_have_no_accents_and_never_come_out_empty():
    assert safe_slug("Capítulo 1: A Ação!") == "capitulo-1-a-acao"
    assert safe_slug("???") == "narracao"
    assert safe_slug("???", "capitulo") == "capitulo"
    assert len(safe_slug("palavra " * 40)) <= 60
    assert not safe_slug("palavra " * 40).endswith("-")


def test_chapter_files_are_numbered_so_repeated_titles_do_not_collide():
    assert chapter_filename(3, "O começo", "wav") == "03-o-comeco.wav"
    assert chapter_filename(10, "O começo", "mp3") == "10-o-comeco.mp3"
    assert chapter_filename(1, "...", "wav") == "01-capitulo.wav"
    assert complete_filename("Meu Livro", "wav") == "meu-livro-completo.wav"


def test_merged_cues_shift_each_chapter_by_the_previous_ones_and_the_gap():
    first = (10.0, [(0.0, 4.0, "a"), (4.35, 10.0, "b")])
    second = (5.0, [(0.0, 5.0, "c")])
    third = (2.0, [(0.0, 2.0, "d")])
    cues, total = merge_chapter_cues([first, second, third])
    gap = CHAPTER_GAP_SECONDS
    assert gap == 1.5
    assert cues == [
        (0.0, 4.0, "a"),
        (4.35, 10.0, "b"),
        (10.0 + gap, 15.0 + gap, "c"),
        (15.0 + 2 * gap, 17.0 + 2 * gap, "d"),
    ]
    assert total == pytest.approx(17.0 + 2 * gap)  # nada de pausa depois do último capítulo


def test_merged_cues_of_a_single_chapter_and_of_nothing():
    assert merge_chapter_cues([(3.0, [(0.0, 3.0, "x")])]) == ([(0.0, 3.0, "x")], 3.0)
    assert merge_chapter_cues([]) == ([], 0.0)


# ---------- tempo estimado ----------


def test_initial_guess_is_documented_per_engine_and_quality():
    assert default_seconds_per_char("omnivoice", False) == 1.4
    assert default_seconds_per_char("omnivoice", True) == 0.7
    assert default_seconds_per_char("kokoro", True) < 0.5
    assert default_seconds_per_char("motor-novo", False) == 1.4  # motor desconhecido: assume o mais lento
    assert speed_key("omnivoice", True) == "omnivoice:draft"
    assert speed_key("kokoro", False) == "kokoro:final"


def test_measured_speed_is_the_character_weighted_average_of_recent_samples():
    # 100 caracteres em 50 s e 300 em 150 s: 0,5 s por caractere, e um texto curto não pesa tanto quanto um longo
    assert seconds_per_char([(100, 50.0), (300, 150.0)], fallback=9.0) == pytest.approx(0.5)
    assert seconds_per_char([(10, 100.0), (1000, 500.0)], fallback=9.0) == pytest.approx(600 / 1010)


def test_without_valid_samples_the_guess_is_used():
    assert seconds_per_char([], fallback=1.4) == 1.4
    assert seconds_per_char([(0, 3.0), (20, 0.0), (-5, 1.0)], fallback=0.7) == 0.7


def test_only_the_most_recent_samples_count():
    old = [(100, 1000.0)] * MAX_SAMPLES  # a máquina estava ocupada, 10 s por caractere
    recent = [(100, 50.0)] * MAX_SAMPLES
    assert seconds_per_char(old + recent, fallback=1.0) == pytest.approx(0.5)
    assert len(append_samples(old, recent)) == MAX_SAMPLES
    assert append_samples([(1, 1.0)], [(2, 2.0)]) == [(1, 1.0), (2, 2.0)]


def test_remaining_time_and_its_label():
    assert remaining_seconds(1000, 1.4) == pytest.approx(1400)
    assert remaining_seconds(-5, 1.4) == 0
    assert format_duration(40) == "40 s"
    assert format_duration(12 * 60 + 20) == "12 min"
    assert format_duration(2 * 3600 + 5 * 60) == "2 h 05 min"
