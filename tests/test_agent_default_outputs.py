"""O destino padrão das ferramentas que gravam sem `out`: o agente pergunta antes de sobrescrever o que já existe."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import dmaker.mcp_server as mcp_server
from dmaker import config
from dmaker.agent.safety import (
    DEFAULT_OUTPUTS,
    DUB_PROJECT_OUTPUTS,
    OVERWRITES_EXISTING_OUTPUT,
    ApproveAll,
    DenyAll,
    ToolGate,
    output_targets,
    read_dub_project,
)
from dmaker.domain.dub import DubProject, save_dub_project
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.pipeline import dubbing, isolation, speech_fix, voice_conversion, voices
from dmaker.pipeline.dubbing import default_output_path as dub_output_path
from dmaker.pipeline.dubbing import default_stems_dir
from dmaker.pipeline.isolation import DEFAULT_EXPORT_FORMAT, IsolationService, default_export_dir, export_name
from dmaker.pipeline.speech_fix import default_output_path as speech_fix_output_path
from dmaker.pipeline.voice_conversion import ConversionRequest
from dmaker.pipeline.voice_conversion import default_output_path as conversion_output_path
from dmaker.pipeline.voices import default_narration_path

from .conftest import fake_ffmpeg_output
from .test_isolation import FakeSeparator
from .test_narration import FakeSynthesizer

VIDEO = "C:/v/aula.mp4"
AUDIO = "C:/v/aula.wav"
TEXT = "Uma narração curta."


def gate(policy=None, existing=()):
    return ToolGate(schemas={}, policy=policy or DenyAll(), exists=set(existing).__contains__)


def question(*paths: str) -> str:
    if len(paths) == 1:
        return f"O arquivo '{paths[0]}' já existe. Posso sobrescrevê-lo?"
    listed = ", ".join(f"'{path}'" for path in paths)
    return f"Os arquivos {listed} já existem. Posso sobrescrevê-los?"


# ---------- narração ----------


def test_narrating_without_out_asks_when_the_default_narration_file_exists():
    target = str(default_narration_path(TEXT))
    asked = ApproveAll()
    g = gate(asked, existing={target})

    assert g.check("synthesize_speech", {"text": TEXT}) is None
    assert g.check("synthesize_speech", {"text": "Outro texto, outro arquivo."}) is None

    assert [r.question for r in asked.asked] == [question(target)]


def test_an_explicit_out_replaces_the_default_destination_in_the_question():
    default = str(default_narration_path(TEXT))
    asked = ApproveAll()
    g = gate(asked, existing={default, "C:/saidas/existe.wav"})

    g.check("synthesize_speech", {"text": TEXT, "out": "C:/saidas/nova.wav"})  # o padrão não será tocado
    g.check("synthesize_speech", {"text": TEXT, "out": "C:/saidas/existe.wav"})
    g.check("synthesize_speech", {"text": TEXT, "out": ""})  # vazio: o servidor usa o padrão

    assert [r.question for r in asked.asked] == [question("C:/saidas/existe.wav"), question(default)]


def test_a_refused_overwrite_of_the_default_file_blocks_the_call():
    target = str(default_narration_path(TEXT))

    text = gate(DenyAll(), existing={target}).check("synthesize_speech", {"text": TEXT})

    assert text is not None and "não autorizou" in text and target in text and "Não execute esta ação" in text


def test_the_default_destination_follows_the_output_folder_of_the_config(monkeypatch, tmp_path):
    """O gate lê a pasta de saída na hora, como o servidor: trocá-la move também a pergunta."""
    before = output_targets("synthesize_speech", {"text": TEXT})
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "outra-pasta")

    (after,) = output_targets("synthesize_speech", {"text": TEXT})

    assert before != [after] and Path(after).parent == tmp_path / "outra-pasta"


def test_the_narration_the_tool_writes_is_the_file_the_gate_asked_about(tmp_path):
    """Contrato de ponta a ponta: o arquivo que `speak` grava sem `out` é o destino que o gate calculou."""
    (predicted,) = output_targets("synthesize_speech", {"text": TEXT})

    result = voices.speak(
        TEXT,
        runner=RecordingRunner(on_run=fake_ffmpeg_output),
        synthesizer=FakeSynthesizer(),
        watermark=False,
    )

    assert str(result.path) == predicted and result.path.exists()
    asked = ApproveAll()
    gate(asked, existing={predicted}).check("synthesize_speech", {"text": TEXT})
    assert [r.question for r in asked.asked] == [question(predicted)]


# ---------- correção de fala ----------


def test_fixing_speech_without_out_asks_when_the_corrected_file_exists():
    corrected = str(speech_fix_output_path(Path(VIDEO), ".mp4"))
    asked = ApproveAll()
    g = gate(asked, existing={VIDEO, corrected})

    g.check("fix_speech", {"path": VIDEO, "text": "olá", "find": "oi"})
    g.check("fix_speech", {"path": VIDEO, "text": "olá", "find": "oi", "out": "C:/saidas/nova.mp4"})

    assert [r.question for r in asked.asked] == [question(corrected)]


def test_the_extension_of_the_corrected_file_depends_on_the_picture_so_each_answer_counts():
    """`corrected_suffix` precisa de `has_video`, que só o `probe` do servidor sabe: o gate olha cada resposta."""
    video_input = {str(speech_fix_output_path(Path(VIDEO), suffix)) for suffix in (".mp4", ".wav")}
    audio_input = {str(speech_fix_output_path(Path(AUDIO), suffix)) for suffix in (".mp4", ".wav")}

    assert set(output_targets("fix_speech", {"path": VIDEO, "text": "a"})) == video_input
    assert set(output_targets("fix_speech", {"path": AUDIO, "text": "a"})) == audio_input


def test_fixing_speech_with_an_explicit_out_is_now_protected_too():
    asked = ApproveAll()
    g = gate(asked, existing={VIDEO, "C:/saidas/existe.mp4"})

    g.check("fix_speech", {"path": VIDEO, "text": "olá", "out": "C:/saidas/existe.mp4"})

    assert [r.question for r in asked.asked] == [question("C:/saidas/existe.mp4")]


# ---------- troca de voz ----------


def conversion_target(voice: str, start, end, suffix: str = ".mp4") -> str:
    request = ConversionRequest(Path(VIDEO), voice, start, end)
    return str(conversion_output_path(request, suffix))


def test_converting_a_voice_asks_only_for_the_same_voice_and_window():
    same = conversion_target("minha-voz", 5.0, 12.0)
    asked = ApproveAll()
    g = gate(asked, existing={VIDEO, same})

    g.check("convert_voice", {"path": VIDEO, "voice": "minha-voz", "start": 5, "end": 12})
    g.check("convert_voice", {"path": VIDEO, "voice": "minha-voz", "start": 6, "end": 12})
    g.check("convert_voice", {"path": VIDEO, "voice": "outra-voz", "start": 5, "end": 12})
    g.check("convert_voice", {"path": VIDEO, "voice": "minha-voz"})

    assert [r.question for r in asked.asked] == [question(same)]


def test_the_seconds_of_the_model_are_read_like_the_server_does():
    """O `5` do modelo chega à ferramenta como `5.0` (pydantic) e o nome do arquivo leva um resumo desse texto."""
    as_integers = output_targets("convert_voice", {"path": VIDEO, "voice": "v", "start": 5, "end": 12})
    as_floats = output_targets("convert_voice", {"path": VIDEO, "voice": "v", "start": 5.0, "end": 12.0})

    assert as_integers == as_floats and conversion_target("v", 5.0, 12.0) in as_integers


def test_a_conversion_the_tool_would_refuse_has_no_destination_to_ask_about():
    refused = [
        {"path": VIDEO, "voice": "v", "start": 9, "end": 3},
        {"path": VIDEO, "voice": "v", "start": -1},
        {"path": VIDEO, "voice": "v", "start": "cinco"},
        {"path": VIDEO, "voice": "  "},
        {"path": "", "voice": "v"},
    ]

    assert [output_targets("convert_voice", arguments) for arguments in refused] == [[]] * len(refused)


# ---------- isolamento vocal ----------


def isolation_files(path: str = VIDEO, audio_format: str = "wav", start=None, end=None) -> list[str]:
    folder = default_export_dir()
    return [
        str(folder / export_name(Path(path), role, audio_format, start, end)) for role in ("voz", "fundo")
    ]


def test_isolating_without_out_dir_asks_once_for_the_voice_and_background_that_exist():
    voice, background = isolation_files()
    asked = ApproveAll()
    g = gate(asked, existing={VIDEO, voice, background})

    g.check("isolate_vocals", {"path": VIDEO})

    assert [r.question for r in asked.asked] == [question(voice, background)]


def test_isolating_asks_only_about_the_file_that_exists():
    voice, background = isolation_files()
    asked = ApproveAll()

    gate(asked, existing={VIDEO, background}).check("isolate_vocals", {"path": VIDEO})

    assert [r.question for r in asked.asked] == [question(background)]


def test_the_existing_output_folder_alone_is_not_a_reason_to_ask():
    """A pasta padrão existe depois do primeiro uso: o que conta são a voz e o fundo daquele arquivo e trecho."""
    asked = ApproveAll()
    g = gate(asked, existing={VIDEO, str(default_export_dir())})

    assert g.check("isolate_vocals", {"path": VIDEO}) is None

    assert asked.asked == []


def test_the_window_and_the_format_pick_the_files_to_check():
    wanted = isolation_files(start=2, end=12.5, audio_format="mp3")
    asked = ApproveAll()
    g = gate(asked, existing={VIDEO, *wanted, *isolation_files()})

    g.check("isolate_vocals", {"path": VIDEO, "start": 2, "end": 12.5, "format": "mp3"})

    assert [r.question for r in asked.asked] == [question(*wanted)]
    assert sorted(wanted) != sorted(isolation_files())  # recortes diferentes não se sobrescrevem


def test_an_explicit_out_dir_keeps_the_old_rule_of_asking_about_the_folder():
    asked = ApproveAll()
    g = gate(asked, existing={VIDEO, "C:/saidas", *isolation_files()})

    g.check("isolate_vocals", {"path": VIDEO, "out_dir": "C:/saidas"})

    assert [r.question for r in asked.asked] == [question("C:/saidas")]


@pytest.fixture
def separator() -> FakeSeparator:
    return FakeSeparator()


@pytest.fixture
def fake_isolation(monkeypatch, tmp_path: Path, separator: FakeSeparator) -> None:
    def touch(command: FFmpegCommand) -> None:
        out = Path(command.args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"audio")

    runner = RecordingRunner(on_run=touch)
    monkeypatch.setattr(config, "STEMS_DIR", tmp_path / "stems")
    monkeypatch.setattr("dmaker.media.ffmpeg.SubprocessRunner", lambda quiet=False, sink=None: runner)
    monkeypatch.setattr(
        "dmaker.pipeline.isolation.default_isolation_service",
        lambda runner_arg, log=None: IsolationService(separator, runner, log=log),
    )


def test_the_stems_the_tool_writes_are_the_files_the_gate_asked_about(fake_isolation, tmp_path):
    """Contrato de ponta a ponta com `isolate_vocals` de verdade (separador falso): sem `out_dir`, o gate acerta."""
    media = tmp_path / "fala.mp4"
    media.write_bytes(b"video")
    arguments = {"path": str(media), "start": 2, "end": 12}
    predicted = output_targets("isolate_vocals", arguments)

    started = mcp_server.isolate_vocals(**arguments)
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)
    result = mcp_server.job_status(started["job_id"])

    assert result["status"] == "done", result.get("error")
    assert predicted == [result["result"]["voice"], result["result"]["background"]]
    assert all(Path(path).exists() for path in predicted)
    asked = ApproveAll()
    gate(asked, existing={str(media), *predicted}).check("isolate_vocals", arguments)
    assert [r.question for r in asked.asked] == [question(*predicted)]


# ---------- dublagem: o destino sai do .dub.json ----------

PROJECT = "C:/dub/aula.en.dub.json"
SENTINEL = Path("C:/outro/lugar.wav")


def dub_project(source: str = VIDEO, target: str = "en") -> DubProject:
    return DubProject(source=source, target_language=target, segments=[])


def dub_gate(policy=None, existing=(), project: DubProject | None = None) -> ToolGate:
    """O gate com um disco falso e um leitor que só conhece o `PROJECT`: nenhum arquivo real é tocado."""
    return ToolGate(
        schemas={},
        policy=policy or DenyAll(),
        exists=set(existing).__contains__,
        read_dub_project=lambda path: project if path == PROJECT else None,
    )


def test_a_draft_dub_render_asks_when_the_default_video_already_exists():
    """Era a lacuna: o rascunho não pede o sim de gerar e, sem destino conhecido, gravava por cima calado."""
    target = str(dub_output_path(Path(VIDEO), "en", ".mp4"))
    asked = ApproveAll()
    g = dub_gate(asked, existing={target}, project=dub_project())

    assert g.check("dub_render", {"project": PROJECT, "draft": True}) is None

    assert [r.question for r in asked.asked] == [question(target)]


def test_a_final_dub_render_asks_to_generate_and_then_to_overwrite():
    target = str(dub_output_path(Path(VIDEO), "en", ".mp4"))
    asked = ApproveAll()
    g = dub_gate(asked, existing={target}, project=dub_project())

    g.check("dub_render", {"project": PROJECT})

    assert [r.question for r in asked.asked] == [
        "Posso gerar o vídeo dublado (leva vários minutos)?",
        question(target),
    ]


def test_a_dub_render_into_a_free_destination_asks_nothing_in_draft():
    asked = ApproveAll()
    g = dub_gate(asked, existing={"C:/dub/outra-coisa.mp4"}, project=dub_project())

    assert g.check("dub_render", {"project": PROJECT, "draft": True}) is None

    assert asked.asked == []


def test_an_audio_dubbing_asks_about_the_audio_file_and_both_extensions_are_looked_at():
    """A extensão depende de o original ter imagem, que só o `probe` do servidor sabe: vale cada resposta possível."""
    as_audio = str(dub_output_path(Path(AUDIO), "en", ".wav"))
    asked = ApproveAll()
    g = dub_gate(asked, existing={as_audio}, project=dub_project(source=AUDIO))

    g.check("dub_render", {"project": PROJECT, "draft": True})

    assert [r.question for r in asked.asked] == [question(as_audio)]
    both = [str(dub_output_path(Path(VIDEO), "en", suffix)) for suffix in (".mp4", ".wav")]
    assert output_targets("dub_render", {"project": PROJECT}, lambda path: dub_project()) == both


def test_a_dub_render_with_out_asks_about_the_out_and_never_reads_the_project():
    def unreadable(path: str):
        raise AssertionError("com `out` o destino já está dito: não há projeto a ler")

    targets = output_targets("dub_render", {"project": PROJECT, "out": "C:/saidas/pronto.mp4"}, unreadable)

    assert targets == ["C:/saidas/pronto.mp4"]


def test_dub_stems_without_out_dir_asks_when_the_default_folder_exists():
    folder = str(default_stems_dir(Path(VIDEO), "en"))
    asked = ApproveAll()
    dub_gate(asked, existing={folder}, project=dub_project()).check("dub_stems", {"project": PROJECT})

    assert [r.question for r in asked.asked][1:] == [
        question(folder)
    ]  # depois da pergunta de gerar as trilhas

    elsewhere = ApproveAll()
    dub_gate(elsewhere, existing={folder}, project=dub_project()).check(
        "dub_stems", {"project": PROJECT, "out_dir": "C:/saidas/trilhas"}
    )

    assert (
        len(elsewhere.asked) == 1 and "gerar as trilhas" in elsewhere.asked[0].question
    )  # o padrão não é tocado


def test_a_project_the_gate_cannot_read_has_no_destination_and_the_tool_refuses_by_itself():
    """Sem projeto a ferramenta falha ao abrir o `.dub.json`, antes de gravar qualquer coisa: o gate não pergunta."""
    asked = ApproveAll()
    g = dub_gate(asked, existing={str(dub_output_path(Path(VIDEO), "en", ".mp4"))}, project=None)

    assert g.check("dub_render", {"project": PROJECT, "draft": True}) is None
    assert g.check("dub_render", {"draft": True}) is None  # sem `project` não há de onde ler

    assert asked.asked == []


def test_the_real_reader_gives_the_project_from_disk_and_none_when_it_cannot_open_it(tmp_path):
    saved = tmp_path / "aula.en.dub.json"
    project = dub_project()
    save_dub_project(project, saved)
    broken = tmp_path / "quebrado.dub.json"
    broken.write_text("{ não é json", encoding="utf-8")

    assert read_dub_project(str(saved)) == project
    assert read_dub_project(str(broken)) is None
    assert read_dub_project(str(tmp_path / "nada.dub.json")) is None


@pytest.mark.parametrize(
    ("tool", "function"), [("dub_render", "default_output_path"), ("dub_stems", "default_stems_dir")]
)
def test_the_gate_asks_the_function_of_the_dub_service_for_the_destination(monkeypatch, tool, function):
    """O destino da dublagem vem das funções que o `DubbingService` usa: se mudarem, a pergunta acompanha."""
    monkeypatch.setattr(dubbing, function, lambda *args, **kwargs: SENTINEL)

    targets = output_targets(tool, {"project": PROJECT}, lambda path: dub_project())

    assert targets and all(str(SENTINEL) == target for target in targets)


# ---------- o gate usa a função da ferramenta, não uma cópia ----------


@pytest.mark.parametrize(
    ("tool", "arguments", "module", "function"),
    [
        ("synthesize_speech", {"text": TEXT}, voices, "default_narration_path"),
        ("fix_speech", {"path": VIDEO, "text": "a"}, speech_fix, "default_output_path"),
        ("convert_voice", {"path": VIDEO, "voice": "v"}, voice_conversion, "default_output_path"),
        ("isolate_vocals", {"path": VIDEO}, isolation, "export_name"),
    ],
)
def test_the_gate_asks_the_function_of_the_tool_for_the_destination(
    monkeypatch, tool, arguments, module, function
):
    def where(*args, **kwargs):
        return SENTINEL if function != "export_name" else SENTINEL.name

    monkeypatch.setattr(module, function, where)

    targets = output_targets(tool, arguments)

    assert targets and all(SENTINEL.name in target for target in targets)


# ---------- contrato com o servidor MCP ----------


def mcp_tools() -> dict:
    return {tool.name: tool for tool in asyncio.run(mcp_server.server.list_tools())}


def test_every_mcp_tool_with_an_output_argument_is_watched_by_the_gate():
    """Uma ferramenta nova com `out` ou `out_dir` que ninguém pôs na lista sobrescreveria sem perguntar."""
    with_output = {
        name
        for name, tool in mcp_tools().items()
        if {"out", "out_dir"} & set(tool.input_schema["properties"])
    }

    assert with_output == set(OVERWRITES_EXISTING_OUTPUT)


def test_every_tool_the_gate_watches_has_a_default_destination():
    """`dub_render` e `dub_stems` decidem o destino pelo conteúdo do `.dub.json`: o gate o lê por um leitor injetado."""
    assert set(DEFAULT_OUTPUTS) <= set(OVERWRITES_EXISTING_OUTPUT)
    assert set(DUB_PROJECT_OUTPUTS) == {"dub_render", "dub_stems"}
    assert set(DEFAULT_OUTPUTS) | set(DUB_PROJECT_OUTPUTS) == set(OVERWRITES_EXISTING_OUTPUT)


def test_the_default_audio_format_of_the_gate_is_the_one_of_the_mcp_tool():
    default = mcp_tools()["isolate_vocals"].input_schema["properties"]["format"]["default"]

    assert default == DEFAULT_EXPORT_FORMAT
