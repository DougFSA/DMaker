"""Comandos `dmaker manual build|export` e `dmaker ajuda` (modelo, Ollama e agente falsos)."""

from __future__ import annotations

import sys

from typer.testing import CliRunner

from dmaker import cli
from dmaker.agent.llm import Reply
from dmaker.manual import files, service
from dmaker.manual.build import ManualBuildError
from dmaker.media.browser import BrowserUnavailable

runner = CliRunner()


def test_manual_build_check_passes_on_the_repository_manual():
    result = runner.invoke(cli.app, ["manual", "build", "--check"])
    assert result.exit_code == 0, result.output
    assert "em dia" in result.output


def test_manual_build_check_fails_and_lists_the_stale_files(monkeypatch):
    monkeypatch.setattr(service, "check", lambda: ["docs/MANUAL.md", "docs/ia/reel.md"])
    result = runner.invoke(cli.app, ["manual", "build", "--check"])
    assert result.exit_code == 1
    assert "dmaker manual build" in result.output and "docs/ia/reel.md" in result.output


def test_manual_build_reports_what_it_changed_or_that_nothing_changed(monkeypatch):
    monkeypatch.setattr(service, "build", lambda: ["docs/MANUAL.md"])
    changed = runner.invoke(cli.app, ["manual", "build"])
    assert changed.exit_code == 0 and "1 arquivo(s) atualizado(s)" in changed.output
    monkeypatch.setattr(service, "build", lambda: [])
    unchanged = runner.invoke(cli.app, ["manual", "build"])
    assert unchanged.exit_code == 0 and "Nada mudou" in unchanged.output


def test_manual_build_shows_the_problems_when_the_manual_does_not_close(monkeypatch):
    def broken():
        raise ManualBuildError(["Reel: a ferramenta não existe."])

    monkeypatch.setattr(service, "build", broken)
    result = runner.invoke(cli.app, ["manual", "build"])
    assert result.exit_code == 1 and "Reel: a ferramenta não existe." in result.output


def test_manual_export_html_writes_the_single_page_with_the_real_manual(tmp_path):
    out = tmp_path / "manual"
    result = runner.invoke(cli.app, ["manual", "export", "--html", "--out", str(out)])
    assert result.exit_code == 0, result.output
    page = (out / "DMaker-manual.html").read_text(encoding="utf-8")
    assert "Sumário" in page and "data:image/" in page and "Manual do DMaker" in page
    assert not (out / "DMaker-manual.pdf").exists()


def test_manual_export_pdf_asks_to_install_the_extra_when_there_is_no_browser(monkeypatch, tmp_path):
    def no_browser(*args, **kwargs):
        raise BrowserUnavailable(
            'O Playwright não está instalado. Instale o extra: pip install -e ".[docs]".'
        )

    monkeypatch.setattr(service, "export_manual", no_browser)
    result = runner.invoke(cli.app, ["manual", "export", "--pdf", "--out", str(tmp_path)])
    assert result.exit_code == 1 and 'pip install -e ".[docs]"' in result.output


class _FakeOllama:
    """Faz as vezes do `OllamaChat`: responde sem rede."""

    alive = True
    installed = True
    prompts: list[list[dict]] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def is_alive(self) -> bool:
        return self.alive

    def has_model(self) -> bool:
        return self.installed

    def chat(self, messages, tools) -> Reply:
        _FakeOllama.prompts.append(messages)
        return Reply(
            content="Use `dmaker voice verify arquivo.mp4`.\nSeção: Verificar se um áudio foi gerado"
        )


def test_ajuda_answers_with_the_model_and_cites_the_sections(monkeypatch):
    monkeypatch.setattr("dmaker.agent.llm.OllamaChat", _FakeOllama)
    _FakeOllama.alive = _FakeOllama.installed = True
    _FakeOllama.prompts = []
    result = runner.invoke(cli.app, ["ajuda", "como sei se um áudio foi gerado pelo DMaker?"])
    assert result.exit_code == 0, result.output
    assert "dmaker voice verify arquivo.mp4" in result.output
    assert (
        "Seções do manual:" in result.output
        and "Verificar se um áudio foi gerado pelo DMaker" in result.output
    )
    prompt = _FakeOllama.prompts[0][1]["content"]
    assert "Tarefa `verificar-audio`" in prompt  # o arquivo de docs/ia da tarefa vai de contexto


def test_ajuda_falls_back_to_the_search_when_ollama_is_down(monkeypatch):
    monkeypatch.setattr("dmaker.agent.llm.OllamaChat", _FakeOllama)
    _FakeOllama.alive = False
    result = runner.invoke(cli.app, ["ajuda", "como dublo um vídeo para inglês?"])
    assert result.exit_code == 0, result.output
    assert "O Ollama não está no ar" in result.output and "dmaker dub prepare" in result.output
    _FakeOllama.alive = True


def test_ajuda_no_model_never_calls_ollama(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("não deveria criar o cliente de chat com resposta")

    monkeypatch.setattr(
        "dmaker.agent.llm.OllamaChat",
        lambda **kw: type("C", (), {"is_alive": lambda s: True, "has_model": lambda s: True, "chat": boom})(),
    )
    result = runner.invoke(cli.app, ["ajuda", "como faço a legenda ficar em caixa?", "--no-model"])
    assert result.exit_code == 0 and "Deixar a legenda em caixa arredondada" in result.output


def test_agent_offer_tells_which_tasks_the_local_agent_can_run_and_which_tools_it_lacks():
    runnable = service.agent_offer("modelo")
    assert runnable is not None and runnable.runnable and "Tarefa `modelo`" in runnable.manual
    lacking = service.agent_offer("reel")
    assert lacking is not None and not lacking.runnable and lacking.missing_tools == ("quick_edit",)
    assert service.agent_offer("nao-existe") is None


def test_offer_runs_the_local_agent_with_the_task_file_as_its_manual(monkeypatch):
    captured: dict = {}

    class FakeLoop:
        def __init__(self, model, tools, system, on_event):
            captured["system"] = system

        def ask(self, message):
            captured.setdefault("messages", []).append(message)
            return "pronto"

    monkeypatch.setattr("dmaker.agent.AgentLoop", FakeLoop)
    monkeypatch.setattr("dmaker.agent.McpToolHost", lambda: object())
    monkeypatch.setattr(cli.typer, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(cli.console, "input", lambda *a, **k: "")
    cli._offer_agent("modelo", "faz um story com esse print", object())
    assert "## Manual da tarefa" in captured["system"] and "Tarefa `modelo`" in captured["system"]
    assert captured["messages"] == [
        "Pedido do usuário: faz um story com esse print\nSiga o manual da tarefa e pergunte o que faltar."
    ]


def test_offer_for_a_task_the_agent_cannot_run_explains_instead_of_pretending(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.typer, "confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deve oferecer"))
    )
    cli._offer_agent("reel", "faz um reel", object())
    out = capsys.readouterr().out
    assert "ainda não enxerga" in out and "quick_edit" in out


def test_ajuda_offer_only_happens_in_an_interactive_terminal(monkeypatch):
    monkeypatch.setattr("dmaker.agent.llm.OllamaChat", _FakeOllama)
    called = []
    monkeypatch.setattr(cli, "_offer_agent", lambda *a: called.append(a))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    runner.invoke(cli.app, ["ajuda", "como sei se um áudio foi gerado pelo DMaker?"])
    assert called == []


def test_manual_files_resolve_to_the_repository_docs():
    assert files.is_checkout() and files.manual_path().name == "MANUAL.md"
    assert files.read_ia_doc("dublar").startswith("# Dublar um vídeo para outro idioma")
    assert files.read_ia_doc("nao-existe") is None


def test_ajuda_warns_when_the_model_cites_a_command_the_cli_does_not_have(monkeypatch):
    class InventingOllama(_FakeOllama):
        def chat(self, messages, tools) -> Reply:
            return Reply(content="Rode `dmaker dub prepare a.mp4 --to en` e depois `dmaker dub get x.json`.")

    monkeypatch.setattr("dmaker.agent.llm.OllamaChat", InventingOllama)
    InventingOllama.alive = InventingOllama.installed = True
    result = runner.invoke(cli.app, ["ajuda", "como dublo um vídeo para inglês?"])
    assert result.exit_code == 0, result.output
    assert "Atenção: o modelo citou comando(s) que a CLI não tem" in result.output
    assert "dmaker dub get x.json" in result.output.split("Atenção")[1]
    assert "dmaker dub prepare a.mp4" not in result.output.split("Atenção")[1].split("Seções do manual")[0]
