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
WAVEFORM = STATIC_DIR / "waveform.js"
PLAYER = STATIC_DIR / "player.js"
EDITOR = STATIC_DIR / "editor.js"
OPTIONS = STATIC_DIR / "options.js"
FILTERS = STATIC_DIR / "filters.js"
MEDIA = STATIC_DIR / "media.js"
PROGRESS = STATIC_DIR / "progress.js"
LAYOUT = STATIC_DIR / "layout.js"

ALL_JS = (JS, KEYMAP, TIMELINE, WAVEFORM, PLAYER, EDITOR, OPTIONS, FILTERS, MEDIA, PROGRESS, LAYOUT)

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


def test_waveform_file_exists_and_is_referenced():
    assert WAVEFORM.is_file(), "waveform.js não encontrado"
    html = INDEX.read_text(encoding="utf-8")
    assert "/static/waveform.js" in html, "index.html não referencia waveform.js"
    js = WAVEFORM.read_text(encoding="utf-8")
    assert "window.DMakerWaveform" in js
    assert "fetchPeaks" in js and "draw" in js
    assert "/api/waveform" in TIMELINE.read_text(encoding="utf-8") or "/api/waveform" in js


def test_progress_file_exists_and_is_referenced():
    assert PROGRESS.is_file(), "progress.js não encontrado"
    html = INDEX.read_text(encoding="utf-8")
    assert "/static/progress.js" in html, "index.html não referencia progress.js"
    js = PROGRESS.read_text(encoding="utf-8")
    assert "window.DMakerProgress" in js
    assert "montagem final" in js  # etapa derivada do log/label que o renderer emite


def test_index_has_progress_panel_step_and_elapsed_ids():
    html = INDEX.read_text(encoding="utf-8")
    for element_id in ("progress-steps", "progress-elapsed", "progress-panel", "progress-bar-fill"):
        assert f'id="{element_id}"' in html, f"id {element_id!r} não encontrado em index.html"


def test_app_js_supports_hash_routing_and_heartbeat():
    js = JS.read_text(encoding="utf-8")
    assert "hashchange" in js
    assert "/api/clients/ping" in js
    assert "DMakerProgress" in js


def test_jobs_panel_has_clear_finished_button():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="btn-clear-jobs"' in html
    js = JS.read_text(encoding="utf-8")
    assert "btn-clear-jobs" in js
    assert "/api/jobs/finished" in js


def test_layout_file_exists_and_is_referenced():
    assert LAYOUT.is_file(), "layout.js não encontrado"
    html = INDEX.read_text(encoding="utf-8")
    assert "/static/layout.js" in html, "index.html não referencia layout.js"
    js = LAYOUT.read_text(encoding="utf-8")
    assert "window.DMakerLayout" in js
    for fn in ("normalizeLayout", "swapPanels", "builtinLayouts", "applyLayout"):
        assert f"function {fn}" in js, f"{fn} não encontrada em layout.js"


def test_builtin_layouts_cover_shotcut_inspired_names():
    js = LAYOUT.read_text(encoding="utf-8")
    for name in ("Edição", "Áudio", "Player"):
        assert f'"{name}"' in js or f"{name}:" in js, f"layout embutido {name!r} não encontrado"


def test_index_has_layout_selector_and_draggable_panels():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="layout-select"' in html
    for panel in ("player", "filters", "media", "timeline"):
        assert f'data-panel="{panel}"' in html, f'data-panel="{panel}" não encontrado em index.html'
    assert 'data-slot="top-left"' in html and 'data-slot="bottom"' in html
    assert html.count('class="panel-title"') >= 4 or html.count("panel-title") >= 4


def test_app_js_and_editor_js_hook_into_layout():
    app_js = JS.read_text(encoding="utf-8")
    editor_js = EDITOR.read_text(encoding="utf-8")
    assert "DMakerLayout.init" in app_js
    assert "DMakerLayout.refresh" in app_js
    assert "dmaker:layout-applied" in editor_js


def test_timeline_has_track_mute_hide_lock_buttons():
    js = TIMELINE.read_text(encoding="utf-8")
    for token in (
        "track-mute",
        "track-hide",
        "track-lock",
        "data-track-action",
        "onTrackToggle",
        "onLockedAttempt",
    ):
        assert token in js, f"{token!r} não encontrado em timeline.js"


def test_keymap_has_track_mute_hide_lock_shortcuts():
    js = KEYMAP.read_text(encoding="utf-8")
    for key in ("Ctrl+m", "Ctrl+h", "Ctrl+l"):
        assert f'"{key}"' in js, f"atalho {key!r} não encontrado em keymap.js"
    for action_id in ("track_mute", "track_hide", "track_lock"):
        assert f'"{action_id}"' in js, f"ação {action_id!r} não encontrada em keymap.js"


def test_editor_js_wires_track_shortcuts_to_set_field():
    js = EDITOR.read_text(encoding="utf-8")
    assert "track_mute" in js and "track_hide" in js and "track_lock" in js
    assert "tracks.${trackId}" in js


def test_player_and_media_js_prefer_resolved_path():
    player_js = PLAYER.read_text(encoding="utf-8")
    media_js = MEDIA.read_text(encoding="utf-8")
    assert "item.path" in player_js
    assert "buildResolvedPathMap" in media_js and "item.path" in media_js
