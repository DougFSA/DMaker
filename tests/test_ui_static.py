"""Verificações básicas dos arquivos estáticos da interface (HTML/CSS/JS sem framework)."""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "dmaker" / "ui" / "static"

INDEX = STATIC_DIR / "index.html"
CSS = STATIC_DIR / "app.css"
JS = STATIC_DIR / "app.js"
KEYMAP = STATIC_DIR / "keymap.js"
TIMELINE = STATIC_DIR / "timeline.js"
PLAYER = STATIC_DIR / "player.js"
EDITOR = STATIC_DIR / "editor.js"
OPTIONS = STATIC_DIR / "options.js"
FILTERS = STATIC_DIR / "filters.js"
MEDIA = STATIC_DIR / "media.js"

ALL_JS = (JS, KEYMAP, TIMELINE, PLAYER, EDITOR, OPTIONS, FILTERS, MEDIA)

# domínios externos permitidos só dentro de comentários JS; fora deles é proibido
EXTERNAL_URL_RE = re.compile(r"https?://")


def _all_static_files() -> list[Path]:
    """Todo arquivo estático servido (html/css/js), para checagens que devem valer sempre."""
    return sorted(p for p in STATIC_DIR.iterdir() if p.suffix in (".html", ".css", ".js"))


def test_static_files_exist():
    assert INDEX.is_file(), "index.html não encontrado"
    assert CSS.is_file(), "app.css não encontrado"
    assert JS.is_file(), "app.js não encontrado"


def test_timeline_editor_files_exist_and_are_referenced():
    for path in (KEYMAP, TIMELINE, PLAYER, EDITOR):
        assert path.is_file(), f"{path.name} não encontrado"
    html = INDEX.read_text(encoding="utf-8")
    for name in ("keymap.js", "timeline.js", "player.js", "editor.js"):
        assert f"/static/{name}" in html, f"index.html não referencia {name}"


def test_filters_and_media_files_exist_and_are_referenced():
    for path in (OPTIONS, FILTERS, MEDIA):
        assert path.is_file(), f"{path.name} não encontrado"
    html = INDEX.read_text(encoding="utf-8")
    for name in ("options.js", "filters.js", "media.js"):
        assert f"/static/{name}" in html, f"index.html não referencia {name}"


def test_index_references_app_js_and_css():
    html = INDEX.read_text(encoding="utf-8")
    assert "/static/app.css" in html
    assert "/static/app.js" in html


def test_no_em_dash_in_static_files():
    for path in _all_static_files():
        text = path.read_text(encoding="utf-8")
        assert "—" not in text, f"travessão encontrado em {path.name}"


def _strip_js_comments(text: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    without_line = re.sub(r"//[^\n]*", "", without_block)
    return without_line


def test_static_files_have_no_external_domains():
    for path in _all_static_files():
        text = path.read_text(encoding="utf-8")
        stripped = _strip_js_comments(text) if path.suffix == ".js" else text
        matches = EXTERNAL_URL_RE.findall(stripped)
        assert not matches, f"{path.name} referencia domínio externo fora de comentários"


def test_keymap_has_essential_shortcuts():
    js = KEYMAP.read_text(encoding="utf-8")
    for key in ("Space", '"s"', '"x"', '"z"', '"i"', '"o"', '"j"', '"k"', '"l"'):
        assert key in js, f"tecla essencial {key!r} não encontrada em keymap.js"


def test_app_js_supports_video_overlays_and_source_sync():
    combined = "\n".join(p.read_text(encoding="utf-8") for p in (JS, OPTIONS))
    assert '{ value: "video", label: "Vídeo (PiP)" }' in combined
    assert "/api/sync" in JS.read_text(encoding="utf-8")
    assert "sources.${name}" in JS.read_text(encoding="utf-8") or "sources." in JS.read_text(encoding="utf-8")


def test_index_has_sources_and_partial_render_blocks():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="block-sources"' in html
    assert 'id="btn-sync-sources"' in html
    assert 'id="preview-segment-from"' in html and 'id="preview-segment-to"' in html


def test_index_has_timeline_editor_ids():
    html = INDEX.read_text(encoding="utf-8")
    for element_id in ("panel-timeline", "timeline-tracks", "live-player", "btn-split"):
        assert f'id="{element_id}"' in html, f"id {element_id!r} não encontrado em index.html"


def test_index_has_filters_and_media_panel_ids():
    html = INDEX.read_text(encoding="utf-8")
    for element_id in ("panel-filters", "btn-add-filter", "panel-media", "btn-add-media"):
        assert f'id="{element_id}"' in html, f"id {element_id!r} não encontrado em index.html"


def test_filter_catalog_covers_main_types():
    js = FILTERS.read_text(encoding="utf-8")
    for applies_type in ("clip", "card", "video", "text"):
        assert f'"{applies_type}"' in js, f"FILTER_CATALOG não cobre o tipo {applies_type!r}"
