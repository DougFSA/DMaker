"""Narração no projeto: estimativas, legendas das falas, avisos do lint e a preparação das faixas."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import Narration, Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.context import RenderContext, RenderOptions
from dmaker.pipeline.lint import lint
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.voiceover import (
    PreparedVoiceover,
    VoiceoverPreparer,
    estimate_narration_duration,
    estimate_speech_duration,
    known_voices,
    narration_cues,
    narration_label,
    narration_text,
    overrun_warnings,
)
from dmaker.voice.library import VoiceLibrary, VoiceNotFoundError
from dmaker.voice.synth import Speech, VoiceRequest

SAMPLE_RATE = 24000


class FakeSynthesizer:
    """Seno de 0,05 s por caractere, contando as sínteses."""

    engine_id = "fake-voiceover"

    def __init__(self) -> None:
        self.requests: list[VoiceRequest] = []

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.requests.append(request)
        t = np.arange(int(len(request.text) * 0.05 * SAMPLE_RATE)) / SAMPLE_RATE
        return Speech((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SAMPLE_RATE)


def _project(tmp_path: Path, narration: list[dict], **extra) -> Project:
    project = Project.model_validate(
        {
            "name": "narrado",
            "timeline": [{"type": "card", "title": "Abertura", "duration": 6.0}],
            "audio": {"narration": narration},
            **extra,
        }
    )
    project.base_dir = tmp_path
    return project


def _context(project: Project, tmp_path: Path, runner: RecordingRunner, **options) -> RenderContext:
    (tmp_path / "job").mkdir(exist_ok=True)
    return RenderContext(
        project=project,
        options=RenderOptions(**options),
        theme=load_theme(None, None),
        preset=get_preset("instagram/reels"),
        fps=30,
        job_dir=tmp_path / "job",
        cache_dir=tmp_path / "mez",
        runner=runner,
        prober=lambda path: None,  # type: ignore[arg-type,return-value]
    )


def _runner() -> RecordingRunner:
    return RecordingRunner(on_run=lambda command: Path(command.args[-1]).write_bytes(b"audio"))


# ---------- funções puras ----------


def test_estimate_scales_with_text_and_speed():
    assert estimate_speech_duration("x" * 70) == pytest.approx(5.0)
    assert estimate_speech_duration("x" * 70, speed=2.0) == pytest.approx(2.5)
    assert estimate_speech_duration("") == 0.5  # nunca um item de largura zero


def test_narration_text_reads_the_script_relative_to_the_project(tmp_path):
    (tmp_path / "roteiro.txt").write_text("Texto do roteiro.", encoding="utf-8")
    project = _project(tmp_path, [{"script": "roteiro.txt"}, {"script": "falta.txt"}, {"text": "Direto"}])
    first, missing, inline = project.audio.narration
    assert narration_text(project, first) == "Texto do roteiro."
    assert narration_text(project, inline) == "Direto"
    with pytest.raises(FileNotFoundError, match="falta.txt"):
        narration_text(project, missing)
    assert estimate_narration_duration(project, missing) == 0.5


def test_narration_label_is_short():
    assert narration_label(Narration(text="Curto")) == "Curto"
    long = narration_label(Narration(text="palavra " * 20))
    assert len(long) <= 40 and long.endswith("…")
    assert narration_label(Narration(script="roteiro.txt")) == "roteiro.txt"


def test_narration_cues_shift_by_start_and_split_into_words():
    voiceovers = [
        PreparedVoiceover(Path("b.wav"), 10.0, 1.0, 3.0, [(0.0, 3.0, "Segunda fala curta.")]),
        PreparedVoiceover(Path("a.wav"), 0.5, 1.0, 4.0, [(0.0, 1.0, "Oi."), (1.5, 4.0, "Tudo bem com você")]),
    ]
    cues = narration_cues(voiceovers)
    assert [(c.start, c.end, c.text) for c in cues] == [
        (0.5, 1.5, "Oi."),
        (2.0, 4.5, "Tudo bem com você"),
        (10.0, 13.0, "Segunda fala curta."),
    ]
    words = cues[1].words
    assert [w.text for w in words] == ["Tudo", "bem", "com", "você"]
    assert words[0].start == pytest.approx(2.0) and words[-1].end == pytest.approx(4.5)
    assert all(a.end == pytest.approx(b.start) for a, b in zip(words, words[1:], strict=False))
    assert words[0].end - words[0].start > words[1].end - words[1].start  # palavra maior leva mais tempo


def test_overrun_warnings_flag_only_what_passes_the_end():
    voiceovers = [
        PreparedVoiceover(Path("a.wav"), 0.0, 1.0, 5.0),
        PreparedVoiceover(Path("b.wav"), 4.0, 1.0, 4.0),
    ]
    warnings = overrun_warnings(voiceovers, total=6.0)
    assert len(warnings) == 1 and "narration[1]" in warnings[0] and "8.0s" in warnings[0]


# ---------- preparação ----------


def test_prepare_synthesizes_with_the_library_voice_and_reuses_the_cache(tmp_path):
    library = VoiceLibrary(tmp_path / "voices")
    library.save_design("Ana", "female, low pitch")
    synthesizer = FakeSynthesizer()
    runner = _runner()
    project = _project(tmp_path, [{"text": "Olá, este é o DMaker.", "voice": "ana", "start": 0.5, "seed": 3}])
    logs: list[str] = []

    def prepare() -> list[PreparedVoiceover]:
        ctx = _context(project, tmp_path, runner)
        ctx.log = logs.append
        ctx.narrator = NarrationService(synthesizer, runner, tmp_path / "cache")
        return VoiceoverPreparer(library).prepare(ctx)

    [item] = prepare()
    assert item.path == tmp_path / "job" / "narration_1.wav" and item.start == 0.5 and item.volume == 1.0
    assert item.duration == pytest.approx(len("Olá, este é o DMaker.") * 0.05)
    assert item.cues[0][2] == "Olá, este é o DMaker."
    [request] = synthesizer.requests
    assert request.voice is not None and request.voice.id == "ana" and request.seed == 3
    assert "Narração 1 de 1" in logs

    prepare()
    assert len(synthesizer.requests) == 1  # a segunda vez veio do cache


def test_prepare_uses_the_pronunciation_of_the_project_brand(tmp_path):
    from dmaker.voice.pronunciation import Lexicon

    spellings = {None: Lexicon.of({"DMaker": "Di Meiker"}), "medlycare": Lexicon.of({"DMaker": "Dimêiker"})}
    synthesizer = FakeSynthesizer()
    runner = _runner()
    library = VoiceLibrary(tmp_path / "voices")
    project = _project(tmp_path, [{"text": "Olá, este é o DMaker."}], brand="medlycare")
    service = NarrationService(
        synthesizer,
        runner,
        tmp_path / "cache",
        lexicons=lambda brand, _language: spellings.get(brand, Lexicon()),
    )

    ctx = _context(project, tmp_path, runner)
    ctx.narrator = service
    [item] = VoiceoverPreparer(library).prepare(ctx)

    assert synthesizer.requests[0].text == "Olá, este é o Dimêiker."
    assert item.cues[0][2] == "Olá, este é o DMaker."  # a legenda mostra o que está escrito
    assert VoiceoverPreparer(library).cached_durations(project, service)[0] == pytest.approx(item.duration)
    unbranded = _project(tmp_path, [{"text": "Olá, este é o DMaker."}])
    assert VoiceoverPreparer(library).cached_durations(unbranded, service) == [
        None
    ]  # outra pronúncia, outro cache


def test_prepare_builds_the_service_lazily_and_only_when_there_is_narration(tmp_path):
    built: list[RenderContext] = []

    def factory(ctx: RenderContext) -> NarrationService:
        built.append(ctx)
        return NarrationService(FakeSynthesizer(), ctx.runner, tmp_path / "cache")

    preparer = VoiceoverPreparer(VoiceLibrary(tmp_path / "voices"), factory)
    plain = _project(tmp_path, [])
    assert preparer.prepare(_context(plain, tmp_path, _runner())) == [] and built == []

    narrated = _project(tmp_path, [{"text": "Primeira."}, {"text": "Segunda."}])
    ctx = _context(narrated, tmp_path, _runner())
    assert len(preparer.prepare(ctx)) == 2
    assert len(built) == 1 and ctx.narrator is not None  # um serviço para as duas narrações


def test_prepare_reads_a_script_and_fails_clearly_for_a_missing_voice_or_script(tmp_path):
    library = VoiceLibrary(tmp_path / "voices")
    (tmp_path / "roteiro.txt").write_text("Do arquivo.", encoding="utf-8")
    synthesizer = FakeSynthesizer()

    def preparer() -> VoiceoverPreparer:
        return VoiceoverPreparer(
            library, lambda ctx: NarrationService(synthesizer, ctx.runner, tmp_path / "cache")
        )

    project = _project(tmp_path, [{"script": "roteiro.txt"}])
    preparer().prepare(_context(project, tmp_path, _runner()))
    assert synthesizer.requests[0].text == "Do arquivo."

    unknown_voice = _project(tmp_path, [{"text": "a", "voice": "nao-existe"}])
    with pytest.raises(VoiceNotFoundError, match="nao-existe"):
        preparer().prepare(_context(unknown_voice, tmp_path, _runner()))
    missing_script = _project(tmp_path, [{"script": "falta.txt"}])
    with pytest.raises(FileNotFoundError, match="falta.txt"):
        preparer().prepare(_context(missing_script, tmp_path, _runner()))


def test_prepare_in_dry_run_estimates_without_synthesizing(tmp_path):
    synthesizer = FakeSynthesizer()
    project = _project(tmp_path, [{"text": "x" * 70, "start": 1.0}])
    preparer = VoiceoverPreparer(
        VoiceLibrary(tmp_path / "voices"),
        lambda ctx: NarrationService(synthesizer, ctx.runner, tmp_path / "c"),
    )
    [item] = preparer.prepare(_context(project, tmp_path, RecordingRunner(), dry_run=True))
    assert synthesizer.requests == [] and item.duration == pytest.approx(5.0) and item.cues == []


def test_cached_durations_know_only_what_was_synthesized(tmp_path):
    library = VoiceLibrary(tmp_path / "voices")
    service = NarrationService(FakeSynthesizer(), _runner(), tmp_path / "cache")
    project = _project(
        tmp_path, [{"text": "Já sintetizada."}, {"text": "Ainda não."}, {"script": "falta.txt"}]
    )
    assert VoiceoverPreparer(library).cached_durations(project, service) == [None, None, None]

    service.render("Já sintetizada.", tmp_path / "out.wav", None)
    durations = VoiceoverPreparer(library).cached_durations(project, service)
    assert durations[0] == pytest.approx(len("Já sintetizada.") * 0.05) and durations[1:] == [None, None]


# ---------- lint ----------


def _lint(project: Project, total: float = 6.0, **kwargs) -> list[str]:
    return lint(
        project, load_theme(None, None), get_preset("instagram/reels"), total, [total], [None], **kwargs
    )


def test_lint_warns_about_unknown_voice_and_lists_the_known_ones(tmp_path):
    project = _project(tmp_path, [{"text": "Oi", "voice": "fantasma"}])
    warnings = _lint(project, known_voices={"ana", "bia"})
    assert any("fantasma" in w and "ana, bia" in w for w in warnings)
    assert not any("fantasma" in w for w in _lint(project, known_voices={"fantasma"}))
    assert not any("fantasma" in w for w in _lint(project))  # sem biblioteca, não confere


def test_lint_warns_when_the_estimated_narration_passes_the_end(tmp_path):
    long_text = "x" * 140  # 10 s estimados
    warnings = _lint(_project(tmp_path, [{"text": long_text, "start": 2.0}]))
    assert any("audio.narration[0]" in w and "12.0s" in w and "cortado" in w for w in warnings)
    assert not any("narration" in w for w in _lint(_project(tmp_path, [{"text": "Curta.", "start": 0.5}])))


def test_lint_warns_about_narration_that_starts_after_the_end_or_misses_its_script(tmp_path):
    warnings = _lint(_project(tmp_path, [{"text": "Tarde", "start": 9.0}, {"script": "falta.txt"}]))
    assert any("começa em 9s" in w for w in warnings)
    assert any("falta.txt" in w and "não encontrado" in w for w in warnings)


def test_lint_warns_about_narration_captions_without_narration(tmp_path):
    project = _project(tmp_path, [], captions={"source": "narration"})
    assert any("sem audio.narration" in w for w in _lint(project))
    with_narration = _project(tmp_path, [{"text": "Oi."}], captions={"source": "narration"})
    assert not any("sem audio.narration" in w for w in _lint(with_narration))


def test_known_voices_helper_only_reads_the_library_when_a_voice_is_requested(tmp_path):
    library = VoiceLibrary(tmp_path / "voices")
    library.save_design("Ana", "female")
    assert known_voices(_project(tmp_path, [{"text": "Oi"}]), library) is None
    assert "ana" in (known_voices(_project(tmp_path, [{"text": "Oi", "voice": "ana"}]), library) or set())
