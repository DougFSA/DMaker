"""Pronúncia: dicionário termo -> fala e marcação pontual `[[termo|pronúncia]]` (funções puras)."""

from __future__ import annotations

from dmaker.voice.pronunciation import (
    Lexicon,
    apply_inline_overrides,
    apply_lexicon,
    language_code,
    spoken_text,
    written_text,
)


def test_lexicon_drops_empty_entries_and_case_duplicates():
    lexicon = Lexicon.of(
        {"DMaker": "Di Meiker", "  ": "x", "vazio": "  ", "dmaker": "Di Maker", " API ": " êi-pi-ai "}
    )

    assert lexicon.as_dict() == {"API": "êi-pi-ai", "dmaker": "Di Maker"}  # o último repetido vence
    assert len(lexicon) == 2 and bool(lexicon) and not Lexicon.of({}) and not Lexicon.of(None)


def test_overlaid_lexicon_wins_on_same_term_ignoring_case():
    base = Lexicon.of({"DMaker": "Di Meiker", "API": "êi-pi-ai"})
    top = Lexicon.of({"dmaker": "Dimêiker"})

    assert base.overlaid_with(top).as_dict() == {"API": "êi-pi-ai", "dmaker": "Dimêiker"}


def test_term_matches_only_whole_words_without_case_sensitivity():
    lexicon = Lexicon.of({"cat": "gato"})

    assert apply_lexicon("Cat, CAT e cat.", lexicon) == "gato, gato e gato."
    assert apply_lexicon("category concat cats", lexicon) == "category concat cats"
    assert apply_lexicon("o_cat e cat_", lexicon) == "o_cat e cat_"  # sublinhado é caractere de palavra


def test_longest_term_wins_when_terms_overlap():
    lexicon = Lexicon.of({"Dr": "doutor", "Dr. Silva": "doutor Silva", "Silva": "Silvá"})

    assert apply_lexicon("Dr. Silva chegou. Dr Souza também. Silva sorriu.", lexicon) == (
        "doutor Silva chegou. doutor Souza também. Silvá sorriu."
    )


def test_terms_with_dots_and_symbols_match_literally():
    lexicon = Lexicon.of({"C++": "cê mais mais", "R$": "reais", "e.g.": "por exemplo", ".NET": "dotnet"})

    assert apply_lexicon("Use C++ ou .NET, e.g. agora. Preço em R$ 10.", lexicon) == (
        "Use cê mais mais ou dotnet, por exemplo agora. Preço em reais 10."
    )
    assert apply_lexicon("aC++ x", lexicon) == "aC++ x"  # começa em letra: não casa no meio de uma palavra
    assert apply_lexicon("exe.g.", lexicon) == "exe.g."


def test_regex_metacharacters_in_terms_are_escaped():
    lexicon = Lexicon.of({"a|b": "ou", "(x)": "xis", "1+1": "dois"})

    assert apply_lexicon("a|b (x) 1+1 e aab", lexicon) == "ou xis dois e aab"


def test_accented_words_keep_their_boundaries():
    lexicon = Lexicon.of({"açaí": "assaí"})

    assert apply_lexicon("Açaí! Um açaízeiro.", lexicon) == "assaí! Um açaízeiro."


def test_empty_lexicon_and_empty_text_pass_through():
    assert apply_lexicon("DMaker", Lexicon()) == "DMaker"
    assert apply_lexicon("", Lexicon.of({"a": "b"})) == ""


def test_lexicon_does_not_rescan_its_own_output_and_is_idempotent_otherwise():
    chained = Lexicon.of({"DMaker": "Di Meiker", "Meiker": "Mêiquer"})
    assert (
        apply_lexicon("Use o DMaker.", chained) == "Use o Di Meiker."
    )  # a pronúncia não é relida na passada

    lexicon = Lexicon.of({"DMaker": "Di Meiker", "API": "êi-pi-ai"})
    once = apply_lexicon("Use o DMaker pela API.", lexicon)
    assert once == "Use o Di Meiker pela êi-pi-ai."
    assert apply_lexicon(once, lexicon) == once


def test_inline_override_with_and_without_pipe():
    assert apply_inline_overrides("Fale [[DMaker|Di Meiker]] e [[Nuh-VAD-uh]] agora.") == (
        "Fale Di Meiker e Nuh-VAD-uh agora."
    )
    assert apply_inline_overrides("[[a|b|c]]") == "b|c"  # só o primeiro pipe separa o termo
    assert apply_inline_overrides("[[]] e [pausa 1] e [x]") == " e [pausa 1] e [x]"
    assert apply_inline_overrides("sem marcação") == "sem marcação"


def test_inline_override_stays_linear_on_unclosed_brackets():
    hostile = "[[" * 5000
    assert apply_inline_overrides(hostile) == hostile
    assert written_text(hostile) == hostile


def test_written_text_keeps_the_term_or_the_bare_word():
    assert written_text("Use o [[DMaker|Di Meiker]] e a [[Samanta]].") == "Use o DMaker e a Samanta."
    assert written_text("sem marcação") == "sem marcação"


def test_spoken_text_resolves_overrides_first_and_lexicon_only_outside_them():
    lexicon = Lexicon.of({"DMaker": "Di Meiker", "API": "êi-pi-ai"})

    assert spoken_text("O DMaker usa a API.", lexicon) == "O Di Meiker usa a êi-pi-ai."
    # a marcação vence o dicionário e a pronúncia escolhida à mão não é reescrita por ele
    assert spoken_text("O [[DMaker|Dimêiker]] usa a API.", lexicon) == "O Dimêiker usa a êi-pi-ai."
    assert spoken_text("[[API|API]] e API", lexicon) == "API e êi-pi-ai"
    assert spoken_text("Sem nada.", Lexicon()) == "Sem nada."


def test_spoken_text_is_idempotent_once_markup_is_resolved():
    lexicon = Lexicon.of({"DMaker": "Di Meiker"})
    once = spoken_text("O DMaker e [[MedlyCare|Médli Quér]].", lexicon)

    assert once == "O Di Meiker e Médli Quér."
    assert spoken_text(once, lexicon) == once


def test_language_code_drops_the_region_and_ignores_case_and_separator():
    assert [language_code(code) for code in ("pt", "pt-BR", "pt_br", " EN-us ", "es")] == [
        "pt",
        "pt",
        "pt",
        "en",
        "es",
    ]
    assert language_code("") == ""
