"""Verificações básicas dos arquivos estáticos da interface (HTML/CSS/JS sem framework)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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
VOICE = STATIC_DIR / "voice.js"
SPEECH = STATIC_DIR / "speech.js"
DUB = STATIC_DIR / "dub.js"

ALL_JS = (
    JS,
    KEYMAP,
    TIMELINE,
    WAVEFORM,
    PLAYER,
    EDITOR,
    OPTIONS,
    FILTERS,
    MEDIA,
    PROGRESS,
    LAYOUT,
    VOICE,
    SPEECH,
    DUB,
)

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node não instalado")

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


def test_voice_file_exists_and_is_referenced_before_app_js():
    assert VOICE.is_file(), "voice.js não encontrado"
    html = INDEX.read_text(encoding="utf-8")
    assert "/static/voice.js" in html, "index.html não referencia voice.js"
    assert html.index("/static/voice.js") < html.index("/static/app.js")
    assert "window.DMakerVoice" in VOICE.read_text(encoding="utf-8")


def test_index_has_voice_tab_and_studio_ids():
    html = INDEX.read_text(encoding="utf-8")
    assert 'data-tab="voice"' in html and 'id="panel-voice"' in html and 'data-panel="voice"' in html
    for element_id in (
        "voice-list",
        "voice-clone-file",
        "voice-rec-toggle",
        "voice-rec-clock",
        "voice-clone-consent",
        "voice-design-gender",
        "voice-design-instruct",
        "voice-script",
        "voice-script-stats",
        "voice-speed",
        "voice-generate",
        "voice-progress-fill",
        "voice-result-audio",
        "voice-result-download",
        "voice-result-insert",
        "voice-history",
    ):
        assert f'id="{element_id}"' in html, f"id {element_id!r} não encontrado em index.html"
    assert "permissão do dono" in html and "5 a 8 segundos" in html
    assert "[pausa 1.2]" in html


def test_voice_js_uses_voice_api_with_jobs_sse_and_recorder():
    js = VOICE.read_text(encoding="utf-8")
    for token in (
        "/api/voices",
        "/api/voices/design-options",
        "/api/voices/clone",
        "/api/voices/design",
        "/api/voices/speak",
        "/preview",
        "/api/jobs/",
        "EventSource",
        "MediaRecorder",
        "getUserMedia",
        "audio.narration",
        "saveProject",
        "getPlayheadTime",
    ):
        assert token in js, f"{token!r} não encontrado em voice.js"


def test_app_js_and_layout_js_hook_into_voice_studio():
    app_js = JS.read_text(encoding="utf-8")
    assert "DMakerVoice.init" in app_js and "DMakerVoice.onShow" in app_js
    assert "getPlayheadTime" in EDITOR.read_text(encoding="utf-8")
    layout_js = LAYOUT.read_text(encoding="utf-8")
    assert '"voice"' in layout_js and "tab-btn-voice" in layout_js
    assert "Voz:" in layout_js, "layout embutido Voz não encontrado"


@requires_node
@pytest.mark.parametrize("path", sorted(STATIC_DIR.glob("*.js")), ids=lambda p: p.name)
def test_every_static_script_has_valid_syntax(path):
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _run_voice_pure(expression: str):
    """Avalia `expression` com as funções puras de voice.js carregadas num `window` falso."""
    script = (
        "global.window = {};"
        f"require({json.dumps(str(VOICE))});"
        "const pure = window.DMakerVoice.pure;"
        f"console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@requires_node
def test_voice_script_estimate_uses_14_chars_per_second_speed_and_pauses():
    assert _run_voice_pure('pure.estimateSeconds("a".repeat(140), 1)') == 10
    assert _run_voice_pure('pure.estimateSeconds("a".repeat(140), 2)') == 5
    assert _run_voice_pure('pure.estimateSeconds("a".repeat(14) + " [pausa 1,5] ", 1)') == 2.5
    assert _run_voice_pure('pure.estimateSeconds("", 1)') == 0


@requires_node
def test_voice_recording_advice_and_formatting():
    levels = _run_voice_pure("[1, 4, 6, 12, 20].map((s) => pure.recordingAdvice(s).level)")
    assert levels == ["bad", "ok", "good", "ok", "bad"]
    assert _run_voice_pure("[pure.formatClock(5400), pure.formatDuration(42), pure.formatDuration(65)]") == [
        "0:05",
        "42 s",
        "1 min 05 s",
    ]
    assert _run_voice_pure(
        '["audio/webm;codecs=opus", "audio/mp4", "audio/ogg"].map(pure.extensionForMime)'
    ) == [
        "webm",
        "m4a",
        "ogg",
    ]


@requires_node
def test_voice_narration_item_for_the_project_spec():
    item = _run_voice_pure(
        'pure.buildNarrationItem({text: "Oi", voiceId: "ana", speed: 1.1, language: null, seed: 0}, 3.456)'
    )
    assert item == {"text": "Oi", "start": 3.46, "speed": 1.1, "voice": "ana", "seed": 0}
    bare = _run_voice_pure(
        'pure.buildNarrationItem({text: "Oi", voiceId: null, speed: 1, language: "en", seed: null}, -1)'
    )
    assert bare == {"text": "Oi", "start": 0, "speed": 1, "language": "en"}
    error = json.dumps("ValueError: voz sumiu\nTraceback (most recent call last)")
    assert _run_voice_pure(f"pure.jobErrorMessage({error})") == "voz sumiu"


def test_voice_studio_has_pronunciation_section_wired_to_the_api():
    html = INDEX.read_text(encoding="utf-8")
    for element_id in (
        "voice-pron-brand",
        "voice-pron-language",
        "voice-pron-rows",
        "voice-pron-term",
        "voice-pron-spoken",
        "voice-pron-add",
    ):
        assert f'id="{element_id}"' in html, f"id {element_id!r} não encontrado em index.html"
    assert "[[termo|pronúncia]]" in html
    js = VOICE.read_text(encoding="utf-8")
    assert "/api/voices/pronunciation" in js and "data-pron-action" in js and "/api/voices/speak" in js


@requires_node
def test_voice_pure_helpers_understand_inline_pronunciation():
    assert (
        _run_voice_pure('pure.spokenForm("Fale [[DMaker|Di Meiker]] e [[Samanta]].")')
        == "Fale Di Meiker e Samanta."
    )
    assert _run_voice_pure('pure.spokenForm("sem marcacao")') == "sem marcacao"
    assert (
        _run_voice_pure('pure.estimateSeconds("[[" + "a".repeat(140) + "|" + "b".repeat(14) + "]]", 1)') == 1
    )
    assert _run_voice_pure('pure.pronunciationPreviewText(" DMaker ")') == "Eu falo DMaker. Repito: DMaker."


# ---------- isolar voz e corrigir fala (speech.js) ----------


def test_speech_file_is_referenced_after_voice_js_and_before_app_js():
    html = INDEX.read_text(encoding="utf-8")
    assert SPEECH.is_file() and "window.DMakerSpeech" in SPEECH.read_text(encoding="utf-8")
    assert html.index("/static/voice.js") < html.index("/static/speech.js") < html.index("/static/app.js")
    app_js = JS.read_text(encoding="utf-8")
    assert "DMakerSpeech.init" in app_js and "DMakerSpeech.onShow" in app_js
    assert "followJob" in VOICE.read_text(encoding="utf-8")


def test_index_has_the_isolate_and_fix_speech_sections():
    html = INDEX.read_text(encoding="utf-8")
    for element_id in (
        "speech-iso-source",
        "speech-iso-file",
        "speech-iso-start",
        "speech-iso-end",
        "speech-iso-format",
        "speech-iso-run",
        "speech-iso-progress",
        "speech-iso-voice",
        "speech-iso-background",
        "speech-iso-voice-download",
        "speech-iso-background-download",
        "speech-fix-source",
        "speech-fix-file",
        "speech-fix-from",
        "speech-fix-to",
        "speech-fix-transcribe",
        "speech-words",
        "speech-selection",
        "speech-fix-text",
        "speech-fix-voice",
        "speech-fix-expand",
        "speech-fix-run",
        "speech-fix-progress",
        "speech-ab-original",
        "speech-ab-fixed",
        "speech-fix-original",
        "speech-fix-fixed",
        "speech-fix-download",
        "speech-fix-use",
    ):
        assert f'id="{element_id}"' in html, f"id {element_id!r} não encontrado em index.html"
    assert "<legend>Isolar voz</legend>" in html and "<legend>Corrigir fala</legend>" in html
    assert "—" not in html and "—" not in html  # a marca não usa travessão em texto na tela


def test_speech_js_uses_the_speech_api_with_jobs_upload_and_project_ops():
    js = SPEECH.read_text(encoding="utf-8")
    for token in (
        "/api/speech/upload",
        "/api/speech/isolate",
        "/api/speech/words",
        "/api/speech/fix",
        "DMakerVoice.followJob",
        "collectMediaEntries",
        "DMakerEditor.applyOp",
        "saveProject",
        "set_field",
        "data-word",
    ):
        assert token in js, f"{token!r} não encontrado em speech.js"
    assert all(rule in CSS.read_text(encoding="utf-8") for rule in (".speech-word.selected", ".speech-words"))


def _run_speech_pure(expression: str):
    """Avalia `expression` com as funções puras de speech.js carregadas num `window` falso."""
    script = (
        "global.window = {};"
        f"require({json.dumps(str(SPEECH))});"
        "const pure = window.DMakerSpeech.pure;"
        f"console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


WORDS_JS = (
    "[{start:1.0,end:1.4,text:'Hoje'},{start:1.4,end:1.9,text:'é'},{start:2.5,end:3.0,text:'o'},"
    "{start:3.0,end:3.6,text:'casamento'},{start:5.0,end:5.4,text:'Depois'}]"
)


@requires_node
def test_speech_words_are_grouped_by_breath():
    assert _run_speech_pure(f"pure.groupWordsByBreath({WORDS_JS})") == [[0, 1], [2, 3], [4]]
    assert _run_speech_pure(f"pure.groupWordsByBreath({WORDS_JS}, 1)") == [[0, 1, 2, 3], [4]]
    assert _run_speech_pure("pure.groupWordsByBreath([])") == []


@requires_node
def test_speech_selection_accepts_the_clicks_in_any_order():
    forward = _run_speech_pure(f"pure.selectionFor({WORDS_JS}, 2, 3)")
    assert forward == {"first": 2, "last": 3, "start": 2.5, "end": 3.6, "text": "o casamento"}
    assert _run_speech_pure(f"pure.selectionFor({WORDS_JS}, 3, 2)") == forward
    single = _run_speech_pure(f"pure.selectionFor({WORDS_JS}, 4, 4)")
    assert single["text"] == "Depois" and (single["start"], single["end"]) == (5.0, 5.4)


@requires_node
def test_speech_project_sources_only_list_media_with_audio_and_a_path():
    entries = (
        "[{kind:'clip',label:'a.mp4',path:'D:/a.mp4',src:'a.mp4'},{kind:'image',label:'f.png',path:'D:/f.png'},"
        "{kind:'audio',label:'m.mp3',path:'D:/m.mp3',src:'m.mp3'},{kind:'clip',label:'x',path:''}]"
    )
    options = _run_speech_pure(f"pure.projectSourceOptions({entries}).map(o => [o.value, o.label, o.path])")
    assert options == [["project:0", "a.mp4", "D:/a.mp4"], ["project:1", "m.mp3", "D:/m.mp3"]]


@requires_node
def test_speech_replace_source_ops_cover_clips_overlays_and_named_sources():
    spec = (
        "{timeline:[{type:'clip',src:'a.mp4'},{type:'card'},{type:'clip',src:'b.mp4'},{type:'clip',src:'a.mp4'}],"
        "overlays:[{type:'video',src:'a.mp4'},{type:'image',src:'a.mp4'}]}"
    )
    ops = _run_speech_pure(f"pure.replaceSourceOps({spec}, {{src:'a.mp4'}}, 'out/c.mp4')")
    assert [op["path"] for op in ops] == ["timeline.0.src", "timeline.3.src", "overlays.0.src"]
    assert all(op["type"] == "set_field" and op["value"] == "out/c.mp4" for op in ops)
    named = _run_speech_pure(f"pure.replaceSourceOps({spec}, {{source:'cam1'}}, 'out/c.mp4')")
    assert named == [{"type": "set_field", "path": "sources.cam1.src", "value": "out/c.mp4"}]
    assert _run_speech_pure(f"pure.replaceSourceOps({spec}, null, 'x')") == []


@requires_node
def test_speech_ab_window_pads_the_region_and_never_goes_negative():
    assert _run_speech_pure("pure.abWindow([21.4, 23.4])") == {"start": 19.9, "end": 24.9}
    assert _run_speech_pure("pure.abWindow([0.5, 2], 1)") == {"start": 0, "end": 3}


@requires_node
def test_speech_number_parsing_and_summary():
    assert _run_speech_pure("['', ' 3,5 ', 'abc', '-2', '0', 12].map(pure.numberOrNull)") == [
        None,
        3.5,
        None,
        None,
        0,
        12,
    ]
    summary = _run_speech_pure(
        "pure.describeFix({old_text:'João',new_text:'Pedro',region:[21.44,23.4],rule:'duração mantida (1.2 s)',squeezed:true})"
    )
    assert summary.startswith('Trocado "João" por "Pedro" (região 21.4 a 23.4 s). Duração: duração mantida')
    assert "apertada" in summary


# ---------- dublagem (dub.js) ----------


def test_dub_file_is_referenced_after_speech_js_and_before_app_js():
    html = INDEX.read_text(encoding="utf-8")
    assert DUB.is_file() and "window.DMakerDub" in DUB.read_text(encoding="utf-8")
    assert html.index("/static/speech.js") < html.index("/static/dub.js") < html.index("/static/app.js")
    app_js = JS.read_text(encoding="utf-8")
    assert "DMakerDub.init" in app_js and "DMakerDub.onShow" in app_js


def test_index_has_the_dubbing_section_with_every_element_dub_js_uses():
    html = INDEX.read_text(encoding="utf-8")
    js = DUB.read_text(encoding="utf-8")
    used = set(re.findall(r'el\("(dub-[a-z-]+)"\)', js)) | set(re.findall(r'"(dub-[a-z-]+-progress)"', js))
    assert len(used) > 20
    for element_id in sorted(used):
        assert f'id="{element_id}"' in html, f"id {element_id!r} usado em dub.js não existe em index.html"
    assert "<legend>Dublar</legend>" in html
    assert "—" not in html and "—" not in js  # a marca não usa travessão em texto na tela


def test_dub_js_uses_the_dub_api_with_jobs_upload_and_project_ops():
    js = DUB.read_text(encoding="utf-8")
    for token in (
        "/api/speech/upload",
        "/api/dub/prepare",
        "/api/dub/project",
        "/api/dub/projects",
        "/api/dub/retranslate",
        "/api/dub/render",
        "/api/dub/stems",
        "DMakerVoice.followJob",
        "collectMediaEntries",
        "DMakerSpeech.pure.replaceSourceOps",
        "DMakerEditor.applyOp",
        "saveProject",
    ):
        assert token in js, f"{token!r} não encontrado em dub.js"
    css = CSS.read_text(encoding="utf-8")
    assert all(rule in css for rule in (".dub-row", ".dub-segments", ".dub-ab"))


def _run_dub_pure(expression: str):
    """Avalia `expression` com as funções puras de dub.js carregadas num `window` falso."""
    script = (
        "global.window = {};"
        f"require({json.dumps(str(DUB))});"
        "const pure = window.DMakerDub.pure;"
        f"console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@requires_node
def test_dub_glossary_is_split_trimmed_and_deduplicated():
    assert _run_dub_pure("pure.parseGlossary(' DMaker, medlycare\\nDMAKER ,, Ollama ')") == [
        "DMaker",
        "medlycare",
        "Ollama",
    ]
    assert _run_dub_pure("pure.parseGlossary('')") == []


@requires_node
def test_dub_keep_level_is_always_a_negative_db_or_null():
    assert _run_dub_pure("['', ' ', '-18', '18', '-6,5', 'abc', '0'].map(pure.parseKeepDb)") == [
        None,
        None,
        -18,
        -18,
        -6.5,
        None,
        0,
    ]


@requires_node
def test_dub_segment_rows_escape_text_and_mark_locked_segments():
    html = _run_dub_pure(
        "pure.segmentRowsHtml([{id:'s1',start:1.04,end:3.5,original:'a <b> & c',text:'x \"q\"',locked:true},"
        "{id:'s2',start:4,end:6,original:'o',text:'t',locked:false}])"
    )
    assert 'data-id="s1"' in html and "1.0 a 3.5 s" in html
    assert "a &lt;b&gt; &amp; c" in html and "&quot;q&quot;" in html and "<b>" not in html
    assert html.count("checked") == 1 and html.count("dub-row") == 2


@requires_node
def test_dub_edits_and_result_summary():
    edits = _run_dub_pure(
        "pure.segmentEdits([{id:'s1',text:'  Olá  ',locked:1},{id:'s2',text:null,locked:false}])"
    )
    assert edits == [{"id": "s1", "text": "Olá", "locked": True}, {"id": "s2", "text": "", "locked": False}]
    summary = _run_dub_pure("pure.describeResult({report:[1,2,3],regenerated:1,timings:{a:10.2,b:5}})")
    assert summary == "1 fala(s) sintetizada(s) agora e 2 reaproveitada(s) do cache, em 15 s."
    assert _run_dub_pure("['fits','squeezed','overflow','empty','x'].map(pure.statusLabel)") == [
        "cabe",
        "comprimida",
        "não coube",
        "sem tradução",
        "x",
    ]


@requires_node
def test_dub_stems_summary_names_the_files_and_the_original_voice_level():
    plain = _run_dub_pure("pure.describeStems({files:['a.wav','b.wav'],duration:40,original_voice_db:null})")
    assert plain == "Trilhas prontas (a.wav, b.wav), cada uma com 40.00 s."
    kept = _run_dub_pure("pure.describeStems({files:['a.wav'],duration:12.5,original_voice_db:-18})")
    assert "a voz original a -18 dB" in kept and "sem atenuar" in kept


@requires_node
def test_pronunciation_preview_phrase_follows_the_language_of_the_entry():
    assert (
        _run_voice_pure('pure.pronunciationPreviewText("DMaker", "en-US")') == "I say DMaker. Again: DMaker."
    )
    assert (
        _run_voice_pure('pure.pronunciationPreviewText("DMaker", "pt")') == "Eu falo DMaker. Repito: DMaker."
    )
    assert _run_voice_pure('pure.pronunciationPreviewText("DMaker")') == "Eu falo DMaker. Repito: DMaker."
