"""Folha de contato das transições: grafo puro, cache, rotas /api/transitions e comandos da CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app as cli_app
from dmaker.domain.curves import CURVES
from dmaker.domain.transitions import all_transition_names
from dmaker.media.ffmpeg import FFmpegCommand, FFmpegError, RecordingRunner
from dmaker.pipeline.transition_preview import (
    PREVIEW_SIZE,
    SHEET_FRAMES,
    TransitionPreview,
    preview_sources,
    sheet_command,
    sheet_graph,
    sheet_indices,
    sheet_key,
)
from dmaker.ui import server
from dmaker.ui.transition_routes import get_transition_preview


def _write_png(command: FFmpegCommand) -> None:
    out = Path(command.args[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x89PNG fake")


def test_sheet_indices_go_from_the_frame_before_the_window_to_the_first_after_it():
    indices = sheet_indices(18, 18)
    assert indices[0] == 17 and indices[-1] == 36
    assert indices == sorted(set(indices)) and len(indices) == SHEET_FRAMES
    assert sheet_indices(0, 15)[0] == 0  # janela no começo: não há quadro antes


@pytest.mark.parametrize("name", sorted(all_transition_names()))
def test_sheet_graph_exists_for_every_transition(name):
    graph = sheet_graph(name)
    text = ";".join(graph.lines)
    assert graph.out == "[sheet]" and text.endswith("[sheet]")
    assert "anullsink" in text  # o áudio mudo do clipe sintético precisa de um destino
    assert "select='eq(n," in text and "tile=8x1" in text
    assert len(graph.inputs) == 2 and all(
        "[out0]" in source and "anullsrc" in source for source in graph.inputs
    )


def test_sheet_graph_uses_the_curve_and_refuses_unknown_names_and_curves():
    assert sheet_graph("wipeleft", "linear").lines != sheet_graph("wipeleft", "spring").lines
    with pytest.raises(KeyError, match="Transição desconhecida"):
        sheet_graph("giro3d")
    with pytest.raises(ValueError, match="Curva desconhecida"):
        sheet_graph("fade", "elastico")


def test_sheet_key_changes_with_the_curve_and_the_transition_but_not_between_calls():
    assert sheet_key(sheet_graph("whippan")) == sheet_key(sheet_graph("whippan"))
    keys = {sheet_key(sheet_graph(name, curve)) for name in ("whippan", "fade") for curve in CURVES}
    assert len(keys) == 6


def test_sheet_command_feeds_lavfi_sources_and_writes_one_frame(tmp_path):
    command = sheet_command(sheet_graph("crosszoom"), tmp_path / "x.png")
    assert command.args.count("-f") == 2 and command.args.count("lavfi") == 2
    assert command.args[-5:] == ["-map", "[sheet]", "-frames:v", "1", str(tmp_path / "x.png")]
    width, height = PREVIEW_SIZE
    assert all(f"{width}x{height}" in source for source in preview_sources())


def test_preview_renders_once_and_serves_the_cache_afterwards():
    runner = RecordingRunner(on_run=_write_png)
    preview = TransitionPreview(runner)
    first = preview.sheet("whippan", "spring")
    second = preview.sheet("whippan", "spring")
    assert first == second and first.exists() and first.is_relative_to(config.CACHE_DIR / "transitions")
    assert len(runner.commands) == 1
    preview.sheet("whippan", "linear")  # outra curva, outra folha
    assert len(runner.commands) == 2


# ---------- rotas ----------


@pytest.fixture
def client():
    runner = RecordingRunner(on_run=_write_png)
    server.app.dependency_overrides[get_transition_preview] = lambda: TransitionPreview(runner)
    with TestClient(server.app) as c:
        c.runner = runner  # type: ignore[attr-defined]
        yield c
    server.app.dependency_overrides.pop(get_transition_preview, None)


def test_catalog_route_lists_every_transition_with_kind_and_summary(client):
    body = client.get("/api/transitions").json()
    assert body["curves"] == ["linear", "ease", "spring"]
    names = [item["name"] for item in body["transitions"]]
    assert set(names) == all_transition_names() and names[:5] == [
        "crosszoom",
        "whippan",
        "blurslide",
        "filmburn",
        "lightleak",
    ]
    by_name = {item["name"]: item for item in body["transitions"]}
    assert by_name["whippan"]["kind"] == "motion" and by_name["fade"]["kind"] == "xfade"
    assert all(item["summary"] for item in body["transitions"])


def test_sheet_route_generates_the_image_then_reuses_it(client):
    response = client.get("/api/transitions/lightleak/sheet", params={"curve": "ease"})
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    client.get("/api/transitions/lightleak/sheet", params={"curve": "ease"})
    assert len(client.runner.commands) == 1


def test_sheet_route_validates_name_and_curve(client):
    assert client.get("/api/transitions/giro3d/sheet").status_code == 404
    bad_curve = client.get("/api/transitions/fade/sheet", params={"curve": "elastico"})
    assert bad_curve.status_code == 400 and "Curva desconhecida" in bad_curve.json()["detail"]


def test_sheet_route_reports_an_ffmpeg_failure_in_portuguese():
    def broken(command: FFmpegCommand) -> None:
        raise FFmpegError("ffmpeg falhou em: prévia da transição")

    server.app.dependency_overrides[get_transition_preview] = lambda: TransitionPreview(
        RecordingRunner(on_run=broken)
    )
    try:
        with TestClient(server.app) as c:
            response = c.get("/api/transitions/fade/sheet")
    finally:
        server.app.dependency_overrides.pop(get_transition_preview, None)
    assert response.status_code == 500 and "Não foi possível gerar a prévia" in response.json()["detail"]


# ---------- CLI ----------


def test_cli_lists_transitions_and_filters_by_kind():
    result = CliRunner().invoke(cli_app, ["transitions", "list", "--kind", "movimento"])
    assert result.exit_code == 0
    assert "crosszoom" in result.output and "wipeleft" not in result.output
    assert "linear" in result.output and "spring" in result.output  # lembra das curvas
    assert CliRunner().invoke(cli_app, ["transitions", "list", "--kind", "folha"]).exit_code == 1


def test_cli_sheet_refuses_unknown_names_and_curves():
    runner = CliRunner()
    assert runner.invoke(cli_app, ["transitions", "sheet", "giro3d"]).exit_code == 1
    assert runner.invoke(cli_app, ["transitions", "sheet", "fade", "--curve", "elastico"]).exit_code == 1
