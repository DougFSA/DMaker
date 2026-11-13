"""Cache da transcrição automática: a chave só muda com a fala, as legendas andam com os clipes e a edição à mão
é reconhecida (funções puras, sem disco além de um arquivo temporário)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.spec import CardSegment, ClipSegment, Transition
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.sources import Source
from dmaker.pipeline.transcript_cache import (
    TranscriptKeys,
    TranscriptStore,
    reuse,
    speech_layout,
    transcript_keys,
    transcript_record,
    was_edited,
)
from dmaker.text.captions import Cue, Word, follow_moves

VIDEO = MediaInfo(Path("take.mp4"), 8.0, 1920, 1080, 30.0, True, True, False)
CUES = [Cue(0.2, 1.4, "chega de pausa", [Word(0.2, 0.6, "chega", 0.9), Word(0.6, 1.4, "de pausa", 0.8)])]


def _layout(timeline: list) -> tuple:
    sources = [
        Source(None, VIDEO) if isinstance(seg, ClipSegment) else Source(None, None) for seg in timeline
    ]
    layout = speech_layout(timeline, sources)
    return layout, transcript_keys(layout, ["pt", "small"], movable=True)


def _clip() -> ClipSegment:
    return ClipSegment(src="take.mp4", start=1, end=3)


def test_cards_only_count_by_the_shift_they_cause():
    base_layout, base = _layout([CardSegment(title="Abertura", duration=1.0), _clip()])
    _, renamed = _layout([CardSegment(title="Outro título", duration=1.0), _clip()])
    _, closing = _layout(
        [CardSegment(title="Abertura", duration=1.0), _clip(), CardSegment(title="Fim", duration=2.0)]
    )
    pushed_layout, pushed = _layout([CardSegment(title="Abertura", duration=3.0), _clip()])

    assert base_layout.spans == [(1.0, 3.0)]
    assert (
        renamed.exact == closing.exact == base.exact
    )  # título e cartão no fim não mudam a fala nem o lugar dela
    assert pushed.speech == base.speech and pushed.exact != base.exact  # a mesma fala, em outro instante
    assert pushed_layout.spans == [(3.0, 5.0)]


def test_a_transition_into_the_clip_shifts_it():
    layout, _ = _layout(
        [
            CardSegment(title="A", duration=1.0),
            _clip().model_copy(update={"transition": Transition(type="fade")}),
        ]
    )
    assert layout.spans == [(0.5, 2.5)]  # o fade de 0.5 s sobrepõe o clipe ao cartão


def test_follow_moves_moves_each_cue_with_its_clip():
    cues = [Cue(0.5, 1.0, "um"), Cue(4.2, 4.8, "dois", [Word(4.2, 4.8, "dois")]), Cue(9.0, 9.5, "fora")]
    moved = follow_moves(cues, [(0.0, 2.0, 1.0), (4.0, 6.0, 3.0)])
    assert [(c.start, c.text) for c in moved] == [(1.5, "um"), (7.2, "dois"), (12.0, "fora")]
    assert moved[1].words[0].start == pytest.approx(7.2)  # a palavra anda com a cue
    assert follow_moves(cues, []) == cues


def _record(keys: TranscriptKeys, *, edited: bool = False) -> dict:
    return transcript_record(CUES, "pt", keys, {"model": "small"}, edited=edited)


def test_reuse_keeps_shifts_or_refuses():
    _, base = _layout([CardSegment(title="A", duration=1.0), _clip()])
    _, pushed = _layout([CardSegment(title="A", duration=3.0), _clip()])
    _, recut = _layout([CardSegment(title="A", duration=1.0), ClipSegment(src="take.mp4", start=1, end=4)])
    data = _record(base)

    same = reuse(data, base)
    assert same is not None and not same.rewrite and same.cues == CUES
    moved = reuse(data, pushed)
    assert moved is not None and moved.rewrite and moved.cues[0].start == pytest.approx(2.2)
    assert reuse(data, recut) is None  # outro corte: outra fala
    fixed = TranscriptKeys(pushed.exact, pushed.speech, pushed.spans, movable=False)
    assert reuse(data, fixed) is None  # voz que não anda com os clipes: não dá para deslocar


def test_reuse_accepts_the_file_written_before_v3():
    _, keys = _layout([_clip()])
    legacy = {"language": "pt", "cues": json.loads(json.dumps(_record(keys)["cues"])), "hash": "antiga"}
    with_legacy = TranscriptKeys(keys.exact, keys.speech, keys.spans, movable=True, legacy="antiga")
    found = reuse(legacy, with_legacy)
    assert found is not None and found.rewrite and found.cues == CUES
    assert was_edited(legacy)  # sem impressão digital não dá para saber: conta como editado


def test_edits_are_detected_by_the_fingerprint():
    _, keys = _layout([_clip()])
    data = _record(keys)
    assert not was_edited(data)
    data["cues"][0]["words"][0]["text"] = "basta"
    assert was_edited(data)
    assert "cues_hash" not in _record(keys, edited=True)


def test_store_keeps_an_edited_copy_once(tmp_path: Path):
    _, keys = _layout([_clip()])
    store = TranscriptStore(tmp_path / "captions.auto.json")
    store.save(_record(keys), CUES)
    assert (tmp_path / "captions.auto.srt").exists()
    assert store.keep_edited() is None  # sem edição, nada a guardar

    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["cues"][0]["text"] = "basta de pausa"
    store.path.write_text(json.dumps(data), encoding="utf-8")
    first, second = store.keep_edited(), store.keep_edited()
    assert first is not None and first == second and "basta" in first.read_text(encoding="utf-8")
    assert len(list(tmp_path.glob("captions.auto.editado-*.json"))) == 1
