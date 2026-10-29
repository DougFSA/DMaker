"""Receitas do servidor MCP: várias ferramentas numa chamada, sobre os mesmos serviços das ferramentas simples."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dmaker import mcp_server
from dmaker.agent.tools import McpToolHost
from dmaker.domain.spec import Project
from dmaker.pipeline.recipes import (
    NarrationRequest,
    RecipeError,
    add_narration,
    build_explainer,
    cut_summary,
    distribute_subject_ends,
    narrate_into_project,
)


def card_project(**extra) -> Project:
    return Project.model_validate(
        {
            "name": "meu-video",
            "timeline": [{"type": "card", "title": "Olá", "duration": 3}],
            "output": {"preset": "instagram/reels"},
            **extra,
        }
    )


# ---------- narrar e pôr no projeto ----------


def test_add_narration_sets_the_narration_and_uses_the_spoken_text_as_captions():
    project = add_narration(
        card_project(), NarrationRequest(text="  Bem-vindo ao DMaker.  ", voice="dora", start=0.5)
    )

    narration = project.audio.narration[0]
    assert (narration.text, narration.voice, narration.start) == ("Bem-vindo ao DMaker.", "dora", 0.5)
    assert project.captions is not None and project.captions.source == "narration"


def test_add_narration_keeps_the_existing_narrations_and_the_caption_style():
    existing = card_project(
        audio={"narration": [{"text": "Primeira fala.", "voice": "alex"}]},
        captions={"source": "auto", "style": {"mode": "karaoke"}},
    )

    project = add_narration(existing, NarrationRequest(text="Segunda fala.", start=4))

    assert [n.text for n in project.audio.narration] == ["Primeira fala.", "Segunda fala."]
    assert project.audio.narration[1].voice is None  # sem voz: a automática do motor
    assert project.captions.source == "narration" and project.captions.style.mode == "karaoke"


def test_add_narration_can_leave_the_captions_alone():
    project = add_narration(card_project(), NarrationRequest(text="Oi", captions=False))

    assert project.captions is None and len(project.audio.narration) == 1


def test_add_narration_refuses_an_empty_text_in_portuguese():
    with pytest.raises(RecipeError, match="vazio"):
        add_narration(card_project(), NarrationRequest(text="   "))


def test_narrate_into_project_checks_the_voice_first_then_saves():
    saved: list[Project] = []
    checked: list[str] = []

    def unknown_voice(voice_id):
        raise ValueError(f"Voz {voice_id!r} não encontrada.")

    with pytest.raises(ValueError, match="não encontrada"):
        narrate_into_project(
            "meu-video",
            NarrationRequest(text="Oi", voice="fantasma"),
            check_voice=unknown_voice,
            load=lambda name: card_project(),
            save=lambda project: saved.append(project) or Path("spec.json"),
        )
    assert saved == []  # voz inexistente: nada foi salvo

    project, path = narrate_into_project(
        "meu-video",
        NarrationRequest(text="Oi", voice="dora"),
        check_voice=checked.append,
        load=lambda name: card_project(),
        save=lambda project: saved.append(project) or Path("spec.json"),
    )
    assert checked == ["dora"] and path == Path("spec.json") and saved == [project]


# ---------- explicativo ----------


def test_subjects_with_ends_pass_through_untouched():
    subjects = [{"fim": 20, "fundo": "escuro"}, {"fim": 40}]

    assert distribute_subject_ends(subjects, None) == subjects


def test_subjects_without_ends_split_the_recording_evenly_and_the_last_ends_at_the_total():
    ends = distribute_subject_ends([{"fundo": "escuro"}, {"fundo": "claro"}, {}], 10.0)

    assert [subject["fim"] for subject in ends] == [3.33, 6.67, 10.0]
    assert ends[0]["fundo"] == "escuro"


def test_mixing_subjects_with_and_without_end_is_refused_instead_of_guessed():
    with pytest.raises(RecipeError, match="de todos os assuntos ou de nenhum"):
        distribute_subject_ends([{"fim": 5}, {}], 10.0)


def test_subjects_without_ends_and_without_a_duration_ask_for_the_ends():
    with pytest.raises(RecipeError, match="informe o 'fim'"):
        distribute_subject_ends([{}], None)
    with pytest.raises(RecipeError, match="pelo menos um assunto"):
        distribute_subject_ends([], 10.0)


def test_build_explainer_measures_the_recording_only_when_the_ends_are_missing():
    created: list[dict] = []
    probed: list[Path] = []

    def prober(path):
        probed.append(path)
        return SimpleNamespace(duration=8.0)

    def create(template, name, params):
        created.append({"template": template, "name": name, **params})
        return "projeto"

    build_explainer("exp", "C:/g.mp4", [{"fundo": "escuro"}, {}], {"legendas": False}, prober, create)
    build_explainer("exp", "C:/g.mp4", [{"fim": 4}], None, prober, create)

    assert probed == [Path("C:/g.mp4")]  # a segunda chamada já trouxe os fins: não mediu
    assert created[0]["template"] == "explicativo" and created[0]["legendas"] is False
    assert [s["fim"] for s in created[0]["assuntos"]] == [4.0, 8.0]
    assert created[1]["gravacao"] == "C:/g.mp4"


def test_cut_summary_is_compact_and_points_to_the_next_step():
    result = {
        "project": "corte",
        "spec_path": "projects/corte/spec.json",
        "report": {
            "duration_before_s": 60.0,
            "duration_after_s": 48.5,
            "removed_s": 11.5,
            "removed_percent": 19.2,
            "counts": {"silence": 3, "filler": 2},
            "cuts": [{"id": 1}] * 5,
        },
        "warnings": ["aviso"],
    }

    summary = cut_summary(result)

    assert "cuts" not in summary and summary["cuts_by_reason"] == {"silence": 3, "filler": 2}
    assert summary["removed_s"] == 11.5 and summary["captions"] is True and "list_cuts" in summary["next"]


# ---------- as ferramentas do servidor ----------


def call(name: str, arguments: dict) -> str:
    """A chamada como o agente local a faz (servidor MCP em processo): JSON em caso de sucesso, `erro: ...` se falhar."""
    return McpToolHost(allowed=[name], argument_defaults={}).call(name, arguments)


def test_the_three_recipes_are_registered_on_the_mcp_server():
    names = {tool.name for tool in asyncio.run(mcp_server.server.list_tools())}

    assert {"narrate_into_project", "cut_pauses_and_caption", "build_explainer_video"} <= names


def test_narrate_into_project_tool_edits_the_saved_project_and_returns_the_summary(tmp_path):
    from dmaker.pipeline.projects import load_project, save_project

    save_project(card_project())

    result = json.loads(
        call(
            "narrate_into_project",
            {"name_or_path": "meu-video", "text": "Bem-vindo ao DMaker.", "voice": "dora", "start": 0.5},
        )
    )

    assert result["narrations"] == 1 and result["name"] == "meu-video" and "total_s" in result
    saved = load_project("meu-video")
    assert saved.audio.narration[0].voice == "dora" and saved.captions.source == "narration"


def test_narrate_into_project_tool_reports_an_unknown_voice_before_saving():
    from dmaker.pipeline.projects import load_project, save_project

    save_project(card_project())

    text = call("narrate_into_project", {"name_or_path": "meu-video", "text": "Oi", "voice": "fantasma"})

    assert text.startswith("erro:") and "fantasma" in text
    assert load_project("meu-video").audio.narration == []


def test_narrate_into_project_tool_explains_an_empty_text():
    from dmaker.pipeline.projects import save_project

    save_project(card_project())

    text = call("narrate_into_project", {"name_or_path": "meu-video", "text": " "})

    assert text.startswith("erro:") and "vazio" in text


def test_build_explainer_video_tool_needs_the_end_of_every_subject_or_none(tmp_path):
    recording = tmp_path / "g.mp4"
    recording.write_bytes(b"x")

    text = call(
        "build_explainer_video",
        {"name": "exp", "recording": str(recording), "subjects": [{"fim": 3}, {}]},
    )

    assert text.startswith("erro:") and "de todos os assuntos ou de nenhum" in text


def test_cut_pauses_and_caption_waits_forces_captions_and_returns_the_compact_summary(monkeypatch, tmp_path):
    seen = {}

    class FakeReport:
        def to_dict(self):
            return {
                "duration_before_s": 60.0,
                "duration_after_s": 50.0,
                "removed_s": 10.0,
                "removed_percent": 16.7,
                "counts": {"silence": 4},
                "cuts": [{"id": 1}] * 4,
            }

    class FakeService:
        def validate(self, request):
            seen["request"] = request

        def cut(self, request, report):
            return SimpleNamespace(
                project=SimpleNamespace(name=request.name),
                spec_path=tmp_path / "spec.json",
                report=FakeReport(),
                warnings=[],
            )

    monkeypatch.setattr(mcp_server, "_autocut_service", lambda job=None: FakeService())
    source = tmp_path / "gravacao.mp4"
    source.write_bytes(b"x")

    text = call("cut_pauses_and_caption", {"source": str(source), "name": "corte", "intensity": "agressiva"})

    summary = json.loads(text)
    assert summary["project"] == "corte" and summary["removed_s"] == 10.0 and "cuts" not in summary
    assert seen["request"].captions is True and seen["request"].options.intensity == "agressiva"
    assert seen["request"].overwrite is False


def test_the_recipes_descriptions_say_what_calls_they_replace():
    tools = {tool.name: tool.description for tool in asyncio.run(mcp_server.server.list_tools())}

    assert (
        "edit_project" in tools["narrate_into_project"]
        and "validate_project" in tools["narrate_into_project"]
    )
    assert "autocut" in tools["cut_pauses_and_caption"] and "job_status" in tools["cut_pauses_and_caption"]
    assert "new_from_template" in tools["build_explainer_video"]
    assert json.dumps(tools).count("—") == 0
