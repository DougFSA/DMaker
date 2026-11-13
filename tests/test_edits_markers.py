"""Os marcadores acompanham as edições da linha do tempo, e `marker:<texto>` vale onde a operação pede um instante."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker import mcp_server
from dmaker.domain.edits import EditError, restore_gap
from dmaker.domain.spec import Marker, Project
from dmaker.domain.time_map import TimeMap
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import edits as edits_module
from dmaker.pipeline.edit_time import EDIT_TIME_MAPS, restored_gap_time_map
from dmaker.pipeline.edits import EditOutcome, apply_edit, apply_edit_report
from dmaker.pipeline.layout import aggregate_by_origin, project_layout
from dmaker.pipeline.projects import load_project, save_project, summarize
from dmaker.pipeline.timeline_view import build_timeline_view

from .test_autocut_service import (  # noqa: F401
    FakeTranscriber,
    fake_prober,
    request,
    service,
    writes_the_recording,
)

CARD = {"type": "card", "duration": 20}


def three_cards(
    markers: list[dict] | None = None, transition: dict | None = None, overlays: list[dict] | None = None
) -> Project:
    """Três cartões de 20 s (0 a 20, 20 a 40, 40 a 60), com os marcadores dados."""
    timeline = [
        {**CARD, "title": "um"},
        {**CARD, "title": "dois", **({"transition": transition} if transition else {})},
        {**CARD, "title": "três", **({"transition": transition} if transition else {})},
    ]
    return Project.model_validate(
        {"name": "mk-edits", "timeline": timeline, "markers": markers or [], "overlays": overlays or []}
    )


MARKERS = [
    {"at": 5.0, "text": "A"},
    {"at": 25.0, "text": "B"},
    {"at": 45.0, "text": "C"},
    {"start": 22.0, "end": 38.0, "text": "R"},
    {"at": 60.0, "text": "fim"},
]


def times(project: Project) -> dict[str, tuple[float, float]]:
    return {m.text: (m.begin, m.finish) for m in project.markers}


# ---------- tirar tempo ----------


def test_removing_a_segment_pulls_back_what_comes_after_and_drops_what_was_inside():
    report = apply_edit_report(three_cards(MARKERS), {"type": "remove", "index": 1})
    assert times(report.project) == {"A": (5, 5), "C": (25, 25), "fim": (40, 40)}
    assert report.warnings == [
        'O marcador "B" em 25 s estava dentro do trecho removido e foi apagado.',
        'O marcador "R" de 22 a 38 s estava dentro do trecho removido e foi apagado.',
    ]


def test_removing_the_first_segment_drops_what_was_in_it_and_shifts_the_rest():
    report = apply_edit_report(three_cards(MARKERS), {"type": "remove", "index": 0})
    assert times(report.project) == {"B": (5, 5), "C": (25, 25), "R": (2, 18), "fim": (40, 40)}
    assert len(report.warnings) == 1 and '"A" em 5 s' in report.warnings[0]


def test_removing_the_last_segment_drops_what_was_in_it_and_after_the_end():
    report = apply_edit_report(three_cards(MARKERS), {"type": "remove", "index": 2})
    assert times(report.project) == {"A": (5, 5), "B": (25, 25), "R": (22, 38)}
    assert [w.split(" ")[2] for w in report.warnings] == ['"C"', '"fim"']


def test_trimming_the_out_edge_cuts_three_seconds_and_moves_what_is_after_it():
    markers = [{"at": 18.0, "text": "no corte"}, {"at": 25.0, "text": "depois"}]
    report = apply_edit_report(three_cards(markers), {"type": "trim", "index": 0, "side": "out", "delta": -3})
    assert times(report.project) == {"depois": (22, 22)}
    assert "no corte" in report.warnings[0]


def test_trimming_the_in_edge_drops_the_head_and_the_content_that_stays_moves_with_the_cut():
    markers = [{"at": 22.0, "text": "cabeça"}, {"at": 25.0, "text": "B"}, {"at": 45.0, "text": "C"}]
    report = apply_edit_report(three_cards(markers), {"type": "trim", "index": 1, "side": "in", "delta": 5})
    assert times(report.project) == {"B": (20, 20), "C": (40, 40)}  # o segundo trecho perdeu 5 s no começo
    assert "cabeça" in report.warnings[0]


def test_lengthening_the_in_edge_pushes_everything_in_the_segment_forward():
    report = apply_edit_report(
        three_cards([{"at": 25.0, "text": "B"}, {"at": 5.0, "text": "A"}]),
        {"type": "trim", "index": 1, "side": "in", "delta": -5},
    )
    assert times(report.project) == {"A": (5, 5), "B": (30, 30)}
    assert report.warnings == []


def test_changing_a_duration_by_set_field_moves_the_markers_after_it_and_drops_the_ones_in_the_lost_tail():
    markers = [*MARKERS, {"at": 35.0, "text": "D"}]
    report = apply_edit_report(
        three_cards(markers), {"type": "set_field", "path": "timeline.1.duration", "value": 10}
    )
    assert times(report.project) == {
        "A": (5, 5),
        "B": (25, 25),
        "C": (35, 35),
        "R": (22, 30),
        "fim": (50, 50),
    }
    assert [w.split(" ")[2] for w in report.warnings] == ['"D"']


# ---------- pôr tempo e mudar de lugar ----------


def test_duplicating_a_segment_pushes_forward_the_markers_after_it_and_keeps_the_ones_inside():
    report = apply_edit_report(three_cards(MARKERS), {"type": "duplicate", "index": 0})
    assert times(report.project) == {
        "A": (5, 5),
        "B": (45, 45),
        "C": (65, 65),
        "R": (42, 58),
        "fim": (80, 80),
    }
    assert report.warnings == []


def test_inserting_a_segment_pushes_forward_what_is_after_the_point():
    op = {"type": "insert", "index": 1, "segment": {"type": "card", "title": "novo", "duration": 7}}
    report = apply_edit_report(three_cards(MARKERS), op)
    assert times(report.project) == {
        "A": (5, 5),
        "B": (32, 32),
        "C": (52, 52),
        "R": (29, 45),
        "fim": (67, 67),
    }


def test_moving_a_segment_takes_its_markers_along():
    report = apply_edit_report(three_cards(MARKERS), {"type": "move", "index": 0, "to": 2})
    assert times(report.project) == {"A": (45, 45), "B": (5, 5), "C": (25, 25), "R": (2, 18)}
    assert [w.split(" ")[2] for w in report.warnings] == ['"fim"']  # o fim de antes não é mais o fim do vídeo


def test_a_transition_overlap_does_not_make_markers_jump():
    transition = {"type": "fade", "duration": 1.0}
    markers = [{"at": 10.0, "text": "A"}, {"at": 45.0, "text": "C"}, {"at": 25.0, "text": "B"}]
    report = apply_edit_report(three_cards(markers, transition), {"type": "remove", "index": 1})
    # o terceiro trecho começava em 38 s (a transição de 1 s o puxa para trás) e passa a começar em 19 s
    assert times(report.project) == {"A": (10, 10), "C": (26, 26)}
    assert 'O marcador "B"' in report.warnings[0]


# ---------- o que não mexe no tempo ----------


@pytest.mark.parametrize(
    "op",
    [
        {"type": "split", "index": 1, "at": 5},
        {"type": "overlay_span", "index": 0, "start": 3, "end": 9},
        {"type": "overlay_remove", "index": 0},
        {"type": "set_field", "path": "audio.music", "value": None},
        {"type": "marker_set", "index": 0, "text": "outro"},
    ],
)
def test_edits_that_keep_the_time_leave_every_marker_where_it_is(op):
    project = three_cards(MARKERS, overlays=[{"type": "text", "text": "t", "start": 0, "end": 5}])
    report = apply_edit_report(project, op)
    assert [(m.begin, m.finish) for m in report.project.markers] == [
        (m.begin, m.finish) for m in project.markers
    ]
    assert report.warnings == []


def test_without_markers_no_time_map_is_ever_calculated(monkeypatch):
    def boom(change):
        raise AssertionError("não devia calcular nada sem marcador")

    monkeypatch.setitem(EDIT_TIME_MAPS, "remove", boom)
    report = apply_edit_report(three_cards(), {"type": "remove", "index": 1})
    assert len(report.project.timeline) == 2 and report.warnings == [] and report.time_map.is_identity


def test_an_edit_with_no_time_map_registered_does_not_touch_the_markers(monkeypatch):
    monkeypatch.delitem(EDIT_TIME_MAPS, "remove")
    report = apply_edit_report(three_cards(MARKERS), {"type": "remove", "index": 1})
    assert times(report.project) == times(three_cards(MARKERS))


def test_set_field_that_changes_the_number_of_segments_warns_that_markers_did_not_follow():
    timeline = [{**CARD, "title": "só um"}]
    report = apply_edit_report(
        three_cards(MARKERS), {"type": "set_field", "path": "timeline", "value": timeline}
    )
    assert report.warnings == [
        "Os marcadores não acompanharam esta mudança na linha do tempo: confira a posição deles."
    ]
    assert times(report.project) == times(three_cards(MARKERS))


def test_an_operation_that_knows_its_intervals_returns_the_time_map_itself(monkeypatch):
    def cut_ten_to_twelve(project, op, layout):
        return EditOutcome(project, TimeMap.from_changes(removed=[(10.0, 12.0)]))

    monkeypatch.setitem(edits_module.EDIT_OPERATIONS, "cortar_faixa", cut_ten_to_twelve)
    markers = [{"at": 11.0, "text": "dentro"}, {"at": 30.0, "text": "depois"}]
    report = apply_edit_report(three_cards(markers), {"type": "cortar_faixa"})
    assert times(report.project) == {"depois": (28, 28)}
    assert len(report.warnings) == 1 and "dentro" in report.warnings[0]


def test_the_original_project_is_never_changed():
    project = three_cards(MARKERS)
    apply_edit_report(project, {"type": "remove", "index": 0})
    assert times(project) == times(three_cards(MARKERS)) and len(project.timeline) == 3


# ---------- marker:<texto> ----------


def test_split_at_a_marker_cuts_exactly_there_without_saying_which_segment():
    project = three_cards(MARKERS)
    new = apply_edit(project, {"type": "split", "at": "marker:B"})
    assert [seg.duration for seg in new.timeline] == [20, 5, 15, 20]  # B está a 5 s do começo do 2º trecho
    assert times(new) == times(project)


def test_split_at_a_marker_with_an_index_checks_that_the_marker_is_inside_that_segment():
    project = three_cards(MARKERS)
    assert apply_edit(project, {"type": "split", "index": 1, "at": "marker:B"}).timeline[1].duration == 5
    with pytest.raises(EditError, match="entre 0 e a duração do trecho"):
        apply_edit(project, {"type": "split", "index": 0, "at": "marker:B"})
    with pytest.raises(EditError, match="fora do intervalo"):
        apply_edit(project, {"type": "split", "index": 9, "at": "marker:B"})


def test_split_at_a_marker_outside_the_timeline_or_on_a_seam_is_a_clear_error():
    project = three_cards(MARKERS)
    with pytest.raises(EditError, match="fora da linha do tempo"):
        apply_edit(project, {"type": "split", "at": "marker:fim"})
    with pytest.raises(EditError):
        apply_edit(three_cards([{"at": 20.0, "text": "emenda"}]), {"type": "split", "at": "marker:emenda"})


def test_a_marker_with_a_group_and_a_duplicated_text_asks_for_the_group():
    markers = [{"at": 5.0, "text": "x"}, {"at": 25.0, "text": "x", "group": "meus"}]
    project = three_cards(markers)
    with pytest.raises(EditError, match="2 marcadores chamados"):
        apply_edit(project, {"type": "split", "at": "marker:x"})
    new = apply_edit(project, {"type": "split", "at": "marker:meus/x"})
    assert [seg.duration for seg in new.timeline] == [20, 5, 15, 20]


def test_an_unknown_marker_is_an_edit_error_in_portuguese():
    with pytest.raises(EditError, match="não existe o marcador 'coda'"):
        apply_edit(three_cards(MARKERS), {"type": "split", "at": "marker:coda"})


def test_overlay_span_takes_markers_in_start_and_end():
    project = three_cards(MARKERS, overlays=[{"type": "text", "text": "t", "start": 0, "end": 3}])
    new = apply_edit(project, {"type": "overlay_span", "index": 0, "start": "marker:A", "end": "marker:B"})
    assert (new.overlays[0].start, new.overlays[0].end) == (5.0, 25.0)
    with pytest.raises(EditError, match="número de segundos ou marker"):
        apply_edit(project, {"type": "overlay_span", "index": 0, "start": "cedo"})


# ---------- operações dos marcadores ----------


def test_marker_operations_add_change_and_remove_with_index_or_reference():
    project = three_cards([{"at": 5.0, "text": "A"}])
    added = apply_edit(project, {"type": "marker_add", "at": 12.5, "text": "novo", "color": "#00ff00"})
    assert times(added) == {"A": (5, 5), "novo": (12.5, 12.5)}
    moved = apply_edit(added, {"type": "marker_set", "ref": "marker:novo", "at": 14})
    assert times(moved)["novo"] == (14, 14)
    renamed = apply_edit(moved, {"type": "marker_set", "index": 1, "text": "outro nome"})
    assert "outro nome" in times(renamed)
    assert times(apply_edit(renamed, {"type": "marker_remove", "ref": "marker:A"})) == {
        "outro nome": (14, 14)
    }
    with pytest.raises(EditError, match="informe `index`"):
        apply_edit(renamed, {"type": "marker_remove"})


# ---------- a vista ----------


def test_the_timeline_view_has_one_marker_track_per_group_with_the_items_in_time_order():
    markers = [
        {"at": 30.0, "text": "tarde"},
        {"start": 5.0, "end": 9.0, "text": "região", "color": "#112233"},
        {"at": 12.0, "text": "análise 1", "group": "análise", "low_hz": 100.0, "high_hz": 900.0},
    ]
    project = three_cards(markers)
    layout = project_layout(project, lambda path: MediaInfo(path, 5.0, 1, 1, 30.0, True, True, False))
    view = build_timeline_view(project, layout)
    tracks = {track.id: track for track in view.tracks}
    assert [track.id for track in view.tracks][-2:] == ["MK", "MK:análise"]
    assert tracks["MK"].kind == "markers" and tracks["MK"].label == "MK"
    assert tracks["MK:análise"].label == "MK análise"
    first, second = tracks["MK"].items
    assert (first.id, first.kind, first.index, first.label, first.start, first.end) == (
        "MK-1",
        "marker",
        1,
        "região",
        5.0,
        9.0,
    )
    assert first.extra == {"color": "#112233", "group": "", "instant": False}
    assert (second.id, second.start, second.end, second.extra["instant"]) == ("MK-0", 30.0, 30.0, True)
    assert tracks["MK:análise"].items[0].extra["low_hz"] == 100.0


def test_the_timeline_view_of_a_project_without_markers_has_no_marker_track():
    project = three_cards()
    layout = project_layout(project, lambda path: MediaInfo(path, 5.0, 1, 1, 30.0, True, True, False))
    assert all(track.kind != "markers" for track in build_timeline_view(project, layout).tracks)


# ---------- o desfazer do corte ----------


def clip_project(markers: list[dict]) -> Project:
    """Uma gravação de 5 s cortada em dois clipes: sobrou 0 a 2 e 3 a 5, e o 2 a 3 saiu."""
    return Project.model_validate(
        {
            "name": "mk-undo",
            "timeline": [
                {"type": "clip", "src": "a.mp4", "start": 0, "end": 2},
                {"type": "clip", "src": "a.mp4", "start": 3, "end": 5},
            ],
            "markers": markers,
        }
    )


def prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 5.0, 1920, 1080, 30.0, True, True, False)


def test_undoing_a_cut_pushes_forward_the_markers_after_the_gap(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    before = clip_project([{"at": 1.0, "text": "antes"}, {"at": 3.0, "text": "depois"}])
    before.base_dir = tmp_path
    restored = restore_gap(before, 2.0, 3.0)
    restored.base_dir = tmp_path

    def layout(project: Project):
        return aggregate_by_origin(project, project_layout(project, prober))

    time_map = restored_gap_time_map(before, restored, layout(before), layout(restored))
    assert time_map.move_instant(1.0) == 1.0  # antes do corte desfeito: fica
    assert time_map.move_instant(3.0) == pytest.approx(4.0)  # depois: avança o 1 s que voltou


# ---------- as ferramentas do servidor MCP ----------


def test_edit_project_tool_cuts_at_a_marker_and_reports_the_markers_it_dropped():
    save_project(three_cards(MARKERS))

    cut = mcp_server.edit_project("mk-edits", {"type": "split", "at": "marker:B"})
    assert [seg["duration_s"] for seg in cut["segments"]] == [20, 5, 15, 20]
    assert "edit_warnings" not in cut
    assert times(load_project("mk-edits"))["B"] == (25, 25)  # cortar não mexe no tempo

    # tirar os 5 s que vinham antes do B: ele recua 5 s e a região R perde a ponta
    shorter = mcp_server.edit_project("mk-edits", {"type": "remove", "index": 1})
    assert "edit_warnings" not in shorter
    saved = times(load_project("mk-edits"))
    assert saved["B"] == (20, 20) and saved["R"] == (20, 33) and saved["fim"] == (55, 55)

    # tirar o trecho em que o B e o R estão: os dois somem, e o aviso diz quais
    emptied = mcp_server.edit_project("mk-edits", {"type": "remove", "index": 1})
    assert [w.split(" ")[2] for w in emptied["edit_warnings"]] == ['"B"', '"R"']
    assert set(times(load_project("mk-edits"))) == {"A", "C", "fim"}


def test_timeline_view_tool_lists_the_marker_track():
    save_project(three_cards([{"at": 5.0, "text": "A"}]))
    view = mcp_server.timeline_view("mk-edits")
    assert view["tracks"][-1]["id"] == "MK" and view["tracks"][-1]["items"][0]["label"] == "A"


def test_validate_project_warns_about_a_marker_after_the_end_and_repeated_texts():
    project = three_cards([{"at": 99.0, "text": "longe"}, {"at": 1.0, "text": "x"}, {"at": 2.0, "text": "x"}])
    warnings = summarize(project).warnings
    assert any("markers[0]" in w and "depois do fim do vídeo" in w for w in warnings)
    assert any("markers[2]" in w and "já é de markers[1]" in w for w in warnings)


def test_undo_cut_of_an_autocut_project_moves_the_markers_that_come_after_the_gap(tmp_path):
    from dmaker.pipeline.autocut import load_cut_report, undo_cut

    source = tmp_path / "gravacao.mp4"
    source.write_bytes(b"x" * 64)
    result = service().cut(request(source, intensity="agressiva"))
    project = load_project("corte")
    end_of_video = summarize(project, prober=fake_prober).total
    marked = project.model_copy(
        update={
            "markers": [Marker(at=end_of_video - 0.5, text="perto do fim"), Marker(at=0.1, text="começo")]
        }
    )
    save_project(marked)

    first_cut = result.report.cuts[0]
    undo_cut("corte", first_cut.id, prober=fake_prober)

    after = times(load_project("corte"))
    assert after["começo"] == (0.1, 0.1)  # antes do trecho que voltou: não anda
    expected = end_of_video - 0.5 + (first_cut.end - first_cut.start)
    assert after["perto do fim"][0] == pytest.approx(expected, abs=0.01)
    assert load_cut_report(load_project("corte").base_dir).find(first_cut.id).undone
