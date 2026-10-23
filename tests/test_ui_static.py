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
QUEUE = STATIC_DIR / "queue.js"

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
    QUEUE,
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


# ---------- trocar voz (speech.js) ----------


def test_index_has_the_voice_swap_section_with_every_element_speech_js_uses():
    html = INDEX.read_text(encoding="utf-8")
    js = SPEECH.read_text(encoding="utf-8")
    used = set(re.findall(r'el\("(speech-conv-[a-z-]+)"\)', js)) | set(
        re.findall(r'"(speech-conv-[a-z-]+)"', js)
    )
    assert len(used) >= 15
    for element_id in sorted(used):
        assert f'id="{element_id}"' in html, f"id {element_id!r} usado em speech.js não existe em index.html"
    assert "<legend>Trocar voz</legend>" in html
    assert "/api/speech/convert" in js
    assert "—" not in html and "—" not in js  # a marca não usa travessão em texto na tela


@requires_node
def test_voice_swap_summary_says_what_was_converted_and_how_the_volume_changed():
    whole = _run_speech_pure(
        "pure.describeConversion({voice:'dora',seconds:30,blocks:2,gain_db:-3.04,excerpt:false})"
    )
    assert (
        whole
        == "Arquivo convertido para a voz dora: 30.0 s em 2 bloco(s); volume desceu 3.0 dB para igualar ao original."
    )
    excerpt = _run_speech_pure(
        "pure.describeConversion({voice:'alex',seconds:20,blocks:1,gain_db:0.01,excerpt:true})"
    )
    assert excerpt.startswith("Trecho convertido para a voz alex") and "volume igual ao original" in excerpt


@requires_node
def test_voice_swap_only_replaces_the_original_in_the_project_when_the_whole_file_was_converted():
    assert _run_speech_pure("pure.canUseConversion({entry:{src:'a.mp4'},excerpt:false})") is True
    assert _run_speech_pure("pure.canUseConversion({entry:{src:'a.mp4'},excerpt:true})") is False
    assert _run_speech_pure("pure.canUseConversion({entry:null,excerpt:false})") is False
    assert _run_speech_pure("pure.canUseConversion(null)") is False


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
def test_pronunciation_preview_phrase_follows_the_language_of_the_entry():
    assert (
        _run_voice_pure('pure.pronunciationPreviewText("DMaker", "en-US")') == "I say DMaker. Again: DMaker."
    )
    assert (
        _run_voice_pure('pure.pronunciationPreviewText("DMaker", "pt")') == "Eu falo DMaker. Repito: DMaker."
    )
    assert _run_voice_pure('pure.pronunciationPreviewText("DMaker")') == "Eu falo DMaker. Repito: DMaker."


@requires_node
def test_dub_table_shows_a_speaker_select_only_when_the_project_has_two_or_more():
    segments = "[{id:'s1',start:1,end:3,original:'a',text:'b',locked:false,speaker:'Falante 2'},{id:'s2',start:4,end:6,original:'o',text:'t',locked:false,speaker:null}]"
    alone = _run_dub_pure(f"pure.segmentRowsHtml({segments}, ['Falante 1'])")
    assert "dub-speaker-pick" not in alone
    shared = _run_dub_pure(f"pure.segmentRowsHtml({segments}, ['Falante 1', 'Falante <2>'])")
    assert shared.count("dub-speaker-pick") == 2 and "Falante &lt;2&gt;" in shared
    first, second = shared.split('data-id="s2"')
    assert '<option value="Falante 1">' in first and '<option value="Falante 1" selected>' not in first
    assert "Sem falante" not in first and "Sem falante" in second  # fala sem falante ainda deixa escolher


@requires_node
def test_dub_edits_carry_the_speaker_only_when_one_is_chosen_and_the_count_is_a_small_integer():
    edits = _run_dub_pure(
        "pure.segmentEdits([{id:'s1',text:'a',locked:false,speaker:'Falante 2'},{id:'s2',text:'b',locked:false,speaker:null}])"
    )
    assert edits == [
        {"id": "s1", "text": "a", "locked": False, "speaker": "Falante 2"},
        {"id": "s2", "text": "b", "locked": False},
    ]
    assert _run_dub_pure("['', ' 3 ', '2', '0', '13', '1,5', 'dois', '-1'].map(pure.parseSpeakerCount)") == [
        None,
        3,
        2,
        None,
        None,
        None,
        None,
        None,
    ]


def test_the_dub_form_offers_the_per_speaker_mode_first_and_a_speaker_count():
    html = INDEX.read_text(encoding="utf-8")
    select = html[html.index('id="dub-speaker"') : html.index("</select>", html.index('id="dub-speaker"'))]
    assert (
        select.index('value="per_speaker"')
        < select.index('value="per_segment"')
        < select.index('value="single"')
    )
    assert 'id="dub-speaker-count"' in html and 'id="dub-speaker-count-field"' in html
    css = CSS.read_text(encoding="utf-8")
    assert ".dub-with-speakers .dub-row" in css and ".dub-speaker-pick" in css and ".dub-who" in css


# ---------- fila de narrações (queue.js) ----------


def test_queue_file_is_referenced_after_voice_js_and_before_app_js():
    html = INDEX.read_text(encoding="utf-8")
    assert QUEUE.is_file() and "window.DMakerQueue" in QUEUE.read_text(encoding="utf-8")
    assert html.index("/static/voice.js") < html.index("/static/queue.js") < html.index("/static/app.js")
    app_js = JS.read_text(encoding="utf-8")
    for hook in ("DMakerQueue.init", "DMakerQueue.onShow", "DMakerQueue.onHide"):
        assert hook in app_js


def test_index_has_the_queue_section_with_every_element_queue_js_uses():
    html = INDEX.read_text(encoding="utf-8")
    js = QUEUE.read_text(encoding="utf-8")
    used = set(re.findall(r'el\("((?:voice-queue|voice-enqueue)[a-z-]*)"\)', js)) | {"voice-script"}
    assert {"voice-queue-list", "voice-queue-summary", "voice-queue-file", "voice-enqueue"} <= used
    for element_id in sorted(used):
        assert f'id="{element_id}"' in html, f"id {element_id!r} usado em queue.js não existe em index.html"
    assert "<legend>Fila de narrações</legend>" in html and "Mandar para a fila" in html
    assert "—" not in html and "—" not in js  # a marca não usa travessão em texto na tela


def test_queue_js_uses_the_queue_api_with_sse_upload_and_every_command():
    js = QUEUE.read_text(encoding="utf-8")
    for token in (
        "/api/voices/queue",
        "/api/voices/queue/events",
        "/api/voices/queue/upload",
        "EventSource",
        "FormData",
        "/move",
        "clear-finished",
        "data-queue-action",
    ):
        assert token in js, f"{token!r} não encontrado em queue.js"
    for state in ("pending", "running", "paused", "done", "failed", "cancelled"):
        assert f"{state}:" in js, f"estado {state!r} sem botões definidos"
    assert all(rule in CSS.read_text(encoding="utf-8") for rule in (".queue-file", ".queue-state-running"))


def test_every_queue_endpoint_called_by_queue_js_exists_on_the_server():
    from dmaker.ui.queue_routes import build_queue_router

    js = QUEUE.read_text(encoding="utf-8")
    paths = {route.path for route in build_queue_router().routes}
    for needed in (
        "/api/voices/queue",
        "/api/voices/queue/events",
        "/api/voices/queue/upload",
        "/api/voices/queue/clear-finished",
        "/api/voices/queue/{item_id}/move",
        "/api/voices/queue/{item_id}",
    ):
        assert needed in paths, needed
    # as ações dos botões viram o último trecho do caminho: precisam existir como rotas POST
    for action in ("pause", "resume", "cancel", "retry"):
        assert f"/api/voices/queue/{{item_id}}/{action}" in paths and action in js


def _run_queue_pure(expression: str):
    """Avalia `expression` com as funções puras de queue.js carregadas num `window` falso."""
    script = (
        "global.window = {};"
        f"require({json.dumps(str(QUEUE))});"
        "const pure = window.DMakerQueue.pure;"
        f"console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@requires_node
def test_queue_actions_follow_the_state_of_the_item():
    assert _run_queue_pure("pure.actionsFor('running')") == ["pause", "cancel"]
    assert _run_queue_pure("pure.actionsFor('pending')") == ["pause", "cancel", "up", "down"]
    assert _run_queue_pure("pure.actionsFor('paused')") == ["resume", "cancel", "up", "down"]
    assert _run_queue_pure("pure.actionsFor('failed')") == ["retry", "remove"]
    assert _run_queue_pure("pure.actionsFor('done')") == ["remove"]
    assert _run_queue_pure("pure.actionsFor('inexistente')") == []


@requires_node
def test_queue_progress_line_names_chapter_utterance_and_time_left():
    running = "{state:'running',chapter:2,chapters_total:5,utterance:12,utterances:40,percent:30,eta_label:'25 min'}"
    assert _run_queue_pure(f"pure.describeProgress({running})") == (
        "capítulo 2 de 5, fala 12 de 40 · faltam cerca de 25 min"
    )
    one = "{state:'running',chapter:1,chapters_total:1,utterance:3,utterances:9,eta_label:null}"
    assert _run_queue_pure(f"pure.describeProgress({one})") == "fala 3 de 9"
    waiting = "{state:'pending',chapters_total:3,eta_label:'2 h 05 min'}"
    assert _run_queue_pure(f"pure.describeProgress({waiting})") == (
        "Aguardando a vez · 3 capítulos · faltam cerca de 2 h 05 min"
    )
    done = "{state:'done',chapters_total:1,duration_s:125}"
    assert _run_queue_pure(f"pure.describeProgress({done})") == "Pronto · 1 capítulo · 2 min de áudio"
    failed = "{state:'failed',error:'ValueError: voz inexistente\\nTraceback...'}"
    assert _run_queue_pure(f"pure.describeProgress({failed})") == "voz inexistente"
    assert _run_queue_pure("pure.describeProgress({state:'paused',percent:40,chapters_total:2})") == (
        "Pausado em 40% · 2 capítulos"
    )


@requires_node
def test_queue_summary_and_file_links_escape_and_explain():
    assert _run_queue_pure("pure.queueSummary({items:[]})") == "A fila está vazia."
    busy = "{items:[{state:'pending'},{state:'done'}],eta_label:'10 min',running:false,worker:false}"
    summary = _run_queue_pure(f"pure.queueSummary({busy})")
    assert summary.startswith("2 itens · tempo estimado para esvaziar: 10 min · nenhum executor ativo")
    working = "{items:[{state:'running'}],eta_label:'1 min',running:true,worker:false}"
    assert _run_queue_pure(f"pure.queueSummary({working})") == "1 item · tempo estimado para esvaziar: 1 min"

    links = _run_queue_pure(
        "pure.fileLinks([{name:'<b>.wav',url:'/api/x/%3Cb%3E.wav',audio:true},{name:'a.srt',url:'/a.srt',audio:false}])"
    )
    assert "&lt;b&gt;.wav" in links and "<b>.wav" not in links
    assert links.count("Ouvir") == 1 and links.count("Baixar") == 2  # a legenda só baixa
    assert "/a.srt?download=true" in links


@requires_node
def test_queue_text_body_matches_the_server_contract():
    body = _run_queue_pure(
        "pure.textBody({text:'Oi',voice:'',language:'',speed:1.2,brand:'',draft:true,format:'mp3',title:'  Meu  '})"
    )
    assert body == {
        "text": "Oi",
        "voice": None,
        "language": None,
        "speed": 1.2,
        "brand": None,
        "draft": True,
        "format": "mp3",
        "title": "Meu",
    }
    bare = _run_queue_pure("pure.textBody({text:'Oi',speed:1})")
    assert "title" not in bare and bare["format"] == "wav" and bare["draft"] is False

    from dmaker.ui.queue_routes import QueueTextRequest

    QueueTextRequest.model_validate(body)  # o corpo que a tela monta é aceito pelo servidor


def test_voice_studio_has_live_preview_and_stop_wired_to_the_job_api():
    html = INDEX.read_text(encoding="utf-8")
    for element_id in ("voice-stop", "voice-live", "voice-live-status", "voice-live-mute"):
        assert f'id="{element_id}"' in html, f"id {element_id!r} não encontrado em index.html"
    assert "fala crua" in html and "acabamento" in html  # avisa que a prévia não tem o acabamento final
    # a prévia fica fora do bloco de progresso: ele some quando o job acaba, e o áudio ainda toca depois
    before_live = html[html.index('id="voice-progress"') : html.index('id="voice-live"')]
    assert before_live.count("<div") == before_live.count("</div>")
    js = VOICE.read_text(encoding="utf-8")
    for token in ('"utterance"', "/cancel", "decodeAudioData", "createLivePlayer", "cancelled"):
        assert token in js, f"{token!r} não encontrado em voice.js"
    assert "—" not in html and "—" not in js  # sem travessão em texto de tela


FAKE_AUDIO_CONTEXT = """
class Param {
  constructor() { this.events = []; this.value = 1; }
  setValueAtTime(value, time) { this.events.push(["set", value, time]); return this; }
  linearRampToValueAtTime(value, time) { this.events.push(["ramp", value, time]); return this; }
  cancelScheduledValues() { return this; }
}
function fakeContext(startTime) {
  const ctx = { currentTime: startTime, destination: {}, gains: [], sources: [] };
  ctx.createGain = () => {
    const node = { gain: new Param(), connect() {}, disconnect() {} };
    ctx.gains.push(node);
    return node;
  };
  ctx.createBufferSource = () => {
    const source = { buffer: null, connect() {}, start(when) { this.startedAt = when; },
                     stop(when) { this.stoppedAt = when; } };
    ctx.sources.push(source);
    return source;
  };
  ctx.decodeAudioData = async (bytes) => ({ duration: bytes.duration });
  return ctx;
}
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
"""


def _run_voice_script(body: str):
    """Roda `body` (que define `result`) com voice.js carregado e um AudioContext falso que só registra."""
    script = (
        "global.window = {};"
        f"require({json.dumps(str(VOICE))});"
        "const pure = window.DMakerVoice.pure;"
        f"{FAKE_AUDIO_CONTEXT}"
        f"(async () => {{ let result; {body}; console.log(JSON.stringify(result)); }})();"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@requires_node
def test_live_plan_chains_each_utterance_right_after_the_previous_one_plus_the_script_pause():
    plans = _run_voice_script(
        """
        let cursor = null; const out = [];
        for (const [duration, pause] of [[1.0, 0.35], [2.0, 0.7], [0.5, 0]]) {
          const plan = pure.planLiveChunk(cursor, 10, duration, pause);
          out.push(plan); cursor = plan.nextCursor;
        }
        result = out;
        """
    )
    starts = [round(p["startAt"], 6) for p in plans]
    assert starts == [10.06, 11.41, 14.11]  # fala 1 + 0,35 s de pausa, fala 2 + 0,7 s de pausa
    assert [round(p["endAt"] - p["startAt"], 6) for p in plans] == [1.0, 2.0, 0.5]
    assert round(plans[1]["startAt"] - plans[0]["endAt"], 6) == 0.35  # a pausa do roteiro, ao centésimo
    assert [p["late"] for p in plans] == [False, False, False]


@requires_node
def test_live_plan_flags_a_late_utterance_and_never_schedules_it_in_the_past():
    late = _run_voice_script("result = pure.planLiveChunk(12.0, 20.0, 1.0, 0.35)")
    assert late["late"] is True and late["startAt"] == pytest.approx(20.06)
    on_time = _run_voice_script("result = pure.planLiveChunk(20.02, 20.0, 1.0, 0)")
    assert on_time["late"] is False and on_time["startAt"] == pytest.approx(
        20.02
    )  # dentro da folga: mantém a emenda


@requires_node
def test_live_plan_fade_is_5ms_but_never_more_than_half_of_a_very_short_utterance():
    fades = _run_voice_script(
        "result = [pure.planLiveChunk(null, 0, 1.0, 0).fade, pure.planLiveChunk(null, 0, 0.004, 0).fade]"
    )
    assert fades == [0.005, 0.002]


@requires_node
def test_live_player_schedules_in_arrival_order_with_a_fade_on_both_ends_of_each_utterance():
    result = _run_voice_script(
        """
        const ctx = fakeContext(10);
        const bytes = { a: { duration: 1.0 }, b: { duration: 2.0 } };
        const slowFirst = async (url) => { if (url === "a") await wait(40); return bytes[url]; };
        const player = pure.createLivePlayer(ctx, slowFirst);
        player.enqueue({ index: 1, url: "a", pauseAfter: 0.35 });
        await player.enqueue({ index: 2, url: "b", pauseAfter: 0 });  // a 1ª demora mais para decodificar
        const chunkGain = ctx.gains[1];  // ctx.gains[0] é o ganho geral
        result = {
          starts: ctx.sources.map((s) => Number(s.startedAt.toFixed(6))),
          indexes: player.plans.map((p) => p.index),
          firstEvents: chunkGain.gain.events.map(([kind, value, time]) => [kind, value, Number(time.toFixed(6))]),
        };
        """
    )
    assert result["indexes"] == [1, 2] and result["starts"] == [10.06, 11.41]
    assert result["firstEvents"] == [
        ["set", 0, 10.06],
        ["ramp", 1, 10.065],
        ["set", 1, 11.055],
        ["ramp", 0, 11.06],
    ]


@requires_node
def test_live_player_stop_ramps_to_silence_and_ignores_utterances_that_arrive_later():
    result = _run_voice_script(
        """
        const ctx = fakeContext(5);
        const player = pure.createLivePlayer(ctx, async () => ({ duration: 1.0 }));
        await player.enqueue({ index: 1, url: "a", pauseAfter: 0 });
        player.stop();
        await player.enqueue({ index: 2, url: "b", pauseAfter: 0 });
        result = {
          scheduled: ctx.sources.length,
          stoppedAt: ctx.sources[0].stoppedAt,
          masterEvents: ctx.gains[0].gain.events,
        };
        """
    )
    assert result["scheduled"] == 1  # a fala 2 chegou depois do Parar e não foi agendada
    assert result["stoppedAt"] == pytest.approx(5.025)
    assert ["ramp", 0, pytest.approx(5.02)] in result["masterEvents"]


@requires_node
def test_live_player_reports_load_errors_without_breaking_the_next_utterances():
    result = _run_voice_script(
        """
        const ctx = fakeContext(0);
        const errors = [];
        const loader = async (url) => { if (url === "ruim") throw new Error("falhou"); return { duration: 1.0 }; };
        const player = pure.createLivePlayer(ctx, loader, (err) => errors.push(err.message));
        player.enqueue({ index: 1, url: "ruim", pauseAfter: 0 });
        await player.enqueue({ index: 2, url: "boa", pauseAfter: 0 });
        result = { errors, indexes: player.plans.map((p) => p.index) };
        """
    )
    assert result == {"errors": ["falhou"], "indexes": [2]}


@requires_node
def test_live_status_follows_what_is_playing_and_what_is_still_being_generated():
    result = _run_voice_script(
        """
        const plans = [{ index: 1, nextCursor: 11.4 }, { index: 2, nextCursor: 14.0 }];
        result = {
          playing: [9, 10.5, 11.4, 13.9, 14.0].map((t) => pure.playingIndexAt(plans, t)),
          none: pure.playingIndexAt([], 3),
          texts: [
            pure.liveStatusText({ total: 5, ready: 0, playing: null, stoppedAfter: null }),
            pure.liveStatusText({ total: 5, ready: 2, playing: 1, stoppedAfter: null }),
            pure.liveStatusText({ total: 5, ready: 5, playing: 4, stoppedAfter: null }),
            pure.liveStatusText({ total: 5, ready: 2, playing: null, stoppedAfter: null }),
            pure.liveStatusText({ total: 5, ready: 5, playing: null, stoppedAfter: null }),
            pure.liveStatusText({ total: 5, ready: 3, playing: 2, stoppedAfter: 3 }),
          ],
        };
        """
    )
    assert result["playing"] == [1, 1, 2, 2, None] and result["none"] is None
    assert result["texts"] == [
        "Esperando a primeira fala ficar pronta...",
        "Tocando fala 1 de 5 · 2 prontas",
        "Tocando fala 4 de 5",
        "Esperando a fala 3 de 5 ficar pronta...",
        "Prévia ao vivo terminada.",
        "Parado depois da fala 3 de 5. O que já saiu ficou guardado.",
    ]


def _run_timeline_pure(expression: str):
    """Avalia `expression` com as funções puras da linha do tempo carregadas num `window` falso."""
    script = (
        "global.window = {};"
        f"require({json.dumps(str(TIMELINE))});"
        "const tl = window.DMakerTimeline;"
        f"console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@requires_node
def test_timeline_narration_blocks_drag_whole_but_have_no_trim_handles():
    item = '{kind: "narration", index: 1}'
    assert _run_timeline_pure(f'tl.isDraggable("NAR", {item})') is True
    assert _run_timeline_pure(f'tl.hasTrimHandles("NAR", {item})') is False
    assert _run_timeline_pure('tl.hasTrimHandles("V1", {kind: "clip"})') is True
    assert _run_timeline_pure('tl.isDraggable("A1", {kind: "clip-audio"})') is False


@requires_node
def test_timeline_narration_drag_becomes_a_set_field_on_its_own_start():
    assert _run_timeline_pure("tl.narrationMoveOp({index: 2}, 3.14159)") == {
        "type": "set_field",
        "path": "audio.narration.2.start",
        "value": 3.142,
    }
    assert _run_timeline_pure("tl.narrationMoveOp({index: 0}, -0.4)")["value"] == 0


@requires_node
def test_timeline_narration_title_tells_real_from_estimated_duration():
    real = '{kind: "narration", label: "Olá", start: 1, end: 3.25, extra: {estimated: false}}'
    guess = '{kind: "narration", label: "Olá", start: 1, end: 6, extra: {estimated: true}}'
    assert _run_timeline_pure(f"tl.itemTitle({real})") == "Olá (duração real: 2,3 s)"
    assert _run_timeline_pure(f"tl.itemTitle({guess})") == "Olá (duração estimada: 5,0 s)"
    assert _run_timeline_pure('tl.itemTitle({kind: "clip", label: "a.mp4"})') == "a.mp4"


def test_timeline_styles_dashed_border_for_estimated_narration():
    css = CSS.read_text(encoding="utf-8")
    assert ".tl-item-narration" in css and ".tl-item-narration.tl-item-estimated" in css
    assert "tl-item-estimated" in TIMELINE.read_text(encoding="utf-8")
