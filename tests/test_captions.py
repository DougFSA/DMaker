from dmaker.text.captions import (
    Cue,
    Word,
    flatten_words,
    from_json,
    parse_srt,
    regroup,
    shift,
    to_json,
    to_srt,
)

SRT = """﻿1
00:00:00,200 --> 00:00:01,600
Olá, este é um <i>teste</i>

2
00:00:01,700 --> 00:00:03,400
de legendas
em duas linhas
"""


def test_parse_srt():
    cues = parse_srt(SRT)
    assert len(cues) == 2
    assert cues[0].start == 0.2 and cues[0].end == 1.6
    assert cues[0].text == "Olá, este é um teste"
    assert cues[1].text == "de legendas em duas linhas"


def test_srt_roundtrip():
    cues = parse_srt(SRT)
    again = parse_srt(to_srt(cues))
    assert [(c.start, c.end, c.text) for c in again] == [(c.start, c.end, c.text) for c in cues]


def test_json_roundtrip_keeps_words():
    cue = Cue(0, 1, "oi tudo", [Word(0, 0.4, "oi"), Word(0.5, 1, "tudo")])
    back = from_json(to_json([cue]))
    assert back[0].words[1].text == "tudo" and back[0].words[1].start == 0.5


def test_flatten_distributes_when_no_word_timing():
    words = flatten_words([Cue(0, 2, "um dois")])
    assert [w.text for w in words] == ["um", "dois"]
    assert words[0].start == 0 and abs(words[-1].end - 2) < 1e-6


def test_regroup_by_words_chars_punctuation_and_gap():
    words = [
        Word(0.0, 0.3, "a"),
        Word(0.3, 0.6, "b"),
        Word(0.6, 0.9, "c"),
        Word(0.9, 1.2, "d"),
        Word(1.2, 1.5, "e."),  # fim de frase
        Word(1.5, 1.8, "f"),
        Word(3.5, 3.8, "g"),  # pausa longa antes de g
    ]
    lines = regroup([Cue(0, 4, "", words)], max_words=4, max_chars=40, max_gap=0.8)
    assert [ln.text for ln in lines] == ["a b c d", "e.", "f", "g"]
    assert lines[2].end <= lines[3].start  # duração mínima não invade a próxima linha
    assert all(ln.words for ln in lines)


def test_regroup_max_chars():
    words = [Word(i * 0.5, i * 0.5 + 0.4, "palavra") for i in range(6)]
    lines = regroup([Cue(0, 3, "", words)], max_words=10, max_chars=16)
    assert all(len(ln.text) <= 16 for ln in lines)
    assert len(lines) == 3


def test_shift():
    out = shift([Cue(1, 2, "x", [Word(1, 1.5, "x")])], 0.5)
    assert out[0].start == 1.5 and out[0].words[0].end == 2.0


def test_apply_replacements_words_and_pairs():
    from dmaker.text.captions import apply_replacements

    cue = Cue(
        0,
        3,
        "com o medriquer, e o medli care.",
        [
            Word(0, 0.2, "com"),
            Word(0.2, 0.4, "o"),
            Word(0.4, 0.9, "medriquer,"),
            Word(0.9, 1.0, "e"),
            Word(1.0, 1.1, "o"),
            Word(1.1, 1.5, "medli"),
            Word(1.5, 2.0, "care."),
        ],
    )
    out = apply_replacements([cue], {"medriquer": "MedlyCare", "medli care": "MedlyCare"})
    assert out[0].text == "com o MedlyCare, e o MedlyCare."
    assert [w.text for w in out[0].words] == ["com", "o", "MedlyCare,", "e", "o", "MedlyCare."]
    assert out[0].words[-1].start == 1.1 and out[0].words[-1].end == 2.0
    # sem palavras: corrige o texto
    plain = apply_replacements([Cue(0, 1, "Medriquer chegou")], {"medriquer": "MedlyCare"})
    assert plain[0].text == "MedlyCare chegou"


def test_regroup_holds_short_gaps():
    words = [Word(0.0, 0.5, "um"), Word(0.9, 1.4, "dois."), Word(1.6, 2.0, "tres"), Word(4.0, 4.5, "quatro")]
    lines = regroup([Cue(0, 5, "", words)], max_words=2)
    assert [ln.text for ln in lines] == ["um dois.", "tres", "quatro"]
    assert lines[0].end == 1.6  # pausa curta segurada até a próxima linha
    assert lines[1].end < 4.0  # pausa longa não é segurada
