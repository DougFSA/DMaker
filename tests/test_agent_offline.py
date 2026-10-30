"""`dmaker doctor --offline`: o relatório de "funciona sem internet?", com a sonda do disco trocada por um falso."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dmaker import cli, config
from dmaker.agent import offline
from dmaker.agent.offline import (
    REQUIRED_MODELS,
    REQUIRED_MODULES,
    DiskOfflineProbe,
    OfflineItem,
    OfflineReport,
    build_report,
    render_report,
)
from dmaker.agent.settings import AgentSettings

runner = CliRunner()
SETTINGS = AgentSettings(engine="ollama", model="modelo-x", url="http://127.0.0.1:11434")


class FakeProbe:
    """Uma máquina de mentira: tudo pronto, e cada teste estraga o que quer provar."""

    def __init__(self, **broken):
        self.broken = broken
        self.browsers: dict[Path, list[str]] = {}

    def model_state(self, model_id):
        return self.broken.get("models", {}).get(model_id, "installed")

    def module_available(self, name):
        return name not in self.broken.get("modules", ())

    def path_exists(self, path):
        return str(path) not in self.broken.get("paths", ())

    def list_dir(self, path):
        if "no_chromium" in self.broken:
            return []
        return self.browsers.get(path, ["chromium-1234"])

    def tool_path(self, name):
        return None if name in self.broken.get("tools", ()) else Path(f"/bin/{name}")

    def language_model_state(self, settings):
        return self.broken.get("language_model", "ready")


def by_name(report: OfflineReport) -> dict[str, OfflineItem]:
    return {item.name: item for item in report.items}


def test_everything_downloaded_means_the_machine_is_ready_to_work_offline():
    report = build_report(SETTINGS, FakeProbe())

    assert report.ready and report.missing == ()
    assert render_report(report)[-1] == "Tudo pronto: o DMaker funciona sem internet."


def test_the_report_covers_every_piece_the_card_lists():
    report = build_report(SETTINGS, FakeProbe())
    names = " ".join(item.name for item in report.items)

    for needed in (
        "Modelo de linguagem modelo-x",
        "whisper-small",
        "omnivoice",
        "demucs-htdemucs",
        "rvm-resnet50",
        "audioseal",
        "Chromium do Playwright",
        "Efeitos sonoros",
        "Fonte Poppins",
        "FFmpeg e ffprobe",
    ):
        assert needed in names, needed
    assert len(report.items) == 3 + 1 + len(REQUIRED_MODELS) + len(REQUIRED_MODULES) + 1


def test_every_item_says_where_it_looked_and_a_missing_one_says_what_fails_and_how_to_download():
    report = build_report(SETTINGS, FakeProbe(models={"omnivoice": "absent"}, no_chromium=True))

    for item in report.items:
        assert item.where.strip()
    omni = by_name(report)["Modelo omnivoice"]
    assert omni.status == "missing" and omni.download == "dmaker models download omnivoice"
    assert "narração" in omni.needed_by
    chromium = by_name(report)["Chromium do Playwright"]
    assert chromium.status == "missing" and chromium.download == "dmaker setup --html"


def test_a_partial_download_counts_as_missing_and_is_called_that():
    report = build_report(SETTINGS, FakeProbe(models={"demucs-htdemucs": "partial"}))

    item = by_name(report)["Modelo demucs-htdemucs (download pela metade)"]
    assert item.status == "missing"


def test_the_language_model_reports_a_stopped_server_and_a_missing_model_differently():
    down = by_name(build_report(SETTINGS, FakeProbe(language_model="server_down")))
    absent = by_name(build_report(SETTINGS, FakeProbe(language_model="model_missing")))

    assert down["Modelo de linguagem modelo-x (servidor parado)"].download == "ollama serve"
    assert absent["Modelo de linguagem modelo-x"].download == "ollama pull modelo-x"


def test_the_openai_engine_does_not_suggest_ollama_commands():
    settings = AgentSettings(engine="openai", model="m", url="http://127.0.0.1:8080")

    down = by_name(build_report(settings, FakeProbe(language_model="server_down")))

    assert "ollama" not in down["Modelo de linguagem m (servidor parado)"].download
    assert "servidor compatível com a OpenAI" in down["Modelo de linguagem m (servidor parado)"].where


def test_missing_python_packages_point_to_the_pip_extra():
    report = build_report(SETTINGS, FakeProbe(modules=("faster_whisper",)))

    item = by_name(report)["Pacote Python faster_whisper"]
    assert item.status == "missing" and item.download == 'pip install -e ".[captions]"'


def test_the_pdf_reader_is_an_optional_module_with_its_own_extra():
    report = build_report(SETTINGS, FakeProbe(modules=("pypdf",)))

    item = by_name(report)["Pacote Python pypdf"]
    assert item.status == "missing" and item.download == 'pip install -e ".[agente]"'
    assert "PDF" in item.needed_by and not report.ready
    assert by_name(build_report(SETTINGS, FakeProbe()))["Pacote Python pypdf"].ok


def test_missing_ffmpeg_fonts_and_sounds_are_reported_with_dmaker_setup():
    report = build_report(
        SETTINGS,
        FakeProbe(tools=("ffprobe",), paths=(str(config.FONTS_DIR / "Poppins-Regular.ttf"),)),
    )

    items = by_name(report)
    assert (
        items["FFmpeg e ffprobe"].status == "missing" and items["FFmpeg e ffprobe"].download == "dmaker setup"
    )
    assert items["Fonte Poppins"].status == "missing"
    assert items["Efeitos sonoros"].status == "ok"


def test_the_text_report_lists_each_gap_with_the_command_and_counts_them():
    report = build_report(SETTINGS, FakeProbe(models={"omnivoice": "absent", "audioseal": "absent"}))

    lines = render_report(report)
    text = "\n".join(lines)

    assert "[FALTA] Modelo omnivoice" in text and "[ok] FFmpeg e ffprobe" in text
    assert "para baixar agora, com internet: dmaker models download omnivoice" in text
    assert "sem isso falha:" in text
    assert lines[-1] == "2 item(ns) vão falhar sem rede. Rode os comandos acima enquanto há conexão."


def test_the_report_has_no_dashes_in_its_screen_text():
    text = "\n".join(
        render_report(build_report(SETTINGS, FakeProbe(no_chromium=True, language_model="server_down")))
    )

    assert "—" not in text and "–" not in text


# ---------- onde o Chromium conta ----------


def test_chromium_in_bin_playwright_is_found_there(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "playwright")
    (tmp_path / "playwright" / "chromium-1169").mkdir(parents=True)

    item = offline._chromium_item(DiskOfflineProbe())

    assert item.status == "ok" and item.where == str(tmp_path / "playwright")


def test_the_headless_shell_folder_also_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "playwright")
    (tmp_path / "playwright" / "chromium_headless_shell-1248").mkdir(parents=True)

    assert offline._chromium_item(DiskOfflineProbe()).status == "ok"


def test_a_chromium_outside_the_dmaker_folder_does_not_count(tmp_path, monkeypatch):
    """O render abre o Chromium com o ambiente do Playwright apontado para `bin/playwright`: o que está na pasta
    padrão do sistema não serve, e dizer "ok" aqui faria o render falhar sem rede."""
    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "bin" / "playwright")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "padrao"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "padrao"))
    (tmp_path / "padrao" / "ms-playwright" / "chromium-1169").mkdir(parents=True)
    (tmp_path / "padrao" / "chromium-1169").mkdir(parents=True)

    item = offline._chromium_item(DiskOfflineProbe())

    assert item.status == "missing" and item.download == "dmaker setup --html"


# ---------- a sonda de verdade ----------


def test_the_disk_probe_reads_folders_and_modules_without_raising(tmp_path):
    probe = DiskOfflineProbe()
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    assert probe.list_dir(tmp_path) == ["a.txt"] and probe.list_dir(tmp_path / "nao-existe") == []
    assert probe.path_exists(tmp_path / "a.txt") and not probe.path_exists(tmp_path / "b.txt")
    assert probe.module_available("json") and not probe.module_available("modulo_que_nao_existe_xyz")


def test_the_disk_probe_reads_model_state_from_the_models_folder():
    assert DiskOfflineProbe().model_state("omnivoice") == "absent"  # pasta de dados vazia do teste


def test_the_disk_probe_asks_the_configured_engine_whether_the_model_is_there(monkeypatch):
    class Chat:
        alive = True
        installed = False

        def is_alive(self):
            return Chat.alive

        def has_model(self):
            return Chat.installed

    monkeypatch.setattr("dmaker.agent.settings.build_chat", lambda settings: Chat())
    probe = DiskOfflineProbe()

    assert probe.language_model_state(SETTINGS) == "model_missing"
    Chat.installed = True
    assert probe.language_model_state(SETTINGS) == "ready"
    Chat.alive = False
    assert probe.language_model_state(SETTINGS) == "server_down"


# ---------- a linha de comando ----------


def test_doctor_offline_exits_zero_when_ready_and_one_when_something_is_missing(monkeypatch):
    monkeypatch.setattr("dmaker.agent.offline.DiskOfflineProbe", FakeProbe)

    ready = runner.invoke(cli.app, ["doctor", "--offline"])
    assert ready.exit_code == 0 and "Tudo pronto" in ready.output

    monkeypatch.setattr(
        "dmaker.agent.offline.DiskOfflineProbe", lambda: FakeProbe(models={"omnivoice": "absent"})
    )
    missing = runner.invoke(cli.app, ["doctor", "--offline"])
    assert missing.exit_code == 1
    assert "dmaker models download omnivoice" in missing.output and "vão falhar sem rede" in missing.output


def test_doctor_offline_uses_the_configured_engine_and_model(monkeypatch):
    seen = {}

    def fake_build(settings, probe):
        seen["settings"] = settings
        return OfflineReport(())

    monkeypatch.setattr("dmaker.agent.offline.build_report", fake_build)
    monkeypatch.setenv("DMAKER_AGENT_ENGINE", "openai")
    monkeypatch.setenv("DMAKER_AGENT_MODEL", "qwen-x")

    result = runner.invoke(cli.app, ["doctor", "--offline"])

    assert result.exit_code == 0
    assert (seen["settings"].engine, seen["settings"].model) == ("openai", "qwen-x")


def test_doctor_offline_complains_about_a_bad_engine_variable(monkeypatch):
    monkeypatch.setenv("DMAKER_AGENT_ENGINE", "gpt")

    result = runner.invoke(cli.app, ["doctor", "--offline"])

    assert result.exit_code == 1 and "DMAKER_AGENT_ENGINE" in result.output
