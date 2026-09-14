"""Recorte de pessoa (matte): contas puras, comando do ffmpeg e integração no pipeline com um
recortador falso. O modelo de verdade só roda em `test_render_integration.py` quando está baixado."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.spec import Project
from dmaker.filtergraph.mezzanine import matte_mezzanine
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.matting import MatteRequest, composite, downsample_ratio_for, hex_to_rgb, tone_of
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from tests.test_pipeline_unit import LOUDNORM_JSON, FakeTranscriber, touch_output


def test_downsample_ratio_follows_rvm_recommendation():
    assert downsample_ratio_for(1080, 1920) == pytest.approx(512 / 1920)
    assert downsample_ratio_for(1280, 720) == pytest.approx(0.4)
    assert downsample_ratio_for(480, 360) == 1.0


def test_tone_follows_background_luminance():
    assert tone_of((255, 255, 255)) == "light" and tone_of((178, 225, 207)) == "light"
    assert tone_of((12, 83, 90)) == "dark"


def test_hex_to_rgb():
    assert hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert hex_to_rgb("0C535A") == (12, 83, 90)


def test_composite_mixes_foreground_and_background_by_alpha():
    foreground = np.zeros((3, 1, 2), np.float32)  # pessoa preta
    alpha = np.array([[[1.0, 0.25]]], np.float32)  # pixel opaco e pixel 25 % pessoa
    frame = np.frombuffer(composite(foreground, alpha, (200, 100, 0)), np.uint8).reshape(1, 2, 3)
    assert frame[0, 0].tolist() == [0, 0, 0]
    assert frame[0, 1].tolist() == [150, 75, 0]


def test_matte_mezzanine_takes_frames_from_stdin_and_audio_from_the_source(tmp_path: Path):
    cmd = matte_mezzanine(iter(()), tmp_path / "take.mp4", 2.5, 4.0, 1080, 1920, 30, tmp_path / "m.mov")
    args = " ".join(cmd.args)
    assert "-i pipe:0" in args and "-s 1080x1920" in args
    assert "-ss 2.500 -t 4.000" in args and "[1:a:0]" in args
    assert cmd.total == 4.0 and cmd.frames is not None

    silent = matte_mezzanine(
        iter(()), tmp_path / "t.mp4", 0, 1, 10, 10, 30, tmp_path / "s.mov", has_audio=False
    )
    assert "anullsrc" in " ".join(silent.args)


class FakeMatter:
    """Devolve quadros lisos do tamanho pedido e registra o que foi pedido."""

    def __init__(self) -> None:
        self.requests: list[MatteRequest] = []

    def frames(self, request: MatteRequest):
        self.requests.append(request)
        frame = bytes(request.background) * (request.width * request.height)
        for _ in range(round(request.length * request.fps)):
            yield frame


def fake_prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 20.0, 1080, 1920, 30.0, True, True, False)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    (tmp_path / "take.mp4").write_bytes(b"x")
    spec = {
        "name": "matte-unit",
        "output": {"preset": "instagram/reels"},
        "brand": "medlycare",
        "timeline": [
            {"type": "clip", "src": "take.mp4", "start": 2, "end": 4, "matte": {"background": "mint"}},
        ],
        "captions": {"source": "auto", "language": "pt"},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


def _pipeline(project: Project, runner: RecordingRunner, matter: FakeMatter, **opts) -> RenderPipeline:
    d = project.base_dir
    return RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=d / "out.mp4", **opts),
        runner=runner,
        prober=fake_prober,
        transcriber_factory=lambda captions: FakeTranscriber(),
        matter=matter,
        cache_dir=d / "mez",
        jobs_dir=d / "jobs",
        output_dir=d / "output",
    )


def test_clip_with_matte_renders_the_cutout_before_the_mezzanine(project: Project):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    matter = FakeMatter()
    _pipeline(project, runner, matter).run()

    request = matter.requests[0]
    assert request.start == 2 and request.length == 2 and (request.width, request.height) == (1080, 1920)
    assert request.model == "resnet50"  # padrão: o contorno melhor
    assert request.background == hex_to_rgb("#B2E1CF")  # chave `mint` resolvida pelo tema
    assert runner.frames_consumed == 60

    ass = (project.base_dir / "jobs" / "matte-unit_preview" / "overlay.ass").read_text(encoding="utf-8")
    assert "Style: CapLight," in ass  # legendas como sobre cartão claro (o fundo menta é claro)

    cutout, mezzanine = runner.commands[0], runner.commands[1]
    assert "pipe:0" in cutout and cutout[-1].endswith("_matte.mov")
    assert cutout[-1] in mezzanine  # o mezanino parte do arquivo recortado, do início dele
    assert "-ss 0.000" in " ".join(mezzanine)


def test_matte_cache_survives_unrelated_spec_changes(project: Project):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    matter = FakeMatter()
    _pipeline(project, runner, matter).run()
    project.timeline[0].color.brightness = 0.1  # muda o mezanino, não o recorte
    _pipeline(project, runner, matter).run()
    assert len(matter.requests) == 1
    assert sum(1 for c in runner.commands if "pipe:0" in c) == 1

    project.timeline[0].matte.model = "mobilenetv3"  # outro modelo: recorte novo
    _pipeline(project, runner, matter).run()
    assert len(matter.requests) == 2 and matter.requests[1].model == "mobilenetv3"


def test_dry_run_never_asks_the_model_for_frames(project: Project):
    runner = RecordingRunner(capture_stderr=LOUDNORM_JSON)
    matter = FakeMatter()
    _pipeline(project, runner, matter, dry_run=True).run()

    assert matter.requests == [] and runner.frames_consumed == 0
    assert any("pipe:0" in c for c in runner.commands)
