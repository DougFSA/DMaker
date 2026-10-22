"""Vista de linha do tempo multitrilha: ordem das trilhas, spans, faixas (lanes) e itens sintéticos
(áudio dos clipes, faixas externas, música, legendas)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.spec import Project, TrackState
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


def test_music_spans_become_one_item_each(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "trilha.mp3").write_bytes(b"x")
    spec = {
        "name": "trilha-em-janelas",
        "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 20}],
        "audio": {
            "music": {"src": "trilha.mp3", "spans": [{"start": 0, "end": 10}, {"start": 15, "start_at": 30}]}
        },
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    mus = next(t for t in view.tracks if t.id == "MUS")
    assert [(i.start, i.end, i.in_point) for i in mus.items] == [(0.0, 10.0, 0.0), (15.0, 20.0, 30.0)]


def test_music_span_from_end_and_tail_resolved_with_total_and_music_duration(tmp_path):
    """Span ancorado no fim do vídeo (`from_end`) e no fim da música (`tail`): a vista mostra o
    instante absoluto (não os 33.5 s brutos) e, com a duração da música, a folga já ancorada."""
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "trilha.mp3").write_bytes(b"x")
    spec = {
        "name": "trilha-no-fim",
        "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 20}],
        "audio": {
            "music": {
                "src": "trilha.mp3",
                "spans": [{"start": 5, "from_end": True, "tail": True, "start_at": 0.5}],
            }
        },
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    layout = project_layout(project, prober=fake_prober)  # total = 20.0 (o clipe inteiro)
    view = build_timeline_view(project, layout, music_duration=12.0)
    mus = next(t for t in view.tracks if t.id == "MUS")
    item = mus.items[0]
    assert (item.start, item.end) == (15.0, 20.0)  # 20 - 5 (from_end) até o fim
    assert item.in_point == 12.0 - 5.0 - 0.5  # duração - comprimento da janela (5s) - folga


# ---------- path resolvido (caminho absoluto) e estado de trilha ----------


def test_v1_item_path_resolves_relative_src_against_project_dir(tmp_path):
    """O bug real: um trecho como `{"type": "image", "src": "cards/abertura.png"}` é relativo à
    pasta do projeto, não ao diretório de trabalho do servidor; `item.path` já vem resolvido."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    (cards_dir / "abertura.png").write_bytes(b"x")
    spec = {
        "name": "caminho-relativo",
        "timeline": [{"type": "image", "src": "cards/abertura.png", "duration": 2}],
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    v1 = next(t for t in view.tracks if t.id == "V1")
    assert v1.items[0].path == str((cards_dir / "abertura.png").resolve())


def test_clip_item_path_resolves_named_source(tmp_path):
    project = make_project(tmp_path)  # já tem overlays com src="webcam.mp4"
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    v1 = next(t for t in view.tracks if t.id == "V1")
    assert v1.items[0].path == str((tmp_path / "a.mp4").resolve())
    v2 = next(t for t in view.tracks if t.id == "V2")
    assert v2.items[0].path == str((tmp_path / "webcam.mp4").resolve())


def test_card_and_text_items_have_no_path(tmp_path):
    project = make_project(tmp_path)
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    v1 = next(t for t in view.tracks if t.id == "V1")
    assert v1.items[1].kind == "card" and v1.items[1].path is None
    tx = next(t for t in view.tracks if t.id == "TX")
    assert tx.items[0].path is None


def test_sources_dict_has_resolved_path(tmp_path):
    (tmp_path / "cam1.mp4").write_bytes(b"x")
    spec = {
        "name": "fonte-sync",
        "sources": {"cam1": {"src": "cam1.mp4"}},
        "timeline": [{"type": "clip", "source": "cam1", "start": 0, "end": 2}],
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    assert view.sources["cam1"]["path"] == str((tmp_path / "cam1.mp4").resolve())


def test_track_state_flows_into_view(tmp_path):
    (tmp_path / "rec.wav").write_bytes(b"x")
    spec = {
        "name": "trilha-marcada",
        "sources": {"rec": {"src": "rec.wav"}},
        "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 2}],
        "audio": {"tracks": [{"source": "rec"}]},
        "tracks": {"A2": {"muted": True}, "V1": {"locked": True}},
    }
    (tmp_path / "a.mp4").write_bytes(b"x")
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    a2 = next(t for t in view.tracks if t.id == "A2")
    assert a2.muted is True
    assert a2.items[0].muted is True  # o item também reflete a trilha, não só o cabeçalho
    v1 = next(t for t in view.tracks if t.id == "V1")
    assert v1.locked is True and v1.hidden is False


def test_music_span_tail_without_music_duration_keeps_raw_gap(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "trilha.mp3").write_bytes(b"x")
    spec = {
        "name": "trilha-sem-duracao",
        "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 20}],
        "audio": {"music": {"src": "trilha.mp3", "spans": [{"start": 5, "tail": True, "start_at": 0.5}]}},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    mus = next(t for t in view.tracks if t.id == "MUS")
    assert mus.items[0].in_point == 0.5


def _narrated_project(tmp_path: Path, **audio) -> Project:
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "roteiro.txt").write_text("x" * 140, encoding="utf-8")
    spec = {
        "name": "narrado",
        "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 20}],
        "audio": {
            "narration": [
                {"text": "x" * 70, "start": 1.0, "voice": "ana"},
                {"script": "roteiro.txt", "start": 8.0, "speed": 2.0},
            ],
            **audio,
        },
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


def test_narration_track_has_one_estimated_item_per_narration(tmp_path):
    project = _narrated_project(tmp_path)
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    ids = [t.id for t in view.tracks]
    assert ids.index("A1") < ids.index("NAR")
    track = next(t for t in view.tracks if t.id == "NAR")
    first, second = track.items
    # ~14 caracteres por segundo: 70 caracteres = 5 s; 140 caracteres a 2x = 5 s
    assert (first.start, first.end) == (1.0, pytest.approx(6.0))
    assert (second.start, second.end) == (8.0, pytest.approx(13.0))
    assert first.extra == {"voice": "ana", "estimated": True}
    assert second.path == str((tmp_path / "roteiro.txt").resolve()) and first.path is None
    assert first.kind == "narration" and first.id == "NAR-0"


def test_narration_track_uses_real_durations_when_known(tmp_path):
    project = _narrated_project(tmp_path)
    layout = project_layout(project, prober=fake_prober)
    view = build_timeline_view(project, layout, narration_durations=[7.25, None])
    first, second = next(t for t in view.tracks if t.id == "NAR").items
    assert first.end == pytest.approx(8.25) and first.extra["estimated"] is False
    assert second.extra["estimated"] is True


def test_narration_track_respects_the_saved_track_state(tmp_path):
    project = _narrated_project(tmp_path)
    project = project.model_copy(update={"tracks": {"NAR": TrackState(muted=True, locked=True)}})
    track = next(
        t
        for t in build_timeline_view(project, project_layout(project, prober=fake_prober)).tracks
        if t.id == "NAR"
    )
    assert track.muted and track.locked and all(item.muted for item in track.items)


def test_no_narration_means_no_nar_track(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    project = Project.model_validate(
        {"name": "sem", "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 2}]}
    )
    project.base_dir = tmp_path
    view = build_timeline_view(project, project_layout(project, prober=fake_prober))
    assert "NAR" not in [t.id for t in view.tracks]
