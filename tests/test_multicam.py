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

    offsets = SyncResolver(finder).resolve(wedding, store)
    assert offsets == {"cam1": 0.0, "cam2": 12.5, "altar": -3.0}
    assert sorted(calls) == ["altar.wav", "cam2.mp4"]
    cached = json.loads(store.read_text(encoding="utf-8"))
    assert cached["cam2"]["offset"] == 12.5 and cached["cam2"]["confidence"] == 9.0
    # segunda vez: tudo do cache
    assert SyncResolver(finder).resolve(wedding, store) == offsets and len(calls) == 2


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
