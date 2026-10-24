"""Dicionários de pronúncia em disco: global, por marca, e como a marca se sobrepõe ao global."""

from __future__ import annotations

import json

import pytest

from dmaker import config
from dmaker.voice.lexicon_store import LexiconStore
from dmaker.voice.pronunciation import Lexicon, apply_lexicon


@pytest.fixture
def store(tmp_path):
    (tmp_path / "brands" / "medlycare").mkdir(parents=True)
    (tmp_path / "brands" / "outra").mkdir()
    return LexiconStore(tmp_path)


def test_missing_files_are_empty_lexicons(store):
    assert store.list() == Lexicon()
    assert store.list("medlycare") == Lexicon()
    assert store.for_brand("medlycare") == Lexicon()
    assert store.for_brand("marca-sem-pasta") == Lexicon()  # ler nunca falha por falta de arquivo


def test_add_writes_sorted_utf8_json_in_the_global_file(store, tmp_path):
    store.add("MedlyCare", "Médli Quér")
    store.add("DMaker", "Di Meiker")

    written = (tmp_path / "pronunciation.json").read_text(encoding="utf-8")
    assert json.loads(written) == {"pt": {"DMaker": "Di Meiker", "MedlyCare": "Médli Quér"}}
    assert "Médli" in written  # UTF-8 legível, sem é
    assert list(json.loads(written)["pt"]) == ["DMaker", "MedlyCare"]
    assert store.list().as_dict() == {"DMaker": "Di Meiker", "MedlyCare": "Médli Quér"}


def test_add_replaces_the_same_term_ignoring_case(store):
    store.add("DMaker", "Di Meiker")
    updated = store.add("dmaker", "Dimêiker")

    assert updated.as_dict() == {"dmaker": "Dimêiker"}
    assert store.list().as_dict() == {"dmaker": "Dimêiker"}


def test_brand_lexicon_overrides_the_global_one(store):
    store.add("DMaker", "Di Meiker")
    store.add("API", "êi-pi-ai")
    store.add("DMaker", "Dimêiker", brand="medlycare")

    assert store.for_brand("medlycare").as_dict() == {"API": "êi-pi-ai", "DMaker": "Dimêiker"}
    assert store.for_brand("outra").as_dict() == {"API": "êi-pi-ai", "DMaker": "Di Meiker"}
    assert store.for_brand().as_dict() == {"API": "êi-pi-ai", "DMaker": "Di Meiker"}
    assert store.list("medlycare").as_dict() == {"DMaker": "Dimêiker"}  # list mostra só o escopo pedido


def test_remove_only_touches_the_given_scope_and_ignores_case(store):
    store.add("DMaker", "Di Meiker")
    store.add("DMaker", "Dimêiker", brand="medlycare")

    store.remove("dmaker", brand="medlycare")
    assert store.list("medlycare") == Lexicon()
    assert store.for_brand("medlycare").as_dict() == {"DMaker": "Di Meiker"}

    store.remove("DMAKER")
    assert store.list() == Lexicon()


def test_removing_an_unknown_term_is_an_error(store):
    with pytest.raises(ValueError, match="não está no dicionário global"):
        store.remove("fantasma")
    with pytest.raises(ValueError, match="da marca medlycare"):
        store.remove("fantasma", brand="medlycare")


def test_add_requires_term_and_pronunciation(store):
    with pytest.raises(ValueError, match="termo"):
        store.add("  ", "algo")
    with pytest.raises(ValueError, match="termo"):
        store.add("DMaker", "")


def test_unknown_or_malicious_brand_is_refused_when_writing(store, tmp_path):
    with pytest.raises(ValueError, match="não encontrada"):
        store.add("DMaker", "Di Meiker", brand="nao-existe")
    with pytest.raises(ValueError, match="inválido"):
        store.add("DMaker", "Di Meiker", brand="../fora")
    with pytest.raises(ValueError, match="inválido"):
        store.list("a/b")
    assert not (tmp_path / "brands" / "nao-existe").exists()


def test_file_that_is_not_an_object_is_reported(store, tmp_path):
    (tmp_path / "pronunciation.json").write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ValueError, match="objeto JSON"):
        store.list()


def test_default_root_is_the_assets_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LEXICON_DIR", tmp_path)
    LexiconStore().add("DMaker", "Di Meiker")

    assert (tmp_path / "pronunciation.json").is_file()


def test_entries_are_scoped_by_language_and_default_to_portuguese(store, tmp_path):
    store.add("DMaker", "Di Mêiker")
    store.add("MedlyCare", "Medly Care", language="en")

    assert store.list().as_dict() == {"DMaker": "Di Mêiker"}
    assert store.list(language="en").as_dict() == {"MedlyCare": "Medly Care"}
    assert store.list(language="es") == Lexicon()
    assert json.loads((tmp_path / "pronunciation.json").read_text(encoding="utf-8")) == {
        "en": {"MedlyCare": "Medly Care"},
        "pt": {"DMaker": "Di Mêiker"},
    }


def test_language_code_is_normalized_like_the_synthesizer_does(store):
    store.add("DMaker", "Di Mêiker", language="pt-BR")
    store.add("Samanta", "Sâmanta", language="PT_br")
    store.add("MedlyCare", "Medly Care", language="en-US")

    assert store.list(language="pt").as_dict() == {"DMaker": "Di Mêiker", "Samanta": "Sâmanta"}
    assert store.for_brand(language="en-GB").as_dict() == {"MedlyCare": "Medly Care"}
    assert store.for_brand(language="pt_BR").as_dict() == {"DMaker": "Di Mêiker", "Samanta": "Sâmanta"}
    assert list(store.by_language()) == ["en", "pt"]


def test_for_brand_in_a_language_without_entries_does_not_replace_the_term(store):
    store.add("DMaker", "Di Mêiker")  # feita para o português

    assert store.for_brand(language="en") == Lexicon()
    assert apply_lexicon("The DMaker app.", store.for_brand(language="en")) == "The DMaker app."
    assert apply_lexicon("O DMaker.", store.for_brand(language="pt")) == "O Di Mêiker."


def test_brand_overrides_the_global_entry_only_in_the_same_language(store):
    store.add("DMaker", "Di Mêiker")
    store.add("DMaker", "Dee Maker", language="en")
    store.add("DMaker", "Dimêiker", brand="medlycare")

    assert store.for_brand("medlycare", "pt").as_dict() == {"DMaker": "Dimêiker"}
    assert store.for_brand("medlycare", "en").as_dict() == {"DMaker": "Dee Maker"}
    assert store.for_brand("outra", "pt").as_dict() == {"DMaker": "Di Mêiker"}


def test_old_flat_json_counts_as_portuguese_and_is_migrated_on_write(store, tmp_path):
    path = tmp_path / "pronunciation.json"
    path.write_text('{"DMaker": "Di Mêiker", "MedlyCare": "Médlikér"}', encoding="utf-8")

    assert store.list().as_dict() == {"DMaker": "Di Mêiker", "MedlyCare": "Médlikér"}
    assert store.list(language="en") == Lexicon()

    store.add("MedlyCare", "Medly Care", language="en")

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "en": {"MedlyCare": "Medly Care"},
        "pt": {"DMaker": "Di Mêiker", "MedlyCare": "Médlikér"},
    }


def test_mixed_flat_and_language_sections_are_merged(store, tmp_path):
    (tmp_path / "pronunciation.json").write_text(
        '{"DMaker": "Di Mêiker", "pt-BR": {"API": "êi-pi-ai"}, "en": {"API": "A P I"}}', encoding="utf-8"
    )

    assert store.list(language="pt").as_dict() == {"DMaker": "Di Mêiker", "API": "êi-pi-ai"}
    assert store.list(language="en").as_dict() == {"API": "A P I"}


def test_remove_is_per_language(store):
    store.add("DMaker", "Di Mêiker")
    store.add("DMaker", "Dee Maker", language="en")

    store.remove("dmaker", language="en")

    assert store.list(language="en") == Lexicon()
    assert store.list().as_dict() == {"DMaker": "Di Mêiker"}
    with pytest.raises(ValueError, match="idioma en"):
        store.remove("DMaker", language="en")


def test_for_brand_without_language_gathers_the_terms_of_every_language(store):
    store.add("DMaker", "Di Mêiker")
    store.add("MedlyCare", "Medly Care", language="en")
    store.add("Samanta", "Sâmanta", brand="medlycare", language="es")

    terms = [term for term, _ in store.for_brand("medlycare", None).entries]

    assert terms == ["DMaker", "MedlyCare", "Samanta"]
    assert [term for term, _ in store.for_brand(None, None).entries] == ["DMaker", "MedlyCare"]


def test_blank_language_is_refused_when_writing(store):
    with pytest.raises(ValueError, match="idioma"):
        store.add("DMaker", "Di Mêiker", language="  ")
