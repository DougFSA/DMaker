"""Cadastro de personas: as prontas somente leitura, as do usuário em pasta temporária, a aparência conferida pelo motor."""

from __future__ import annotations

import json

import pytest

from dmaker import config
from dmaker.persona.engine import PersonaEngineError
from dmaker.persona.library import PersonaLibrary, PersonaNotFoundError, slugify
from dmaker.pipeline import personas
from dmaker.voice.library import VoiceNotFoundError


@pytest.fixture
def library(tmp_path) -> PersonaLibrary:
    return PersonaLibrary(root=tmp_path / "suas", presets_root=tmp_path / "prontas")


def test_the_ready_made_personas_ship_with_the_repository_and_the_users_live_elsewhere():
    ready = PersonaLibrary().list()
    assert {"lia", "caio"} <= {p.id for p in ready}
    assert all(p.builtin and p.kind == "2d" for p in ready)
    assert config.PERSONA_PRESETS_DIR != config.PERSONAS_DIR
    assert config.PERSONAS_DIR.is_relative_to(
        config.DATA_DIR
    )  # o dado da máquina nunca cai dentro do repositório


def test_create_get_list_and_the_defaults_filled_in(library):
    created = library.create("Dona Clara", voice="dora", appearance={"hair_style": "bun", "skin": "#c98e6b"})
    assert created.id == "dona-clara" and created.kind == "2d" and not created.builtin
    assert created.appearance["hair_style"] == "bun"
    assert created.appearance["skin"] == "#C98E6B"  # cor normalizada
    assert created.appearance["outfit_color"]  # o que faltou ganhou o padrão
    assert library.get("dona-clara").voice == "dora"
    assert [p.id for p in library.list()] == ["dona-clara"]
    saved = json.loads((library.root / "dona-clara" / "persona.json").read_text(encoding="utf-8"))
    assert "folder" not in saved and "builtin" not in saved


def test_an_invalid_appearance_or_kind_is_refused_with_a_clear_message(library):
    with pytest.raises(PersonaEngineError, match="não é uma cor"):
        library.create("Ruim", appearance={"skin": "marrom"})
    with pytest.raises(PersonaEngineError, match="hair_style"):
        library.create("Ruim", appearance={"hair_style": "careca"})
    with pytest.raises(PersonaEngineError, match="ainda não tem motor"):
        library.create("Tridimensional", kind="3d")
    with pytest.raises(PersonaEngineError, match="não existe no tipo 2d"):
        library.create("Dancarina", gestures=["dance"])
    assert library.list() == []  # nada pela metade no cadastro


def test_a_duplicate_name_is_refused_and_so_is_the_id_of_a_ready_made_persona(tmp_path):
    ready = tmp_path / "prontas" / "lia"
    ready.mkdir(parents=True)
    (ready / "persona.json").write_text(
        json.dumps({"id": "lia", "name": "Lia", "kind": "2d", "appearance": {}}), encoding="utf-8"
    )
    library = PersonaLibrary(root=tmp_path / "suas", presets_root=tmp_path / "prontas")
    with pytest.raises(ValueError, match="Já existe"):
        library.create("Lia")
    library.create("Beto")
    with pytest.raises(ValueError, match="Já existe"):
        library.create("beto")


def test_a_ready_made_persona_cannot_be_edited_or_removed(tmp_path):
    library = PersonaLibrary(root=tmp_path / "suas")
    with pytest.raises(ValueError, match="persona pronta"):
        library.remove("lia")
    with pytest.raises(ValueError, match="persona pronta"):
        library.update("lia", {"name": "Outra"})
    assert library.get("lia").name == "Lia"


def test_update_merges_the_appearance_and_keeps_the_kind(library):
    library.create("Beto", appearance={"skin": "#B9825F", "hair_style": "short"})
    updated = library.update("beto", {"name": "Beto Silva", "appearance": {"hair_style": "long"}})
    assert updated.name == "Beto Silva" and updated.id == "beto" and updated.kind == "2d"
    assert updated.appearance["hair_style"] == "long" and updated.appearance["skin"] == "#B9825F"
    assert library.get("beto").appearance["hair_style"] == "long"
    with pytest.raises(ValueError, match="não aceita editar"):
        library.update("beto", {"kind": "3d"})
    with pytest.raises(PersonaEngineError):
        library.update("beto", {"appearance": {"eye_color": "azul"}})
    assert library.get("beto").appearance["hair_style"] == "long"  # a edição recusada não gravou nada


def test_remove_deletes_the_folder_and_an_unknown_id_lists_the_known_ones(library):
    library.create("Beto")
    library.remove("beto")
    assert not (library.root / "beto").exists()
    with pytest.raises(PersonaNotFoundError, match="Personas disponíveis"):
        library.get("beto")


def test_slugify_drops_accents_and_refuses_a_name_without_letters():
    assert slugify("Zé da Conceição") == "ze-da-conceicao"
    with pytest.raises(ValueError):
        slugify("???")


def test_the_service_checks_the_voice_in_the_voice_library_and_reports_what_the_persona_can_do(
    library, tmp_path
):
    from dmaker.voice.library import VoiceLibrary

    voices = VoiceLibrary(root=tmp_path / "vozes")
    with pytest.raises(VoiceNotFoundError, match="Vozes disponíveis"):
        personas.create_persona("Beto", voice="inexistente", library=library, voices=voices)
    made = personas.create_persona("Beto", voice="dora", library=library, voices=voices)
    assert made["voice"] == "dora" and set(made["gestures"]) == {"nod", "shake", "tilt", "wave"}
    assert "surprised" in made["expressions"] and made["builtin"] is False
    with pytest.raises(ValueError, match="não está disponível"):
        personas.create_persona("Beto 3D", kind="3d", library=library, voices=voices)
    personas.edit_persona("beto", {"name": "Beto Novo"}, library, voices)
    assert personas.get_persona("beto", library)["name"] == "Beto Novo"
    personas.remove_persona("beto", library)
    assert personas.list_personas(library) == []


def test_the_fingerprint_changes_with_the_look_but_not_with_the_name_or_the_voice(library):
    first = library.create("Beto", voice="dora")
    renamed = library.update("beto", {"name": "Outro Nome", "voice": "alex"})
    assert first.fingerprint() == renamed.fingerprint()
    recolored = library.update("beto", {"appearance": {"hair_color": "#FFFFFF"}})
    assert recolored.fingerprint() != first.fingerprint()
