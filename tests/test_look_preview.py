"""Folha de contato dos looks: grafo puro, cache, rotas /api/looks e comandos da CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app as cli_app
from dmaker.domain.looks import DEFAULT_LOOKS, NO_LOOK, available_looks
from dmaker.media.ffmpeg import FFmpegCommand, FFmpegError, RecordingRunner
from dmaker.pipeline.look_preview import (
    SCENE_FPS,
    SCENE_SECONDS,
    SHEET_FRAME,
    LookPreview,
    scene_source,
    sheet_command,
    sheet_graph,
    sheet_key,
)
from dmaker.ui import server
from dmaker.ui.look_routes import get_look_preview


def _write_jpeg(command: FFmpegCommand) -> None:
    out = Path(command.args[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\xff\xd8\xff fake jpeg")


def test_the_scene_is_deterministic_and_carries_what_each_effect_needs():
    scene = scene_source()
    assert scene == scene_source() and "seed=" in scene  # sem semente, o degradê mudaria a cada folha
    assert scene.count("drawbox") >= 10 and scene.endswith("format=yuv420p")
    assert f"rate={SCENE_FPS:g}" in scene and f"duration={SCENE_SECONDS:g}" in scene


def test_the_sheet_graph_shows_the_original_and_one_tile_per_look_in_a_row():
    looks = list(DEFAULT_LOOKS.values())
    graph = sheet_graph(looks)
    text = ";".join(graph.lines)
    assert graph.out == "[sheet]" and text.endswith("[sheet]")
    assert f"split={len(looks) + 1}" in text and f"hstack=inputs={len(looks) + 1}" in text
    assert text.count(f"select='eq(n,{SHEET_FRAME})'") == len(looks) + 1
    # cada look passa pelo acabamento de verdade, com rótulos próprios (os efeitos de dois looks não se misturam)
    assert "[lk1_in]" in text and f"[lk{len(looks)}_in]" in text and "vignette=angle=" in text
    assert "drawtext" not in text  # sem fonte, só a tarja
    assert "drawtext=fontfile=" in ";".join(sheet_graph(looks, Path("C:/fontes/Poppins.ttf")).lines)


def test_the_sheet_graph_needs_at_least_one_look():
    with pytest.raises(ValueError, match="ao menos um look"):
        sheet_graph([])


def test_sheet_key_follows_the_recipe_of_the_look_and_not_the_call():
    cinema, frio = DEFAULT_LOOKS["cinema"], DEFAULT_LOOKS["frio"]
    assert sheet_key(sheet_graph([cinema])) == sheet_key(sheet_graph([cinema]))
    assert sheet_key(sheet_graph([cinema])) != sheet_key(sheet_graph([frio]))
    tweaked = type(cinema)(
        cinema.name, cinema.summary, cinema.color.model_copy(update={"grain": 0.9}), cinema.aliases
    )
    assert sheet_key(sheet_graph([cinema])) != sheet_key(
        sheet_graph([tweaked])
    )  # ajustou o look, outra folha


def test_sheet_command_feeds_the_lavfi_scene_and_writes_one_jpeg_frame(tmp_path):
    command = sheet_command(sheet_graph([DEFAULT_LOOKS["cinema"]]), tmp_path / "x.jpg")
    assert command.args[:3] == ["-f", "lavfi", "-i"] and command.args[3] == scene_source()
    assert command.args[-7:] == ["-map", "[sheet]", "-frames:v", "1", "-q:v", "3", str(tmp_path / "x.jpg")]


def test_preview_renders_once_and_serves_the_cache_afterwards():
    runner = RecordingRunner(on_run=_write_jpeg)
    preview = LookPreview(runner, font=None)
    first = preview.sheet("cinema")
    second = preview.sheet("Cinema")  # o nome vale sem diferenciar maiúsculas
    assert first == second and first.exists() and first.is_relative_to(config.CACHE_DIR / "looks")
    assert len(runner.commands) == 1
    preview.sheet("frio")
    overview = preview.overview()
    assert overview.name.startswith("todos-") and len(runner.commands) == 3
    assert preview.overview() == overview and len(runner.commands) == 3


def test_overview_includes_the_brand_looks_and_a_brand_look_changes_the_sheet():
    runner = RecordingRunner(on_run=_write_jpeg)
    preview = LookPreview(runner, font=None)
    brand = {"clinica": {"summary": "Limpo", "color": {"saturation": 1.1}}}
    plain, with_brand = preview.overview(), preview.overview(brand)
    assert plain != with_brand
    assert f"hstack=inputs={len(available_looks(brand)) + 1}" in " ".join(runner.commands[-1])
    assert preview.sheet("clinica", brand).exists()


# ---------- rotas ----------


@pytest.fixture
def client():
    runner = RecordingRunner(on_run=_write_jpeg)
    server.app.dependency_overrides[get_look_preview] = lambda: LookPreview(runner, font=None)
    with TestClient(server.app) as c:
        c.runner = runner  # type: ignore[attr-defined]
        yield c
    server.app.dependency_overrides.pop(get_look_preview, None)


def test_catalog_route_lists_every_look_with_summary_origin_and_effects(client):
    body = client.get("/api/looks").json()
    assert body["off"] == NO_LOOK
    assert [item["name"] for item in body["looks"]] == list(DEFAULT_LOOKS)
    by_name = {item["name"]: item for item in body["looks"]}
    assert by_name["frio"]["effects"] == {"vignette": 0.1} and by_name["cinema"]["source"] == "padrão"
    assert by_name["vintage"]["effects"]["light_leak"] == 0.3
    assert all(item["summary"] for item in body["looks"])


def test_catalog_route_adds_the_brand_looks(client, tmp_path, monkeypatch):
    from dmaker.domain import brand as brand_module

    folder = tmp_path / "brands" / "minha"
    folder.mkdir(parents=True)
    (folder / "brand.json").write_text(
        json.dumps({"looks": {"cinema": {"summary": "Meu cinema", "color": {"grain": 0.05}}, "novo": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(brand_module, "BRANDS_DIR", tmp_path / "brands")
    body = client.get("/api/looks", params={"brand": "minha"}).json()
    by_name = {item["name"]: item for item in body["looks"]}
    assert by_name["cinema"]["source"] == "marca" and by_name["cinema"]["summary"] == "Meu cinema"
    assert by_name["novo"]["source"] == "marca" and by_name["quente"]["source"] == "padrão"
    assert client.get("/api/looks", params={"brand": "nao-existe"}).status_code == 404


def test_sheet_routes_generate_the_jpeg_then_reuse_it(client):
    response = client.get("/api/looks/vintage/sheet")
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8")
    client.get("/api/looks/vintage/sheet")
    assert len(client.runner.commands) == 1
    overview = client.get("/api/looks/sheet")
    assert overview.status_code == 200 and len(client.runner.commands) == 2


def test_sheet_route_validates_the_name(client):
    missing = client.get("/api/looks/neon/sheet")
    assert missing.status_code == 404 and "look desconhecido" in missing.json()["detail"]
    assert client.runner.commands == []  # nada foi gerado


def test_sheet_route_reports_an_ffmpeg_failure_in_portuguese():
    def broken(command: FFmpegCommand) -> None:
        raise FFmpegError("ffmpeg falhou em: prévia dos looks")

    server.app.dependency_overrides[get_look_preview] = lambda: LookPreview(
        RecordingRunner(on_run=broken), font=None
    )
    try:
        with TestClient(server.app) as c:
            response = c.get("/api/looks/cinema/sheet")
    finally:
        server.app.dependency_overrides.pop(get_look_preview, None)
    assert response.status_code == 500 and "Não foi possível gerar a prévia" in response.json()["detail"]


# ---------- CLI ----------


def test_cli_lists_the_looks_with_their_effects():
    result = CliRunner().invoke(cli_app, ["looks", "list"])
    assert result.exit_code == 0
    for name in DEFAULT_LOOKS:
        assert name in result.output
    assert "vazamento de luz" in result.output and NO_LOOK in result.output


def test_cli_list_adds_the_looks_of_a_brand_and_refuses_an_unknown_brand(tmp_path, monkeypatch):
    from dmaker.domain import brand as brand_module

    folder = tmp_path / "brands" / "minha"
    folder.mkdir(parents=True)
    (folder / "brand.json").write_text(
        json.dumps({"looks": {"clinica": {"summary": "Limpo"}}}), encoding="utf-8"
    )
    monkeypatch.setattr(brand_module, "BRANDS_DIR", tmp_path / "brands")
    shown = CliRunner().invoke(cli_app, ["looks", "list", "--brand", "minha"])
    assert shown.exit_code == 0 and "clinica" in shown.output and "marca" in shown.output
    assert CliRunner().invoke(cli_app, ["looks", "list", "--brand", "nao-existe"]).exit_code == 1


def test_cli_sheet_refuses_unknown_names():
    result = CliRunner().invoke(cli_app, ["looks", "sheet", "neon"])
    assert result.exit_code == 1 and "dmaker looks list" in result.output.replace("\n", " ")


def test_cli_sheet_writes_one_jpeg_per_look_and_the_overview(monkeypatch, tmp_path):
    runner = RecordingRunner(on_run=_write_jpeg)
    monkeypatch.setattr("dmaker.media.ffmpeg.SubprocessRunner", lambda quiet=True: runner)
    out = tmp_path / "folhas"
    result = CliRunner().invoke(cli_app, ["looks", "sheet", "all", "--out-dir", str(out)])
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.glob("*.jpg")) == sorted(
        ["looks-todos.jpg", *(f"{name}.jpg" for name in DEFAULT_LOOKS)]
    )
    assert "original, cinema, quente" in result.output.replace(chr(10), " ")
    only = CliRunner().invoke(cli_app, ["looks", "sheet", "frio", "--out-dir", str(tmp_path / "um")])
    assert only.exit_code == 0 and [p.name for p in (tmp_path / "um").glob("*.jpg")] == ["frio.jpg"]
