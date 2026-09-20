"""Multicâmera e faixas externas: relógio da sessão, offsets e fatias de áudio (sem ffmpeg, com fakes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.spec import Project
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.projects import summarize
from dmaker.pipeline.sources import expand_parts, resolve_session
from dmaker.pipeline.sync import SyncResolver

from .test_pipeline_unit import LOUDNORM_JSON, touch_output


def fake_prober(path: Path) -> MediaInfo:
    if path.suffix == ".wav":
        return MediaInfo(path, 300.0, 0, 0, 0.0, False, True, False)
    return MediaInfo(path, 120.0, 1920, 1080, 30.0, True, True, False)


def fake_finder(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult({"cam2.mp4": 12.5, "altar.wav": -3.0}[other.name], confidence=9.0)


@pytest.fixture
def wedding(tmp_path: Path) -> Project:
    for name in ("cam1.mp4", "cam2.mp4", "altar.wav"):
        (tmp_path / name).write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "casamento",
            "output": {"preset": "youtube/video"},
            "sources": {
                "cam1": {"src": "cam1.mp4"},
                "cam2": {"src": "cam2.mp4", "sync": "auto"},
                "altar": {"src": "altar.wav", "sync": "auto"},
            },
            "timeline": [
                {"type": "clip", "source": "cam1", "start": 20, "end": 30},
                {"type": "clip", "source": "cam2", "start": 30, "end": 45, "transition": {"type": "cut"}},
                {
                    "type": "clip",
                    "source": "cam1",
                    "start": 45,
                    "end": 50,
                    "transition": {"type": "fade", "duration": 0.5},
                },
            ],
            "audio": {"tracks": [{"source": "altar", "volume": 0.8}], "normalize": "two-pass"},
        }
    )
    project.base_dir = tmp_path
    return project


def test_spec_rejects_unknown_sources_and_requires_src_or_source():
    base = {"name": "x", "sources": {"cam1": {"src": "a.mp4"}}}
    with pytest.raises(ValueError, match="desconhecida"):
        Project.model_validate({**base, "timeline": [{"type": "clip", "source": "cam9"}]})
    with pytest.raises(ValueError, match="um dos dois"):
        Project.model_validate({**base, "timeline": [{"type": "clip"}]})
    with pytest.raises(ValueError, match="master"):
        Project.model_validate({**base, "master": "cam2", "timeline": [{"type": "clip", "source": "cam1"}]})
    ok = Project.model_validate({**base, "timeline": [{"type": "clip", "source": "cam1", "end": 5}]})
    assert ok.master_source == "cam1"


def test_sync_resolver_caches_auto_offsets(wedding, tmp_path):
    store = tmp_path / "sync.json"
    calls = []

    def finder(master, other, ms, os_):
        calls.append(other.name)
        return fake_finder(master, other, ms, os_)

    resolution = SyncResolver(finder).resolve(wedding, store)
    assert resolution.offsets == {"cam1": 0.0, "cam2": 12.5, "altar": -3.0}
    assert resolution.parts == {} and resolution.warnings == []
    assert sorted(calls) == ["altar.wav", "cam2.mp4"]
    cached = json.loads(store.read_text(encoding="utf-8"))
    assert cached["cam2"]["offset"] == 12.5 and cached["cam2"]["confidence"] == 9.0
    # segunda vez: tudo do cache
    assert SyncResolver(finder).resolve(wedding, store).offsets == resolution.offsets and len(calls) == 2


def test_summary_uses_session_clock(wedding):
    summary = summarize(wedding, prober=fake_prober, offset_finder=fake_finder)
    assert summary.offsets["cam2"] == 12.5
    assert [s.duration for s in summary.segments] == [10.0, 15.0, 5.0]
    assert summary.total == pytest.approx(10 + 15 + 5 - 0.5)
    assert not summary.warnings


def test_render_uses_in_points_and_track_slices(wedding, tmp_path):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    pipeline = RenderPipeline(
        wedding,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=runner,
        prober=fake_prober,
        offset_finder=fake_finder,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
    )
    result = pipeline.run()
    assert result.duration == pytest.approx(29.5)
    mezz = [c for c in runner.commands if "-filter_complex" in c and "pcm_s16le" in c][:3]
    # cam2 começa em 12.5 s da sessão: trecho em 30 s da sessão = 17.5 s no arquivo
    assert mezz[1][mezz[1].index("-ss") + 1] == "17.500"
    # gravador começou 3 s antes do master: trecho em 20 s da sessão = 23 s na faixa
    altar_ss = [mezz[0][i + 1] for i, a in enumerate(mezz[0]) if a == "-ss"]
    assert altar_ss == ["20.000", "23.000"]
    graph = " ".join(mezz[0])
    assert "amix=inputs=2" in graph and "volume=0.800" in graph
    assert (tmp_path / "sync.json").exists()


def test_partial_render_keeps_only_requested_segments(wedding, tmp_path):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = RenderPipeline(
        wedding,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "part.mp4", segments=(1, 2)),
        runner=runner,
        prober=fake_prober,
        offset_finder=fake_finder,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
    ).run()
    assert result.duration == pytest.approx(15 + 5 - 0.5)
    with pytest.raises(ValueError, match="fora da linha"):
        RenderPipeline(
            wedding,
            RenderOptions(dry_run=True, segments=(2, 9)),
            runner=RecordingRunner(),
            prober=fake_prober,
            offset_finder=fake_finder,
            cache_dir=tmp_path / "mez",
            jobs_dir=tmp_path / "jobs",
        ).run()


def test_lint_rejects_clip_outside_source_coverage(wedding):
    wedding.timeline[1] = wedding.timeline[1].model_copy(
        update={"start": 5.0, "end": 8.0}
    )  # cam2 só começa em 12.5
    with pytest.raises(ValueError, match="fora da fonte"):
        summarize(wedding, prober=fake_prober, offset_finder=fake_finder)


def test_track_outside_segment_is_left_out_of_the_mix(tmp_path):
    """Gravador em dois arquivos (0-120 s e 200-320 s da sessão): cada trecho mistura só o que cobre."""
    for name in ("cam1.mp4", "rec_a.wav", "rec_b.wav"):
        (tmp_path / name).write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "dois-gravadores",
            "output": {"preset": "youtube/video"},
            "sources": {
                "cam1": {"src": "cam1.mp4"},
                "rec_a": {"src": "rec_a.wav"},
                "rec_b": {"src": "rec_b.wav", "sync": 200.0},
            },
            "timeline": [
                {"type": "clip", "source": "cam1", "start": 10, "end": 20},
                {"type": "clip", "source": "cam1", "start": 150, "end": 160, "transition": {"type": "cut"}},
                {"type": "clip", "source": "cam1", "start": 110, "end": 210, "transition": {"type": "cut"}},
            ],
            "audio": {"tracks": [{"source": "rec_a"}, {"source": "rec_b"}], "normalize": "fast"},
        }
    )
    project.base_dir = tmp_path

    def prober(path: Path) -> MediaInfo:
        if path.suffix == ".wav":
            return MediaInfo(path, 120.0, 0, 0, 0.0, False, True, False)
        return MediaInfo(path, 400.0, 1920, 1080, 30.0, True, True, False)

    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=runner,
        prober=prober,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
    ).run()
    mezz = [c for c in runner.commands if "-filter_complex" in c and "pcm_s16le" in c][:3]
    inputs = [[c[i + 1] for i, a in enumerate(c) if a == "-i"] for c in mezz]
    assert [Path(p).name for p in inputs[0]] == ["cam1.mp4", "rec_a.wav"]  # 10-20 s: só o primeiro
    assert [Path(p).name for p in inputs[1]] == ["cam1.mp4"]  # 150-160 s: nenhum gravador
    assert [Path(p).name for p in inputs[2]] == ["cam1.mp4", "rec_a.wav", "rec_b.wav"]  # 110-210 s: os dois


# ---------- fonte com `parts` (câmera em vários arquivos) ----------


def _parts_fake_prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 60.0, 1920, 1080, 30.0, True, True, False)


def _parts_project(tmp_path: Path, timeline: list, tracks: list | None = None) -> Project:
    for name in ("cam1_a.mp4", "cam1_b.mp4"):
        (tmp_path / name).write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "multiarquivo",
            "output": {"preset": "youtube/video"},
            "sources": {"cam1": {"parts": ["cam1_a.mp4", "cam1_b.mp4"]}},
            "timeline": timeline,
            "audio": {"tracks": tracks or []},
        }
    )
    project.base_dir = tmp_path
    return project


def test_expand_parts_splits_clip_at_the_file_boundary(tmp_path):
    """Um clipe que atravessa a fronteira das duas partes vira dois pedaços físicos, um por arquivo;
    transição e fades ficam só na primeira/última peça (o corte interno não é uma transição)."""
    project = _parts_project(
        tmp_path,
        [
            {
                "type": "clip",
                "source": "cam1",
                "start": 50,
                "end": 70,
                "transition": {"type": "fade", "duration": 0.3},
                "fade_in": 0.5,
                "fade_out": 0.8,
            }
        ],
    )
    session = resolve_session(project, _parts_fake_prober, {}, {"cam1": [0.0, 60.0]})

    physical, origin = expand_parts(project, session, {"cam1": [0.0, 60.0]})

    assert origin == [0, 0]
    assert [seg.source for seg in physical.timeline] == ["cam1#0", "cam1#1"]
    assert (physical.timeline[0].start, physical.timeline[0].end) == (50.0, 60.0)
    assert (physical.timeline[1].start, physical.timeline[1].end) == (60.0, 70.0)
    assert physical.timeline[0].transition.type == "fade"
    assert physical.timeline[1].transition is None
    assert physical.timeline[0].fade_in == 0.5 and physical.timeline[0].fade_out == 0.0
    assert physical.timeline[1].fade_in == 0.0 and physical.timeline[1].fade_out == 0.8


def test_expand_parts_splits_audio_tracks_one_per_part(tmp_path):
    project = _parts_project(
        tmp_path,
        [{"type": "clip", "source": "cam1", "start": 0, "end": 20}],
        tracks=[{"source": "cam1", "volume": 0.7}],
    )
    session = resolve_session(project, _parts_fake_prober, {}, {"cam1": [0.0, 60.0]})

    physical, _ = expand_parts(project, session, {"cam1": [0.0, 60.0]})

    assert [(t.source, t.volume) for t in physical.audio.tracks] == [("cam1#0", 0.7), ("cam1#1", 0.7)]


def test_expand_parts_rejects_a_clip_that_falls_in_a_gap_between_parts(tmp_path):
    """Partes com um buraco entre elas (a câmera parou de gravar um tempo antes de voltar): um clipe
    inteiramente no buraco não tem como ser montado."""
    project = _parts_project(tmp_path, [{"type": "clip", "source": "cam1", "start": 61, "end": 64}])
    # parte 0: 0-60s; parte 1 começa só em 65s (buraco de 61-65s da sessão)
    session = resolve_session(project, _parts_fake_prober, {}, {"cam1": [0.0, 65.0]})

    with pytest.raises(ValueError, match="não cobre"):
        expand_parts(project, session, {"cam1": [0.0, 65.0]})


def test_expand_parts_is_identity_without_any_source_with_parts(wedding):
    session = resolve_session(wedding, fake_prober, {"cam1": 0.0, "cam2": 12.5, "altar": -3.0})
    physical, origin = expand_parts(wedding, session, {})
    assert physical is wedding
    assert origin == list(range(len(wedding.timeline)))


def test_summarize_aggregates_duration_of_a_clip_split_across_parts(tmp_path):
    """Um trecho que atravessa a fronteira das partes mostra, no resumo, a duração somada dos dois
    pedaços; o corte interno some por trás do trecho original."""
    project = _parts_project(
        tmp_path,
        [
            {"type": "clip", "source": "cam1", "start": 0, "end": 50},
            {"type": "clip", "source": "cam1", "start": 50, "end": 70, "transition": {"type": "cut"}},
        ],
    )

    summary = summarize(project, prober=_parts_fake_prober)

    assert [s.duration for s in summary.segments] == [50.0, 20.0]
    assert summary.total == pytest.approx(70.0)
    assert any("sem link de áudio nem relógio" in w for w in summary.warnings)


def test_render_uses_correct_ss_for_each_physical_part(tmp_path):
    """No render de verdade, cada pedaço físico usa o `-ss` da parte que ele veio (o arquivo certo,
    no ponto certo dentro dele)."""
    project = _parts_project(
        tmp_path, [{"type": "clip", "source": "cam1", "start": 50, "end": 70, "transition": {"type": "cut"}}]
    )
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=runner,
        prober=_parts_fake_prober,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
    ).run()

    assert result.duration == pytest.approx(20.0)
    mezz = [c for c in runner.commands if "-filter_complex" in c and "pcm_s16le" in c][:2]
    inputs = [[c[i + 1] for i, a in enumerate(c) if a == "-i"][0] for c in mezz]
    ss = [c[c.index("-ss") + 1] for c in mezz]
    assert [Path(p).name for p in inputs] == ["cam1_a.mp4", "cam1_b.mp4"]
    assert ss == ["50.000", "0.000"]  # 50s na parte 0 (começa em 0); a parte 1 começa em 60s da sessão
