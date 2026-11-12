"""A persona no render, com tudo de mentira (ffmpeg gravado, motor falso, voz falsa, transcritor falso): a orquestração,
o cache do clipe, a mixagem da fala e a validação da spec."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.persona import Persona
from dmaker.domain.spec import PersonaOverlay, PersonaSegment, Project
from dmaker.domain.timeline import persona_segment_duration
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.persona import engine as registry
from dmaker.persona.library import PersonaLibrary
from dmaker.persona.validation import persona_problems
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.persona_render import PersonaStage
from dmaker.text.captions import Word
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.synth import Speech

from .test_pipeline_unit import LOUDNORM_JSON, fake_prober, touch_output

TEXT = "Olá, eu sou a Ana e estou falando."  # 34 caracteres: 1,7 s com a voz falsa


class FakeSynthesizer:
    engine_id = "fake-persona"

    def synthesize(self, request):
        t = np.arange(int(len(request.text) * 0.05 * 24000)) / 24000
        return Speech((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 24000)


class FakeEngine:
    """O motor 2D de mentira: grava o pedido e cria o clipe, sem navegador."""

    kind = "2d"
    version = "fake1"
    produces_alpha = True
    expressions = ("neutral", "happy", "sad", "surprised")
    gestures = ("nod", "shake", "tilt", "wave")

    def __init__(self):
        self.requests = []

    def normalize_appearance(self, appearance):
        return dict(appearance)

    def cache_parts(self, request):
        return ()

    def unavailable_reason(self):
        return None

    def render(self, request, out: Path, runner, on_warning):
        self.requests.append(request)
        out.write_bytes(b"clip")


@pytest.fixture
def engine(monkeypatch) -> FakeEngine:
    fake = FakeEngine()
    monkeypatch.setattr(registry, "_ENGINES", {"2d": fake})
    return fake


@pytest.fixture
def library(tmp_path, engine) -> PersonaLibrary:
    library = PersonaLibrary(root=tmp_path / "personas", presets_root=tmp_path / "nenhuma")
    library.create("Ana", appearance={})
    return library


def timed_words(_ctx):
    return lambda path, language: [Word(0.1, 0.6, "olá"), Word(0.7, 1.2, "eu"), Word(1.3, 1.6, "sou")]


def pipeline(tmp_path, library, spec: dict, runner: RecordingRunner) -> RenderPipeline:
    (tmp_path / "base.mp4").write_bytes(b"x")
    project = Project.model_validate({"name": "pessoa", "output": {"preset": "instagram/reels"}, **spec})
    project.base_dir = tmp_path
    return RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=runner,
        prober=fake_prober,
        transcriber_factory=lambda captions: pytest.fail("a persona não legenda pelo Whisper"),
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
        narrator=NarrationService(FakeSynthesizer(), runner, tmp_path / "voice-cache"),
        personas=PersonaStage(library, VoiceLibrary(tmp_path / "vozes"), word_timer=timed_words),
    )


def full_screen(**changes) -> dict:
    segment = {
        "type": "persona",
        "persona": "ana",
        "speech": {"text": TEXT},
        "marks": [{"at": 0.5, "expression": "happy"}, {"at": 1.0, "gesture": "nod"}],
    }
    return {"timeline": [{**segment, **changes}]}


def runner_for_pipeline() -> RecordingRunner:
    return RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)


def test_a_full_screen_persona_lasts_as_long_as_her_speech_plus_the_tail(tmp_path, library, engine):
    runner = runner_for_pipeline()
    result = pipeline(tmp_path, library, full_screen(), runner).run()

    assert result.duration == pytest.approx(len(TEXT) * 0.05 + 0.5, abs=0.05)
    request = engine.requests[0]
    assert request.duration == pytest.approx(result.duration, abs=0.05)
    assert request.size == (540, 960) and request.fps == 30  # a prévia é metade do reels
    assert [s.viseme for s in request.visemes][0] == "sil" and request.visemes[-1].viseme == "sil"
    assert request.expression == "neutral" and len(request.marks) == 2
    mezzanine = next(c for c in runner.commands if "mz_persona" in " ".join(c))
    joined = " ".join(mezzanine)
    assert "_persona.mov" in joined and "persona_" in joined  # o clipe e o áudio da fala
    assert "overlay=x=0:y=0" in joined and "apad" in joined


def test_the_clip_comes_from_the_cache_the_second_time(tmp_path, library, engine):
    pipeline(tmp_path, library, full_screen(), runner_for_pipeline()).run()
    pipeline(tmp_path, library, full_screen(), runner_for_pipeline()).run()
    assert len(engine.requests) == 1  # o mesmo projeto reaproveita o clipe
    pipeline(tmp_path, library, full_screen(expression="sad"), runner_for_pipeline()).run()
    assert len(engine.requests) == 2  # uma expressão diferente é outro clipe


def test_a_fixed_duration_wins_and_the_background_reaches_the_mezzanine(tmp_path, library, engine):
    runner = runner_for_pipeline()
    spec = full_screen(duration=3.0, background={"color": "#112233"}, marks=[])
    result = pipeline(tmp_path, library, spec, runner).run()
    assert result.duration == pytest.approx(3.0)
    assert any("0x112233" in " ".join(c) for c in runner.commands)


def test_an_overlay_persona_speaks_over_the_video_and_her_voice_enters_the_mix(tmp_path, library, engine):
    runner = runner_for_pipeline()
    spec = {
        "timeline": [{"type": "clip", "src": "base.mp4", "start": 0, "end": 6}],
        "overlays": [
            {
                "type": "persona",
                "persona": "ana",
                "start": 1.0,
                "width": 0.4,
                "aspect": "1:1",
                "background": "#F3E9D2",
                "shape": "circle",
                "speech": {"text": TEXT},
            }
        ],
    }
    result = pipeline(tmp_path, library, spec, runner).run()
    assert result.duration == pytest.approx(6.0)
    request = engine.requests[0]
    assert request.size == (216, 216)  # 40% da largura da prévia, quadrado
    assert request.duration == pytest.approx(1.7, abs=0.1)  # acaba junto com a fala
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "fade=t=in" in graph and "alpha=1" in graph  # entra e sai suave
    assert "persona_" in graph or any(
        "persona_" in " ".join(c) for c in runner.commands[-3:]
    )  # a fala na mixagem
    framing = [c for c in runner.commands if "alphamerge" in " ".join(c)]
    assert framing  # o fundo em círculo foi composto por um comando próprio


def test_an_opaque_engine_gets_no_background_composed_over_it(tmp_path, library, engine):
    engine.produces_alpha = False
    runner = runner_for_pipeline()
    pipeline(tmp_path, library, full_screen(background={"color": "#112233"}), runner).run()
    assert not any("0x112233" in " ".join(c) for c in runner.commands)


def test_a_missing_persona_or_a_gesture_the_type_cannot_do_stops_the_render_with_a_clear_message(
    tmp_path, library, engine
):
    with pytest.raises(ValueError, match=r"timeline\[0\]\.persona: Persona 'fantasma' não encontrada"):
        pipeline(tmp_path, library, full_screen(persona="fantasma"), runner_for_pipeline()).run()
    bad = full_screen(marks=[{"at": 0.2, "gesture": "dance"}])
    with pytest.raises(ValueError, match=r"marks\[0\]: o gesto 'dance' não existe nesta persona \(tipo 2d\)"):
        pipeline(tmp_path, library, bad, runner_for_pipeline()).run()
    assert engine.requests == []


def test_a_mark_past_the_real_duration_of_the_speech_is_refused_once_the_speech_is_known(
    tmp_path, library, engine
):
    late = full_screen(marks=[{"at": 9.0, "expression": "sad"}])
    with pytest.raises(ValueError, match=r"a marca em 9s cai fora da fala"):
        pipeline(tmp_path, library, late, runner_for_pipeline()).run()


def test_the_spec_problems_are_listed_without_rendering(library, engine):
    project = Project.model_validate(
        {
            "name": "p",
            "timeline": [
                {
                    "type": "persona",
                    "persona": "ana",
                    "duration": 2.0,
                    "expression": "furioso",
                    "speech": {"text": "oi"},
                    "marks": [{"at": 2.5, "expression": "sad"}],
                }
            ],
            "overlays": [
                {"type": "persona", "persona": "x", "start": 0, "end": 2, "speech": {"audio": "a.wav"}}
            ],
        }
    )
    problems = persona_problems(project, library.get)
    assert any(
        "timeline[0].expression: a expressão 'furioso'" in p and "neutral, happy" in p for p in problems
    )
    assert any("timeline[0].marks[0]" in p and "fora da fala" in p for p in problems)
    assert any(p.startswith("overlays[0].persona: Persona 'x' não encontrada") for p in problems)


def test_the_speech_needs_exactly_one_of_text_or_audio_and_a_mark_exactly_one_of_expression_or_gesture():
    with pytest.raises(ValueError, match="text.*audio"):
        PersonaSegment.model_validate({"type": "persona", "persona": "a", "speech": {}})
    with pytest.raises(ValueError, match="text.*audio"):
        PersonaSegment.model_validate(
            {"type": "persona", "persona": "a", "speech": {"text": "oi", "audio": "a.wav"}}
        )
    with pytest.raises(ValueError, match="expression.*gesture"):
        PersonaSegment.model_validate(
            {
                "type": "persona",
                "persona": "a",
                "speech": {"text": "oi"},
                "marks": [{"at": 1, "expression": "sad", "gesture": "nod"}],
            }
        )
    with pytest.raises(ValueError, match="só um"):
        PersonaSegment.model_validate(
            {
                "type": "persona",
                "persona": "a",
                "speech": {"text": "oi"},
                "background": {"color": "#fff", "image": "a.png"},
            }
        )
    overlay = PersonaOverlay.model_validate({"type": "persona", "persona": "a", "speech": {"text": "oi"}})
    assert overlay.position == "bottom-right" and overlay.background is None


def test_the_segment_duration_is_fixed_measured_or_estimated():
    segment = PersonaSegment.model_validate(
        {"type": "persona", "persona": "a", "speech": {"text": "x" * 28}, "tail": 1.0}
    )
    assert persona_segment_duration(segment, None) == pytest.approx(
        3.0
    )  # 28 caracteres a 14 por segundo + o respiro
    fixed = segment.model_copy(update={"duration": 4.0})
    assert persona_segment_duration(fixed, None) == 4.0
    assert isinstance(Persona(id="a", name="A"), Persona)


def test_the_real_speech_duration_is_kept_for_the_timeline_and_the_qa(tmp_path, library, engine):
    from dmaker.pipeline.persona_speech_store import STORE_FILE, with_spoken_durations
    from dmaker.pipeline.sources import Source

    runner = runner_for_pipeline()
    render = pipeline(tmp_path, library, full_screen(), runner)
    project = render.project
    estimated = persona_segment_duration(project.timeline[0], None)

    # antes de sintetizar só há a estimativa
    before = with_spoken_durations(project, [Source(None, None)], library)
    assert before[0].info is None

    result = render.run()

    assert (tmp_path / STORE_FILE).is_file()
    after = with_spoken_durations(project, [Source(None, None)], library)
    assert after[0].info is not None
    real = persona_segment_duration(project.timeline[0], after[0].info)
    assert real == pytest.approx(result.duration, abs=0.05)
    assert abs(real - estimated) > 0.3  # a estimativa do texto erra; a duração guardada, não


def test_the_timeline_view_shows_personas_by_name_with_the_real_speech_duration(tmp_path):
    from dmaker.pipeline.persona_speech_store import save_duration, speech_key
    from dmaker.pipeline.timeline_service import project_timeline_view

    project = Project.model_validate(
        {
            "name": "vista",
            "output": {"preset": "instagram/reels"},
            "timeline": [{"type": "persona", "persona": "bia", "speech": {"text": TEXT}}],
            "overlays": [{"type": "persona", "persona": "bia", "start": 1.0, "speech": {"text": TEXT}}],
        }
    )
    project.base_dir = tmp_path
    bia = PersonaLibrary().get("bia")

    def items(view):
        return {track.id: track.items for track in view.tracks}

    estimated = project_timeline_view(project, prober=fake_prober)
    save_duration(tmp_path, speech_key(bia, project.timeline[0].speech), 6.0)
    real = project_timeline_view(project, prober=fake_prober)

    main, corner = items(real)["V1"][0], items(real)["V2"][0]
    assert main.label == bia.name and corner.label == bia.name and corner.kind == "persona"
    assert main.end - main.start == pytest.approx(6.0 + project.timeline[0].tail)
    assert corner.start == 1.0 and corner.end == pytest.approx(min(7.0, real.total))
    first = items(estimated)["V1"][0]
    assert first.end - first.start == pytest.approx(len(TEXT) / 14.0 + project.timeline[0].tail)


def test_the_speech_of_a_corner_persona_is_captioned_at_the_overlay_start(tmp_path, library, engine):
    runner = runner_for_pipeline()
    spec = {
        "timeline": [{"type": "clip", "src": "base.mp4", "start": 0, "end": 8}],
        "overlays": [
            {"type": "persona", "persona": "ana", "start": 2.0, "speech": {"text": TEXT}},
        ],
        "captions": {"source": "narration"},
    }
    render = pipeline(tmp_path, library, spec, runner)

    render.run()

    ass = next((tmp_path / "jobs").rglob("overlay.ass")).read_text(encoding="utf-8-sig")
    # as palavras do transcritor falso (olá, eu, sou) a partir de 2,0 s, mais o início de cada uma
    assert "OLÁ" in ass.upper() and "0:00:02.1" in ass
