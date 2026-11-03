"""O mapa de tempo e os marcadores seguindo a edição: cortes, inserções, regiões e o aviso do que some."""

from __future__ import annotations

import pytest

from dmaker.domain.spec import Marker
from dmaker.domain.time_map import Piece, TimeMap, describe_marker, shift_markers


def instant(at: float, text: str = "") -> Marker:
    return Marker(at=at, text=text)


def region(start: float, end: float, text: str = "") -> Marker:
    return Marker(start=start, end=end, text=text)


# ---------- o mapa ----------


def test_identity_keeps_every_instant_where_it_was():
    time_map = TimeMap.identity()
    assert time_map.is_identity
    assert time_map.move_instant(0.0) == 0.0
    assert time_map.move_instant(1234.5) == 1234.5


def test_a_removed_interval_pulls_back_what_comes_after_it():
    time_map = TimeMap.from_changes(removed=[(10.0, 13.0)])
    assert time_map.move_instant(5.0) == 5.0
    assert time_map.move_instant(13.0) == pytest.approx(10.0)  # o fim do corte é half-open: o marcador fica
    assert time_map.move_instant(20.0) == pytest.approx(17.0)


def test_an_instant_inside_the_removed_interval_disappears_and_so_does_the_one_at_its_start():
    time_map = TimeMap.from_changes(removed=[(10.0, 13.0)])
    assert time_map.move_instant(11.0) is None
    assert time_map.move_instant(10.0) is None  # o primeiro instante cortado já é cortado


def test_inserted_time_pushes_forward_what_is_at_or_after_the_point():
    time_map = TimeMap.from_changes(inserted=[(10.0, 2.0)])
    assert time_map.move_instant(9.999) == pytest.approx(9.999)
    assert time_map.move_instant(10.0) == pytest.approx(12.0)
    assert time_map.move_instant(30.0) == pytest.approx(32.0)


def test_removing_and_inserting_at_once_is_described_in_old_time():
    time_map = TimeMap.from_changes(removed=[(2.0, 4.0)], inserted=[(8.0, 1.0)])
    assert time_map.move_instant(6.0) == pytest.approx(4.0)  # depois do corte, antes da inserção
    assert time_map.move_instant(8.0) == pytest.approx(7.0)  # no ponto da inserção: -2 + 1
    assert time_map.move_instant(9.0) == pytest.approx(8.0)


def test_overlapping_and_touching_removals_merge():
    time_map = TimeMap.from_changes(removed=[(5.0, 8.0), (7.0, 10.0), (10.0, 11.0)])
    assert time_map.move_instant(4.0) == 4.0
    assert time_map.move_instant(9.0) is None
    assert time_map.move_instant(11.0) == pytest.approx(5.0)


def test_pieces_are_joined_when_a_point_changes_nothing():
    time_map = TimeMap.from_changes(inserted=[(5.0, 0.0)])
    assert time_map.is_identity


def test_a_region_loses_only_the_part_that_was_cut():
    time_map = TimeMap.from_changes(removed=[(10.0, 13.0)])
    assert time_map.move_region(8.0, 12.0) == pytest.approx((8.0, 10.0))  # perdeu a ponta
    assert time_map.move_region(11.0, 15.0) == pytest.approx((10.0, 12.0))  # perdeu o começo
    assert time_map.move_region(5.0, 20.0) == pytest.approx((5.0, 17.0))  # perdeu o miolo
    assert time_map.move_region(11.0, 12.0) is None  # inteira dentro do corte
    assert time_map.move_region(10.0, 13.0) is None


def test_a_region_grows_when_time_is_inserted_inside_it():
    time_map = TimeMap.from_changes(inserted=[(12.0, 2.0)])
    assert time_map.move_region(10.0, 14.0) == pytest.approx((10.0, 16.0))
    assert time_map.move_region(12.0, 14.0) == pytest.approx((14.0, 16.0))  # começa no ponto: anda inteira


def test_pieces_may_point_anywhere_so_a_moved_block_takes_its_markers_along():
    # o bloco [0, 4) foi para depois do bloco [4, 10): ele passa a ficar em [6, 10)
    time_map = TimeMap((Piece(0.0, 4.0, 6.0), Piece(4.0, float("inf"), -4.0)))
    assert time_map.move_instant(1.0) == pytest.approx(7.0)
    assert time_map.move_instant(5.0) == pytest.approx(1.0)


# ---------- os marcadores ----------


def test_cutting_three_seconds_before_a_marker_moves_it_three_seconds_back():
    markers = [instant(5.0, "antes"), instant(20.0, "refrão")]
    result = shift_markers(markers, TimeMap.from_changes(removed=[(17.0, 20.0)]))
    assert [m.at for m in result.markers] == [5.0, 17.0]
    assert result.warnings == []


def test_a_marker_inside_the_cut_is_dropped_with_a_warning_that_names_it():
    markers = [instant(5.0, "antes"), instant(11.5, "palavrão"), instant(30.0, "depois")]
    result = shift_markers(markers, TimeMap.from_changes(removed=[(10.0, 13.0)]))
    assert [m.text for m in result.markers] == ["antes", "depois"]
    assert [m.at for m in result.markers] == [5.0, 27.0]
    assert result.warnings == [
        'O marcador "palavrão" em 11,5 s estava dentro do trecho removido e foi apagado.'
    ]


def test_a_region_that_loses_everything_is_dropped_and_one_that_loses_a_part_shrinks():
    markers = [region(10.5, 12.5, "some"), region(8.0, 11.0, "encolhe"), region(14.0, 18.0, "anda")]
    result = shift_markers(markers, TimeMap.from_changes(removed=[(10.0, 13.0)]))
    assert [m.text for m in result.markers] == ["encolhe", "anda"]
    assert (result.markers[0].start, result.markers[0].end) == (8.0, 10.0)
    assert (result.markers[1].start, result.markers[1].end) == (11.0, 15.0)
    assert result.warnings == [
        'O marcador "some" de 10,5 a 12,5 s estava dentro do trecho removido e foi apagado.'
    ]


def test_shifting_keeps_color_group_and_frequency():
    marker = Marker(at=20.0, text="x", color="#ff0000", group="análise", low_hz=100.0, high_hz=900.0)
    moved = shift_markers([marker], TimeMap.from_changes(removed=[(0.0, 5.0)])).markers[0]
    assert (moved.at, moved.color, moved.group, moved.low_hz, moved.high_hz) == (
        15.0,
        "#ff0000",
        "análise",
        100.0,
        900.0,
    )


def test_the_shifted_time_has_no_float_noise():
    moved = shift_markers([instant(0.3 + 0.6)], TimeMap.from_changes(removed=[(0.0, 0.1)])).markers[0]
    assert moved.at == 0.8


def test_the_identity_map_returns_the_same_markers_and_no_warning():
    markers = [instant(1.0, "a"), region(2.0, 3.0, "b")]
    result = shift_markers(markers, TimeMap.identity())
    assert result.markers == markers and result.warnings == []


def test_describe_marker_reads_like_a_person_would_say_it():
    assert describe_marker(instant(12.0, "refrão")) == '"refrão" em 12 s'
    assert describe_marker(region(1.25, 4.0)) == "sem texto de 1,25 a 4 s"
