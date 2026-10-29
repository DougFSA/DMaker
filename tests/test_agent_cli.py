"""`dmaker agent` na linha de comando: motor configurado, kit na tela e confirmação no terminal (modelo falso)."""

from __future__ import annotations

from typer.testing import CliRunner

from dmaker import cli
from dmaker.agent.llm import Reply, ToolCall
from dmaker.agent.safety import ConfirmationRequest

runner = CliRunner()


class FakeChat:
    """Um motor de mentira: responde pelo roteiro e diz se o servidor e o modelo estão de pé."""

    def __init__(self, replies=(), alive=True, installed=True):
        self.replies = list(replies)
        self.alive = alive
        self.installed = installed
        self.seen: list[list[dict]] = []

    def is_alive(self):
        return self.alive

    def has_model(self):
        return self.installed

    def chat(self, messages, tools):
        self.seen.append(messages)
        return self.replies.pop(0)


def use_chat(monkeypatch, chat: FakeChat) -> None:
    monkeypatch.setattr("dmaker.agent.build_chat", lambda settings: chat)


def test_once_runs_a_request_and_shows_the_chosen_kit_the_tool_and_the_answer(monkeypatch):
    chat = FakeChat(
        [Reply("", [ToolCall("list_templates", {})]), Reply("Os templates são produto e stories.")]
    )
    use_chat(monkeypatch, chat)

    result = runner.invoke(cli.app, ["agent", "--once", "Quais templates de vídeo existem?"])

    assert result.exit_code == 0, result.output
    assert "kit: Edição e render (keywords)" in result.output
    assert "-> list_templates()" in result.output
    assert "Os templates são produto e stories." in result.output
    assert (
        "# Kit Edição e render" in chat.seen[0][0]["content"]
    )  # o prompt leva o manual do kit, não a skill inteira


def test_the_model_and_engine_come_from_the_options_over_the_environment(monkeypatch):
    seen = {}

    def fake_build(settings):
        seen["settings"] = settings
        return FakeChat([Reply("ok"), Reply("ok")])

    monkeypatch.setattr("dmaker.agent.build_chat", fake_build)
    monkeypatch.setenv("DMAKER_AGENT_MODEL", "do-ambiente")

    runner.invoke(cli.app, ["agent", "--once", "oi", "--engine", "openai", "--model", "da-linha"])

    settings = seen["settings"]
    assert (settings.engine, settings.model) == ("openai", "da-linha")
    assert settings.url == "http://127.0.0.1:8080"  # o endereço padrão acompanha o motor


def test_a_stopped_model_server_stops_the_command_early_with_the_remedy(monkeypatch):
    use_chat(monkeypatch, FakeChat(alive=False))

    result = runner.invoke(cli.app, ["agent", "--once", "oi"])

    assert (
        result.exit_code == 1 and "não está respondendo" in result.output and "ollama serve" in result.output
    )


def test_a_missing_ollama_model_says_which_pull_to_run(monkeypatch):
    use_chat(monkeypatch, FakeChat(installed=False))

    result = runner.invoke(cli.app, ["agent", "--once", "oi", "--model", "modelo-x"])

    assert result.exit_code == 1 and "ollama pull modelo-x" in result.output


def test_a_bad_engine_option_is_a_clear_error():
    result = runner.invoke(cli.app, ["agent", "--once", "oi", "--engine", "gpt"])

    assert result.exit_code == 1 and "motor deve ser ollama ou openai" in result.output


def test_a_final_render_asks_in_the_terminal_and_a_refusal_keeps_the_tool_from_running(monkeypatch):
    chat = FakeChat(
        [
            Reply("", [ToolCall("render_project", {"name_or_path": "x"})]),
            Reply("Não renderizei, você não confirmou."),
        ]
    )
    use_chat(monkeypatch, chat)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    asked = []
    monkeypatch.setattr(cli.typer, "confirm", lambda text, **kwargs: asked.append(text) or False)

    result = runner.invoke(cli.app, ["agent", "--once", "renderiza o vídeo final do projeto x"])

    assert result.exit_code == 0 and asked == ["Confirma?"]
    assert "Posso gerar o vídeo final" in result.output and "barrado:" in result.output


def test_without_an_interactive_terminal_everything_that_needs_confirmation_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    request = ConfirmationRequest("render_project", {}, "Posso gerar o vídeo final?")

    assert cli._TerminalConfirmation().confirm(request) is False
    assert "Sem terminal interativo" in capsys.readouterr().out


def test_cloning_a_voice_asks_whether_the_owner_authorized_it(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    questions = []
    monkeypatch.setattr(cli.typer, "confirm", lambda text, **kwargs: questions.append(text) or True)
    request = ConfirmationRequest("clone_voice", {}, "Vou clonar a voz joao.", "voice_consent")

    assert cli._TerminalConfirmation().confirm(request) is True
    assert questions == ["O dono da voz autorizou o uso dela?"]
