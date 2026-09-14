"""Vista de linha do tempo multitrilha: ordem das trilhas, spans, faixas (lanes) e itens sintéticos
(áudio dos clipes, faixas externas, música, legendas)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.spec import Project
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.layout import project_layout
from dmaker.pipeline.timeline_view import TrackItem, build_timeline_view, stack_lanes


def fake_prober(path: Path) -> MediaInfo:
    if path.suffix == ".png":
        return MediaInfo(path, 0.0, 1000, 620, 0.0, True, False, True)
    return MediaInfo(path, 20.0, 1920, 1080, 30.0, True, True, False)


def _item(start: float, end: float) -> TrackItem:
    return TrackItem(
        id="",
        kind="video",
        index=0,
        label="",
        start=start,
        end=end,
        in_point=0.0,
        out_point=None,
        src=None,
        source=None,
        transition=None,
        muted=False,
        extra={},
    )


# ---------- stack_lanes (pura) ----------


def test_stack_lanes_keeps_non_overlapping_in_one_lane():
    items = [_item(0, 2), _item(2, 4), _item(4, 6)]
    lanes = stack_lanes(items)
    assert len(lanes) == 1 and len(lanes[0]) == 3


def test_stack_lanes_splits_overlapping_pips():
    items = [_item(0, 3), _item(1, 4), _item(2, 5)]
    lanes = stack_lanes(items)
    assert len(lanes) == 3  # os três se sobrepõem dois a dois


def test_stack_lanes_reuses_lane_once_free():
    items = [_item(0, 1), _item(0.5, 2), _item(1, 3)]
    lanes = stack_lanes(items)
    assert len(lanes) == 2
    assert [it.start for it in lanes[0]] == [0, 1]  # a primeira faixa reaproveita o espaço livre


# ---------- build_timeline_view ----------


def make_project(tmp_path: Path) -> Project:
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "webcam.mp4").write_bytes(b"x")
    (tmp_path / "trilha.mp3").write_bytes(b"x")
    spec = {
        "name": "vista-teste",
        "timeline": [
            {"type": "clip", "src": "a.mp4", "start": 0, "end": 4},
            {
                "type": "card",
                "title": "Cartão",
                "duration": 3.0,
                "transition": {"type": "fade", "duration": 1.0},
            },
        ],
        "overlays": [
            {"type": "video", "src": "webcam.mp4", "start": 0, "end": 3, "offset": 0.5},
            {"type": "video", "src": "webcam.mp4", "start": 1, "end": 5, "offset": 0.0},
            {"type": "text", "text": "Gancho", "start": 0, "end": 2},
            {"type": "image", "src": "logo", "position": "top-right"},
            {"type": "progress-bar"},
        ],
        "audio": {
            "music": {"src": "trilha.mp3", "volume": 0.2},
            "mute_clips": False,
        },
        "captions": {"source": "auto"},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


def test_track_order_and_ids(tmp_path):
    project = make_project(tmp_path)
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout)
    ids = [t.id for t in view.tracks]
    # V2/V3 (os dois PiPs se sobrepõem: 0-3 e 1-5), TX, GR, V1, A1, MUS, CC (sem audio.tracks -> sem A2)
    assert ids == ["V2", "V3", "TX", "GR", "V1", "A1", "MUS", "CC"]


def test_v1_spans_overlap_by_transition(tmp_path):
    project = make_project(tmp_path)
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout)
    v1 = next(t for t in view.tracks if t.id == "V1")
    first, second = v1.items
    assert first.start == 0 and first.end == 4  # clipe de 4s (start 0, end 4)
    assert second.start == pytest.approx(4 - 1.0)  # cartão entra 1s antes (a transição sobrepõe)
    assert view.total == pytest.approx(4 + 3 - 1.0)


def test_overlay_end_none_becomes_total(tmp_path):
    project = make_project(tmp_path)
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout)
    gr = next(t for t in view.tracks if t.id == "GR")
    logo_item = next(it for it in gr.items if it.kind == "image")
    assert logo_item.end == view.total  # image overlay sem end vai até o fim
    progress_item = next(it for it in gr.items if it.kind == "progress-bar")
    assert progress_item.start == 0 and progress_item.end == view.total


def test_a1_muted_flags(tmp_path):
    (tmp_path / "muted.mp4").write_bytes(b"x")
    spec = {
        "name": "muted-teste",
        "timeline": [
            {"type": "clip", "src": "muted.mp4", "start": 0, "end": 2, "mute": True},
        ],
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout)
    a1 = next(t for t in view.tracks if t.id == "A1")
    assert a1.items[0].muted is True


def test_audio_tracks_music_and_captions(tmp_path):
    (tmp_path / "cam1.mp4").write_bytes(b"x")
    (tmp_path / "rec.wav").write_bytes(b"x")
    (tmp_path / "trilha.mp3").write_bytes(b"x")
    spec = {
        "name": "multi-audio",
        "sources": {"cam1": {"src": "cam1.mp4"}, "rec": {"src": "rec.wav", "sync": 2.0}},
        "timeline": [{"type": "clip", "source": "cam1", "start": 0, "end": 3}],
        "audio": {"tracks": [{"source": "rec", "volume": 0.5}], "music": {"src": "trilha.mp3"}},
        "captions": {"source": "auto", "enabled": True},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout)
    ids = [t.id for t in view.tracks]
    assert "A2" in ids and "MUS" in ids and "CC" in ids
    a2 = next(t for t in view.tracks if t.id == "A2")
    assert a2.items[0].label == "rec" and a2.items[0].extra["offset"] == 2.0
    assert a2.items[0].start == 0.0 and a2.items[0].end == view.total
    assert "cam1" in view.sources and view.sources["cam1"]["src"] == "cam1.mp4"


def test_captions_disabled_has_no_cc_track(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    spec = {
        "name": "sem-legenda",
        "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 2}],
        "captions": {"source": "auto", "enabled": False},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout)
    assert "CC" not in [t.id for t in view.tracks]


def test_to_dict_is_json_ready(tmp_path):
    project = make_project(tmp_path)
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout)
    data = view.to_dict()
    assert data["width"] and data["height"] and data["fps"]
    assert isinstance(data["tracks"], list) and isinstance(data["tracks"][0]["items"], list)
