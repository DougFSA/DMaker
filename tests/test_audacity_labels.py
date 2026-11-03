"""O .txt de marcadores do Audacity: ler, escrever e a ida e volta byte a byte."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.audacity_labels import format_labels, parse_labels
from dmaker.domain.spec import Marker

DATA = Path(__file__).parent / "data"
TEN_LABELS = DATA / "audacity_labels_10.txt"  # escrito no formato do Audacity: LF, seis casas, UTF-8
SPECTRAL = DATA / "audacity_labels_spectral.txt"


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def test_the_ten_labels_file_comes_in_with_the_same_times_and_texts():
    parsed = parse_labels(read_text(TEN_LABELS))
    assert parsed.warnings == []
    assert len(parsed.markers) == 10
    pairs = [(m.begin, m.finish, m.text, m.is_region) for m in parsed.markers]
    assert pairs == [
        (0.0, 0.0, "Início", False),
        (3.25, 3.25, "palavrão", False),
        (5.5, 12.75, "Introdução", True),
        (12.75, 12.75, "refrão", False),
        (20.123456, 20.123456, "", False),
        (24.0, 31.5, "verso 1/2", True),
        (31.5, 31.5, "Ponte", False),
        (40.000001, 48.999999, "trecho bom", True),
        (52.8, 52.8, "música entra", False),
        (59.999999, 59.999999, "Fim", False),
    ]


def test_ten_labels_go_back_out_identical_byte_by_byte():
    original = TEN_LABELS.read_bytes()
    parsed = parse_labels(original.decode("utf-8"))
    assert format_labels(parsed.markers).encode("utf-8") == original


def test_the_round_trip_also_holds_with_the_windows_line_endings():
    original = TEN_LABELS.read_bytes().replace(b"\n", b"\r\n")
    parsed = parse_labels(original.decode("utf-8"))
    assert len(parsed.markers) == 10 and parsed.warnings == []
    assert format_labels(parsed.markers, "\r\n").encode("utf-8") == original


def test_the_round_trip_survives_going_through_the_spec_json():
    from dmaker.domain.spec import Project

    markers = parse_labels(read_text(TEN_LABELS)).markers
    project = Project.model_validate(
        {
            "name": "ida-e-volta",
            "timeline": [{"type": "card", "title": "x", "duration": 60}],
            "markers": [m.model_dump(exclude_none=True) for m in markers],
        }
    )
    again = Project.from_bytes(project.to_bytes(), Path("."))
    assert format_labels(again.markers) == read_text(TEN_LABELS)


def test_times_are_written_with_six_decimals_and_a_point_whatever_the_value():
    text = format_labels([Marker(at=1), Marker(start=2.5, end=1234.1234567)])
    assert text == "1.000000\t1.000000\t\n2.500000\t1234.123457\t\n"


def test_a_decimal_comma_is_read_and_written_back_with_a_point():
    parsed = parse_labels("1,5\t2,25\ttexto\n")
    assert (parsed.markers[0].start, parsed.markers[0].end) == (1.5, 2.25)
    assert format_labels(parsed.markers) == "1.500000\t2.250000\ttexto\n"


def test_the_markers_are_written_in_start_order_like_the_audacity_keeps_them():
    text = format_labels([Marker(at=9, text="c"), Marker(at=1, text="a"), Marker(at=1, text="b")])
    assert text.splitlines() == ["1.000000\t1.000000\ta", "1.000000\t1.000000\tb", "9.000000\t9.000000\tc"]


def test_tabs_and_line_breaks_in_a_text_become_spaces_so_the_columns_hold():
    text = format_labels([Marker(at=1, text="a\tb\nc")])
    assert text == "1.000000\t1.000000\ta b c\n"


def test_the_whole_text_after_the_second_tab_is_the_label_text():
    parsed = parse_labels("1.000000\t2.000000\tuma\ttexto\tcom tabs\n")
    assert parsed.markers[0].text == "uma\ttexto\tcom tabs"


def test_blank_lines_and_the_bom_are_ignored_and_the_group_is_applied():
    parsed = parse_labels("﻿1.0\t1.0\ta\n\n   \n2.0\t3.0\tb\n", group="meus")
    assert [(m.text, m.group) for m in parsed.markers] == [("a", "meus"), ("b", "meus")]


def test_a_line_that_cannot_be_read_is_skipped_with_its_number():
    text = "1.0\t1.0\tbom\nabc\tdef\tquebrado\n5.0\t2.0\tfim antes do início\n-1.0\t1.0\tnegativo\n7.0\t7.0\tbom 2\n"
    parsed = parse_labels(text)
    assert [m.text for m in parsed.markers] == ["bom", "bom 2"]
    assert parsed.warnings == [
        "Linha 2 ignorada: o início não é um número.",
        "Linha 3 ignorada: o fim vem antes do início.",
        "Linha 4 ignorada: o tempo é negativo.",
    ]


def test_a_line_with_only_a_time_and_a_text_is_an_instant_label():
    parsed = parse_labels("4.5\tsó dois campos\n")
    assert (parsed.markers[0].at, parsed.markers[0].text) == (4.5, "só dois campos")


# ---------- rótulos espectrais ----------


def test_the_spectral_lines_keep_the_frequency_band_of_each_label():
    parsed = parse_labels(read_text(SPECTRAL))
    assert parsed.warnings == []
    bands = [(m.low_hz, m.high_hz) for m in parsed.markers]
    assert bands == [(None, None), (440.0, 880.5), (None, None), (100.0, 8000.0)]


def test_the_spectral_file_goes_back_out_identical_byte_by_byte():
    original = SPECTRAL.read_bytes()
    assert format_labels(parse_labels(original.decode("utf-8")).markers).encode("utf-8") == original


def test_a_spectral_line_right_after_its_label_is_read_too():
    text = "1.0\t1.0\ta\n\\\t200.0\t400.0\n2.0\t2.0\tb\n"
    parsed = parse_labels(text)
    assert [(m.text, m.low_hz, m.high_hz) for m in parsed.markers] == [("a", 200.0, 400.0), ("b", None, None)]


def test_a_broken_spectral_line_changes_nothing_and_does_not_stop_the_reading():
    parsed = parse_labels("1.0\t1.0\ta\n\\\tabc\n2.0\t2.0\tb\n\\\n")
    assert [(m.text, m.low_hz) for m in parsed.markers] == [("a", None), ("b", None)]
    assert parsed.warnings == []


def test_no_marker_with_a_band_means_no_spectral_lines_at_all():
    assert "\\" not in format_labels([Marker(at=1, text="a"), Marker(at=2, text="b")])


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_an_empty_file_has_no_markers_and_exports_nothing(newline):
    assert parse_labels("").markers == [] and parse_labels(newline).markers == []
    assert format_labels([], newline) == ""
