"""Kits de ferramentas e triagem do agente local: dado puro e regra de palavras, sem modelo nenhum."""

from __future__ import annotations

import asyncio

import pytest

from dmaker import mcp_server
from dmaker.agent.kits import (
    BASE_TOOLS,
    DEFAULT_KIT,
    EXCLUDED_TOOLS,
    KITS,
    MAX_KITS_PER_REQUEST,
    all_kit_tool_names,
    kit_by_name,
    kit_tool_names,
    tools_for_kits,
)
from dmaker.agent.llm import Reply
from dmaker.agent.triage import (
    Triage,
    normalize,
    parse_kit_names,
    score_kit,
    triage,
    triage_by_keywords,
    triage_by_model,
    triage_messages,
)

# ---------- kits ----------


def server_tools() -> set[str]:
    return {tool.name for tool in asyncio.run(mcp_server.server.list_tools())}


def test_every_server_tool_is_in_a_kit_or_in_the_excluded_list_with_a_reason():
    """Ferramenta nova no servidor MCP não pode ficar esquecida: ou entra num kit ou diz por que fica de fora."""
    in_kits = set(all_kit_tool_names())
    forgotten = sorted(server_tools() - in_kits - set(EXCLUDED_TOOLS))
    assert not forgotten, f"ferramentas sem kit e sem motivo de exclusão: {forgotten}"


def test_excluded_tools_have_a_reason_exist_and_are_not_also_in_a_kit():
    assert all(reason.strip() for reason in EXCLUDED_TOOLS.values())
    assert set(EXCLUDED_TOOLS) <= server_tools(), "uma exclusão aponta para ferramenta que não existe mais"
    assert not set(EXCLUDED_TOOLS) & set(all_kit_tool_names())


def test_kits_are_well_formed():
    names = [kit.name for kit in KITS]
    assert len(names) == len(set(names))
    assert DEFAULT_KIT in names
    for kit in KITS:
        assert kit.title and kit.description and kit.keywords
        assert len(kit.tools) == len(set(kit.tools)), f"{kit.name} repete ferramenta"
        assert not set(BASE_TOOLS) & set(kit.tools), f"{kit.name} repete uma ferramenta comum"


def test_kits_name_the_tools_that_running_cards_will_create():
    compositions = kit_by_name("compositions").tools
    assert {"render_html_frame", "add_html_overlay", "list_infographics", "add_infographic"} <= set(
        compositions
    )


def test_kit_tool_names_filter_by_what_the_server_exposes_and_keep_the_common_ones_first():
    kit = kit_by_name("compositions")

    exposed = kit_tool_names(kit, available=server_tools())

    assert exposed[: len(BASE_TOOLS)] == list(BASE_TOOLS)
    assert "add_infographic" not in exposed and "edit_project" in exposed
    assert "add_infographic" in kit_tool_names(kit)


def test_tools_for_kits_merges_without_repeating():
    merged = tools_for_kits([kit_by_name("editing"), kit_by_name("multicam")], server_tools())

    assert len(merged) == len(set(merged))
    assert "quick_edit" in merged and "plan_multicam" in merged


def test_kit_by_name_rejects_an_unknown_kit_with_the_known_ones():
    with pytest.raises(KeyError, match="editing"):
        kit_by_name("nada")


def test_no_kit_is_too_big_for_a_small_model():
    """Esquemas demais comem o contexto de 16k: cada kit fica abaixo de 25 ferramentas."""
    for kit in KITS:
        assert len(kit_tool_names(kit, server_tools())) <= 25, kit.name


# ---------- triagem por palavras ----------


def test_normalize_drops_accents_case_and_apostrophes():
    assert normalize("Narração d'Água ÚNICA") == "narracao dagua unica"


@pytest.mark.parametrize(
    ("request_text", "kits"),
    [
        ("Faz um reel do vídeo X com legenda e a marca MedlyCare", ["editing"]),
        ("Narra este roteiro com a voz dora e põe no projeto", ["voice"]),
        ("Corta as pausas e os vícios desta gravação", ["editing"]),
        ("Dubla este vídeo para inglês", ["dubbing"]),
        ("Põe um contador de 0 a 95 mg em cima entre 10 e 14 s", ["compositions"]),
        ("Isola a voz da música deste áudio", ["speech"]),
        ("Separa a voz do ruído", ["speech"]),
        ("Monta o casamento com as duas câmeras", ["multicam"]),
        ("Gera um vídeo para cada linha da planilha", ["batch"]),
        ("Troca a palavra errada na legenda", ["captions"]),
    ],
)
def test_keywords_choose_the_kit_for_the_acceptance_requests(request_text, kits):
    result = triage_by_keywords(request_text)

    assert result is not None and list(result.kits) == kits and result.method == "keywords"


def test_triage_understands_requests_with_and_without_accents():
    with_accents = triage_by_keywords("Narração do roteiro com a voz")
    without = triage_by_keywords("Narracao do roteiro com a voz")

    assert (
        with_accents is not None and without is not None and with_accents.kits == without.kits == ("voice",)
    )


def test_a_tie_between_kits_takes_both_up_to_the_limit():
    result = triage_by_keywords("Corrige a legenda e renderiza")

    assert result is not None and set(result.kits) == {"editing", "captions"}
    assert len(result.kits) <= MAX_KITS_PER_REQUEST


def test_a_cross_kit_request_resolves_by_the_recipe_in_the_stronger_kit():
    """ "Corta as pausas e legenda" tem mais palavras de edição: fica no kit de edição, que traz a receita
    `cut_pauses_and_caption` e cobre os dois passos."""
    result = triage_by_keywords("Corta as pausas e legenda a gravação")

    assert result is not None and result.kits == ("editing",)
    assert "cut_pauses_and_caption" in kit_by_name("editing").tools


def test_short_keywords_only_match_whole_words():
    editing = kit_by_name("editing")

    assert score_kit(editing, "preciso do qa do projeto") >= 2
    assert score_kit(editing, "aqui vai um paquete") == 0  # "qa" dentro de outra palavra não conta


def test_expressions_weigh_one_point_per_word():
    speech = kit_by_name("speech")

    assert score_kit(speech, "separa a voz da música") == 3


def test_no_keyword_means_no_decision_by_words():
    assert triage_by_keywords("faz uma coisa para mim") is None


# ---------- triagem pelo modelo ----------


class CannedChat:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools):
        self.calls.append(messages)
        return Reply(content=self.text)


def test_the_model_triage_lists_every_kit_with_its_description_and_the_request():
    messages = triage_messages("faz uma coisa")

    body = messages[1]["content"]
    assert all(f"- {kit.name}: {kit.description}" in body for kit in KITS)
    assert "Pedido: faz uma coisa" in body


def test_parse_kit_names_reads_names_in_order_and_ignores_the_rest():
    assert parse_kit_names("Kits: speech, editing e batch") == ("speech", "editing")
    assert parse_kit_names("não sei") == ()


def test_triage_by_model_returns_none_when_the_answer_names_no_kit():
    assert triage_by_model("x", CannedChat("hum")) is None
    assert triage_by_model("x", CannedChat("voice")) == Triage(("voice",), "model")


def test_triage_does_not_call_the_model_when_the_words_decide():
    chat = CannedChat("batch")

    result = triage("Dubla este vídeo", chat)

    assert result.kits == ("dubbing",) and chat.calls == []


def test_triage_falls_back_to_the_model_then_to_the_default_kit():
    assert triage("faz uma coisa", CannedChat("dubbing")).kits == ("dubbing",)
    assert triage("faz uma coisa", CannedChat("sei lá")) == Triage((DEFAULT_KIT,), "default")
    assert triage("faz uma coisa") == Triage((DEFAULT_KIT,), "default")


def test_a_short_answer_keeps_the_previous_kit_without_calling_the_model():
    chat = CannedChat("batch")

    result = triage("sim, pode fazer", chat, previous=("voice",))

    assert result == Triage(("voice",), "previous") and chat.calls == []


def test_new_keywords_override_the_previous_kit():
    assert triage("agora dubla em inglês", previous=("voice",)).kits == ("dubbing",)
