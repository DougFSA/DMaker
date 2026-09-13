"""Verificações básicas dos arquivos estáticos da interface (HTML/CSS/JS sem framework)."""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "dmaker" / "ui" / "static"

INDEX = STATIC_DIR / "index.html"
CSS = STATIC_DIR / "app.css"
JS = STATIC_DIR / "app.js"

# domínios externos permitidos só dentro de comentários JS; fora deles é proibido
EXTERNAL_URL_RE = re.compile(r"https?://")


def test_static_files_exist():
    assert INDEX.is_file(), "index.html não encontrado"
    assert CSS.is_file(), "app.css não encontrado"
    assert JS.is_file(), "app.js não encontrado"


def test_index_references_app_js_and_css():
    html = INDEX.read_text(encoding="utf-8")
    assert "/static/app.css" in html
    assert "/static/app.js" in html


def test_no_em_dash_in_static_files():
    for path in (INDEX, CSS, JS):
        text = path.read_text(encoding="utf-8")
        assert "—" not in text, f"travessão encontrado em {path.name}"


def _strip_js_comments(text: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    without_line = re.sub(r"//[^\n]*", "", without_block)
    return without_line


def test_app_js_has_no_external_domains():
    js = JS.read_text(encoding="utf-8")
    stripped = _strip_js_comments(js)
    matches = EXTERNAL_URL_RE.findall(stripped)
    assert not matches, "app.js referencia domínio externo fora de comentários"


def test_app_js_supports_video_overlays_and_source_sync():
    js = JS.read_text(encoding="utf-8")
    assert '{ value: "video", label: "Vídeo (PiP)" }' in js
    assert "/api/sync" in js
    assert "sources.${name}" in js or "sources." in js


def test_index_has_sources_and_partial_render_blocks():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="block-sources"' in html
    assert 'id="btn-sync-sources"' in html
    assert 'id="preview-segment-from"' in html and 'id="preview-segment-to"' in html
