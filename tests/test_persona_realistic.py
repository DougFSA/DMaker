"""O motor da persona realista com a cabeça falante de mentira: a aparência, a chave de cache, o clipe, o quadro parado,
a validação das marcas, a criação pela CLI/MCP (serviço) e o render no pipeline (estimativa no log, cache)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaker.domain.persona import Persona
from dmaker.domain.spec import Project
from dmaker.media import ditto_models
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.talking_head import TalkingHeadError
from dmaker.persona import engine as registry
from dmaker.persona import engine_realistic as realistic
from dmaker.persona.engine import PersonaEngineError, PersonaRender, clip_cache_key
from dmaker.persona.engine_realistic import RealisticEngine
from dmaker.persona.library import PersonaLibrary
from dmaker.persona.portrait import Box
from dmaker.persona.validation import persona_problems
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline import personas as persona_service
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.persona_render import PersonaStage
from dmaker.voice.library import VoiceLibrary

from .test_persona_pipeline import FakeSynthesizer, timed_words
from .test_pipeline_unit import LOUDNORM_JSON, fake_prober, touch_output

pytest.importorskip("cv2")  # o enquadramento e o quadro parado usam o OpenCV (extra persona-realista)


class FakeHead:
    """A cabeça falante de mentira: devolve quadros de uma cor por índice e guarda o que recebeu."""

    def __init__(self, gpu: bool = True, fail_after: int | None = None) -> None:
        self.gpu = gpu
        self.fail_after = fail_after
        self.requests = []
        self.photos: list[np.ndarray] = []

    def has_gpu(self) -> bool:
        return self.gpu

    def frames(self, request, log, warn):
        import cv2

        self.requests.append(request)
        self.photos.append(cv2.imdecode(np.fromfile(str(request.photo), np.uint8), cv2.IMREAD_COLOR))
        log("persona realista: desenhando de mentira")
        warn("aviso do ditto")
        count = max(round(request.duration * 25), 1)
        for index in range(count):
            if self.fail_after is not None and index >= self.fail_after:
                raise TalkingHeadError("a GPU parou")
            yield bytes([index % 256]) * request.frame_bytes


def make_photo(path: Path, size=(1200, 1600), color=(180, 140, 120), fmt="JPEG") -> Path:
    Image.new("RGB", size, color).save(path, format=fmt)
    return path


FACE = Box(450, 500, 300, 300)


@pytest.fixture
def models_dir(tmp_path, monkeypatch) -> Path:
    """Uma pasta de modelos com todos os arquivos (vazios) e os pacotes do extra dados como presentes."""
    root = tmp_path / "models"
    for item in ditto_models.FILES:
        target = root / ditto_models.MODEL_FOLDER / item.folder / item.remote.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    monkeypatch.setattr(realistic, "missing_packages", lambda: [])
    return root


@pytest.fixture
def head() -> FakeHead:
    return FakeHead()


@pytest.fixture
def engine(head, models_dir) -> RealisticEngine:
    return RealisticEngine(head=head, face_finder=lambda image: FACE, models_dir=models_dir)


@pytest.fixture
def library(tmp_path, monkeypatch, engine) -> PersonaLibrary:
    monkeypatch.setattr(registry, "_ENGINES", {"realistic": engine, "2d": registry.engine_for("2d")})
    return PersonaLibrary(root=tmp_path / "personas", presets_root=tmp_path / "nenhuma")


def persona_of(library: PersonaLibrary, tmp_path: Path, name="Ana", **photo) -> Persona:
    made = persona_service.create_persona(
        name,
        kind="realistic",
        library=library,
        voices=VoiceLibrary(tmp_path / "vozes"),
        photo=make_photo(tmp_path / f"{name}.jpg", **photo),
    )
    return library.get(made["id"])


def render_request(persona: Persona, audio: Path | None, **changes) -> PersonaRender:
    fields = {
        "persona": persona,
        "visemes": (),
        "expression": "neutral",
        "marks": (),
        "duration": 1.0,
        "fps": 30.0,
        "size": (270, 480),
        "audio": audio,
    }
    return PersonaRender(**{**fields, **changes})


@pytest.fixture
def speech(tmp_path) -> Path:
    path = tmp_path / "fala.wav"
    path.write_bytes(b"audio-da-fala")
    return path


# ---------- aparência e criação ----------


def test_the_appearance_needs_a_photo_name_and_fills_the_default_steps(engine):
    assert engine.normalize_appearance({"photo": "foto.jpg"}) == {"photo": "foto.jpg", "steps": 15}
    with pytest.raises(PersonaEngineError, match="photo"):
        engine.normalize_appearance({})
    with pytest.raises(PersonaEngineError, match="não é uma foto"):
        engine.normalize_appearance({"photo": "../fora.jpg"})
    with pytest.raises(PersonaEngineError, match="steps deve ficar entre 5 e 50"):
        engine.normalize_appearance({"photo": "foto.jpg", "steps": 2})
    with pytest.raises(PersonaEngineError, match="inválida"):
        engine.normalize_appearance({"photo": "foto.jpg", "cabelo": "longo"})


def test_the_engine_declares_an_opaque_clip_with_only_the_neutral_expression_and_no_gestures(engine):
    assert (engine.kind, engine.version, engine.produces_alpha) == ("realistic", "pr1", False)
    assert engine.expressions == ("neutral",) and engine.gestures == ()
    assert registry.capabilities(Persona(id="a", name="A", kind="realistic")) == (["neutral"], [])


def test_creating_a_realistic_persona_copies_the_photo_into_its_folder(tmp_path, library):
    made = persona_service.create_persona(
        "Ana Real",
        kind="realistic",
        voice=None,
        library=library,
        voices=VoiceLibrary(tmp_path / "vozes"),
        photo=make_photo(tmp_path / "minha.png", fmt="PNG"),
    )
    assert made["kind"] == "realistic" and made["appearance"] == {"photo": "foto.png", "steps": 15}
    assert made["expressions"] == ["neutral"] and made["gestures"] == []
    stored = library.get("ana-real")
    assert stored.folder is not None and (stored.folder / "foto.png").is_file()
    assert (tmp_path / "minha.png").is_file()  # a original fica onde estava


def test_creation_refuses_a_missing_photo_a_wrong_one_and_a_photo_on_another_kind(tmp_path, library):
    voices = VoiceLibrary(tmp_path / "vozes")

    def create(**kwargs):
        return persona_service.create_persona("Ana", library=library, voices=voices, **kwargs)

    with pytest.raises(ValueError, match="precisa de uma foto"):
        create(kind="realistic")
    with pytest.raises(ValueError, match="lado menor precisa ter pelo menos 512"):
        create(kind="realistic", photo=make_photo(tmp_path / "p.jpg", (400, 900)))
    with pytest.raises(ValueError, match=r"\.jpg ou \.png"):
        create(kind="realistic", photo=make_photo(tmp_path / "x.webp", fmt="WEBP"))
    with pytest.raises(ValueError, match="Só a persona realista usa foto"):
        create(kind="2d", photo=make_photo(tmp_path / "q.jpg"))
    assert library.list() == []  # nada pela metade no cadastro


# ---------- a validação das marcas ----------


def test_marks_are_refused_in_portuguese_because_the_realistic_type_only_speaks(tmp_path, library):
    persona_of(library, tmp_path)
    project = Project.model_validate(
        {
            "name": "p",
            "output": {"preset": "instagram/reels"},
            "timeline": [
                {
                    "type": "persona",
                    "persona": "ana",
                    "speech": {"text": "Oi"},
                    "marks": [{"at": 0.1, "expression": "happy"}, {"at": 0.2, "gesture": "wave"}],
                }
            ],
        }
    )
    problems = persona_problems(project, library.get)
    assert len(problems) == 2
    assert "a expressão 'happy' não existe nesta persona (tipo realistic); use: neutral." in problems[0]
    assert "o gesto 'wave' não existe nesta persona (tipo realistic); use: nenhuma." in problems[1]


# ---------- a chave de cache ----------


def test_the_cache_key_follows_the_content_of_the_photo_the_audio_the_seed_and_the_steps(
    tmp_path, library, engine, speech
):
    persona = persona_of(library, tmp_path)
    base = clip_cache_key(engine, render_request(persona, speech))
    assert clip_cache_key(engine, render_request(persona, speech)) == base

    other_path = tmp_path / "outro-nome.wav"
    other_path.write_bytes(speech.read_bytes())
    assert (
        clip_cache_key(engine, render_request(persona, other_path)) == base
    )  # o conteúdo manda, não o caminho

    different = tmp_path / "diferente.wav"
    different.write_bytes(b"outra fala")
    assert clip_cache_key(engine, render_request(persona, different)) != base
    assert clip_cache_key(engine, render_request(persona, speech, seed=9)) != base
    assert clip_cache_key(engine, render_request(persona, speech, framing="corner")) != base

    folder = persona.folder
    assert folder is not None
    (folder / "foto.jpg").write_bytes((folder / "foto.jpg").read_bytes() + b"\x00")  # outra foto
    assert clip_cache_key(engine, render_request(library.get("ana"), speech)) != base

    more_steps = library.update("ana", {"appearance": {"steps": 20}})
    assert clip_cache_key(engine, render_request(more_steps, speech)) != base


def test_the_cache_key_carries_the_models_revision_the_steps_and_the_seed(tmp_path, library, engine, speech):
    persona = persona_of(library, tmp_path)
    parts = engine.cache_parts(render_request(persona, speech))
    assert ditto_models.REVISION in parts and parts[3:] == (15, 7)  # passos e a semente padrão


# ---------- disponibilidade ----------


def test_unavailable_reason_names_what_is_missing_and_the_command_that_fixes_it(
    tmp_path, monkeypatch, engine
):
    assert engine.unavailable_reason() is None
    monkeypatch.setattr(realistic, "missing_packages", lambda: ["openvino", "cv2"])
    reason = engine.unavailable_reason() or ""
    assert "openvino, cv2" in reason and "pip install -e .[persona-realista]" in reason
    monkeypatch.setattr(realistic, "missing_packages", lambda: [])
    empty = RealisticEngine(head=FakeHead(), models_dir=tmp_path / "vazio")
    assert "dmaker models download persona-realista" in (empty.unavailable_reason() or "")


def test_the_doctor_line_says_packages_models_and_gpu(tmp_path, monkeypatch, models_dir):
    assert "pronta, com GPU integrada" in realistic.doctor_line(FakeHead(gpu=True), models_dir)
    assert "só CPU" in realistic.doctor_line(FakeHead(gpu=False), models_dir)
    assert "modelos não baixados" in realistic.doctor_line(FakeHead(), tmp_path / "vazio")
    monkeypatch.setattr(realistic, "missing_packages", lambda: ["openvino"])
    assert "faltam os pacotes openvino" in realistic.doctor_line(FakeHead(), models_dir)


def test_the_forecast_uses_the_measured_estimate_for_the_device(tmp_path, library, speech, models_dir):
    persona = persona_of(library, tmp_path)
    request = render_request(persona, speech, duration=6.0)
    gpu = RealisticEngine(head=FakeHead(gpu=True), models_dir=models_dir).forecast(request)
    cpu = RealisticEngine(head=FakeHead(gpu=False), models_dir=models_dir).forecast(request)
    assert gpu == "estimativa de 19 min 45 s na GPU integrada"  # 135 + 175 x 6
    assert cpu.startswith("estimativa de 1 h 52 min") and "sem GPU integrada" in cpu  # 170 + 1100 x 6


# ---------- o clipe e o quadro parado ----------


def touch_part(command) -> None:
    Path(command.args[-1]).write_bytes(b"clip")


def test_render_frames_the_photo_runs_the_head_and_pipes_the_frames_into_ffmpeg(
    tmp_path, library, engine, head, speech
):
    persona = persona_of(library, tmp_path)
    runner = RecordingRunner(on_run=touch_part)
    out = tmp_path / "cache" / "clip.mov"
    warnings: list[str] = []
    logs: list[str] = []

    engine.render(render_request(persona, speech), out, runner, warnings.append, logs.append)

    assert out.read_bytes() == b"clip" and not list(out.parent.glob("*.part*"))
    assert runner.frames_consumed == 25  # 1 s a 25 quadros por segundo
    joined = " ".join(runner.commands[0])
    assert "-f rawvideo -pix_fmt rgb24 -s 270x480 -r 25 -i pipe:0" in joined
    assert "fps=30" in joined and "-t 1.000" in joined and "libx264" in joined and "bt709" in joined
    request = head.requests[0]
    assert (request.audio, request.size, request.duration, request.seed, request.steps) == (
        speech,
        (270, 480),
        1.0,
        7,
        15,
    )
    assert head.photos[0].shape == (480, 270, 3)  # a foto já enquadrada no tamanho do quadro
    assert warnings == ["aviso do ditto"] and logs == ["persona realista: desenhando de mentira"]
    assert not list(out.parent.glob("photo_*"))  # a pasta da foto enquadrada não fica no cache


def test_the_speech_seed_of_the_request_reaches_the_head(tmp_path, library, engine, head, speech):
    persona = persona_of(library, tmp_path)
    runner = RecordingRunner(on_run=touch_part)
    engine.render(render_request(persona, speech, seed=42), tmp_path / "c.mov", runner, print)
    assert head.requests[0].seed == 42


def test_render_without_the_speech_audio_says_so(tmp_path, library, engine):
    persona = persona_of(library, tmp_path)
    with pytest.raises(PersonaEngineError, match="precisa do áudio da fala"):
        engine.render(render_request(persona, None), tmp_path / "c.mov", RecordingRunner(), print)


def test_a_head_that_stops_midway_leaves_no_clip_and_raises_the_reason(tmp_path, library, models_dir, speech):
    persona = persona_of(library, tmp_path)
    failing = RealisticEngine(
        head=FakeHead(fail_after=3), face_finder=lambda image: FACE, models_dir=models_dir
    )
    out = tmp_path / "c.mov"
    with pytest.raises(PersonaEngineError, match="A persona realista falhou: a GPU parou"):
        failing.render(render_request(persona, speech), out, RecordingRunner(on_run=touch_part), print)
    assert not out.exists() and not list(tmp_path.glob("*.part*"))


def test_a_photo_without_a_face_fails_before_the_head_starts(tmp_path, library, models_dir, speech, head):
    persona = persona_of(library, tmp_path)
    blind = RealisticEngine(head=head, face_finder=lambda image: None, models_dir=models_dir)
    with pytest.raises(PersonaEngineError, match="Não achei um rosto"):
        blind.render(render_request(persona, speech), tmp_path / "c.mov", RecordingRunner(), print)
    assert head.requests == []


def test_a_small_photo_is_warned_about_at_render(tmp_path, library, models_dir, speech, head):
    persona = persona_of(library, tmp_path, name="Pequena", size=(600, 600))
    small = RealisticEngine(
        head=head, face_finder=lambda image: Box(200, 200, 150, 150), models_dir=models_dir
    )
    warnings: list[str] = []
    small.render(
        render_request(persona, speech, size=(1080, 1920)),
        tmp_path / "c.mov",
        RecordingRunner(on_run=touch_part),
        warnings.append,
    )
    assert any("pequena" in warning and "borrado" in warning for warning in warnings)


def test_still_is_the_framed_photo_as_a_png_with_the_notice_that_the_mouth_only_moves_in_the_render(
    tmp_path, library, engine, speech
):
    persona = persona_of(library, tmp_path)
    warnings: list[str] = []
    png = engine.still(render_request(persona, speech), 0.5, warnings.append)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(png)).size == (270, 480)
    assert warnings == [realistic.STILL_NOTICE] and "boca" in warnings[0]


# ---------- o render completo, com o estágio das personas ----------


def test_the_render_logs_the_estimate_and_the_progress_and_the_second_render_comes_from_the_cache(
    tmp_path, library, engine, head
):
    persona_of(library, tmp_path)
    (tmp_path / "base.mp4").write_bytes(b"x")
    spec = {
        "name": "pessoa",
        "output": {"preset": "instagram/reels"},
        "timeline": [
            {
                "type": "persona",
                "persona": "ana",
                "speech": {"text": "Olá, eu sou a Ana e estou falando.", "seed": 5},
            }
        ],
    }

    def render(logs: list[str]) -> None:
        project = Project.model_validate(spec)
        project.base_dir = tmp_path
        RenderPipeline(
            project,
            RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
            runner=RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON),
            prober=fake_prober,
            transcriber_factory=lambda captions: pytest.fail("a persona não legenda pelo Whisper"),
            cache_dir=tmp_path / "mez",
            jobs_dir=tmp_path / "jobs",
            output_dir=tmp_path / "output",
            narrator=NarrationService(
                FakeSynthesizer(), RecordingRunner(on_run=touch_output), tmp_path / "voice-cache"
            ),
            personas=PersonaStage(library, VoiceLibrary(tmp_path / "vozes"), word_timer=timed_words),
            log=logs.append,
        ).run()

    first: list[str] = []
    render(first)
    assert len(head.requests) == 1 and head.requests[0].seed == 5
    estimate = [line for line in first if "estimativa de" in line]
    assert estimate and "na GPU integrada" in estimate[0] and estimate[0].startswith("persona Ana:")
    assert "persona realista: desenhando de mentira" in first  # o andamento do motor chega ao log do render

    second: list[str] = []
    render(second)
    assert len(head.requests) == 1  # o mesmo conteúdo: o clipe veio do cache, o ditto não rodou de novo
    assert not [line for line in second if "estimativa de" in line]
