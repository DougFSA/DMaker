"""O motor 3D sem navegador: aparência, avatar `.glb` conferido, chave de cache, dados da página e o modelo baixável."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from dmaker import config
from dmaker.domain.models import REGISTRY
from dmaker.domain.persona import Persona, PersonaMark
from dmaker.persona.engine import PersonaEngineError, PersonaRender, clip_cache_key, engine_for
from dmaker.persona.engine3d import BUILTIN_MODEL_ID, Engine3D, page_data
from dmaker.persona.glb import REQUIRED_BONES, REQUIRED_VISEMES, avatar_problems, read_glb_json
from dmaker.persona.marks import mark_problems
from dmaker.persona.visemes import VisemeSpan


def write_glb(path: Path, *, targets=REQUIRED_VISEMES, bones=REQUIRED_BONES) -> Path:
    """Um `.glb` mínimo: só o cabeçalho JSON que o motor lê (nenhuma malha de verdade)."""
    description = {
        "asset": {"version": "2.0"},
        "nodes": [{"name": name} for name in bones],
        "meshes": [{"name": "base", "primitives": [], "extras": {"targetNames": list(targets)}}],
    }
    body = json.dumps(description).encode("utf-8")
    body += b" " * (-len(body) % 4)
    total = 12 + 8 + len(body)
    path.write_bytes(
        b"glTF" + struct.pack("<II", 2, total) + struct.pack("<II", len(body), 0x4E4F534A) + body
    )
    return path


class FakeHtml:
    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason

    def unavailable_reason(self) -> str | None:
        return self.reason


def persona(**changes) -> Persona:
    fields = {"id": "bia", "name": "Bia", "kind": "3d", "appearance": {"model": "mpfb"}}
    return Persona(**{**fields, **changes})


def request(**changes) -> PersonaRender:
    fields = {
        "persona": persona(),
        "visemes": (VisemeSpan(0.0, 0.5, "sil"), VisemeSpan(0.5, 1.0, "aa")),
        "expression": "neutral",
        "marks": (PersonaMark(at=0.4, gesture="handup"),),
        "duration": 1.0,
        "fps": 30.0,
        "size": (270, 480),
    }
    return PersonaRender(**{**fields, **changes})


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path / "models"


@pytest.fixture
def page_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "pagina"
    folder.mkdir()
    (folder / "index.html").write_text("<html>v1</html>", encoding="utf-8")
    return folder


def test_the_3d_engine_is_registered_and_declares_what_it_does():
    engine = engine_for("3d")
    assert engine.kind == "3d" and engine.produces_alpha is True
    assert {"neutral", "happy", "sad", "surprised"} == set(engine.expressions)
    # os gestos do TalkingHead que não dependem de arquivo Mixamo, mais a cabeça
    assert {
        "nod",
        "shake",
        "tilt",
        "wave",
        "handup",
        "index",
        "ok",
        "thumbup",
        "thumbdown",
        "side",
        "shrug",
    } == set(engine.gestures)


def test_the_gestures_of_the_2d_engine_are_all_valid_in_3d():
    """Uma spec feita para a persona 2D não pode quebrar ao trocar a persona por uma 3D."""
    assert set(engine_for("2d").gestures) <= set(engine_for("3d").gestures)


def test_marks_the_3d_engine_does_not_know_are_refused_before_rendering():
    engine = engine_for("3d")
    marks = [PersonaMark(at=1, gesture="handup"), PersonaMark(at=2, gesture="cartwheel")]
    problems = mark_problems(marks, "neutral", engine.expressions, engine.gestures, 5.0, "timeline[0]", "3d")
    assert len(problems) == 1 and "'cartwheel'" in problems[0] and "handup" in problems[0]


def test_appearance_defaults_to_the_builtin_model_and_refuses_what_is_not_a_model(page_dir):
    engine = Engine3D(FakeHtml(), page_dir)
    assert engine.normalize_appearance({}) == {"model": "mpfb", "outfit_color": "#3A4A5E"}
    assert engine.normalize_appearance({"model": "meu-personagem.glb", "outfit_color": "#aa3322"}) == {
        "model": "meu-personagem.glb",
        "outfit_color": "#AA3322",
    }
    with pytest.raises(PersonaEngineError):
        engine.normalize_appearance({"outfit_color": "vermelho"})
    for wrong in ("../fora.glb", "pasta/avatar.glb", "avatar.fbx", "C:/x/avatar.glb"):
        with pytest.raises(PersonaEngineError, match="não é um modelo"):
            engine.normalize_appearance({"model": wrong})
    with pytest.raises(PersonaEngineError, match="Aparência 3D inválida"):
        engine.normalize_appearance({"skin": "#FFFFFF"})


def test_without_the_model_the_engine_says_how_to_download_it(models_dir, page_dir):
    engine = Engine3D(FakeHtml(), page_dir)
    reason = engine.unavailable_reason()
    assert reason and f"dmaker models download {BUILTIN_MODEL_ID}" in reason
    with pytest.raises(PersonaEngineError, match="dmaker models download persona3d-mpfb"):
        engine.model_file(request())
    (models_dir / "persona3d").mkdir(parents=True)
    write_glb(models_dir / "persona3d" / "mpfb.glb")
    assert engine.unavailable_reason() is None
    assert engine.model_file(request()).name == "mpfb.glb"


def test_the_browser_problem_comes_before_the_model_problem(models_dir, page_dir):
    assert "Chromium" in Engine3D(FakeHtml("Falta o Chromium."), page_dir).unavailable_reason()


def test_an_avatar_without_visemes_or_bones_is_refused_with_what_is_missing(tmp_path):
    no_visemes = write_glb(tmp_path / "sem-boca.glb", targets=("jawOpen", "viseme_aa"))
    problems = avatar_problems(no_visemes)
    assert len(problems) == 1 and "(viseme_PP," in problems[0] and "viseme_FF" in problems[0]
    no_bones = write_glb(tmp_path / "sem-ossos.glb", bones=("Hips",))
    assert "ossos" in avatar_problems(no_bones)[0] and "Head" in avatar_problems(no_bones)[0]
    assert avatar_problems(write_glb(tmp_path / "bom.glb")) == []


def test_a_file_that_is_not_a_glb_is_refused_without_crashing(tmp_path):
    fake = tmp_path / "foto.glb"
    fake.write_bytes(b"nao sou glTF")
    assert "não é um arquivo .glb" in avatar_problems(fake)[0]
    assert "não consegui abrir" in avatar_problems(tmp_path / "ausente.glb")[0].lower()
    assert read_glb_json(write_glb(tmp_path / "ok.glb"))["asset"]["version"] == "2.0"


def test_the_persona_own_glb_is_read_from_its_folder_and_checked(models_dir, page_dir, tmp_path):
    folder = tmp_path / "bia"
    folder.mkdir()
    engine = Engine3D(FakeHtml(), page_dir)
    own = persona(appearance={"model": "meu.glb"}, folder=folder)
    with pytest.raises(PersonaEngineError, match="não está na pasta dela"):
        engine.model_file(request(persona=own))
    write_glb(folder / "meu.glb", targets=("jawOpen",))
    with pytest.raises(PersonaEngineError, match="visema"):
        engine.model_file(request(persona=own))
    write_glb(folder / "meu.glb")
    assert engine.model_file(request(persona=own)) == folder / "meu.glb"


def test_the_cache_key_follows_the_page_the_framing_and_the_model(models_dir, page_dir):
    engine = Engine3D(FakeHtml(), page_dir)
    base = clip_cache_key(engine, request())
    assert clip_cache_key(engine, request()) == base  # o mesmo pedido, a mesma chave
    assert clip_cache_key(engine, request(framing="corner")) != base
    (page_dir / "index.html").write_text("<html>v2</html>", encoding="utf-8")
    assert clip_cache_key(engine, request()) != base
    after_page = clip_cache_key(engine, request())
    (models_dir / "persona3d").mkdir(parents=True)
    write_glb(models_dir / "persona3d" / "mpfb.glb")
    assert clip_cache_key(engine, request()) != after_page  # baixar o modelo muda o que o clipe desenha


def test_page_data_carries_the_mouth_the_marks_and_the_view():
    data = page_data(
        request(
            expression="happy",
            marks=(PersonaMark(at=2.0, expression="surprised"), PersonaMark(at=1.0, gesture="handup")),
            framing="corner",
        )
    )
    assert data["view"] == "corner" and data["fps"] == 30.0
    assert data["visemes"] == [[0.0, 0.5, "sil"], [0.5, 1.0, "aa"]]
    assert data["expressions"] == [[0.0, "happy"], [2.0, "surprised"]]
    assert data["gestures"] == [[1.0, "handup"]]
    assert page_data(request())["view"] == "full"
    assert data["model"].startswith("/_dmaker/files/")


def test_the_builtin_model_is_a_registered_download_with_a_pinned_hash():
    spec = next(item for item in REGISTRY if item.id == BUILTIN_MODEL_ID)
    assert spec.paths == ("persona3d/mpfb.glb",) and spec.license.startswith("CC0")
    from dmaker.persona.avatar_files import MPFB_AVATAR, TALKINGHEAD_COMMIT

    assert TALKINGHEAD_COMMIT in MPFB_AVATAR.url and len(MPFB_AVATAR.sha256) == 64
    assert MPFB_AVATAR.size == spec.expected_size


def test_a_big_clip_is_drawn_smaller_and_scaled_up_but_a_small_one_is_drawn_as_it_is():
    from dmaker.persona.engine3d import MAX_DRAWN_SIDE, draw_scale

    assert draw_scale((1080, 1920)) == MAX_DRAWN_SIDE / 1920 == 0.5
    assert draw_scale((540, 960)) == 1.0 and draw_scale((270, 480)) == 1.0
    assert draw_scale((1080, 1440)) * 1440 == MAX_DRAWN_SIDE


def test_the_doctor_line_says_the_3d_model_is_optional_and_how_to_download_it(tmp_path, monkeypatch):
    from dmaker import config
    from dmaker.persona.engine3d import builtin_model_path, doctor_line

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    missing = doctor_line()
    assert (
        "opcional" in missing
        and "não baixado" in missing
        and "dmaker models download persona3d-mpfb" in missing
    )
    builtin_model_path().parent.mkdir(parents=True)
    builtin_model_path().write_bytes(b"glb")
    assert "baixado" in doctor_line() and "não baixado" not in doctor_line()
