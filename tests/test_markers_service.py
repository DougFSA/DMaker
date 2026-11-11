"""Importar, exportar e gerar marcadores: o serviço, o comando `dmaker markers` e as ferramentas MCP."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from dmaker import cli, mcp_server
from dmaker.cli import app
from dmaker.domain.markers import MarkerError
from dmaker.domain.spec import Project
from dmaker.pipeline.markers import add_regular_markers, export_labels, import_labels, newline_text
from dmaker.pipeline.projects import load_project, project_path, save_project

DATA = Path(__file__).parent / "data"
TEN_LABELS = DATA / "audacity_labels_10.txt"
runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    monkeypatch.setattr(cli, "console", Console(width=200))


@pytest.fixture
def spec() -> Path:
    """Um áudio de 60 s (um cartão de 60 s) sem marcador, salvo na pasta de projetos do teste."""
    project = Project.model_validate(
        {"name": "mk-servico", "timeline": [{"type": "card", "title": "Áudio", "duration": 60}]}
    )
    return save_project(project)


# ---------- o serviço ----------


def test_importing_the_audacity_file_puts_ten_markers_in_the_project(spec):
    result = import_labels(spec, TEN_LABELS)
    assert (result.added, result.warnings) == (10, [])
    assert len(load_project(spec).markers) == 10
    assert load_project(spec).markers[2].start == 5.5


def test_the_ten_markers_go_out_identical_to_the_file_that_came_in(spec, tmp_path):
    import_labels(spec, TEN_LABELS)
    out = tmp_path / "volta.txt"
    exported = export_labels(spec, out, newline="lf")
    assert exported.count == 10 and out.read_bytes() == TEN_LABELS.read_bytes()


def test_the_round_trip_is_identical_with_windows_line_endings_too(spec, tmp_path):
    crlf = tmp_path / "audacity-windows.txt"
    crlf.write_bytes(TEN_LABELS.read_bytes().replace(b"\n", b"\r\n"))
    import_labels(spec, crlf)
    out = tmp_path / "volta.txt"
    export_labels(spec, out, newline="crlf")
    assert out.read_bytes() == crlf.read_bytes()


def test_importing_into_a_group_appends_and_replace_swaps_only_that_group(spec):
    import_labels(spec, TEN_LABELS, group="análise")
    import_labels(spec, TEN_LABELS)  # o grupo padrão
    assert [m.group for m in load_project(spec).markers] == ["análise"] * 10 + [""] * 10
    import_labels(spec, TEN_LABELS, group="análise")
    assert len(load_project(spec).markers) == 30
    import_labels(spec, TEN_LABELS, group="análise", replace=True)
    assert len(load_project(spec).markers) == 20


def test_exporting_one_group_writes_only_that_group(spec, tmp_path):
    import_labels(spec, TEN_LABELS, group="análise")
    save_project(
        load_project(spec).model_copy(update={"markers": [*load_project(spec).markers, *_one_marker("meus")]})
    )
    out = tmp_path / "meus.txt"
    assert export_labels(spec, out, group="meus", newline="lf").count == 1
    assert out.read_text(encoding="utf-8") == "7.000000\t7.000000\tsó este\n"
    assert export_labels(spec, tmp_path / "todos.txt", newline="lf").count == 11


def _one_marker(group: str):
    from dmaker.domain.spec import Marker

    return [Marker(at=7.0, text="só este", group=group)]


def test_export_without_out_goes_to_the_output_folder_and_without_markers_it_says_so(spec):
    with pytest.raises(MarkerError, match="não tem marcadores"):
        export_labels(spec)
    import_labels(spec, TEN_LABELS)
    exported = export_labels(spec)
    assert exported.path.name == "mk-servico-marcadores.txt" and exported.path.exists()


def test_the_default_line_break_is_the_one_of_the_system():
    import os

    assert newline_text("auto") == os.linesep
    assert (newline_text("lf"), newline_text("crlf")) == ("\n", "\r\n")
    with pytest.raises(MarkerError, match="auto, lf ou crlf"):
        newline_text("mac")  # type: ignore[arg-type]


def test_a_file_that_is_missing_or_not_utf8_is_a_clear_error(spec, tmp_path):
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        import_labels(spec, tmp_path / "nao-existe.txt")
    latin = tmp_path / "latin1.txt"
    latin.write_bytes("1.0\t1.0\tcoração\n".encode("latin-1"))
    with pytest.raises(MarkerError, match="UTF-8"):
        import_labels(spec, latin)


def test_regular_markers_every_15_seconds_over_the_60_second_project_make_4(spec):
    result = add_regular_markers(spec, interval=15, prefix="Parte ")
    assert result.added == 4
    markers = load_project(spec).markers
    assert [(m.text, m.start, m.end) for m in markers] == [
        ("Parte 1", 0, 15),
        ("Parte 2", 15, 30),
        ("Parte 3", 30, 45),
        ("Parte 4", 45, 60),
    ]
    add_regular_markers(spec, parts=2, replace=True)
    assert [m.text for m in load_project(spec).markers] == ["1", "2"]


def test_regular_markers_do_not_pass_the_end_of_the_project(spec):
    with pytest.raises(MarkerError, match="passa do fim do vídeo"):
        add_regular_markers(spec, interval=10, end=90)


# ---------- a CLI ----------


def test_the_markers_group_is_on_the_cli():
    assert "markers" in runner.invoke(app, ["--help"]).output
    out = runner.invoke(app, ["markers", "--help"]).output
    assert all(name in out for name in ("list", "add", "remove", "import", "export", "regular"))


def test_cli_adds_lists_and_removes_markers(spec):
    added = runner.invoke(
        app, ["markers", "add", str(spec), "--at", "12.5", "--text", "refrão", "--color", "#e0a020"]
    )
    assert added.exit_code == 0, added.output
    region = runner.invoke(
        app,
        ["markers", "add", str(spec), "--start", "20", "--end", "30", "--text", "verso", "--group", "meus"],
    )
    assert region.exit_code == 0, region.output
    listing = runner.invoke(app, ["markers", "list", str(spec)])
    assert "refrão" in listing.output and "12.5 s" in listing.output and "#e0a020" in listing.output
    assert "20 a 30 s" in listing.output and "meus" in listing.output and "(padrão)" in listing.output
    assert runner.invoke(app, ["markers", "remove", str(spec), "marker:refrão"]).exit_code == 0
    assert runner.invoke(app, ["markers", "remove", str(spec), "0"]).exit_code == 0
    assert load_project(spec).markers == []
    assert "não tem marcadores" in runner.invoke(app, ["markers", "list", str(spec)]).output


def test_cli_reports_errors_in_portuguese_with_a_failing_exit_code(spec):
    no_time = runner.invoke(app, ["markers", "add", str(spec), "--text", "sem tempo"])
    assert no_time.exit_code == 1 and "at" in no_time.output
    unknown = runner.invoke(app, ["markers", "remove", str(spec), "marker:nada"])
    assert unknown.exit_code == 1 and "não existe o marcador" in unknown.output
    bad_kind = runner.invoke(app, ["markers", "regular", str(spec), "--interval", "5", "--kind", "ponto"])
    assert bad_kind.exit_code == 1 and "region ou instant" in bad_kind.output
    bad_newline = runner.invoke(app, ["markers", "export", str(spec), "--newline", "mac"])
    assert bad_newline.exit_code == 1 and "auto, lf, crlf" in bad_newline.output


def test_cli_imports_and_exports_the_audacity_file_byte_by_byte(spec, tmp_path):
    imported = runner.invoke(app, ["markers", "import", str(spec), str(TEN_LABELS)])
    assert imported.exit_code == 0, imported.output
    assert "10 marcador(es) importado(s)" in imported.output
    out = tmp_path / "saida.txt"
    exported = runner.invoke(app, ["markers", "export", str(spec), "--out", str(out), "--newline", "lf"])
    assert exported.exit_code == 0, exported.output
    assert out.read_bytes() == TEN_LABELS.read_bytes()
    assert "10 marcador(es) exportado(s)" in exported.output


def test_cli_warns_about_the_lines_it_could_not_read(spec, tmp_path):
    broken = tmp_path / "quebrado.txt"
    broken.write_text("1.0\t1.0\tbom\nlixo\tlixo\tlixo\n", encoding="utf-8")
    result = runner.invoke(app, ["markers", "import", str(spec), str(broken)])
    assert result.exit_code == 0 and "1 marcador(es) importado(s)" in result.output
    assert "Linha 2 ignorada" in result.output


def test_cli_makes_regular_markers(spec):
    result = runner.invoke(
        app, ["markers", "regular", str(spec), "--interval", "15", "--prefix", "Parte ", "--digits", "2"]
    )
    assert result.exit_code == 0, result.output
    assert [m.text for m in load_project(spec).markers] == ["Parte 01", "Parte 02", "Parte 03", "Parte 04"]


# ---------- as ferramentas MCP ----------


def test_the_mcp_tools_are_registered_and_describe_the_format():
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.server.list_tools())}
    assert {"markers_import", "markers_export", "markers_regular", "edit_project", "timeline_view"} <= set(
        tools
    )
    assert (
        "Audacity" in tools["markers_import"].description
        and "seis casas" in tools["markers_export"].description
    )
    assert (
        "marker:<texto>" in tools["edit_project"].description and "MK" in tools["timeline_view"].description
    )


def test_the_mcp_tools_import_regular_and_export_a_round_trip(spec, tmp_path):
    imported = mcp_server.markers_import("mk-servico", str(TEN_LABELS))
    assert (imported["added"], imported["markers_total"], imported["warnings"]) == (10, 10, [])
    regular = mcp_server.markers_regular("mk-servico", interval=15, group="partes", prefix="P")
    assert regular["added"] == 4 and regular["markers_total"] == 14
    out = tmp_path / "mcp.txt"
    exported = mcp_server.markers_export("mk-servico", str(out), group="", newline="lf")
    assert exported == {"path": str(out), "count": 10} and out.read_bytes() == TEN_LABELS.read_bytes()
    view = mcp_server.timeline_view("mk-servico")
    assert [t["id"] for t in view["tracks"] if t["kind"] == "markers"] == ["MK", "MK:partes"]


def test_the_mcp_tools_turn_the_expected_errors_into_tool_errors(spec, tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="não encontrado"):
        mcp_server.markers_import("mk-servico", str(tmp_path / "nada.txt"))
    with pytest.raises(ToolError, match="não tem marcadores"):
        mcp_server.markers_export("mk-servico")
    with pytest.raises(ToolError, match="`interval`.*`parts`"):
        mcp_server.markers_regular("mk-servico")
    assert project_path("mk-servico").exists()


# ---------- o gate do agente ----------


def test_the_agent_asks_before_overwriting_the_default_markers_file():
    from dmaker.agent.safety import ApproveAll, DenyAll, ToolGate
    from dmaker.pipeline.markers import default_export_path

    target = str(default_export_path("mk-servico"))
    asked = ApproveAll()
    gate = ToolGate(schemas={}, policy=asked, exists={target}.__contains__)
    assert gate.check("markers_export", {"name": "mk-servico"}) is None
    assert [request.question for request in asked.asked] == [
        f"O arquivo '{target}' já existe. Posso sobrescrevê-lo?"
    ]

    refused = ToolGate(schemas={}, policy=DenyAll(), exists={target}.__contains__)
    assert refused.check("markers_export", {"name": "mk-servico"}) is not None


def test_the_agent_does_not_ask_when_the_file_is_new_or_the_destination_is_explicit():
    from dmaker.agent.safety import ApproveAll, ToolGate

    asked = ApproveAll()
    gate = ToolGate(schemas={}, policy=asked, exists={"C:/saidas/existe.txt"}.__contains__)
    gate.check("markers_export", {"name": "mk-servico"})  # o arquivo padrão não existe
    gate.check("markers_export", {"name": "mk-servico", "out": "C:/saidas/nova.txt"})
    assert asked.asked == []
    gate.check("markers_export", {"name": "mk-servico", "out": "C:/saidas/existe.txt"})
    assert len(asked.asked) == 1
