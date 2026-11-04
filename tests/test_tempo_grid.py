"""A grade do andamento do projeto: contas puras (tempos, compassos, encaixe), as referências `beat:`/`bar:` e a spec.

O critério do card: com o snap ligado, um corte arrastado perto de um tempo cai exatamente nele. A conta que decide isso é
`snap_to_grid`; a interface repete a mesma em TypeScript (`gridSnapPoints`/`snapTime`), com o mesmo caso de teste.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmaker.domain.edits import EditError
from dmaker.domain.markers import MarkerError, is_time_ref, resolve_instant
from dmaker.domain.spec import Marker, Project
from dmaker.domain.tempo_grid import (
    Tempo,
    TempoError,
    bar_time,
    beat_number_at,
    beat_time,
    grid_bars,
    grid_beats,
    grid_instant,
    is_grid_ref,
    nearest_grid_point,
    parse_grid_ref,
    parse_signature,
    position_label,
    snap_to_grid,
)
from dmaker.pipeline.edits import apply_edit

FOUR_FOUR = Tempo(bpm=120.0)


# ---------- o modelo ----------


def test_a_beat_lasts_sixty_over_bpm_and_a_bar_has_the_beats_of_the_signature():
    assert FOUR_FOUR.period == pytest.approx(0.5)
    assert FOUR_FOUR.beats_per_bar == 4 and FOUR_FOUR.bar_period == pytest.approx(2.0)
    waltz = Tempo(bpm=90.0, time_signature="3/4")
    assert waltz.beats_per_bar == 3 and waltz.bar_period == pytest.approx(3 * 60.0 / 90.0)
    assert Tempo(bpm=100.0, time_signature="6/8").beats_per_bar == 6


@pytest.mark.parametrize("bad", ["4", "4/3", "0/4", "100/4", "a/b", "4/", "4/4/4"])
def test_a_bad_time_signature_is_refused_with_the_rule(bad):
    with pytest.raises(ValidationError, match="fórmula de compasso"):
        Tempo(bpm=120.0, time_signature=bad)
    with pytest.raises(TempoError, match="como 4/4"):
        parse_signature(bad)


@pytest.mark.parametrize("bpm", [0, 19.9, 400.1, -5])
def test_the_bpm_stays_inside_the_playable_range(bpm):
    with pytest.raises(ValidationError):
        Tempo(bpm=bpm)


def test_the_tempo_refuses_unknown_fields():
    with pytest.raises(ValidationError):
        Tempo(bpm=120.0, swing=0.2)  # type: ignore[call-arg]


# ---------- a grade ----------


def test_beats_and_bars_count_from_one_at_the_offset():
    tempo = Tempo(bpm=120.0, offset=1.0)
    assert beat_time(tempo, 1) == pytest.approx(1.0)
    assert beat_time(tempo, 5) == pytest.approx(3.0)
    assert bar_time(tempo, 1) == pytest.approx(1.0)
    assert bar_time(tempo, 9) == pytest.approx(1.0 + 8 * 2.0)  # o compasso 9 de 4/4 a 120 BPM
    assert beat_number_at(tempo, 3.0) == pytest.approx(5.0)


def test_grid_beats_and_bars_list_the_instants_of_a_window():
    assert grid_beats(FOUR_FOUR, 0.0, 2.0) == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert grid_bars(FOUR_FOUR, 0.0, 6.0) == [0.0, 2.0, 4.0, 6.0]
    assert grid_beats(Tempo(bpm=60.0, offset=0.25), 1.0, 3.0) == [
        1.25,
        2.25,
    ]  # o primeiro tempo depois do início
    assert grid_beats(Tempo(bpm=60.0, offset=5.0), 0.0, 4.0) == []  # a grade começa no offset


def test_a_window_that_would_list_too_many_points_is_refused():
    with pytest.raises(TempoError, match="peça um trecho menor"):
        grid_beats(Tempo(bpm=400.0), 0.0, 3600.0 * 10)


# ---------- o encaixe: a conta pura do critério ----------


def test_a_cut_dragged_near_a_beat_lands_exactly_on_it():
    tempo = Tempo(bpm=120.0, offset=0.1)
    # 3,12 s está a 20 ms do tempo 7 (3,1 s): dentro de 30 ms de tolerância cai exatamente nele
    assert snap_to_grid(tempo, 3.12, 0.03) == 3.1
    assert snap_to_grid(tempo, 3.08, 0.03) == 3.1
    assert snap_to_grid(tempo, 3.2, 0.03) == 3.2  # longe de todo tempo: fica onde estava
    assert snap_to_grid(tempo, 3.34, 0.03) == 3.34  # a 160 ms do tempo 7 e a 160 ms do 8: nenhum atrai


def test_snapping_to_bars_ignores_the_beats_in_between():
    assert snap_to_grid(FOUR_FOUR, 3.95, 0.1, level="bar") == 4.0
    assert (
        snap_to_grid(FOUR_FOUR, 3.45, 0.1, level="bar") == 3.45
    )  # é um tempo, mas não um início de compasso


def test_the_grid_starts_at_the_offset_so_an_earlier_instant_snaps_to_the_first_beat():
    assert nearest_grid_point(Tempo(bpm=120.0, offset=1.0), 0.2) == 1.0


def test_the_ruler_reads_bar_dot_beat():
    assert position_label(FOUR_FOUR, 0.0) == "1.1"
    assert position_label(FOUR_FOUR, 1.5) == "1.4"
    assert position_label(FOUR_FOUR, 2.0) == "2.1"
    assert position_label(Tempo(bpm=120.0, time_signature="3/4"), 1.5) == "2.1"
    assert position_label(FOUR_FOUR, 16.0) == "9.1"


# ---------- as referências beat:<n> e bar:<n> ----------


def test_a_grid_reference_is_recognised_and_parsed():
    assert is_grid_ref("beat:17") and is_grid_ref(" Bar:9 ") and not is_grid_ref("marker:refrão")
    assert not is_grid_ref(3.0)
    ref = parse_grid_ref("bar:9")
    assert (ref.unit, ref.number) == ("bar", 9)
    assert is_time_ref("beat:1") and is_time_ref("marker:a") and not is_time_ref("12")


@pytest.mark.parametrize("bad", ["beat:0", "bar:-1", "beat:", "beat:um", "bar:2.5"])
def test_a_grid_reference_needs_a_whole_number_from_one(bad):
    with pytest.raises(TempoError, match="inteiro a partir de 1"):
        parse_grid_ref(bad)


def test_the_bar_nine_of_a_120_bpm_four_four_project_is_sixteen_seconds_in():
    assert grid_instant(FOUR_FOUR, "bar:9") == 16.0
    assert grid_instant(FOUR_FOUR, "beat:17") == 8.0


def test_a_grid_reference_without_a_tempo_is_refused_with_the_way_out():
    with pytest.raises(TempoError, match="tempo_set"):
        grid_instant(None, "bar:9")
    with pytest.raises(MarkerError, match="audio.tempo"):
        resolve_instant("bar:9", [], "at")


def test_resolve_instant_takes_numbers_markers_and_the_grid_in_one_place():
    markers = [Marker(at=7.5, text="refrão")]
    assert resolve_instant(2, markers) == 2.0
    assert resolve_instant("marker:refrão", markers) == 7.5
    assert resolve_instant("beat:3", markers, "start", FOUR_FOUR) == 1.0
    with pytest.raises(MarkerError, match="beat:<n>"):
        resolve_instant("depois", markers)


# ---------- a spec e as operações ----------


def project_with(**audio) -> Project:
    return Project.model_validate(
        {
            "name": "ritmo",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [
                {"type": "card", "title": "a", "duration": 10.0},
                {"type": "card", "title": "b", "duration": 10.0},
            ],
            "audio": audio,
        }
    )


def test_a_project_without_tempo_dumps_the_same_bytes_as_before_the_field_existed():
    plain = project_with()
    assert "tempo" not in plain.model_dump(mode="json")["audio"]
    music = project_with(music={"src": "m.wav"})
    dumped = music.model_dump(mode="json")["audio"]["music"]
    assert not {"bpm", "beat_offset", "stretch_to_tempo"} & set(
        dumped
    )  # os campos novos vazios não entram no hash


def test_a_project_with_tempo_keeps_it_and_round_trips():
    project = project_with(tempo={"bpm": 120, "time_signature": "3/4", "offset": 0.5})
    assert project.audio.tempo == Tempo(bpm=120, time_signature="3/4", offset=0.5)
    again = Project.model_validate(project.model_dump(mode="json"))
    assert again.audio.tempo == project.audio.tempo


def test_stretching_the_music_needs_its_bpm_and_a_reasonable_ratio():
    with pytest.raises(ValidationError, match="audio.music.bpm"):
        project_with(music={"src": "m.wav", "stretch_to_tempo": True}, tempo={"bpm": 120})
    with pytest.raises(ValidationError, match="razão"):
        project_with(music={"src": "m.wav", "bpm": 30, "stretch_to_tempo": True}, tempo={"bpm": 400})


def test_tempo_set_creates_the_tempo_then_changes_only_the_fields_given():
    project = apply_edit(project_with(), {"type": "tempo_set", "bpm": 100})
    assert project.audio.tempo == Tempo(bpm=100)
    project = apply_edit(project, {"type": "tempo_set", "time_signature": "3/4", "offset": 1.5})
    assert project.audio.tempo == Tempo(bpm=100, time_signature="3/4", offset=1.5)


def test_tempo_set_refuses_a_first_call_without_bpm_and_a_bad_value():
    with pytest.raises(EditError, match="informe o `bpm`"):
        apply_edit(project_with(), {"type": "tempo_set", "time_signature": "3/4"})
    with pytest.raises(EditError):
        apply_edit(project_with(), {"type": "tempo_set", "bpm": 1000})


def test_tempo_set_offset_accepts_a_marker():
    project = project_with()
    project = apply_edit(project, {"type": "marker_add", "at": 1.25, "text": "primeiro tempo"})
    project = apply_edit(project, {"type": "tempo_set", "bpm": 120, "offset": "marker:primeiro tempo"})
    assert project.audio.tempo.offset == 1.25


def test_tempo_remove_takes_it_away_and_refuses_when_there_is_none():
    project = apply_edit(project_with(tempo={"bpm": 120}), {"type": "tempo_remove"})
    assert project.audio.tempo is None
    with pytest.raises(EditError, match="não tem andamento"):
        apply_edit(project, {"type": "tempo_remove"})


def test_music_tempo_set_changes_the_music_and_forgetting_the_bpm_turns_the_stretch_off():
    project = project_with(music={"src": "m.wav"}, tempo={"bpm": 120})
    project = apply_edit(
        project, {"type": "music_tempo_set", "bpm": 100, "beat_offset": 0.12, "stretch_to_tempo": True}
    )
    music = project.audio.music
    assert (music.bpm, music.beat_offset, music.stretch_to_tempo) == (100, 0.12, True)
    project = apply_edit(project, {"type": "music_tempo_set", "bpm": None})
    assert project.audio.music.bpm is None and project.audio.music.stretch_to_tempo is False
    with pytest.raises(EditError, match="não tem música"):
        apply_edit(project_with(), {"type": "music_tempo_set", "bpm": 100})


def test_an_edit_at_bar_nine_cuts_at_sixteen_seconds_and_without_tempo_it_is_refused():
    """A "operação de edição com snap": o agente escreve `at: "bar:9"` e o corte cai exatamente no compasso 9."""
    project = Project.model_validate(
        {
            "name": "corte",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "card", "title": "a", "duration": 30.0}],
            "audio": {"tempo": {"bpm": 120}},
        }
    )
    cut = apply_edit(project, {"type": "split", "index": 0, "at": "bar:9"})
    assert [segment.duration for segment in cut.timeline] == [16.0, 14.0]
    cut = apply_edit(project, {"type": "split", "index": 0, "at": "beat:5"})
    assert [segment.duration for segment in cut.timeline] == [2.0, 28.0]
    bare = project.model_copy(update={"audio": project.audio.model_copy(update={"tempo": None})})
    with pytest.raises(EditError, match="audio.tempo"):
        apply_edit(bare, {"type": "split", "index": 0, "at": "bar:9"})
