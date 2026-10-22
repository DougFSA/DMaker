"""Design de voz: montagem e validação do instruct."""

from __future__ import annotations

import pytest

from dmaker.voice.design import ACCENTS, AGES, GENDERS, PITCHES, VoiceDesign, parse_instruct


def test_to_instruct_uses_documented_order():
    design = VoiceDesign(gender="female", age="young adult", pitch="high pitch", accent="british accent")
    assert design.to_instruct() == "female, young adult, high pitch, british accent"


def test_whisper_goes_before_accent():
    assert VoiceDesign(gender="male", whisper=True, accent="indian accent").to_instruct() == (
        "male, whisper, indian accent"
    )


def test_portuguese_aliases_are_translated():
    design = VoiceDesign(gender="Feminino", age="idosa", pitch="Médio", accent="Português")
    assert design.to_instruct() == "female, elderly, moderate pitch, portuguese accent"


def test_empty_design_is_rejected_in_portuguese():
    with pytest.raises(ValueError, match="pelo menos um atributo"):
        VoiceDesign().to_instruct()


def test_unknown_value_lists_the_options():
    with pytest.raises(ValueError, match="Gênero inválido"):
        VoiceDesign(gender="robô")
    with pytest.raises(ValueError, match="very low pitch"):
        VoiceDesign(pitch="altíssimo")


def test_parse_instruct_roundtrip_and_aliases():
    design = parse_instruct("masculino, grave, sussurro, british accent")
    assert design.to_instruct() == "male, low pitch, whisper, british accent"


def test_parse_instruct_rejects_unknown_terms_and_conflicts():
    with pytest.raises(ValueError, match="Termo de voz desconhecido: 'azul'"):
        parse_instruct("male, azul")
    with pytest.raises(ValueError, match="conflito"):
        parse_instruct("male, female")


def test_terms_match_the_ones_the_omnivoice_package_accepts():
    voice_design = pytest.importorskip("omnivoice.utils.voice_design")
    ours = set(GENDERS) | set(AGES) | set(PITCHES) | set(ACCENTS) | {"whisper"}
    assert ours <= voice_design._INSTRUCT_VALID_EN
