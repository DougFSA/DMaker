"""Pipeline completo com dependências falsas: sem ffmpeg, sem Whisper. Verifica a orquestração,
o cache, o ASS gerado e o tratamento de silêncio."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.text.captions import Cue, Word
from dmaker.text.transcribe import Transcript

LOUDNORM_JSON = json.dumps(
    {
        "input_i": "-23.5",
        "input_tp": "-4.0",
        "input_lra": "7.0",
        "input_thresh": "-33.9",
        "target_offset": "0.3",
    }
)
SILENT_JSON = json.dumps(
    {
        "input_i": "-inf",
        "input_tp": "-inf",
        "input_lra": "0.0",
        "input_thresh": "-inf",
        "target_offset": "0.0",
    }
)


class FakeTranscriber:
    calls = 0

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        FakeTranscriber.calls += 1
        assert wav.name == "voice.wav"
        assert initial_prompt and "MedlyCare" in initial_prompt  # vocabulário do tema chega ao modelo
        return Transcript(
            [
                Cue(
                    0.2,
                    1.4,
                    "chega de medriquer",
                    [Word(0.2, 0.6, "chega"), Word(0.6, 0.9, "de"), Word(0.9, 1.4, "medriquer")],
                )
            ],
            {"language": language},
        )


def fake_prober(path: Path) -> MediaInfo:
    if path.suffix == ".png":
        return MediaInfo(path, 0.0, 1000, 620, 0.0, True, False, True)
    return MediaInfo(path, 8.0, 1920, 1080, 30.0, True, True, False)


def touch_output(command: FFmpegCommand) -> None:
    """Simula o ffmpeg criando o arquivo de saída (último argumento)."""
    out = Path(command.args[-1])
    if out.suffix in (".mov", ".mp4", ".wav", ".jpg"):
        if command.cwd and not out.is_absolute():
            out = command.cwd / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 1024)


@pytest.fixture
def workspace(tmp_path: Path) -> dict:
    from PIL import Image

    (tmp_path / "take.mp4").write_bytes(b"x")  # o probe é falso; só precisa existir
    Image.new("RGB", (1000, 620), "#3366CC").save(tmp_path / "print.png")
    spec = {
        "name": "unit",
        "output": {"preset": "instagram/reels"},
        "brand": "medlycare",
        "timeline": [
            {"type": "card", "title": "Abertura", "duration": 1.0, "motion": "none"},
            {
                "type": "clip",
                "src": "take.mp4",
                "start": 1,
                "end": 3,
                "transition": {"type": "fade", "duration": 0.4},
            },
            {
                "type": "image",
                "src": "print.png",
                "duration": 1.0,
                "motion": "zoom-in",
                "transition": {"type": "cut"},
            },
        ],
        "overlays": [
            {"type": "image", "src": "logo:symbol", "position": "top-right", "width": 0.1},
            {"type": "text", "text": "Gancho", "role": "hook", "start": 0, "end": 0.9},
            {"type": "progress-bar"},
        ],
        "captions": {"source": "auto", "language": "pt"},
        "audio": {"normalize": "two-pass"},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return {"project": project, "dir": tmp_path}


def _pipeline(workspace: dict, runner: RecordingRunner, **opts) -> RenderPipeline:
    d = workspace["dir"]
    return RenderPipeline(
        workspace["project"],
        RenderOptions(preview=True, quiet=True, out=d / "out.mp4", **opts),
        runner=runner,
        prober=fake_prober,
        transcriber_factory=lambda captions: FakeTranscriber(),
        cache_dir=d / "mez",
        jobs_dir=d / "jobs",
        output_dir=d / "output",
    )


def test_full_pipeline_with_fakes(workspace):
    FakeTranscriber.calls = 0
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(workspace, runner).run()

    labels = [c for c in runner.commands]
    # 3 mezaninos + áudio para transcrição + medição de loudness + montagem + thumbnail
    assert len(labels) == 7
    assert runner.frames_consumed == 30  # 1 s a 30 fps do trecho com movimento (gerado de verdade)
    assert result.output.exists() and result.duration == pytest.approx(1.0 + 2.0 - 0.4 + 1.0)
    assert FakeTranscriber.calls == 1

    final = runner.commands[-2]
    assert "-/filter_complex" in final or "-filter_complex_script" in final
    assert "libx264" in final and "ultrafast" in final  # preview usa rascunho
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "xfade=transition=fade" in graph and "measured_I=-23.5" in graph and "overlay.ass" in graph

    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "Gancho" in ass and "MEDLYCARE" in ass  # legenda corrigida pelo tema (medriquer -> MedlyCare)
    assert "&H005A530C" in ass  # gancho sobre cartão claro sai na cor principal da marca
    store = workspace["dir"] / "captions.auto.json"
    assert store.exists() and json.loads(store.read_text(encoding="utf-8"))["hash"]


def test_second_run_reuses_cache(workspace):
    FakeTranscriber.calls = 0
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _pipeline(workspace, runner).run()
    again = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _pipeline(workspace, again).run()
    # só medição de loudness, montagem e thumbnail: mezaninos e transcrição vieram do cache
    assert len(again.commands) == 3 and again.frames_consumed == 0
    assert FakeTranscriber.calls == 1
    forced = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _pipeline(workspace, forced, force=True).run()
    assert len(forced.commands) == 7 and FakeTranscriber.calls == 2


def test_silent_audio_skips_loudnorm(workspace):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=SILENT_JSON)
    result = _pipeline(workspace, runner, no_captions=True).run()
    assert any("silencioso" in w for w in result.warnings)
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "loudnorm" not in graph


def test_dry_run_records_without_files(workspace):
    result = _pipeline(workspace, RecordingRunner(), dry_run=True).run()
    assert not result.output.exists() and result.size_bytes == 0
    assert len(result.commands) >= 4 and result.thumbnail is None


def test_missing_source_fails_clearly(workspace):
    project = Project.model_validate({"name": "x", "timeline": [{"type": "clip", "src": "nao_existe.mp4"}]})
    project.base_dir = workspace["dir"]
    with pytest.raises(FileNotFoundError):
        RenderPipeline(
            project, RenderOptions(dry_run=True), runner=RecordingRunner(), prober=fake_prober
        ).run()
