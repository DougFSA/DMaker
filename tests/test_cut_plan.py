"""Plano de cortes de uma gravação falada: pausas, vícios, frases repetidas, bordas no vale de energia."""

from __future__ import annotations

import numpy as np
import pytest

from dmaker.text.captions import Word
from dmaker.voice.cut_plan import (
    INTENSITIES,
    MIN_CUT,
    CutOptions,
    drop_reasons,
    plan_cuts,
    refine_words,
)
from dmaker.voice.levels import FRAME_SECONDS, active_frames, frame_rms

RATE = 16000


def audio(total: float, *sounds: tuple[float, float], floor: float = 0.0) -> np.ndarray:
    """Silêncio de `total` s com um tom (a "fala") em cada intervalo; `floor` é o ruído de fundo."""
    samples = np.full(int(total * RATE), floor, dtype=np.float32)
    for start, end in sounds:
        t = np.arange(int((end - start) * RATE)) / RATE
        samples[int(start * RATE) : int(start * RATE) + len(t)] = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(
            np.float32
        )
    return samples


def spoken(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(start, end, text) for text, start, end in items]


def sounds_of(words: list[Word]) -> list[tuple[float, float]]:
    return [(w.start, w.end) for w in words]


def plan(words, samples, **options):
    return plan_cuts(words, samples, RATE, CutOptions(frame_grid=None, **options))


# ---------- tempos das palavras ajustados à energia ----------


def active_of(samples: np.ndarray) -> np.ndarray:
    mask = active_frames(frame_rms(samples, RATE))
    assert mask is not None
    return mask


def test_refine_words_shrinks_a_word_that_the_whisper_stretched_into_the_silence():
    samples = audio(4.0, (0.5, 1.0), (3.0, 3.5))
    stretched = spoken(
        ("oi", 0.5, 2.9), ("tudo", 2.0, 3.5)
    )  # "oi" absorveu a pausa; "tudo" começa cedo demais
    first, second = refine_words(stretched, active_of(samples))
    assert first.end == pytest.approx(1.0, abs=0.02)
    assert second.start == pytest.approx(3.0, abs=0.02)


def test_refine_words_stretches_a_word_whose_sound_goes_past_the_recorded_end():
    samples = audio(4.0, (0.5, 1.3), (3.0, 3.5))
    early = spoken(("agenda", 0.5, 1.1), ("fim", 3.0, 3.5))  # o som de "agenda" vai até 1,3
    refined = refine_words(early, active_of(samples))
    assert refined[0].end == pytest.approx(1.3, abs=0.02)


def test_refine_words_never_runs_into_the_next_word():
    samples = audio(2.0, (0.5, 1.5))  # fala contínua, sem pausa entre as duas palavras
    words = spoken(("a", 0.5, 0.9), ("gente", 1.0, 1.5))
    refined = refine_words(words, active_of(samples))
    assert refined[0].end <= refined[1].start


def test_refine_words_leaves_a_word_with_no_sound_untouched():
    samples = audio(4.0, (0.5, 1.0))
    ghost = spoken(("oi", 0.5, 1.0), ("fantasma", 2.0, 2.5))
    assert refine_words(ghost, active_of(samples))[1] == ghost[1]


# ---------- pausas ----------


def test_a_long_pause_is_cut_leaving_a_breath_on_each_side():
    samples = audio(4.0, (0.0, 1.0), (3.0, 4.0))
    result = plan(spoken(("um", 0.0, 1.0), ("dois", 3.0, 4.0)), samples)
    (cut,) = result.cuts
    assert cut.reason == "silence" and cut.text == ""
    assert cut.start == pytest.approx(1.15, abs=0.02) and cut.end == pytest.approx(2.85, abs=0.02)
    assert result.keep == [(0.0, cut.start), (cut.end, 4.0)]


def test_a_pause_under_the_limit_is_kept():
    samples = audio(3.0, (0.0, 1.0), (1.4, 3.0))
    assert plan(spoken(("um", 0.0, 1.0), ("dois", 1.4, 3.0)), samples).cuts == []


def test_the_pause_limit_is_configurable():
    samples = audio(3.0, (0.0, 1.0), (1.8, 3.0))
    words = spoken(("um", 0.0, 1.0), ("dois", 1.8, 3.0))
    assert plan(words, samples).cuts  # 0,8 s passa de 0,5
    assert plan(words, samples, min_pause=1.0).cuts == []


def test_the_breath_is_configurable_and_never_cuts_into_the_words():
    samples = audio(4.0, (0.0, 1.0), (3.0, 4.0))
    words = spoken(("um", 0.0, 1.0), ("dois", 3.0, 4.0))
    wide = plan(words, samples, breath=0.4).cuts[0]
    assert wide.start == pytest.approx(1.4, abs=0.02) and wide.end == pytest.approx(2.6, abs=0.02)


def test_leading_and_trailing_silence_are_cut():
    samples = audio(6.0, (2.0, 3.0))
    result = plan(spoken(("oi", 2.0, 3.0)), samples)
    head, tail = result.cuts
    assert head.start == 0.0 and head.end == pytest.approx(1.85, abs=0.02)
    assert tail.start == pytest.approx(3.15, abs=0.02) and tail.end == 6.0
    assert result.keep == [(head.end, tail.start)]


def test_the_cut_edge_lands_in_the_energy_valley():
    # a pausa tem um ruído fraco (abaixo do limiar de fala) e uma janela de silêncio total por volta de 1,18 s
    samples = audio(4.0, (0.0, 1.0), (3.0, 4.0), floor=0.003)
    samples[int(1.16 * RATE) : int(1.20 * RATE)] = 0.0
    (cut,) = plan(spoken(("um", 0.0, 1.0), ("dois", 3.0, 4.0)), samples).cuts
    assert 1.16 <= cut.start <= 1.20


def test_a_pause_with_sound_the_whisper_did_not_hear_is_not_cut():
    samples = audio(6.0, (0.0, 1.0), (2.0, 2.4), (5.0, 6.0))  # 0,4 s de som onde o Whisper não pôs palavra
    result = plan(spoken(("um", 0.0, 1.0), ("dois", 5.0, 6.0)), samples)
    assert result.cuts == []


def test_a_soft_breath_in_the_pause_is_cut_with_it():
    # uma inspiração de 0,5 s a -20 dB da fala: passa do limiar de pausa, mas não é fala
    samples = audio(4.0, (0.0, 1.0), (3.0, 4.0))
    t = np.arange(int(0.5 * RATE)) / RATE
    samples[int(1.8 * RATE) : int(1.8 * RATE) + len(t)] = 0.03 * np.sin(2 * np.pi * 300 * t)
    assert len(plan(spoken(("um", 0.0, 1.0), ("dois", 3.0, 4.0)), samples).cuts) == 1


def test_a_word_the_whisper_heard_in_pure_silence_is_ignored_and_does_not_split_the_cut():
    samples = audio(6.0, (0.0, 1.0), (5.0, 6.0))
    ghost = spoken(("um", 0.0, 1.0), ("obrigado", 2.5, 3.0), ("dois", 5.0, 6.0))
    result = plan(ghost, samples)
    (cut,) = result.cuts
    assert cut.start == pytest.approx(1.15, abs=0.02) and cut.end == pytest.approx(4.85, abs=0.02)
    assert [w.text for w in result.words] == [
        "um",
        "obrigado",
        "dois",
    ]  # a legenda continua com todas as palavras


def test_a_click_in_the_pause_does_not_stop_the_cut():
    samples = audio(4.0, (0.0, 1.0), (1.9, 1.93), (3.0, 4.0))  # um estalo de 30 ms
    assert len(plan(spoken(("um", 0.0, 1.0), ("dois", 3.0, 4.0)), samples).cuts) == 1


def test_no_words_or_silent_audio_means_no_cuts():
    assert plan([], audio(4.0, (1.0, 2.0))).cuts == []
    result = plan(spoken(("oi", 0.0, 1.0)), np.zeros(4 * RATE, dtype=np.float32))
    assert result.cuts == [] and result.keep == [(0.0, 4.0)]


def test_a_cut_is_never_shorter_than_the_minimum():
    samples = audio(4.0, (0.0, 1.0), (1.6, 4.0))
    result = plan(spoken(("um", 0.0, 1.0), ("dois", 1.6, 4.0)), samples, min_pause=0.4, breath=0.25)
    assert all(cut.duration >= MIN_CUT for cut in result.cuts)


# ---------- vícios ----------


def filler_scene():
    """ "então" (0 a 1), "é" isolado (2 a 2,3), "vamos" (3,5 a 4,5)."""
    words = spoken(("então", 0.0, 1.0), ("é...", 2.0, 2.3), ("vamos", 3.5, 4.5))
    return words, audio(5.0, (0.0, 1.0), (2.0, 2.3), (3.5, 4.5))


def test_an_isolated_filler_is_cut_together_with_the_pauses_around_it():
    words, samples = filler_scene()
    (cut,) = plan(words, samples).cuts
    assert cut.reason == "filler" and cut.text == "é..."
    assert cut.start == pytest.approx(1.15, abs=0.02) and cut.end == pytest.approx(3.35, abs=0.02)


def test_the_filler_is_not_cut_in_the_soft_intensity():
    words, samples = filler_scene()
    before, after = plan(words, samples, intensity="suave").cuts
    assert before.reason == after.reason == "silence"  # as duas pausas saem, o "é" no meio fica
    assert before.end < 2.0 and after.start > 2.3


def test_a_filler_glued_to_the_next_word_is_cut_only_up_to_its_own_sound():
    words = spoken(("então", 0.0, 1.0), ("hã", 1.1, 1.4), ("vamos", 1.45, 2.5))
    samples = audio(3.0, (0.0, 1.0), (1.1, 1.4), (1.45, 2.5))
    (cut,) = plan(words, samples).cuts
    assert cut.reason == "filler"
    assert 1.0 <= cut.start <= 1.1 and 1.4 <= cut.end <= 1.45


def test_ne_at_the_end_of_a_phrase_before_a_pause_is_a_filler():
    words = spoken(("bonito", 0.0, 0.8), ("né?", 0.9, 1.2), ("agora", 3.0, 4.0))
    samples = audio(4.5, (0.0, 0.8), (0.9, 1.2), (3.0, 4.0))
    (cut,) = plan(words, samples).cuts
    assert cut.reason == "filler" and cut.text == "né?"
    assert 0.8 <= cut.start <= 0.9  # no vale entre "bonito" e o "né?"


def test_ne_in_the_middle_of_a_phrase_is_kept():
    # "isso né difícil" (isso não é difícil), tudo colado
    words = spoken(("isso", 0.0, 0.4), ("né", 0.45, 0.65), ("difícil", 0.7, 1.4))
    samples = audio(2.0, (0.0, 1.4))
    result = plan(words, samples)
    assert all(cut.reason == "silence" for cut in result.cuts)
    assert all(cut.start >= 1.4 for cut in result.cuts)  # só a pausa do fim sai; o "né" não é tocado


def test_nao_e_spelled_out_is_never_a_filler():
    words = spoken(("isso", 0.0, 0.4), ("não", 0.45, 0.6), ("é", 0.65, 0.8), ("difícil", 0.85, 1.4))
    assert drop_reasons(words, "agressiva") == {}


def test_a_stretched_e_is_a_filler_even_glued_to_the_phrase():
    words = spoken(("a", 0.0, 0.2), ("é", 0.22, 0.8), ("gente", 0.82, 1.4))
    assert drop_reasons(words, "normal") == {1: "filler"}


def test_a_short_e_glued_to_the_phrase_is_a_word():
    words = spoken(("ele", 0.0, 0.3), ("é", 0.32, 0.45), ("bom", 0.5, 0.9))
    assert drop_reasons(words, "agressiva") == {}


def test_e_and_tipo_isolated_by_pauses_are_fillers_but_glued_they_are_words():
    isolated = spoken(("então", 0.0, 0.5), ("tipo", 1.0, 1.3), ("assim", 1.8, 2.3))
    assert drop_reasons(isolated, "normal") == {1: "filler"}
    glued = spoken(("um", 0.0, 0.3), ("tipo", 0.35, 0.65), ("de", 0.7, 0.8), ("coisa", 0.85, 1.2))
    assert drop_reasons(glued, "normal") == {}
    lonely_e = spoken(("então", 0.0, 0.5), ("é", 1.0, 1.15), ("assim", 1.7, 2.2))
    assert drop_reasons(lonely_e, "normal") == {1: "filler"}


def test_hesitation_sounds_are_always_fillers():
    for sound in ("hã", "Hã...", "hmmm", "ahn", "uhm", "ééé"):
        words = spoken(("bom", 0.0, 0.3), (sound, 0.32, 0.5), ("dia", 0.52, 0.9))
        assert drop_reasons(words, "normal") == {1: "filler"}, sound


def test_words_that_look_like_fillers_but_mean_something_are_kept():
    for word in ("ah", "um", "aham", "e", "tipos", "nem"):
        words = spoken(("bom", 0.0, 0.3), (word, 0.32, 0.5), ("dia", 0.52, 0.9))
        assert drop_reasons(words, "agressiva") == {}, word


# ---------- frases repetidas ----------


def repeat_scene():
    """Falso começo "hoje eu vou falar sobre" (0 a 2) e a tomada boa (3,5 a 7)."""
    words = spoken(
        ("Hoje", 0.0, 0.4),
        ("eu", 0.45, 0.6),
        ("vou", 0.65, 0.9),
        ("falar", 0.95, 1.4),
        ("sobre...", 1.45, 2.0),
        ("Hoje", 3.5, 3.9),
        ("eu", 3.95, 4.1),
        ("vou", 4.15, 4.4),
        ("falar", 4.45, 4.9),
        ("sobre", 4.95, 5.4),
        ("agenda.", 5.45, 7.0),
    )
    return words, audio(7.5, (0.0, 2.0), (3.5, 7.0))


def test_a_false_start_is_cut_keeping_the_last_take():
    words, samples = repeat_scene()
    (cut,) = plan(words, samples, intensity="agressiva").cuts
    assert cut.reason == "repetition" and cut.text == "Hoje eu vou falar sobre..."
    assert cut.start == 0.0 and cut.end == pytest.approx(3.35, abs=0.02)


def test_repetitions_stay_in_the_normal_intensity():
    words, samples = repeat_scene()
    result = plan(words, samples, intensity="normal")
    assert {cut.reason for cut in result.cuts} == {"silence"}
    assert any(cut.start < 3.5 < cut.end + 0.5 for cut in result.cuts)


def test_a_truncated_first_take_is_still_a_false_start():
    words = spoken(
        ("Hoje", 0.0, 0.4),
        ("eu", 0.45, 0.6),
        ("vou", 0.65, 0.9),
        ("fal", 0.95, 1.1),
        ("Hoje", 2.5, 2.9),
        ("eu", 2.95, 3.1),
        ("vou", 3.15, 3.4),
        ("falar", 3.45, 3.9),
        ("hoje.", 3.95, 4.4),
    )
    assert drop_reasons(words, "agressiva") == {
        0: "repetition",
        1: "repetition",
        2: "repetition",
        3: "repetition",
    }


def test_a_rephrased_sentence_keeps_only_the_last_version():
    first = ["Esse", "produto", "é", "muito", "bom"]
    second = ["Esse", "produto", "é", "muito", "muito", "bom"]
    words = [Word(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate(first)]
    base = 3.0
    words += [Word(base + i * 0.3, base + i * 0.3 + 0.25, w) for i, w in enumerate(second)]
    assert drop_reasons(words, "agressiva") == {i: "repetition" for i in range(5)}


def test_different_sentences_with_a_shared_opening_are_kept():
    words = spoken(
        ("A", 0.0, 0.2),
        ("gente", 0.25, 0.6),
        ("precisa", 0.65, 1.1),
        ("mudar.", 1.15, 1.6),
        ("A", 3.0, 3.2),
        ("gente", 3.25, 3.6),
        ("precisa", 3.65, 4.1),
        ("agir", 4.15, 4.6),
    )
    assert drop_reasons(words, "agressiva") == {}


def test_a_single_repeated_word_is_emphasis_not_a_false_start():
    words = spoken(("Então.", 0.0, 0.5), ("Então", 2.0, 2.5), ("vamos", 2.55, 3.0))
    assert drop_reasons(words, "agressiva") == {}


def test_an_immediate_stutter_of_a_few_words_is_cut():
    words = spoken(
        ("a", 0.0, 0.2),
        ("gente", 0.25, 0.6),
        ("vai", 0.65, 0.9),
        ("a", 0.95, 1.1),
        ("gente", 1.15, 1.5),
        ("vai", 1.55, 1.8),
        ("viajar", 1.85, 2.4),
    )
    assert drop_reasons(words, "agressiva") == {0: "repetition", 1: "repetition", 2: "repetition"}
    assert drop_reasons(words, "normal") == {}


# ---------- propriedades do plano ----------


def test_no_cut_ever_goes_through_a_word_that_stays():
    samples = audio(
        20.0, (0.0, 1.0), (1.8, 2.2), (4.0, 5.5), (6.5, 6.8), (8.5, 10.0), (11.0, 12.5), (15.0, 19.0)
    )
    words = spoken(
        ("então", 0.0, 1.0),
        ("é...", 1.8, 2.2),
        ("vamos", 4.0, 4.8),
        ("falar", 4.85, 5.5),
        ("né?", 6.5, 6.8),
        ("Hoje", 8.5, 9.0),
        ("eu", 9.05, 9.3),
        ("vou", 9.35, 10.0),
        ("Hoje", 11.0, 11.5),
        ("eu", 11.55, 11.8),
        ("vou", 11.85, 12.5),
        ("começar", 15.0, 16.5),
        ("agora.", 16.55, 19.0),
    )
    for intensity in INTENSITIES:
        result = plan(words, samples, intensity=intensity)
        dropped = set(drop_reasons(result.words, intensity))
        for index, word in enumerate(result.words):
            if index in dropped:
                continue
            for cut in result.cuts:
                assert cut.end <= word.start + 1e-6 or cut.start >= word.end - 1e-6, (intensity, word, cut)


def test_the_kept_ranges_and_the_cuts_cover_the_recording_without_overlap():
    words, samples = repeat_scene()
    result = plan(words, samples, intensity="agressiva")
    pieces = sorted([*[(a, b) for a, b in result.keep], *[(c.start, c.end) for c in result.cuts]])
    assert pieces[0][0] == 0.0 and pieces[-1][1] == pytest.approx(7.5)
    for (_, end), (start, _) in zip(pieces, pieces[1:], strict=False):
        assert end == pytest.approx(start)


def test_kept_clips_last_a_whole_number_of_video_frames():
    samples = audio(9.0, (0.0, 1.07), (3.0, 4.31), (7.0, 9.0))
    words = spoken(("um", 0.0, 1.07), ("dois", 3.0, 4.31), ("três", 7.0, 9.0))
    result = plan_cuts(words, samples, RATE, CutOptions(frame_grid=1 / 30))
    assert len(result.cuts) == 2
    for start, end in result.keep[:-1]:
        frames = (end - start) * 30
        assert frames == pytest.approx(round(frames), abs=0.03)


def test_the_options_reject_nonsense():
    with pytest.raises(ValueError, match="intensidade"):
        CutOptions(intensity="brutal")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pausa"):
        CutOptions(min_pause=0)
    with pytest.raises(ValueError, match="respiro"):
        CutOptions(breath=-0.1)


def test_frame_seconds_is_the_energy_resolution_the_plan_assumes():
    assert FRAME_SECONDS == 0.01
