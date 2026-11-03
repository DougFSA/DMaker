"""Desfazer e refazer para toda operação do `edit_project`: a spec volta EXATAMENTE a como estava, byte a byte."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker import mcp_server
from dmaker.domain.spec import Project
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.edit_history import (
    HISTORY_DIR,
    HISTORY_LIMIT,
    EditHistory,
    HistoryError,
    edit_and_record,
    edit_label,
    history_listing,
    redo_edit,
    undo_edit,
)
from dmaker.pipeline.projects import save_project

DURATIONS = {"video.mp4": 10.0, "fala.wav": 6.0, "musica.wav": 30.0, "mesa.wav": 40.0}


def prober(path: Path) -> MediaInfo:
    video = path.suffix == ".mp4"
    return MediaInfo(
        path,
        DURATIONS.get(path.name, 5.0),
        1280 if video else 0,
        720 if video else 0,
        30.0,
        video,
        True,
        False,
    )


@pytest.fixture
def spec(tmp_path) -> Path:
    for name in DURATIONS:
        (tmp_path / name).write_bytes(b"\x00" * 16)
    project = Project.model_validate(
        {
            "name": "historico",
            "sources": {"cam": {"src": "video.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
            "timeline": [
                {"type": "clip", "src": "video.mp4", "start": 0, "end": 5},
                {"type": "clip", "src": "video.mp4", "start": 5, "end": 10},
                {"type": "clip", "source": "cam", "start": 0, "end": 8},
            ],
            "overlays": [
                {"type": "text", "text": "oi", "start": 1, "end": 3},
                {"type": "video", "src": "video.mp4", "start": 0, "end": 4},
            ],
            "markers": [{"at": 2.0, "text": "A"}],
            "audio": {
                "music": {"src": "musica.wav"},
                "narration": [{"text": "olá", "start": 1.0}],
                "voiceover": [{"src": "fala.wav", "start": 2.0}, {"src": "fala.wav", "start": 12.0}],
                "tracks": [{"source": "mesa"}],
                "normalize": "off",
            },
        }
    )
    save_project(project, tmp_path)
    return tmp_path / "spec.json"


def edit(spec: Path, **op) -> None:
    edit_and_record(spec, op, prober=prober)


def on_disk(spec: Path) -> bytes:
    return spec.read_bytes()


# uma operação de cada tipo do `edit_project`, nova ou antiga: todas têm que ser desfeitas exatamente
EVERY_OPERATION = [
    {"type": "split", "index": 0, "at": 2.0},
    {"type": "remove", "index": 1},
    {"type": "move", "index": 0, "to": 1},
    {"type": "trim", "index": 0, "side": "out", "delta": -1},
    {"type": "duplicate", "index": 0},
    {"type": "insert", "index": 1, "segment": {"type": "card", "duration": 2, "title": "novo"}},
    {"type": "overlay_span", "index": 0, "start": 0.5, "end": 2},
    {"type": "overlay_remove", "index": 0},
    {"type": "overlay_duplicate", "index": 0},
    {"type": "set_field", "path": "timeline.0.speed", "value": 1.5},
    {
        "type": "audio_effect",
        "action": "add",
        "target": "audio.master",
        "effect": {"type": "amplify", "gain_db": 3},
    },
    {"type": "marker_add", "at": 4.0, "text": "B"},
    {"type": "marker_set", "index": 0, "text": "mudou"},
    {"type": "marker_remove", "index": 0},
    {"type": "audio_silence", "target": "timeline.0", "start": 1, "end": 2},
    {"type": "audio_cut", "target": "timeline.0", "start": 1, "end": 2},
    {"type": "audio_cut", "target": "audio.voiceover.0", "start": 3, "end": 4},
    {"type": "audio_envelope", "target": "audio.music", "points": [{"at": 1, "db": 0}, {"at": 3, "db": -12}]},
    {"type": "audio_channels", "target": "audio.voiceover.0", "mode": "left"},
    {"type": "audio_trim", "target": "audio.voiceover.0", "start": 3, "end": 6},
    {"type": "audio_trim", "target": "timeline.1", "start": 6, "end": 8},
    {"type": "audio_paste", "target": "audio.voiceover.0", "start": 3, "end": 5, "at": 9},
    {"type": "audio_duplicate", "target": "audio.voiceover.0"},
    {"type": "audio_split", "target": "audio.voiceover.0", "at": 4},
    {"type": "audio_shift", "target": "timeline.0", "delta": 0.4},
    {"type": "audio_shift", "target": "overlays.1", "delta": -0.2},
    {"type": "audio_shift", "target": "audio.tracks.0", "delta": 1},
    {"type": "audio_shift", "target": "audio.voiceover.1", "delta": 2},
    {"type": "audio_shift", "target": "audio.music", "delta": 3},
    {"type": "audio_split_stereo", "target": "audio.tracks.0"},
    {"type": "audio_split_stereo", "target": "audio.voiceover.0"},
    {"type": "track_set", "track": "A1", "gain_db": -3, "pan": 0.5, "solo": True},
]


@pytest.mark.parametrize(
    "op", EVERY_OPERATION, ids=lambda op: f"{op['type']}-{op.get('target', op.get('track', ''))}"
)
def test_undo_gives_back_exactly_the_previous_spec_and_redo_gives_back_the_edit(spec, op):
    before = on_disk(spec)
    edit(spec, **op)
    after = on_disk(spec)
    assert after != before  # a operação fez alguma coisa
    outcome = undo_edit(spec)
    assert on_disk(spec) == before  # byte a byte, no arquivo
    assert outcome.project.to_bytes() == before  # e no `to_bytes` do projeto devolvido
    assert (outcome.undo_steps, outcome.redo_steps) == (0, 1)
    again = redo_edit(spec)
    assert on_disk(spec) == after
    assert (again.undo_steps, again.redo_steps) == (1, 0)


def test_several_edits_are_undone_one_by_one_in_reverse_order(spec):
    states = [on_disk(spec)]
    sequence = [EVERY_OPERATION[index] for index in (14, 15, 17, 18, 24, 31)]
    for op in sequence:
        edit(spec, **op)
        states.append(on_disk(spec))
    for expected in reversed(states[:-1]):
        undo_edit(spec)
        assert on_disk(spec) == expected
    with pytest.raises(HistoryError, match="não há o que desfazer"):
        undo_edit(spec)
    for expected in states[1:]:
        redo_edit(spec)
        assert on_disk(spec) == expected
    with pytest.raises(HistoryError, match="não há o que refazer"):
        redo_edit(spec)


def test_a_new_edit_after_an_undo_empties_the_redo_stack_and_its_files(spec):
    edit(spec, type="audio_silence", target="timeline.0", start=1, end=2)
    edit(spec, type="audio_silence", target="timeline.0", start=3, end=4)
    undo_edit(spec)
    folder = spec.parent / HISTORY_DIR
    assert history_listing(spec)["redo"]
    edit(spec, type="marker_add", at=1.0, text="novo")
    assert history_listing(spec)["redo"] == []
    with pytest.raises(HistoryError, match="não há o que refazer"):
        redo_edit(spec)
    # nada de arquivo órfão: 2 passos de desfazer (a segunda edição já tinha sido desfeita e saiu da pilha)
    assert len(list(folder.glob("*.spec.json"))) == len(history_listing(spec)["undo"])


def test_a_refused_edit_is_not_recorded_and_the_spec_stays_as_it_was(spec):
    before = on_disk(spec)
    with pytest.raises(ValueError, match="maior que"):
        edit(spec, type="audio_silence", target="timeline.0", start=5, end=1)
    assert on_disk(spec) == before
    assert history_listing(spec) == {"undo": [], "redo": [], "limit": HISTORY_LIMIT}


def test_the_history_keeps_only_the_limit_of_steps_and_drops_the_oldest_files(spec, monkeypatch):
    project = Project.load(spec)
    history = EditHistory(spec.parent, limit=3)
    for number in range(5):
        history.record(project, project, f"passo {number}")
    steps = history.steps().undo
    assert [step.label for step in steps] == ["passo 2", "passo 3", "passo 4"]
    assert len(list((spec.parent / HISTORY_DIR).glob("*.spec.json"))) == 3


def test_an_undo_after_a_change_made_outside_the_history_warns_and_keeps_that_state_for_redo(spec):
    edit(spec, type="audio_silence", target="timeline.0", start=1, end=2)
    outside = Project.load(spec).model_copy(update={"name": "historico"})
    outside.timeline[1].volume = 0.3  # alguém mexeu na interface
    save_project(outside, spec.parent)
    changed = on_disk(spec)
    outcome = undo_edit(spec)
    assert any("fora do histórico" in warning for warning in outcome.warnings)
    redo_edit(spec)
    assert on_disk(spec) == changed  # o estado de fora volta no refazer: nada se perdeu


def test_the_listing_names_each_step_with_what_it_touched(spec):
    edit(spec, type="audio_silence", target="timeline.0", start=1, end=2)
    edit(spec, type="track_set", track="MUS", gain_db=-6)
    labels = [step["label"] for step in history_listing(spec)["undo"]]
    assert labels[0].startswith("Estado da trilha track=MUS") and labels[1].startswith(
        "Silenciar target=timeline.0"
    )
    assert edit_label({"type": "split", "index": 1, "at": 2.5}) == "Cortar no cursor index=1 at=2.5"
    assert len(edit_label({"type": "set_field", "path": "x", "value": "y" * 300, "target": "t" * 300})) <= 90


def test_the_history_is_saved_in_the_project_folder_and_is_not_part_of_the_spec(spec):
    edit(spec, type="audio_silence", target="timeline.0", start=1, end=2)
    folder = spec.parent / HISTORY_DIR
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    assert len(index["undo"]) == 1 and index["redo"] == []
    assert b"history" not in on_disk(spec)


# ---------- o desfazer do corte automático continua funcionando ----------


def test_undo_cut_still_works_and_can_itself_be_undone_by_undo_edit(tmp_path):
    from dmaker.pipeline import autocut
    from dmaker.pipeline.autocut import REPORT_FILE, CutReport, save_cut_report

    source = tmp_path / "gravacao.mp4"
    source.write_bytes(b"\x00" * 16)
    project = Project.model_validate(
        {
            "name": "cortado",
            "timeline": [
                {"type": "clip", "src": str(source), "start": 0.0, "end": 3.0},
                {"type": "clip", "src": str(source), "start": 5.0, "end": 9.0},
            ],
        }
    )
    save_project(project, tmp_path)
    save_cut_report(tmp_path, CutReport(str(source), 9.0, 0.5, 0.4, 0.1, [_cut_record()]))
    before = (tmp_path / "spec.json").read_bytes()
    report_before = (tmp_path / REPORT_FILE).read_text(encoding="utf-8")

    autocut.undo_cut(tmp_path / "spec.json", 0, prober=prober)
    joined = Project.load(tmp_path / "spec.json")
    assert len(joined.timeline) == 1 and (joined.timeline[0].start, joined.timeline[0].end) == (0.0, 9.0)
    assert json.loads((tmp_path / REPORT_FILE).read_text(encoding="utf-8"))["cuts"][0]["undone"] is True

    undo_edit(
        tmp_path / "spec.json"
    )  # desfazer o "desfazer o corte": o corte está de volta, e a lista também
    assert (tmp_path / "spec.json").read_bytes() == before
    assert (tmp_path / REPORT_FILE).read_text(encoding="utf-8") == report_before
    redo_edit(tmp_path / "spec.json")
    assert len(Project.load(tmp_path / "spec.json").timeline) == 1


def _cut_record():
    from dmaker.pipeline.autocut import CutRecord

    return CutRecord(0, 3.0, 5.0, "pausa", "", False)


# ---------- o MCP ----------


def test_the_mcp_tools_edit_undo_redo_and_list_the_history():
    project = Project.model_validate(
        {
            "name": "historico-mcp",
            "timeline": [{"type": "card", "duration": 10, "title": "um"}],
            "audio": {"normalize": "off"},
        }
    )
    save_project(project)
    first = mcp_server.edit_project("historico-mcp", {"type": "track_set", "track": "A1", "gain_db": -3})
    assert "spec_path" in first
    listing = mcp_server.edit_history("historico-mcp")
    assert [step["label"].split(" ")[0] for step in listing["undo"]] == ["Estado"]
    undone = mcp_server.undo_edit("historico-mcp")
    assert undone["step"].startswith("Estado da trilha") and (undone["undo_steps"], undone["redo_steps"]) == (
        0,
        1,
    )
    from dmaker.pipeline.projects import load_project

    assert load_project("historico-mcp").tracks == {}
    redone = mcp_server.redo_edit("historico-mcp")
    assert redone["redo_steps"] == 0 and load_project("historico-mcp").tracks["A1"].gain_db == -3
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="não há o que refazer"):
        mcp_server.redo_edit("historico-mcp")
    with pytest.raises(ToolError, match="tracks|trilha"):
        mcp_server.edit_project("historico-mcp", {"type": "track_set", "track": "ZZ", "gain_db": 1})
