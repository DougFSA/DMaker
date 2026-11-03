"""Marcadores na spec: o modelo, `marker:<texto>`, os regulares e a edição (acrescentar, mudar, remover)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmaker.domain.edits import EditError
from dmaker.domain.marker_edits import add_marker, remove_marker, set_marker
from dmaker.domain.markers import (
    MarkerError,
    find_marker,
    marker_groups,
    marker_instant,
    marker_track_id,
    regular_markers,
    resolve_instant,
)
from dmaker.domain.spec import Marker, Project


def project_with(*markers: dict) -> Project:
    return Project.model_validate(
        {
            "name": "marcadores-teste",
            "timeline": [{"type": "card", "title": "Único", "duration": 60}],
            "markers": list(markers),
        }
    )


# ---------- o modelo ----------


def test_a_marker_is_an_instant_or_a_region_and_nothing_else():
    assert Marker(at=3.5).begin == Marker(at=3.5).finish == 3.5 and not Marker(at=3.5).is_region
    region = Marker(start=2, end=5)
    assert (region.begin, region.finish, region.is_region) == (2, 5, True)
    with pytest.raises(ValidationError, match="at"):
        Marker()
    with pytest.raises(ValidationError, match="não tem `start` nem `end`"):
        Marker(at=1, start=1, end=2)
    with pytest.raises(ValidationError, match="start"):
        Marker(start=2)
    with pytest.raises(ValidationError, match="maior que `start`"):
        Marker(start=4, end=4)


def test_color_is_a_hex_and_the_group_name_has_no_slash():
    assert Marker(at=1, color="#E0A020").color == "#E0A020"
    with pytest.raises(ValidationError, match="#RRGGBB"):
        Marker(at=1, color="vermelho")
    with pytest.raises(ValidationError, match="barra"):
        Marker(at=1, group="a/b")
    assert Marker(at=1, group="  análise ").group == "análise"


def test_a_project_without_markers_saves_the_same_bytes_as_before():
    old = project_with()
    assert b"markers" not in old.to_bytes()
    assert b'"markers"' in project_with({"at": 1, "text": "x"}).to_bytes()


def test_markers_round_trip_through_the_saved_spec(tmp_path):
    project = project_with(
        {"at": 1.5, "text": "a", "color": "#112233"}, {"start": 2, "end": 4, "group": "meus"}
    )
    path = project.save(tmp_path / "spec.json")
    assert Project.load(path).markers == project.markers


def test_a_spec_with_a_wrong_marker_is_refused_whole():
    with pytest.raises(ValidationError):
        project_with({"at": 1, "texto": "campo que não existe"})


# ---------- marker:<texto> ----------


MARKERS = [
    Marker(at=10.0, text="Refrão"),
    Marker(start=20, end=30, text="Intro", group="meus"),
    Marker(at=40.0, text="Ponte", group="meus"),
    Marker(at=50.0, text="Refrão", group="meus"),
]


def test_find_marker_by_text_ignoring_case_accent_and_spaces():
    assert find_marker(MARKERS, "marker:Ponte") == 2
    assert find_marker(MARKERS, "marker:  ponte ") == 2
    assert find_marker(MARKERS, "MARKER:intro") == 1
    assert find_marker([Marker(at=1, text="Refrão  Final")], "marker:refrao final") == 0


def test_two_markers_with_the_same_text_are_ambiguous_until_the_group_is_given():
    with pytest.raises(MarkerError, match="2 marcadores chamados 'Refrão'.*grupo 'meus' em 50 s"):
        find_marker(MARKERS, "marker:Refrão")
    assert find_marker(MARKERS, "marker:meus/Refrão") == 3
    assert marker_instant(MARKERS, "marker:meus/Refrão") == 50.0


def test_a_slash_in_the_text_is_part_of_the_name_when_it_is_not_a_group():
    markers = [Marker(at=3.0, text="verso 1/2")]
    assert find_marker(markers, "marker:verso 1/2") == 0


def test_an_unknown_or_empty_reference_is_a_clear_error():
    with pytest.raises(MarkerError, match="não existe o marcador 'coda'.*Ponte"):
        find_marker(MARKERS, "marker:coda")
    with pytest.raises(MarkerError, match="precisa do texto"):
        find_marker(MARKERS, "marker:")
    with pytest.raises(MarkerError, match="inválida"):
        find_marker(MARKERS, "Ponte")
    with pytest.raises(MarkerError, match="nenhum marcador com texto"):
        find_marker([Marker(at=1)], "marker:x")


def test_a_region_is_referenced_by_its_start():
    assert marker_instant(MARKERS, "marker:Intro") == 20


def test_resolve_instant_takes_numbers_and_marker_references_only():
    assert resolve_instant(2, MARKERS) == 2.0
    assert resolve_instant("marker:Ponte", MARKERS) == 40.0
    for bad in ("12", None, True):
        with pytest.raises(MarkerError, match="número de segundos ou marker"):
            resolve_instant(bad, MARKERS, "at")


def test_groups_keep_the_order_they_first_appear_and_each_has_a_track_id():
    assert marker_groups(MARKERS) == ["", "meus"]
    assert marker_track_id("") == "MK" and marker_track_id("meus") == "MK:meus"


# ---------- marcadores regulares ----------


def test_every_15_seconds_over_60_creates_4_numbered_regions():
    markers = regular_markers(60.0, interval=15)
    assert [(m.start, m.end, m.text) for m in markers] == [
        (0, 15, "1"),
        (15, 30, "2"),
        (30, 45, "3"),
        (45, 60, "4"),
    ]


def test_parts_split_the_range_in_equal_pieces_with_prefix_numbering_and_padding():
    markers = regular_markers(
        60.0, parts=3, start=0, prefix="Parte ", first_number=8, digits=2, group="partes"
    )
    assert [m.text for m in markers] == ["Parte 08", "Parte 09", "Parte 10"]
    assert [(m.start, m.end) for m in markers] == [(0, 20), (20, 40), (40, 60)]
    assert {m.group for m in markers} == {"partes"}


def test_a_leftover_at_the_end_becomes_a_shorter_last_region():
    markers = regular_markers(65.0, interval=15)
    assert len(markers) == 5 and (markers[-1].start, markers[-1].end) == (60, 65)


def test_instant_kind_marks_the_start_of_each_interval_and_a_range_can_be_chosen():
    markers = regular_markers(60.0, interval=10, start=20, end=50, kind="instant", color="#00ff00")
    assert [m.at for m in markers] == [20, 30, 40]
    assert {m.color for m in markers} == {"#00ff00"}


def test_regular_markers_without_float_noise_in_the_edges():
    markers = regular_markers(1.0, parts=3)
    assert [round(m.end, 6) for m in markers] == [0.333333, 0.666667, 1.0]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "`interval`.*ou `parts`"),
        ({"interval": 5, "parts": 3}, "`interval`.*ou `parts`"),
        ({"interval": 0}, "maior que zero"),
        ({"parts": 0}, "pelo menos 1"),
        ({"interval": 5, "start": 70}, "inválido"),
        ({"interval": 5, "end": 90}, "passa do fim"),
        ({"interval": 0.001}, "mais de 10000"),
    ],
)
def test_regular_markers_refuse_a_request_that_makes_no_sense(arguments, message):
    with pytest.raises(MarkerError, match=message):
        regular_markers(60.0, **arguments)


# ---------- editar ----------


def test_add_set_and_remove_a_marker_keep_the_original_project_untouched():
    project = project_with({"at": 1, "text": "a"})
    added = add_marker(project, {"type": "marker_add", "at": 5, "text": "b", "group": "x"})
    assert len(project.markers) == 1 and [m.text for m in added.markers] == ["a", "b"]
    changed = set_marker(added, 1, {"text": "novo", "color": "#abcdef"})
    assert (changed.markers[1].text, changed.markers[1].color, changed.markers[1].at) == (
        "novo",
        "#abcdef",
        5,
    )
    assert [m.text for m in remove_marker(changed, 0).markers] == ["novo"]


def test_set_marker_switches_between_instant_and_region():
    project = project_with({"at": 4, "text": "a"})
    region = set_marker(project, 0, {"start": 4, "end": 6})
    assert (region.markers[0].at, region.markers[0].start, region.markers[0].end) == (None, 4, 6)
    back = set_marker(region, 0, {"at": 5})
    assert (back.markers[0].at, back.markers[0].start, back.markers[0].end) == (5, None, None)
    assert set_marker(back, 0, {"color": None}).markers[0].color is None


def test_marker_edits_say_what_is_wrong_in_portuguese():
    project = project_with({"at": 4, "text": "a"})
    with pytest.raises(EditError, match="desconhecido.*cor"):
        add_marker(project, {"type": "marker_add", "at": 1, "cor": "x"})
    with pytest.raises(EditError, match="nada a mudar"):
        set_marker(project, 0, {"type": "marker_set", "index": 0})
    with pytest.raises(EditError, match="fora do intervalo"):
        remove_marker(project, 3)
    with pytest.raises(EditError):
        add_marker(project, {"type": "marker_add", "text": "sem tempo"})
