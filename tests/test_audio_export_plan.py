"""Exportação múltipla de áudio, a parte pura: nomes de arquivo, regiões, pausas, seleção e trilhas."""

from __future__ import annotations

import pytest

from dmaker.domain.audio_export import (
    STEM_NAMES,
    available_stems,
    region_files,
    sanitize_file_name,
    selection_file,
    stem_files,
)
from dmaker.domain.markers import MarkerError
from dmaker.domain.spec import Marker


def region(start, end, text="", group=""):
    return Marker(start=start, end=end, text=text, group=group)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Introdução", "Introdução"),
        ('Parte 1: "o começo"', "Parte 1 o começo"),
        ("a/b\\c|d?e*f", "a b c d e f"),
        ("  espaços   demais  ", "espaços demais"),
        ("termina com ponto...", "termina com ponto"),
        ("CON", "CON_"),
        ("lpt1", "lpt1_"),
        ("", ""),
        ('<>:"/\\|?*', ""),
        ("x" * 200, "x" * 80),
    ],
)
def test_the_marker_text_becomes_a_safe_windows_file_name(text, name):
    assert sanitize_file_name(text) == name


def test_one_file_per_region_named_after_the_marker_in_time_order():
    files = region_files([region(30, 40, "Fim"), region(0, 10, "Abertura"), Marker(at=5, text="ponto")])
    assert [(f.name, f.start, f.end) for f in files] == [("Abertura", 0, 10), ("Fim", 30, 40)]
    assert all(f.kind == "region" and f.duration == f.end - f.start for f in files)


def test_a_region_without_text_or_with_a_repeated_text_is_numbered():
    files = region_files(
        [
            region(0, 1, "Intro"),
            region(1, 2, ""),
            region(2, 3, "intro"),
            region(3, 4, "Final"),
            region(4, 5, "???"),
        ]
    )
    # "Intro" e "intro" se repetem (sem diferenciar maiúscula); sem texto (ou só caracteres proibidos) vira regiao-NN
    assert [f.name for f in files] == ["Intro-01", "regiao-02", "intro-03", "Final", "regiao-05"]
    assert len({f.name.casefold() for f in files}) == len(files)


def test_numbering_in_front_follows_the_audacity_option():
    files = region_files([region(0, 1, "A"), region(1, 2, "B")], numbered=True)
    assert [f.name for f in files] == ["01 - A", "02 - B"]


def test_the_number_of_digits_grows_with_the_amount_of_regions():
    files = region_files([region(i, i + 1, "") for i in range(120)])
    assert files[0].name == "regiao-001" and files[-1].name == "regiao-120"


def test_pauses_are_the_gaps_before_and_between_regions_even_when_they_overlap():
    files = region_files([region(2, 5, "A"), region(4, 8, "B"), region(10, 12, "C")], pauses=True)
    assert [(f.name, f.kind, f.start, f.end) for f in files] == [
        ("pausa-01", "pause", 0.0, 2),
        ("A", "region", 2, 5),
        ("B", "region", 4, 8),
        ("pausa-02", "pause", 8, 10),
        ("C", "region", 10, 12),
    ]
    assert (
        region_files([region(0, 3, "A"), region(3, 6, "B")], pauses=True)[0].kind == "region"
    )  # sem vazios, sem pausas


def test_only_the_regions_of_the_asked_group_go():
    markers = [region(0, 1, "a", "capitulos"), region(1, 2, "b", "outros"), region(2, 3, "c", "capitulos")]
    assert [f.name for f in region_files(markers, "capitulos")] == ["a", "c"]
    with pytest.raises(MarkerError, match="grupo 'vazio'"):
        region_files(markers, "vazio")


def test_without_regions_the_error_says_how_to_create_them():
    with pytest.raises(MarkerError, match="não tem regiões"):
        region_files([Marker(at=1, text="só um ponto")])


def test_the_selection_takes_seconds_or_markers_and_a_region_marker_gives_exactly_that_region():
    markers = [region(10, 20, "Intro"), Marker(at=35, text="fim")]
    assert (selection_file(markers, 3, 8).start, selection_file(markers, 3, 8).end) == (3, 8)
    exact = selection_file(markers, "marker:Intro", "marker:Intro")
    assert (exact.start, exact.end) == (10, 20)
    open_end = selection_file(markers, "marker:fim", None)
    assert (open_end.start, open_end.end) == (35, None) and open_end.duration is None


def test_a_selection_that_does_not_make_sense_explains_why():
    with pytest.raises(MarkerError, match="depois do início"):
        selection_file([], 5, 5)
    with pytest.raises(MarkerError, match="não existe o marcador"):
        selection_file([], "marker:nada", None)
    with pytest.raises(MarkerError, match="negativo"):
        selection_file([], -1, 4)


def test_one_file_per_track_that_the_project_has_and_unknown_tracks_are_refused():
    have = available_stems(has_clips=False, narrations=1, voice_files=0, has_music=True, has_sfx=False)
    assert have == ["NAR", "MUS"]
    assert [f.track for f in stem_files(have)] == ["NAR", "MUS"]
    assert [f.name for f in stem_files(have, ["MUS"])] == [STEM_NAMES["MUS"]]
    with pytest.raises(MarkerError, match="não tem a trilha SFX"):
        stem_files(have, ["SFX"])
    with pytest.raises(MarkerError, match="trilha desconhecida"):
        stem_files(have, ["XYZ"])
    with pytest.raises(MarkerError, match="nenhuma trilha"):
        stem_files([])
