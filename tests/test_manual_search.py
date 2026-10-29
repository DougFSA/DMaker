"""Busca no manual (BM25), `dmaker ajuda` com modelo falso e a correção da bateria de perguntas."""

from __future__ import annotations

import json

import pytest

from dmaker.agent.llm import Reply
from dmaker.manual import files
from dmaker.manual.ask import (
    NO_MODEL_NOTICE,
    answer_question,
    build_context,
    build_messages,
    search_only,
)
from dmaker.manual.bm25 import Bm25
from dmaker.manual.evaluation import grade, load_battery, normalize
from dmaker.manual.examples import extract_commands
from dmaker.manual.search import KIND_REFERENCE, KIND_TASK, ManualIndex, split_chunks
from dmaker.manual.tokens import STOPWORDS, stem, tokenize

from .manual_support import SAMPLE_MANUAL

BATTERY_PATH = files.checkout_docs_dir().parent / "tests" / "data" / "manual_perguntas.json"


def test_stem_puts_related_words_on_the_same_root():
    assert {stem(w) for w in ("dublar", "dublo", "dublagem", "dublado", "dublagens")} == {"dubl"}
    assert stem("legendas") == stem("legenda") == "legend"
    assert stem("voz") == "voz" and stem("vozes") == "voz"
    assert stem("123") == "123"


def test_tokenize_drops_accents_stopwords_and_keeps_identifiers_whole():
    assert "como" in STOPWORDS
    terms = tokenize("Como dublo o vídeo? Use render_project e --no-ui")
    assert "dubl" in terms and "como" not in terms
    assert (
        "render_project" in terms and "rend" in terms and "project" in terms
    )  # "rend" é o radical de render
    assert "no-ui" in terms
    assert tokenize("Áudio ÁUDIO audio") == ["audi", "audi", "audi"]


def test_bm25_ranks_the_document_that_has_the_rarer_matching_term_first():
    index = Bm25([["video", "corte"], ["video", "dublagem"], ["video", "video", "video"]])
    scores = index.scores(["dublagem"])
    assert scores[1] > 0 == scores[0] == scores[2]
    assert index.scores(["inexistente"]) == [0.0, 0.0, 0.0]
    assert Bm25([]).scores(["x"]) == []


def test_split_chunks_keeps_the_path_kind_and_task_of_each_piece():
    chunks = split_chunks(SAMPLE_MANUAL)
    cli_chunk = next(c for c in chunks if c.section.endswith("Pela CLI") and c.task_id == "reel")
    assert cli_chunk.kind == KIND_TASK and "dmaker quick" in cli_chunk.text
    assert cli_chunk.section == "Tarefas de vídeo > Fazer um Reel > Pela CLI"
    assert not any("indice" in c.text for c in chunks)  # o bloco do índice só repete títulos


def test_reference_blocks_are_chunked_by_entry_and_marked_as_reference():
    from dmaker.manual.build import build_all

    from .test_manual_generators import _inputs

    chunks = split_chunks(build_all(SAMPLE_MANUAL, _inputs()).manual)
    reference = [c for c in chunks if c.kind == KIND_REFERENCE]
    assert reference and all(c.task_id is None for c in reference)
    assert any("dmaker comando" not in c.text and "dmaker quick" in c.text for c in reference)


def test_search_finds_the_task_that_answers_and_ranks_task_intent_for_the_winner():
    index = ManualIndex.from_text(SAMPLE_MANUAL)
    hits = index.search("como dublo um vídeo para inglês?", limit=3)
    assert hits[0].chunk.task_id == "dublar"
    ranked = index.rank_tasks("quero a versão em inglês")
    assert ranked[0][0].id == "dublar"
    assert index.search("") == [] and index.search("xyzzy qwerty") == []


def test_real_manual_answers_the_fixed_battery_by_search_alone():
    """Sem modelo: a busca já põe a seção esperada entre as consultadas (o modelo só redige em cima)."""
    index = ManualIndex.from_text(files.read_manual())
    battery = load_battery(BATTERY_PATH.read_text(encoding="utf-8"))
    assert len(battery) == 10
    misses = []
    for question in battery:
        answer = search_only(question.text, index)
        sections = " ; ".join(source.section for source in answer.sources)
        if not any(normalize(wanted) in normalize(sections) for wanted in question.sections):
            misses.append(question.text)
    assert not misses, f"a busca não achou a seção esperada para: {misses}"


class _FakeChat:
    def __init__(self, text: str = "Rode `dmaker dub gravacao.mp4 --to en`.\nSeção: Dublar um vídeo") -> None:
        self.text = text
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls.append(messages)
        assert tools == []
        return Reply(content=self.text)


def test_answer_question_sends_the_task_file_as_context_and_cites_the_sections():
    index = ManualIndex.from_text(SAMPLE_MANUAL)
    chat = _FakeChat()
    answer = answer_question(
        "como dublo um vídeo para inglês?", index, chat, ia_doc=lambda task_id: f"ARQUIVO IA {task_id}"
    )
    system, user = chat.calls[0]
    assert system["role"] == "system" and "SOMENTE" in system["content"] and "travessão" in system["content"]
    assert "[1] Seção: Tarefas de vídeo > Dublar um vídeo\nARQUIVO IA dublar" in user["content"]
    assert answer.task_id == "dublar" and answer.text.startswith("Rode `dmaker dub")
    assert (
        answer.sources[0].section == "Tarefas de vídeo > Dublar um vídeo"
        and answer.sources[0].task_id == "dublar"
    )


def test_answer_question_without_the_task_file_falls_back_to_the_best_chunks():
    index = ManualIndex.from_text(SAMPLE_MANUAL)
    chat = _FakeChat()
    answer = answer_question("como instalo o instalador?", index, chat)
    assert answer.task_id is None
    assert answer.sources[0].section == "Instalação passo a passo"
    assert "Rode o instalador" in chat.calls[0][1]["content"]


def test_answer_question_with_nothing_found_does_not_call_the_model():
    chat = _FakeChat()
    answer = answer_question("xyzzy qwerty", ManualIndex.from_text(SAMPLE_MANUAL), chat)
    assert chat.calls == [] and "Não achei nada" in answer.text and answer.sources == ()


def test_search_only_lists_the_best_passages_without_a_model():
    answer = search_only("dublar em inglês", ManualIndex.from_text(SAMPLE_MANUAL))
    assert answer.text.startswith(NO_MODEL_NOTICE) and "Dublar um vídeo" in answer.text
    assert answer.task_id == "dublar"


def test_build_messages_cuts_the_context_at_the_budget():
    index = ManualIndex.from_text(SAMPLE_MANUAL)
    hits = index.search("reel", limit=5)
    context = build_context("reel", index, hits, ia_doc=lambda _id: "x" * 20000)
    messages = build_messages("reel", context)
    assert len(messages[1]["content"]) < 21000 and messages[1]["content"].startswith("Pergunta: reel")


def test_grade_requires_the_expected_section_and_all_terms():
    battery = load_battery(
        json.dumps(
            {
                "perguntas": [
                    {
                        "id": "a",
                        "pergunta": "p",
                        "secoes": ["Dublar um vídeo"],
                        "termos": ["dub", "en|inglês"],
                    }
                ]
            }
        )
    )
    from dmaker.manual.ask import Answer, Source

    question = battery[0]
    good = Answer(
        "p",
        "Use dmaker DUB com --to EN. Seção: Dublar um vídeo",
        (Source("Tarefas > Dublar um vídeo", "x", "dublar"),),
        "dublar",
    )
    assert grade(good, question).ok and grade(good, question).section_in_text
    wrong_section = Answer("p", "dub en", (Source("Outra seção", "y", None),), None)
    assert not grade(wrong_section, question).ok and not grade(wrong_section, question).section_ok
    missing_term = Answer("p", "dub", (Source("Dublar um vídeo", "x", "dublar"),), "dublar")
    result = grade(missing_term, question)
    assert not result.ok and result.missing_terms == ("en|inglês",)


def test_load_battery_requires_sections_and_terms():
    with pytest.raises(ValueError, match="precisa de 'secoes' e de 'termos'"):
        load_battery(json.dumps({"perguntas": [{"id": "x", "pergunta": "p", "secoes": []}]}))


def test_the_battery_file_has_the_three_mandatory_questions():
    questions = {q.text for q in load_battery(BATTERY_PATH.read_text(encoding="utf-8"))}
    assert {
        "como dublo um vídeo para inglês?",
        "como faço a legenda ficar em caixa?",
        "como sei se um áudio foi gerado pelo DMaker?",
    } <= questions


def test_thinking_level_shortens_only_the_gpt_oss_reasoning():
    from dmaker.manual.ask import thinking_level

    assert thinking_level("gpt-oss:20b") == "low"
    assert thinking_level("qwen3:30b-a3b") is None


def test_extract_commands_finds_dmaker_commands_in_blocks_and_inline_code():
    text = (
        "Rode `dmaker dub prepare gravacao.mp4 --to en`, depois:\n"
        "```powershell\ndmaker dub render projeto.dub.json --draft\n```\n"
        "e de novo `dmaker dub prepare gravacao.mp4 --to en`."
    )
    assert extract_commands(text) == [
        "dmaker dub prepare gravacao.mp4 --to en",
        "dmaker dub render projeto.dub.json --draft",
    ]
    assert extract_commands("sem comando nenhum") == []


def test_grade_reports_the_dmaker_commands_that_the_cli_does_not_have():
    from dmaker.manual.ask import Answer, Source
    from dmaker.manual.examples import command_problem

    from .manual_support import fake_cli_root

    root = fake_cli_root()
    question = load_battery(
        json.dumps({"perguntas": [{"id": "a", "pergunta": "p", "secoes": ["Dublar"], "termos": ["dub"]}]})
    )[0]
    answer = Answer(
        "p",
        "Use `dmaker dub a.mp4 --to en` e depois `dmaker dub get x.json` ou `dmaker quick a.mp4 --fit_mode video`.",
        (Source("Dublar um vídeo", "x", "dublar"),),
        "dublar",
    )
    result = grade(answer, question, lambda line: command_problem(line, root, require_arguments=False))
    assert result.ok  # o acerto não depende dos comandos
    assert result.invalid_commands == ("dmaker dub get x.json", "dmaker quick a.mp4 --fit_mode video")
    assert grade(answer, question).invalid_commands == ()
