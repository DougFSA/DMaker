"""Troca de rotas da interface: a nova (build do Vue) em "/", a anterior sempre em "/classica"."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dmaker.ui import server

NEW_MARKER = "<!doctype html><title>nova</title><div id=app></div>"


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture
def dist(tmp_path, monkeypatch):
    """Um build falso do Vue: index.html e um arquivo em assets/."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(NEW_MARKER, encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log('nova')", encoding="utf-8")
    monkeypatch.setattr(server, "DIST_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def no_dist(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DIST_DIR", tmp_path / "inexistente")


def test_without_dist_the_classic_ui_keeps_serving_root(client, no_dist):
    root = client.get("/")
    assert root.status_code == 200
    assert root.text == server.CLASSIC_INDEX.read_text(encoding="utf-8")


def test_classic_ui_is_always_on_classica(client, no_dist):
    assert client.get("/classica").text == server.CLASSIC_INDEX.read_text(encoding="utf-8")


def test_with_dist_the_new_ui_takes_root_and_classic_moves_to_classica(client, dist):
    assert client.get("/").text == NEW_MARKER
    assert client.get("/classica").text == server.CLASSIC_INDEX.read_text(encoding="utf-8")


def test_dist_assets_are_served(client, dist):
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "nova" in response.text


def test_client_side_routes_fall_back_to_the_new_index(client, dist):
    assert client.get("/projetos").text == NEW_MARKER
    assert client.get("/projetos/meu-video").text == NEW_MARKER


def test_missing_asset_is_a_real_404_not_the_index(client, dist):
    assert client.get("/assets/antigo.js").status_code == 404


def test_unknown_api_route_is_404_not_the_index(client, dist):
    assert client.get("/api/rota-que-nao-existe").status_code == 404


def test_fallback_does_not_leave_the_dist_folder(client, dist, tmp_path):
    secret = tmp_path.parent / "segredo.txt"
    secret.write_text("nao pode sair", encoding="utf-8")
    assert server._dist_file("../segredo.txt") is None
    assert server._dist_file("assets/../../segredo.txt") is None
    response = client.get("/assets/..%2f..%2fsegredo.txt")
    assert "nao pode sair" not in response.text


def test_fallback_keeps_api_method_semantics(client, dist):
    """O fallback só atende GET sem rota: método errado numa rota da API continua 405, e um DELETE
    em caminho desconhecido continua 404, não a página da interface."""
    assert client.post("/api/state").status_code == 405
    assert client.delete("/projetos").status_code == 404


def test_without_dist_unknown_paths_are_404(client, no_dist):
    assert client.get("/projetos").status_code == 404


def test_api_and_classic_static_still_win_over_the_fallback(client, dist):
    assert client.get("/api/state").status_code == 200
    assert client.get("/static/app.js").status_code == 200
