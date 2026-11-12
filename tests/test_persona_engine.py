"""O contrato do motor, o registro por tipo, a chave de cache do clipe e os dados da página 2D (sem navegador)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.persona import Persona, PersonaMark
from dmaker.media.ffmpeg import FFmpegCommand, FFmpegError
from dmaker.persona import engine as registry
from dmaker.persona.engine import PersonaEngineError, PersonaRender, clip_cache_key, engine_for
from dmaker.persona.engine2d import Appearance2D, Engine2D, page_data
from dmaker.persona.visemes import VisemeSpan


def request(**changes) -> PersonaRender:
    fields = {
        "persona": Persona(id="a", name="A", appearance=Appearance2D().model_dump()),
        "visemes": (VisemeSpan(0.0, 0.5, "sil"), VisemeSpan(0.5, 1.0, "aa")),
        "expression": "neutral",
        "marks": (PersonaMark(at=0.4, expression="happy"),),
        "duration": 1.0,
        "fps": 30.0,
        "size": (270, 480),
    }
    return PersonaRender(**{**fields, **changes})


class RecordingEngine:
    """Um motor de mentira, como o dos próximos tipos: registra-se pelo mesmo caminho."""

    kind = "fake"
    version = "f1"
    produces_alpha = False
    expressions = ("neutral",)
    gestures = ()

    def normalize_appearance(self, appearance):
        return dict(appearance)

    def cache_parts(self, request):
        return ("pagina",)

    def unavailable_reason(self):
        return None

    def render(self, request, out, runner, on_warning):
        out.write_bytes(b"clip")


def test_the_2d_engine_is_registered_by_default_and_an_unknown_kind_says_which_exist():
    assert engine_for("2d").kind == "2d" and "2d" in registry.engine_kinds()
    with pytest.raises(PersonaEngineError, match="ainda não tem motor.*2d"):
        engine_for("realistic")


def test_a_new_engine_registers_without_touching_the_pipeline(monkeypatch):
    monkeypatch.setattr(registry, "_ENGINES", dict(registry._ENGINES))
    registry.register_engine(RecordingEngine())
    assert engine_for("fake").produces_alpha is False and "fake" in registry.engine_kinds()


def test_capabilities_are_the_engines_limited_by_the_persona_lists():
    full = Persona(id="a", name="A")
    assert registry.capabilities(full)[0] == ["neutral", "happy", "sad", "surprised"]
    restricted = Persona(id="a", name="A", expressions=["happy"], gestures=["nod"])
    assert registry.capabilities(restricted) == (["happy"], ["nod"])


def test_the_cache_key_is_stable_and_changes_with_everything_that_changes_a_frame():
    engine = engine_for("2d")
    base = clip_cache_key(engine, request())
    assert clip_cache_key(engine, request()) == base
    assert clip_cache_key(engine, request(duration=1.5)) != base
    assert clip_cache_key(engine, request(fps=25.0)) != base
    assert clip_cache_key(engine, request(size=(540, 960))) != base
    assert clip_cache_key(engine, request(expression="sad")) != base
    assert clip_cache_key(engine, request(marks=())) != base
    assert clip_cache_key(engine, request(visemes=(VisemeSpan(0.0, 1.0, "sil"),))) != base
    other = Persona(id="a", name="A", appearance=Appearance2D(hair_style="bun").model_dump())
    assert clip_cache_key(engine, request(persona=other)) != base
    renamed = Persona(id="a", name="Outro nome", voice="alex", appearance=Appearance2D().model_dump())
    assert clip_cache_key(engine, request(persona=renamed)) == base  # nome e voz não mudam um quadro


def test_the_engine_version_and_the_page_content_enter_the_key(monkeypatch, tmp_path):
    engine = Engine2D(page_dir=tmp_path / "pagina")
    (tmp_path / "pagina").mkdir()
    (tmp_path / "pagina" / "index.html").write_text("<p>1</p>", encoding="utf-8")
    first = clip_cache_key(engine, request())
    (tmp_path / "pagina" / "index.html").write_text("<p>2</p>", encoding="utf-8")
    assert clip_cache_key(engine, request()) != first
    bumped = Engine2D(page_dir=tmp_path / "pagina")
    bumped.version = "p2"
    assert clip_cache_key(bumped, request()) != clip_cache_key(engine, request())


def test_the_page_data_carries_the_mouth_the_expressions_and_the_gestures():
    marks = (PersonaMark(at=2.0, expression="happy"), PersonaMark(at=1.0, gesture="nod"))
    data = page_data(request(marks=marks, expression="sad"), {"skin": "#FFFFFF"})
    assert data["appearance"] == {"skin": "#FFFFFF"}
    assert data["mouth"] == [[0.0, 0.5, "rest"], [0.5, 1.0, "open"]]
    assert data["expressions"] == [[0.0, "sad"], [2.0, "happy"]]
    assert data["gestures"] == [[1.0, "nod"]]
    assert page_data(request(marks=marks), {}) == page_data(request(marks=marks), {})  # função pura


def test_the_2d_appearance_is_normalized_and_refused_when_wrong():
    engine = Engine2D()
    assert engine.normalize_appearance({"hair_style": "long"})["hair_style"] == "long"
    assert engine.normalize_appearance({})["skin"].startswith("#")
    with pytest.raises(PersonaEngineError, match="Aparência 2D inválida"):
        engine.normalize_appearance({"cor_da_pele": "#FFFFFF"})


class FakeHtmlRenderer:
    def __init__(self, fail_after: int | None = None):
        self.fail_after = fail_after
        self.compositions = []

    def unavailable_reason(self):
        return None

    def frames(self, composition, times, on_warning):
        self.compositions.append((composition, list(times)))
        for number, _ in enumerate(times):
            if self.fail_after is not None and number >= self.fail_after:
                raise RuntimeError("a página travou")
            yield b"\x00" * (composition.size[0] * composition.size[1] * 4)


class DrainingRunner:
    """Um ffmpeg de mentira que lê os quadros do stdin e cria o arquivo, como o de verdade."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.commands: list[FFmpegCommand] = []
        self.frames = 0

    def run(self, command: FFmpegCommand) -> None:
        self.commands.append(command)
        for _ in command.frames or ():
            self.frames += 1
        if self.fail:
            raise FFmpegError("ffmpeg falhou", command.args, "stdin fechou")
        Path(command.args[-1]).write_bytes(b"mov")


def test_the_2d_engine_draws_one_page_frame_per_video_frame_through_the_html_renderer(tmp_path):
    html = FakeHtmlRenderer()
    runner = DrainingRunner()
    out = tmp_path / "clip.mov"
    Engine2D(renderer=html).render(request(), out, runner, lambda message: None)
    composition, times = html.compositions[0]
    assert composition.source.name == "2d" and composition.size == (270, 480)
    assert times == [i / 30 for i in range(30)]  # 1 s a 30 fps
    assert composition.data["mouth"] and runner.frames == 30
    assert out.exists() and not list(tmp_path.glob("*.part*"))  # o arquivo só ganha o nome final inteiro
    assert "png" in runner.commands[0].args  # vídeo com alfa, como a camada das composições


def test_a_page_that_stops_midway_is_reported_and_leaves_nothing_in_the_cache(tmp_path):
    out = tmp_path / "clip.mov"
    with pytest.raises(PersonaEngineError, match="a página travou"):
        Engine2D(renderer=FakeHtmlRenderer(fail_after=3)).render(
            request(), out, DrainingRunner(), lambda message: None
        )
    assert not out.exists() and not list(tmp_path.glob("*.part*"))
    with pytest.raises(PersonaEngineError, match="a página travou"):
        Engine2D(renderer=FakeHtmlRenderer(fail_after=3)).render(
            request(), out, DrainingRunner(fail=True), lambda message: None
        )
    assert not out.exists() and not list(tmp_path.glob("*.part*"))
