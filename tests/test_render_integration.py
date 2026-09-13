"""Renderiza de verdade com ffmpeg (clipes sintéticos). Pula se o ffmpeg não estiver instalado."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.spec import Project
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline, contact_sheet

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def _project(media: dict[str, Path], tmp_path: Path, **overrides) -> Project:
    data = {
        "name": "teste_integracao",
        "output": {"preset": "instagram/reels", "quality": "medium"},
        "brand": "medlycare",
        "timeline": [
            {"type": "card", "title": "Teste do DMaker", "subtitle": "cartão gerado", "duration": 1.5},
            {
                "type": "clip",
                "src": str(media["clip_a"]),
                "start": 0.5,
                "end": 2.5,
                "transition": {"type": "fade", "duration": 0.4},
                "reframe": {"mode": "blur"},
            },
            {
                "type": "clip",
                "src": str(media["clip_b"]),
                "end": 1.5,
                "transition": {"type": "cut"},
                "speed": 1.5,
            },
            {
                "type": "image",
                "src": str(media["photo"]),
                "duration": 1.5,
                "motion": "zoom-in",
                "transition": {"type": "wipeleft", "duration": 0.3},
            },
        ],
        "overlays": [
            {"type": "image", "src": "logo", "position": "top-right", "width": 0.25},
            {"type": "text", "text": "Gancho no topo", "role": "hook", "start": 0, "end": 3},
            {"type": "text", "text": "medlycare.com.br", "role": "cta", "start": 3, "end": 6},
            {"type": "progress-bar"},
        ],
        "captions": {"source": str(media["srt"]), "style": {"mode": "karaoke"}},
        "audio": {
            "music": {"src": str(media["music"]), "volume": 0.2, "ducking": True},
            "normalize": "two-pass",
        },
    }
    data.update(overrides)
    p = Project.model_validate(data)
    p.base_dir = tmp_path
    return p


def test_dry_run_lists_commands(synthetic_media, tmp_path):
    project = _project(synthetic_media, tmp_path)
    result = RenderPipeline(project, RenderOptions(dry_run=True, out=tmp_path / "x.mp4")).run()
    assert len(result.commands) >= 5  # 4 mezaninos + montagem
    assert any("libx264" in c for c in result.commands)
    assert result.job_dir and (result.job_dir / "graph.txt").exists()
    # duração: 1.5 + (2.0 - 0.4) + 1.0 + (1.5 - 0.3) = 5.3
    assert abs(result.duration - 5.3) < 0.01


def test_preview_render(synthetic_media, tmp_path):
    project = _project(synthetic_media, tmp_path)
    out = tmp_path / "preview.mp4"
    result = RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True)).run()
    assert out.exists() and result.size_bytes > 10_000
    info = probe(out)
    assert (info.width, info.height) == (540, 960)
    assert info.has_audio and abs(info.duration - 5.3) < 0.25
    assert result.thumbnail and result.thumbnail.exists()
    sheet = contact_sheet(out, tmp_path / "sheet.png", 3, 2, 200)
    assert sheet.exists()


def test_full_render_with_two_pass_loudnorm_and_export_preset(synthetic_media, tmp_path):
    project = _project(synthetic_media, tmp_path)
    out = tmp_path / "final.mp4"
    result = RenderPipeline(project, RenderOptions(out=out, quiet=True, preset="youtube/shorts")).run()
    assert out.exists()
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio
    assert result.job_dir and (result.job_dir / "loudnorm.json").exists()
    assert result.preset.id == "youtube/shorts"


def test_landscape_preset_with_pad_and_no_extras(synthetic_media, tmp_path):
    data = {
        "name": "teste_yt",
        "output": {"preset": "youtube/video"},
        "timeline": [
            {
                "type": "clip",
                "src": str(synthetic_media["clip_b"]),
                "end": 1.0,
                "reframe": {"mode": "pad", "pad_color": "#101010"},
            },
        ],
        "audio": {"normalize": "fast"},
    }
    project = Project.model_validate(data)
    project.base_dir = tmp_path
    out = tmp_path / "yt.mp4"
    RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True, thumbnail=False)).run()
    info = probe(out)
    assert info.width > info.height


def test_missing_source_fails_clearly(tmp_path):
    project = Project.model_validate({"name": "x", "timeline": [{"type": "clip", "src": "nao_existe.mp4"}]})
    project.base_dir = tmp_path
    with pytest.raises(FileNotFoundError):
        RenderPipeline(project, RenderOptions(dry_run=True)).run()
