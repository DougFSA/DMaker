"""Vista de linha do tempo multitrilha: ordem das trilhas, spans, faixas (lanes) e itens sintéticos
(áudio dos clipes, faixas externas, música, legendas)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dmaker.domain.spec import Project, TrackState
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.layout import project_layout
from dmaker.pipeline.timeline_view import TrackItem, build_timeline_view, stack_lanes

from .test_pipeline_unit import LOUDNORM_JSON, touch_output


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
    # o gravador só começa em 2 s da sessão: a faixa soa de 2 s ao fim do clipe, e o `in_point` é o
    # tempo NO ARQUIVO (zero, o começo dele), por isso `extra.offset` é zero
    (item,) = a2.items
    assert item.label == "rec" and item.extra["offset"] == 0.0 and item.extra["volume"] == 0.5
    assert (item.start, item.end, item.in_point) == (2.0, 3.0, 0.0)
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
        "sources": {"cam": {"src": "a.mp4"}, "rec": {"src": "rec.wav"}},
        "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 2}],
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


# ---------- faixas externas fatiadas por clipe (a conta do render) ----------


def _session_prober(path: Path) -> MediaInfo:
    """Câmeras de 400 s, gravadores de 120 s e câmeras em partes de 60 s."""
    if path.suffix == ".wav":
        return MediaInfo(path, 120.0, 0, 0, 0.0, False, True, False)
    if path.name.startswith("cam1_"):
        return MediaInfo(path, 60.0, 1920, 1080, 30.0, True, True, False)
    return MediaInfo(path, 400.0, 1920, 1080, 30.0, True, True, False)


def _session_project(tmp_path: Path, **spec) -> Project:
    for name in (
        "cam1.mp4",
        "cam2.mp4",
        "cam1_a.mp4",
        "cam1_b.mp4",
        "mesa.wav",
        "rec_a.wav",
        "rec_b.wav",
        "rec_c.wav",
    ):
        (tmp_path / name).write_bytes(b"x")
    project = Project.model_validate({"name": "sessao", "output": {"preset": "youtube/video"}, **spec})
    project.base_dir = tmp_path
    return project


def _no_audio_link(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    """Correlação sem confiança: a cadeia das partes cai para o relógio (uma parte encosta na outra)."""
    return SyncResult(0.0, confidence=0.0)


def _session_view(project: Project):
    return build_timeline_view(
        project, project_layout(project, prober=_session_prober, offset_finder=_no_audio_link)
    )


def _track(view, track_id: str):
    return next(t for t in view.tracks if t.id == track_id)


def _windows(track) -> list[tuple[float, float, float]]:
    return [(item.start, item.end, item.in_point) for item in track.items]


def test_external_track_is_sliced_by_clip_with_the_renders_in_points(tmp_path):
    """A mesa começa 3 s antes da câmera principal (sync -3): em cada clipe ela toca do ponto dela que
    corresponde ao instante da sessão, e cada corte é um item (não um bloco corrido de 0 ao fim)."""
    project = _session_project(
        tmp_path,
        sources={
            "cam1": {"src": "cam1.mp4"},
            "cam2": {"src": "cam2.mp4", "sync": 12.5},
            "mesa": {"src": "mesa.wav", "sync": -3.0},
        },
        timeline=[
            {"type": "clip", "source": "cam1", "start": 20, "end": 30, "mute": True},
            {
                "type": "clip",
                "source": "cam2",
                "start": 30,
                "end": 45,
                "mute": True,
                "transition": {"type": "cut"},
            },
            {
                "type": "clip",
                "source": "cam1",
                "start": 45,
                "end": 50,
                "mute": True,
                "transition": {"type": "cut"},
            },
        ],
        audio={"tracks": [{"source": "mesa", "volume": 0.5}]},
    )
    a2 = _track(_session_view(project), "A2")
    assert _windows(a2) == [(0.0, 10.0, 23.0), (10.0, 25.0, 33.0), (25.0, 30.0, 48.0)]
    assert [item.id for item in a2.items] == ["A2-0-0", "A2-0-1", "A2-0-2"]
    for item in a2.items:
        assert item.path == str((tmp_path / "mesa.wav").resolve())
        assert item.index == 0 and item.kind == "track"  # editar continua apontando para audio.tracks.0
        assert item.extra == {"offset": 0.0, "speed": 1.0, "volume": 0.5}


def test_track_that_does_not_cover_a_clip_gets_no_item_there(tmp_path):
    """Dois gravadores em sequência (0-120 s e 200-320 s da sessão): cada um só tem item nos clipes que
    grava, e o trecho que nenhum cobre fica sem item."""
    project = _session_project(
        tmp_path,
        sources={
            "cam1": {"src": "cam1.mp4"},
            "rec_a": {"src": "rec_a.wav"},
            "rec_b": {"src": "rec_b.wav", "sync": 200.0},
        },
        timeline=[
            {"type": "clip", "source": "cam1", "start": 10, "end": 20},
            {"type": "clip", "source": "cam1", "start": 150, "end": 160, "transition": {"type": "cut"}},
            {"type": "clip", "source": "cam1", "start": 110, "end": 210, "transition": {"type": "cut"}},
        ],
        audio={"tracks": [{"source": "rec_a"}, {"source": "rec_b"}]},
    )
    view = _session_view(project)
    # rec_a: clipe 1 inteiro e só os 10 s finais do clipe 3 (o arquivo acaba em 120 s); nada no clipe 2
    assert _windows(_track(view, "A2")) == [(0.0, 10.0, 10.0), (20.0, 30.0, 110.0)]
    # rec_b entra 90 s depois do início do clipe 3 e começa no começo do arquivo, não antes dele
    assert _windows(_track(view, "A3")) == [(110.0, 120.0, 0.0)]


def test_track_sync_before_and_after_the_camera(tmp_path):
    """Sincronia negativa: o gravador já rodava, então o clipe começa no meio do arquivo. Positiva: o
    gravador liga depois, então a faixa só soa dali em diante e nunca toca o começo do arquivo antes."""
    project = _session_project(
        tmp_path,
        sources={
            "cam1": {"src": "cam1.mp4"},
            "rec_a": {"src": "rec_a.wav", "sync": 5.0},
            "rec_b": {"src": "rec_b.wav", "sync": -3.0},
        },
        timeline=[{"type": "clip", "source": "cam1", "start": 0, "end": 10}],
        audio={"tracks": [{"source": "rec_a"}, {"source": "rec_b"}]},
    )
    view = _session_view(project)
    assert _windows(_track(view, "A2")) == [(5.0, 10.0, 0.0)]
    assert _windows(_track(view, "A3")) == [(0.0, 10.0, 3.0)]


def test_track_item_follows_the_clip_speed(tmp_path):
    """A 2x o clipe dura metade e o atraso do gravador (4 s de fonte) também: a faixa entra em 2 s."""
    project = _session_project(
        tmp_path,
        sources={"cam1": {"src": "cam1.mp4"}, "rec_a": {"src": "rec_a.wav", "sync": 4.0}},
        timeline=[{"type": "clip", "source": "cam1", "start": 0, "end": 10, "speed": 2.0}],
        audio={"tracks": [{"source": "rec_a"}]},
    )
    (item,) = _track(_session_view(project), "A2").items
    assert (item.start, item.end, item.in_point) == (2.0, 5.0, 0.0)
    assert item.extra["speed"] == 2.0 and item.out_point == pytest.approx(6.0)


def test_standalone_clip_gets_no_external_track(tmp_path):
    """O render só mistura faixa externa em clipe de fonte sincronizada; clipe avulso não ganha item."""
    project = _session_project(
        tmp_path,
        sources={"cam1": {"src": "cam1.mp4"}, "rec_a": {"src": "rec_a.wav"}},
        timeline=[{"type": "clip", "src": "cam2.mp4", "start": 0, "end": 5}],
        audio={"tracks": [{"source": "rec_a"}]},
    )
    assert _track(_session_view(project), "A2").items == []


def test_source_with_parts_points_each_piece_to_the_file_that_records_it(tmp_path):
    """Câmera em dois arquivos de 60 s: o clipe que atravessa a fronteira é um item só (a edição aponta
    para ele), com um pedaço por arquivo; o clipe da segunda parte aponta para o arquivo dela, e a mesa
    é fatiada nos dois pedaços sem perder a continuidade do ponto dela."""
    project = _session_project(
        tmp_path,
        sources={"cam1": {"parts": ["cam1_a.mp4", "cam1_b.mp4"]}, "rec_a": {"src": "rec_a.wav", "sync": 5.0}},
        timeline=[
            {"type": "clip", "source": "cam1", "start": 50, "end": 70},
            {"type": "clip", "source": "cam1", "start": 70, "end": 80, "transition": {"type": "cut"}},
        ],
        audio={"tracks": [{"source": "rec_a"}]},
    )
    view = _session_view(project)
    file_a, file_b = (str((tmp_path / name).resolve()) for name in ("cam1_a.mp4", "cam1_b.mp4"))
    crossing, inside_b = _track(view, "V1").items
    assert (crossing.start, crossing.end, crossing.path) == (0.0, 20.0, file_a)
    assert crossing.extra["pieces"] == [
        {"start": 0.0, "end": 10.0, "in_point": 50.0, "path": file_a},
        {"start": 10.0, "end": 20.0, "in_point": 0.0, "path": file_b},
    ]
    assert inside_b.path == file_b
    assert inside_b.extra["pieces"] == [{"start": 20.0, "end": 30.0, "in_point": 10.0, "path": file_b}]
    assert _track(view, "A1").items[0].extra["pieces"] == crossing.extra["pieces"]
    # rec_a começa em 5 s da sessão: 50 s da sessão = 45 s no arquivo, e a emenda segue contínua (55 s)
    assert _windows(_track(view, "A2")) == [(0.0, 10.0, 45.0), (10.0, 20.0, 55.0), (20.0, 30.0, 65.0)]


def test_track_from_a_source_with_parts_uses_the_part_that_records_each_instant(tmp_path):
    """Câmera em partes usada como faixa de áudio: cada pedaço do clipe toca o arquivo da parte certa,
    e a parte que não grava aquele instante não ganha item (como o `expand_parts` do render)."""
    project = _session_project(
        tmp_path,
        sources={"cam1": {"parts": ["cam1_a.mp4", "cam1_b.mp4"]}},
        timeline=[{"type": "clip", "source": "cam1", "start": 50, "end": 70, "mute": True}],
        audio={"tracks": [{"source": "cam1", "volume": 0.7}]},
    )
    a2 = _track(_session_view(project), "A2")
    assert _windows(a2) == [(0.0, 10.0, 50.0), (10.0, 20.0, 0.0)]
    assert [Path(item.path).name for item in a2.items] == ["cam1_a.mp4", "cam1_b.mp4"]
    assert all(item.index == 0 and item.extra["volume"] == 0.7 for item in a2.items)


def _render_track_inputs(project: Project, tmp_path: Path) -> list[list[tuple[str, float, int]]]:
    """Por mezanino do render de verdade (com ffmpeg falso): (arquivo, `-ss`, atraso em ms) de cada
    faixa externa que o comando mistura, lidos dos argumentos que o ffmpeg receberia."""
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=runner,
        prober=_session_prober,
        offset_finder=_no_audio_link,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
    ).run()
    mezzanines = [c for c in runner.commands if "-filter_complex" in c and "pcm_s16le" in c]
    result = []
    for command in mezzanines:
        inputs, last_ss = [], 0.0
        for position, arg in enumerate(command):
            if arg == "-ss":
                last_ss = float(command[position + 1])
            elif arg == "-i":
                inputs.append((Path(command[position + 1]).name, last_ss))
                last_ss = 0.0
        graph = command[command.index("-filter_complex") + 1]
        tracks = []
        for k, (name, ss) in enumerate(inputs[1:]):  # a primeira entrada é a câmera
            chain = re.search(rf"asetpts=PTS-STARTPTS(?:,adelay=(\d+):all=1)?[^\[;]*\[mz_trk{k}\]", graph)
            assert chain, f"faixa {k} sem cadeia no grafo"
            tracks.append((name, ss, int(chain.group(1) or 0)))
        result.append(tracks)
    return result


def test_view_and_render_share_the_same_track_calculation(tmp_path):
    """Contrato entre a prévia e o vídeo final: para cada clipe, as faixas que o render mistura (arquivo,
    `-ss` e atraso) são exatamente os itens que a vista desenha, na mesma ordem e com o mesmo ponto."""
    project = _session_project(
        tmp_path,
        sources={
            "cam1": {"src": "cam1.mp4"},
            "rec_a": {"src": "rec_a.wav"},
            "rec_b": {"src": "rec_b.wav", "sync": 200.0},
            "rec_c": {"src": "rec_c.wav", "sync": 8.0},
            "mesa": {"src": "mesa.wav", "sync": -3.0},
        },
        timeline=[
            {"type": "clip", "source": "cam1", "start": 10, "end": 20},
            {"type": "clip", "source": "cam1", "start": 150, "end": 160, "transition": {"type": "cut"}},
            {"type": "clip", "source": "cam1", "start": 110, "end": 210, "transition": {"type": "cut"}},
            {
                "type": "clip",
                "source": "cam1",
                "start": 5,
                "end": 25,
                "speed": 2.0,
                "transition": {"type": "cut"},
            },
        ],
        audio={
            "tracks": [{"source": "rec_a"}, {"source": "rec_b"}, {"source": "rec_c"}, {"source": "mesa"}],
            "normalize": "fast",
        },
    )
    view = _session_view(project)
    rendered = _render_track_inputs(project, tmp_path)
    clips = _track(view, "V1").items
    assert len(rendered) == len(clips)
    for clip, from_render in zip(clips, rendered, strict=True):
        speed = project.timeline[clip.index].speed
        from_view = [
            (Path(item.path).name, item.in_point, round((item.start - clip.start) * speed * 1000))
            for track_id in ("A2", "A3", "A4", "A5")
            for item in _track(view, track_id).items
            if clip.start <= item.start < clip.end
        ]
        assert from_render == [(name, pytest.approx(ss), delay) for name, ss, delay in from_view]
    assert any(delay > 0 for clip in rendered for _, _, delay in clip)  # o contrato cobre o atraso também


def test_music_items_carry_the_music_volume(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "trilha.mp3").write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "trilha-com-volume",
            "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 20}],
            "audio": {"music": {"src": "trilha.mp3", "volume": 0.3, "spans": [{"start": 0, "end": 5}]}},
        }
    )
    project.base_dir = tmp_path
    mus = _track(build_timeline_view(project, project_layout(project, prober=fake_prober)), "MUS")
    assert mus.items[0].extra == {"loop": True, "volume": 0.3}
