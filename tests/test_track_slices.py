"""Conta das faixas externas por trecho (`pipeline/track_slices.py`): cobertura, ponto no arquivo e a
janela em que a faixa soa na linha do tempo final. Pura, sem disco nem ffmpeg."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.spec import AudioTrack, ClipSegment, Project
from dmaker.filtergraph.mezzanine import TrackSlice
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.sources import Source, part_name, physical_source_names
from dmaker.pipeline.track_slices import source_covers, track_slice, track_slices, track_window


def _recorder(offset: float, duration: float = 100.0, name: str = "rec") -> Source:
    path = Path(f"{name}.wav")
    return Source(path, MediaInfo(path, duration, 0, 0, 0.0, False, True, False), offset, 0, name)


def _clip(start: float, end: float | None, source: str = "cam") -> ClipSegment:
    return ClipSegment(source=source, start=start, end=end)


# ---------- source_covers / track_slice ----------


def test_source_covers_only_when_the_file_records_part_of_the_clip():
    rec = _recorder(offset=50.0, duration=20.0)  # grava a sessão de 50 s a 70 s
    assert source_covers(rec, _clip(40, 60))
    assert source_covers(rec, _clip(60, 90))
    assert not source_covers(rec, _clip(0, 50))  # acaba de começar quando o clipe termina
    assert not source_covers(rec, _clip(70, 80))  # o arquivo já tinha acabado
    assert source_covers(rec, _clip(60, None))  # sem fim: vai até onde o arquivo for


def test_track_slice_carries_the_files_in_point_volume_and_stream():
    rec = _recorder(offset=-3.0)
    piece = track_slice(AudioTrack(source="rec", volume=0.5), rec, _clip(20, 30))
    assert piece == TrackSlice(rec.path, 23.0, 0.5, 0)
    assert track_slice(AudioTrack(source="rec"), _recorder(offset=500.0), _clip(20, 30)) is None


def test_track_slices_keep_the_track_order_and_skip_uncovered_ones():
    session = {"a": _recorder(0.0, name="a"), "b": _recorder(500.0, name="b"), "c": _recorder(0.0, name="c")}
    tracks = [AudioTrack(source="a"), AudioTrack(source="b"), AudioTrack(source="c", volume=2.0)]
    pieces = track_slices(tracks, session, _clip(10, 20))
    assert [(p.path.name, p.volume) for p in pieces] == [("a.wav", 1.0), ("c.wav", 2.0)]


# ---------- track_window ----------


def test_window_of_a_track_that_covers_the_whole_clip():
    window = track_window(TrackSlice(Path("r.wav"), 23.0), 100.0, 1.0, (10.0, 20.0))
    assert (window.start, window.end, window.file_in) == (10.0, 20.0, 23.0)


def test_window_of_a_track_that_starts_after_the_clip_does_not_touch_the_file_start():
    """Gravador ligado 4 s depois: a faixa entra atrasada e começa do começo do arquivo, nunca antes."""
    window = track_window(TrackSlice(Path("r.wav"), -4.0), 100.0, 1.0, (10.0, 20.0))
    assert (window.start, window.end, window.file_in) == (14.0, 20.0, 0.0)


def test_window_of_a_track_whose_file_ends_inside_the_clip():
    window = track_window(TrackSlice(Path("r.wav"), 95.0), 100.0, 1.0, (0.0, 10.0))
    assert (window.start, window.end, window.file_in) == (0.0, 5.0, 95.0)


def test_window_scales_delay_and_length_by_the_clip_speed():
    """A 2x o clipe consome 20 s de fonte em 10 s de linha do tempo: o atraso de 4 s vira 2 s."""
    window = track_window(TrackSlice(Path("r.wav"), -4.0), 100.0, 2.0, (5.0, 15.0))
    assert (window.start, window.end, window.file_in) == (7.0, 15.0, 0.0)
    assert track_window(TrackSlice(Path("r.wav"), 0.0), 100.0, 0.5, (0.0, 10.0)).end == pytest.approx(10.0)


def test_window_is_none_when_nothing_of_the_track_falls_in_the_clip():
    assert track_window(TrackSlice(Path("r.wav"), -30.0), 100.0, 1.0, (0.0, 10.0)) is None  # entra depois
    assert track_window(TrackSlice(Path("r.wav"), 100.0), 100.0, 1.0, (0.0, 10.0)) is None  # já acabou


# ---------- nomes das partes ----------


def test_physical_source_names_follow_the_parts_of_the_source():
    project = Project.model_validate(
        {
            "name": "p",
            "sources": {"cam": {"parts": ["a.mp4", "b.mp4", "c.mp4"]}, "mesa": {"src": "mesa.wav"}},
            "timeline": [{"type": "clip", "source": "cam", "end": 5}],
        }
    )
    assert physical_source_names(project, "cam") == ["cam#0", "cam#1", "cam#2"]
    assert physical_source_names(project, "mesa") == ["mesa"]
    assert physical_source_names(project, "desconhecida") == ["desconhecida"]
    assert part_name("cam", 1) == "cam#1"
