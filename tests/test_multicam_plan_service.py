"""Serviço `plan_multicam` (`pipeline/multicam_plan.py`): funções puras testadas isoladas e o fluxo
completo com probe, sincronização e transcrição falsos (sem ffmpeg nem Whisper de verdade)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.multicam import Coverage, PhaseRule, PlannedClip, Speech, default_wedding_phases
from dmaker.domain.spec import ClipSegment, MulticamBlock, PhaseRuleSpec, Project, Transition
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.multicam_plan import (
    block_to_plan,
    clips_from_plan,
    coverage_from_session,
    expand_multicam,
    plan_multicam,
    speech_from_cues,
)
from dmaker.pipeline.sources import Source
from dmaker.text.captions import Cue
from dmaker.text.transcribe import Transcript

from .test_pipeline_unit import touch_output

# ---------- funções puras ----------


def test_coverage_from_session_handles_plain_and_parted_sources():
    info = MediaInfo(Path("x"), 50.0, 1920, 1080, 30.0, True, True, False)
    session = {
        "cam1": Source(Path("cam1.mp4"), info, 0.0, 0, "cam1"),
        "cam2#0": Source(Path("cam2_a.mp4"), info, 0.0, 0, "cam2#0"),
        "cam2#1": Source(Path("cam2_b.mp4"), info, 50.0, 0, "cam2#1"),
    }

    coverage = coverage_from_session(session, ["cam1", "cam2"])

    assert coverage == [
        Coverage("cam1", 0.0, 50.0),
        Coverage("cam2", 0.0, 50.0),
        Coverage("cam2", 50.0, 100.0),
    ]


def test_speech_from_cues_shifts_to_session_clock():
    cues = [Cue(1.0, 2.0, "ola"), Cue(3.0, 4.0, "mundo")]

    speech = speech_from_cues(cues, part_offset=10.0)

    assert speech == [Speech(11.0, 12.0, "ola"), Speech(13.0, 14.0, "mundo")]


def test_block_to_plan_uses_default_wedding_phases_by_name():
    block = MulticamBlock(at=0, cameras=["a", "b"], main="a", audio="a")

    plan = block_to_plan(block)

    assert plan.phases == default_wedding_phases()
    assert plan.cameras == ("a", "b")
    assert plan.main == "a" and plan.audio == "a"


def test_block_to_plan_converts_custom_phase_rules():
    block = MulticamBlock(
        at=0,
        cameras=["a", "b"],
        main="a",
        audio="a",
        phases=[PhaseRuleSpec(name="votos", match=["te recebo"], cadence=(60.0, 15.0))],
    )

    plan = block_to_plan(block)

    assert plan.phases == (PhaseRule("votos", ("te recebo",), None, (60.0, 15.0), None),)


def test_clips_from_plan_sets_transition_only_on_first_clip():
    block = MulticamBlock(
        at=0, cameras=["a", "b"], main="a", audio="a", transition_in=Transition(type="dissolve", duration=1.0)
    )
    clips = [
        PlannedClip("a", 0.0, 10.0, "geral", False),
        PlannedClip("b", 10.0, 15.0, "votos", True),
    ]

    segments = clips_from_plan(clips, block)

    assert [s.source for s in segments] == ["a", "b"]
    assert segments[0].transition.type == "dissolve"
    assert segments[1].transition is None
    assert [s.label for s in segments] == ["geral", "votos"]
    assert segments[1].mute is True and segments[0].mute is False
    assert segments[0].volume == 1.0 and segments[1].volume == 1.0


def test_clips_from_plan_uses_block_label_over_phase_label_when_set():
    block = MulticamBlock(at=0, cameras=["a"], main="a", audio="a", label="corte automático")

    segments = clips_from_plan([PlannedClip("a", 0.0, 5.0, "geral", False)], block)

    assert segments[0].label == "corte automático"


def test_expand_multicam_inserts_clips_at_index_and_clears_block(tmp_path):
    project = Project.model_validate(
        {
            "name": "x",
            "sources": {"a": {"src": "a.mp4"}},
            "timeline": [
                {"type": "clip", "source": "a", "start": 0, "end": 5},
                {"type": "clip", "source": "a", "start": 5, "end": 10},
            ],
            "multicam": {"at": 1, "cameras": ["a"], "main": "a", "audio": "a"},
        }
    )
    project.base_dir = tmp_path
    planned = [ClipSegment(source="a", start=10, end=15)]

    updated = expand_multicam(project, planned)

    assert updated.multicam is None
    assert len(updated.timeline) == 3
    assert updated.timeline[1].start == 10 and updated.timeline[1].end == 15
    assert updated.base_dir == project.base_dir


# ---------- ponta a ponta, com probe/sincronização/transcrição falsos ----------


def _fake_prober(path: Path) -> MediaInfo:
    if path.suffix == ".wav":
        return MediaInfo(path, 200.0, 0, 0, 0.0, False, True, False)
    return MediaInfo(path, 200.0, 1920, 1080, 30.0, True, True, False)


def _fake_finder(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult({"cam2.mp4": 5.0, "altar.wav": 0.0}[other.name], confidence=9.0)


class _FakeTranscriber:
    calls = 0

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        _FakeTranscriber.calls += 1
        return Transcript([Cue(8.0, 10.0, "Eu, Daniel, te recebo, Bruna")], {"language": language})


def _write_wedding_multicam_spec(tmp_path: Path) -> Path:
    for name in ("cam1.mp4", "cam2.mp4", "altar.wav"):
        target = tmp_path / name
        if not target.exists():
            target.write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "casamento",
            "output": {"preset": "youtube/video"},
            "sources": {
                "cam1": {"src": "cam1.mp4"},
                "cam2": {"src": "cam2.mp4", "sync": "auto"},
                "altar": {"src": "altar.wav", "sync": "auto"},
            },
            "timeline": [{"type": "card", "title": "Abertura", "duration": 2.0}],
            "multicam": {
                "at": 1,
                "cameras": ["cam1", "cam2"],
                "main": "cam1",
                "audio": "altar",
                "cadence": [10.0, 5.0],
                "min_clip": 1.0,
                "phases": [{"name": "votos", "match": ["te recebo"], "cadence": [6.0, 3.0]}],
                "start": 0.0,
                "end": 20.0,
            },
        }
    )
    return project.save(tmp_path / "spec.json")


def test_plan_multicam_rejects_project_without_multicam_block(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    project = Project.model_validate({"name": "sem-bloco", "timeline": [{"type": "clip", "src": "a.mp4"}]})
    spec_path = project.save(tmp_path / "spec.json")

    with pytest.raises(ValueError, match="sem bloco multicam"):
        plan_multicam(spec_path, prober=_fake_prober)


def test_plan_multicam_expands_block_and_saves_the_project(tmp_path):
    _FakeTranscriber.calls = 0
    spec_path = _write_wedding_multicam_spec(tmp_path)
    runner = RecordingRunner(on_run=touch_output)

    result = plan_multicam(
        spec_path,
        prober=_fake_prober,
        transcriber_factory=lambda: _FakeTranscriber(),
        offset_finder=_fake_finder,
        runner=runner,
        cache_dir=tmp_path / "transcripts",
    )

    assert result.clips >= 2
    assert result.start == 0.0 and result.end == 20.0
    assert any(name == "votos" for name, _at in result.phases)
    assert _FakeTranscriber.calls == 1

    saved = Project.load(spec_path)
    assert saved.multicam is None
    assert len(saved.timeline) == 1 + result.clips
    assert all(seg.source in ("cam1", "cam2") for seg in saved.timeline[1:])


def test_plan_multicam_default_start_ignores_what_a_camera_recorded_before_the_master(tmp_path):
    """Câmera que começou antes da principal fica com posição negativa na sessão; sem `start` no
    bloco, o plano começa em 0 (um trecho não pode começar antes do relógio da sessão)."""
    _FakeTranscriber.calls = 0
    spec_path = _write_wedding_multicam_spec(tmp_path)
    project = Project.load(spec_path)
    project.multicam = project.multicam.model_copy(update={"start": None, "end": None})
    project.save(spec_path)

    def finder(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
        return SyncResult({"cam2.mp4": -30.0, "altar.wav": 0.0}[other.name], confidence=9.0)

    result = plan_multicam(
        spec_path,
        prober=_fake_prober,
        transcriber_factory=lambda: _FakeTranscriber(),
        offset_finder=finder,
        runner=RecordingRunner(on_run=touch_output),
        cache_dir=tmp_path / "transcripts",
    )

    assert result.start == 0.0
    saved = Project.load(spec_path)
    assert all(seg.start >= 0 for seg in saved.timeline[1:])


def test_plan_multicam_reuses_cached_transcription_on_second_call(tmp_path):
    _FakeTranscriber.calls = 0
    cache_dir = tmp_path / "transcripts"

    spec_path = _write_wedding_multicam_spec(tmp_path)
    plan_multicam(
        spec_path,
        prober=_fake_prober,
        transcriber_factory=lambda: _FakeTranscriber(),
        offset_finder=_fake_finder,
        runner=RecordingRunner(on_run=touch_output),
        cache_dir=cache_dir,
    )
    assert _FakeTranscriber.calls == 1

    # bloco multicam de novo, mesmo áudio (arquivo sem mudar de tamanho/data): cache reaproveitado
    spec_path = _write_wedding_multicam_spec(tmp_path)
    plan_multicam(
        spec_path,
        prober=_fake_prober,
        transcriber_factory=lambda: _FakeTranscriber(),
        offset_finder=_fake_finder,
        runner=RecordingRunner(on_run=touch_output),
        cache_dir=cache_dir,
    )
    assert _FakeTranscriber.calls == 1
