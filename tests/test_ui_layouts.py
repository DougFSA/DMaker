"""LayoutStore (persistência em disco) e os endpoints /api/layouts da interface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dmaker.ui import server
from dmaker.ui.layouts import LayoutStore, deserialize_layouts, serialize_layouts

SAMPLE = {
    "version": 1,
    "areas": {"top-left": "filters"},
    "sizes": {"col-left": 300.0},
    "hidden": ["progress"],
}


def test_serialize_and_deserialize_round_trip():
    text = serialize_layouts({"Foco": SAMPLE})
    assert deserialize_layouts(text) == {"Foco": SAMPLE}


def test_deserialize_empty_and_invalid_text_is_empty_dict():
    assert deserialize_layouts("") == {}
    assert deserialize_layouts("   ") == {}
    assert deserialize_layouts("[]") == {}


def test_store_list_on_missing_file_is_empty(tmp_path):
    store = LayoutStore(tmp_path / "layouts.json")
    assert store.list() == {}
    assert store.get("Foco") is None


def test_store_save_list_get_delete(tmp_path):
    store = LayoutStore(tmp_path / "layouts.json")
    store.save("Foco", SAMPLE)
    assert store.list() == {"Foco": SAMPLE}
    assert store.get("Foco") == SAMPLE

    outro = {**SAMPLE, "hidden": []}
    store.save("Outro", outro)
    assert set(store.list()) == {"Foco", "Outro"}

    assert store.delete("Foco") is True
    assert store.list() == {"Outro": outro}
    assert store.delete("Foco") is False


def test_store_persists_across_instances(tmp_path):
    path = tmp_path / "layouts.json"
    LayoutStore(path).save("Foco", SAMPLE)
    assert LayoutStore(path).get("Foco") == SAMPLE


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "layout_store", LayoutStore(tmp_path / "layouts.json"))
    with TestClient(server.app) as c:
        yield c


def test_list_layouts_starts_empty(client):
    assert client.get("/api/layouts").json() == {"layouts": {}}


def test_save_list_and_delete_layout(client):
    resp = client.put("/api/layouts/Foco", json=SAMPLE)
    assert resp.status_code == 200

    listed = client.get("/api/layouts").json()
    assert listed["layouts"]["Foco"]["areas"] == {"top-left": "filters"}
    assert listed["layouts"]["Foco"]["hidden"] == ["progress"]

    assert client.delete("/api/layouts/Foco").status_code == 200
    assert client.get("/api/layouts").json() == {"layouts": {}}


def test_delete_missing_layout_is_404(client):
    resp = client.delete("/api/layouts/nao-existe")
    assert resp.status_code == 404


def test_save_layout_rejects_unknown_panel(client):
    bad = {**SAMPLE, "areas": {"top-left": "sofa"}}
    resp = client.put("/api/layouts/Foco", json=bad)
    assert resp.status_code == 400
    assert client.get("/api/layouts").json() == {"layouts": {}}


def test_save_layout_rejects_unknown_hidden_panel(client):
    bad = {**SAMPLE, "hidden": ["sofa"]}
    resp = client.put("/api/layouts/Foco", json=bad)
    assert resp.status_code == 400
