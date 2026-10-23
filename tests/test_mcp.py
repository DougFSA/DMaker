"""Servidor MCP: sobe por stdio e conversa com o cliente oficial."""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

from dmaker import config

from .conftest import requires_ffmpeg


async def _session(fn):
    # o servidor é outro processo: sem a pasta de dados do teste ele gravaria em projects/ e cache/ reais
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "dmaker.mcp_server"],
        cwd=str(config.ROOT),
        env={**get_default_environment(), "DMAKER_DATA_DIR": str(config.DATA_DIR)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _text(result) -> str:
    return "".join(c.text for c in result.content if getattr(c, "type", "") == "text")


def test_lists_tools_and_prompt():
    async def go(session):
        tools = await session.list_tools()
        prompts = await session.list_prompts()
        resources = await session.list_resources()
        return (
            {t.name for t in tools.tools},
            {p.name for p in prompts.prompts},
            {str(r.uri) for r in resources.resources},
        )

    tools, prompts, resources = asyncio.run(_session(go))
    assert {
        "dmaker_guide",
        "spec_schema",
        "presets",
        "probe_media",
        "save_project",
        "list_templates",
        "new_from_template",
        "validate_project",
        "render_project",
        "job_status",
        "contact_sheet",
        "qa_report",
        "frames",
        "fix_captions",
        "edit_project",
        "timeline_view",
        "list_voices",
        "clone_voice",
        "design_voice",
        "synthesize_speech",
        "pronunciation",
    } <= tools
    assert "editar-video" in prompts
    assert "dmaker://guide" in resources and "dmaker://schema" in resources


def test_presets_and_schema_tools():
    async def go(session):
        presets = await session.call_tool("presets", {"platform": "youtube"})
        schema = await session.call_tool("spec_schema", {})
        guide = await session.call_tool("dmaker_guide", {})
        return _text(presets), _text(schema), _text(guide)

    presets, schema, guide = asyncio.run(_session(go))
    assert "youtube/shorts" in presets and "instagram" not in presets
    assert "timeline" in json.loads(schema)["properties"]
    assert "spec" in guide.lower()


def test_save_and_validate_project_via_mcp(tmp_path):
    spec = {
        "output": {"preset": "instagram/stories"},
        "brand": "medlycare",
        "timeline": [{"type": "card", "title": "Teste via MCP", "duration": 2}],
        "audio": {"normalize": "off"},
    }

    async def go(session):
        saved = await session.call_tool("save_project", {"name": "mcp-teste", "spec": spec})
        validated = await session.call_tool("validate_project", {"name_or_path": "mcp-teste"})
        return _text(saved), _text(validated)

    saved, validated = asyncio.run(_session(go))
    assert "mcp-teste" in saved and json.loads(validated)["total_s"] == 2.0
    spec_path = config.PROJECTS_DIR / "mcp-teste" / "spec.json"
    assert spec_path.exists()
    spec_path.unlink()
    spec_path.parent.rmdir()


def test_list_templates_via_mcp():
    async def go(session):
        result = await session.call_tool("list_templates", {})
        return result.structured_content["result"]

    data = asyncio.run(_session(go))
    assert len(data) >= 4
    names = {t["name"] for t in data}
    assert "reel-medlycare-produto" in names
    produto = next(t for t in data if t["name"] == "reel-medlycare-produto")
    assert "prints" in produto["params"]
    assert produto["params"]["prints"]["required"] is True
    assert "titulo" in produto["summary"]


@requires_ffmpeg
def test_new_from_template_via_mcp(synthetic_media):
    params = {"prints": [str(synthetic_media["photo"])] * 2}

    async def go(session):
        created = await session.call_tool(
            "new_from_template",
            {"template": "reel-medlycare-produto", "name": "mcp-template-teste", "params": params},
        )
        return _text(created)

    created = json.loads(asyncio.run(_session(go)))
    assert created["name"] == "mcp-template-teste"
    assert created["total_s"] > 0

    spec_path = config.PROJECTS_DIR / "mcp-template-teste" / "spec.json"
    saved = json.loads(spec_path.read_text(encoding="utf-8"))
    assert saved["name"] == "mcp-template-teste"
    assert len(saved["timeline"]) == 4  # cartão + 2 prints + cartão de CTA
    spec_path.unlink()
    spec_path.parent.rmdir()


def test_new_from_template_missing_required_param_via_mcp():
    async def go(session):
        return await session.call_tool(
            "new_from_template",
            {"template": "reel-medlycare-produto", "name": "mcp-template-erro", "params": {}},
        )

    result = asyncio.run(_session(go))
    assert result.is_error
    assert "prints" in _text(result)


class _FakeUIClient:
    """Dublê de UIClient: nunca fala HTTP de verdade, só registra o que recebeu."""

    def __init__(self):
        self.base_url = "http://127.0.0.1:9"
        self.rendered = None
        self.exported = None

    def render(self, name, options):
        self.rendered = (name, options)
        return {"job_id": "abc123"}

    def export(self, name, presets):
        self.exported = (name, presets)
        return {"job_id": "abc123"}

    def job(self, job_id):
        return {"job_id": job_id, "status": "done", "result": {"output": "x.mp4"}}


class _FakeDispatcher:
    """Dispatcher que sempre "consegue" abrir a interface, sem subir nenhum processo de verdade."""

    def __init__(self):
        self.client = _FakeUIClient()
        self.opened: list[tuple[str, str]] = []

    def ensure_ui(self):
        return True

    def open_browser_if_needed(self, name, job_id):
        self.opened.append((name, job_id))


class _FailingDispatcher:
    """Simula a interface indisponível: ensure_ui() sempre lança, como o dispatcher de verdade faria
    se `dmaker ui` não conseguisse subir."""

    def ensure_ui(self):
        raise RuntimeError("interface indisponível (teste)")


def test_render_project_show_ui_false_keeps_local_job_behavior():
    # importado direto (não via stdio): o decorator @server.tool devolve a função original, chamável
    # como Python puro, o que evita depender de um subprocesso para testar o roteamento show_ui.
    import dmaker.mcp_server as mcp_server

    result = mcp_server.render_project("projeto-inexistente-xyz", show_ui=False, wait_seconds=5)
    assert "where" not in result
    assert result["status"] == "error" and "não encontrada" in result["error"]


def test_render_project_show_ui_true_falls_back_to_local_when_ui_unavailable(monkeypatch):
    import dmaker.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "_dispatcher", lambda: _FailingDispatcher())
    result = mcp_server.render_project("projeto-inexistente-xyz", show_ui=True, wait_seconds=5)
    assert "where" not in result  # caiu no job local de sempre, igual ao show_ui=False
    assert result["status"] == "error" and "não encontrada" in result["error"]


def test_render_project_show_ui_true_delegates_to_ui_when_available(monkeypatch):
    import dmaker.mcp_server as mcp_server

    fake = _FakeDispatcher()
    monkeypatch.setattr(mcp_server, "_dispatcher", lambda: fake)
    result = mcp_server.render_project("qualquer-projeto", show_ui=True, wait_seconds=5)
    assert result["where"] == "ui" and result["status"] == "done"
    assert result["url"] == "http://127.0.0.1:9/#project=qualquer-projeto&job=abc123"
    assert fake.client.rendered[0] == "qualquer-projeto"
    assert fake.opened == [("qualquer-projeto", "abc123")]


def test_export_project_show_ui_true_delegates_to_ui_when_available(monkeypatch):
    import dmaker.mcp_server as mcp_server

    fake = _FakeDispatcher()
    monkeypatch.setattr(mcp_server, "_dispatcher", lambda: fake)
    result = mcp_server.export_project(
        "qualquer-projeto", ["instagram/reels", "youtube/shorts"], show_ui=True, wait_seconds=5
    )
    assert result["where"] == "ui" and result["status"] == "done"
    assert fake.client.exported == ("qualquer-projeto", ["instagram/reels", "youtube/shorts"])


def test_export_project_show_ui_false_keeps_local_job_behavior():
    import dmaker.mcp_server as mcp_server

    result = mcp_server.export_project("projeto-inexistente-xyz", ["instagram/reels"], show_ui=False)
    assert "where" not in result
    assert result["status"] == "error"


def test_edit_project_and_timeline_view_via_mcp():
    spec = {
        "output": {"preset": "instagram/stories"},
        "timeline": [{"type": "card", "title": "Editar via MCP", "duration": 1.0}],
        "audio": {"normalize": "off"},
    }

    async def go(session):
        await session.call_tool("save_project", {"name": "mcp-edit-teste", "spec": spec})
        view = await session.call_tool("timeline_view", {"name": "mcp-edit-teste"})
        edited = await session.call_tool(
            "edit_project",
            {"name": "mcp-edit-teste", "op": {"type": "split", "index": 0, "at": 0.5}},
        )
        return _text(view), _text(edited)

    view, edited = asyncio.run(_session(go))
    view_data = json.loads(view)
    assert any(t["id"] == "V1" for t in view_data["tracks"])
    assert json.loads(edited)["total_s"] == 1.0  # dividir não muda a duração total

    spec_path = config.PROJECTS_DIR / "mcp-edit-teste" / "spec.json"
    saved = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(saved["timeline"]) == 2
    spec_path.unlink()
    spec_path.parent.rmdir()


def test_read_captions_compact_and_full():
    # direto (não via stdio), igual aos testes de render_project: evita subprocesso para checar o roteamento.
    import dmaker.mcp_server as mcp_server

    name = "mcp-captions-teste"
    project_dir = config.PROJECTS_DIR / name
    project_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "name": name,
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "card", "title": "Legendas via MCP", "duration": 1.0}],
        "captions": {"source": "auto"},
        "audio": {"normalize": "off"},
    }
    (project_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    data = {
        "language": "pt",
        "cues": [
            {
                "start": 0.0,
                "end": 0.8,
                "text": "oi tudo bem",
                "words": [
                    {"start": 0.0, "end": 0.3, "text": "oi", "probability": 0.95},
                    {"start": 0.3, "end": 0.6, "text": "tudo", "probability": 0.3},
                    {"start": 0.6, "end": 0.8, "text": "bem", "probability": 0.9},
                ],
            }
        ],
    }
    (project_dir / "captions.auto.json").write_text(json.dumps(data), encoding="utf-8")
    try:
        compact = mcp_server.read_captions(name)
        assert compact["digest"]["total_cues"] == 1
        assert any("baixa confiança" in reason for issue in compact["issues"] for reason in issue["reasons"])
        assert "hint" in compact

        full = mcp_server.read_captions(name, mode="full")
        assert full["cues"][0]["words"][1]["probability"] == 0.3
    finally:
        (project_dir / "captions.auto.json").unlink()
        (project_dir / "spec.json").unlink()
        project_dir.rmdir()


def test_qa_report_via_mcp():
    spec = {
        "output": {"preset": "instagram/stories"},
        "timeline": [{"type": "card", "title": "QA via MCP", "duration": 1.0}],
        "audio": {"normalize": "off"},
    }

    async def go(session):
        await session.call_tool("save_project", {"name": "mcp-qa-teste", "spec": spec})
        return await session.call_tool("qa_report", {"name_or_path": "mcp-qa-teste"})

    result = asyncio.run(_session(go))
    data = json.loads(_text(result))
    assert "Checagens feitas" in data["text"]
    assert data["project"] == "mcp-qa-teste"

    spec_path = config.PROJECTS_DIR / "mcp-qa-teste" / "spec.json"
    spec_path.unlink()
    spec_path.parent.rmdir()


class _FakeSynthesizer:
    engine_id = "fake-mcp"

    def __init__(self):
        self.texts: list[str] = []

    def synthesize(self, request):
        import numpy as np

        from dmaker.voice.synth import Speech

        self.texts.append(request.text)
        return Speech(np.zeros(int(0.5 * 24000), dtype=np.float32), 24000)


def test_voice_tools_with_temporary_library(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server
    from dmaker.voice.library import VoiceLibrary

    library = VoiceLibrary(tmp_path / "voices")
    monkeypatch.setattr(mcp_server, "_voice_library", lambda: library)

    presets = mcp_server.list_voices()
    assert [(v["id"], v["engine"], v["kind"]) for v in presets] == [
        ("dora", "kokoro", "preset"),
        ("alex", "kokoro", "preset"),
        ("santa", "kokoro", "preset"),
    ]
    created = mcp_server.design_voice("Locutora", gender="feminino", pitch="grave", brand="medlycare")
    assert created["id"] == "locutora" and created["instruct"] == "female, low pitch"
    assert mcp_server.design_voice("Locutor", instruct="male, elderly")["instruct"] == "male, elderly"

    stored = [v["id"] for v in mcp_server.list_voices() if v["kind"] != "preset"]
    assert stored == ["locutor", "locutora"]
    assert created["engine"] == "omnivoice"
    by_brand = [v["id"] for v in mcp_server.list_voices(brand="outra") if v["kind"] != "preset"]
    assert by_brand == ["locutor"]


def test_synthesize_speech_runs_as_a_job(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server
    from dmaker.media.ffmpeg import RecordingRunner
    from dmaker.voice.library import VoiceLibrary

    library = VoiceLibrary(tmp_path / "voices")
    library.save_design("Locutora", "female")
    fake = _FakeSynthesizer()
    out = tmp_path / "narracao.wav"
    runner = RecordingRunner(on_run=lambda command: out.write_bytes(b"audio"))
    monkeypatch.setattr(mcp_server, "_voice_library", lambda: library)
    monkeypatch.setattr(mcp_server, "_voice_synthesizer", lambda: fake)
    monkeypatch.setattr("dmaker.pipeline.voices.SubprocessRunner", lambda quiet=True: runner)
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "cache")

    started = mcp_server.synthesize_speech(
        "Esta é a primeira frase longa. Esta é a segunda frase longa.",
        out=str(out),
        voice="locutora",
        srt=True,
    )
    assert started["job_id"]
    job = mcp_server.jobs.get(started["job_id"])
    mcp_server.jobs.wait(job, 30)

    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "done", status.get("error")
    assert status["result"]["output"] == str(out)
    assert [c["text"] for c in status["result"]["cues"]] == [
        "Esta é a primeira frase longa.",
        "Esta é a segunda frase longa.",
    ]
    assert status["progress"]["label"] == "fala 2 de 2"
    assert fake.texts == ["Esta é a primeira frase longa.", "Esta é a segunda frase longa."]


def test_synthesize_speech_rejects_unknown_voice_immediately(monkeypatch, tmp_path):
    import pytest

    import dmaker.mcp_server as mcp_server
    from dmaker.voice.library import VoiceLibrary, VoiceNotFoundError

    monkeypatch.setattr(mcp_server, "_voice_library", lambda: VoiceLibrary(tmp_path))
    with pytest.raises(VoiceNotFoundError, match="fantasma"):
        mcp_server.synthesize_speech("Oi.", voice="fantasma")


def test_pronunciation_tool_lists_adds_and_removes_by_scope(monkeypatch, tmp_path):
    import pytest

    import dmaker.mcp_server as mcp_server
    from dmaker.voice.lexicon_store import LexiconStore

    (tmp_path / "brands" / "medlycare").mkdir(parents=True)
    store = LexiconStore(tmp_path)
    monkeypatch.setattr(mcp_server, "_lexicon_store", lambda: store)

    assert mcp_server.pronunciation("list") == {
        "scope": "global",
        "language": "pt",
        "entries": {},
        "effective": {},
        "languages": [],
    }
    mcp_server.pronunciation("add", term="DMaker", spoken="Di Meiker")
    branded = mcp_server.pronunciation("add", term="DMaker", spoken="Dimêiker", brand="medlycare")
    assert branded == {
        "scope": "medlycare",
        "language": "pt",
        "entries": {"DMaker": "Dimêiker"},
        "effective": {"DMaker": "Dimêiker"},
        "languages": ["pt"],
    }
    assert mcp_server.pronunciation("list")["entries"] == {"DMaker": "Di Meiker"}

    removed = mcp_server.pronunciation("remove", term="DMaker", brand="medlycare")
    assert removed["entries"] == {} and removed["effective"] == {"DMaker": "Di Meiker"}

    with pytest.raises(ValueError, match="term e spoken"):
        mcp_server.pronunciation("add", term="DMaker")
    with pytest.raises(ValueError, match="term"):
        mcp_server.pronunciation("remove")
    with pytest.raises(ValueError, match="não está no dicionário"):
        mcp_server.pronunciation("remove", term="fantasma")


def test_synthesize_speech_uses_the_pronunciation_of_the_brand(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server
    from dmaker.media.ffmpeg import RecordingRunner
    from dmaker.voice.lexicon_store import LexiconStore
    from dmaker.voice.library import VoiceLibrary

    (tmp_path / "brands" / "medlycare").mkdir(parents=True)
    store = LexiconStore(tmp_path)
    store.add("DMaker", "Di Meiker")
    store.add("MedlyCare", "Médli Quér", brand="medlycare")
    fake = _FakeSynthesizer()
    out = tmp_path / "narracao.wav"
    runner = RecordingRunner(on_run=lambda command: out.write_bytes(b"audio"))
    monkeypatch.setattr(mcp_server, "_lexicon_store", lambda: store)
    monkeypatch.setattr(mcp_server, "_voice_library", lambda: VoiceLibrary(tmp_path / "voices"))
    monkeypatch.setattr(mcp_server, "_voice_synthesizer", lambda: fake)
    monkeypatch.setattr("dmaker.pipeline.voices.SubprocessRunner", lambda quiet=True: runner)
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "cache")

    started = mcp_server.synthesize_speech(
        "O DMaker é da MedlyCare. Veja [[Samanta|Samanta]] aqui.", out=str(out), brand="medlycare"
    )
    job = mcp_server.jobs.get(started["job_id"])
    mcp_server.jobs.wait(job, 30)

    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "done", status.get("error")
    assert fake.texts == ["O Di Meiker é da Médli Quér.", "Veja Samanta aqui."]
    assert [c["text"] for c in status["result"]["cues"]] == [
        "O DMaker é da MedlyCare.",
        "Veja Samanta aqui.",
    ]


def test_pronunciation_tool_is_scoped_by_language(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server
    from dmaker.voice.lexicon_store import LexiconStore

    store = LexiconStore(tmp_path)
    monkeypatch.setattr(mcp_server, "_lexicon_store", lambda: store)

    mcp_server.pronunciation("add", term="DMaker", spoken="Di Mêiker")  # padrão: pt
    english = mcp_server.pronunciation("add", term="MedlyCare", spoken="Medly Care", language="en-US")

    assert english["language"] == "en" and english["entries"] == {"MedlyCare": "Medly Care"}
    assert english["languages"] == ["en", "pt"]
    assert mcp_server.pronunciation("list")["effective"] == {"DMaker": "Di Mêiker"}
    assert mcp_server.pronunciation("list", language="es")["effective"] == {}

    mcp_server.pronunciation("remove", term="medlycare", language="en")
    assert mcp_server.pronunciation("list", language="en")["entries"] == {}


def test_synthesize_speech_in_english_does_not_use_the_portuguese_pronunciation(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server
    from dmaker.media.ffmpeg import RecordingRunner
    from dmaker.voice.lexicon_store import LexiconStore
    from dmaker.voice.library import VoiceLibrary

    store = LexiconStore(tmp_path)
    store.add("DMaker", "Di Mêiker")
    fake = _FakeSynthesizer()
    out = tmp_path / "narracao.wav"
    runner = RecordingRunner(on_run=lambda command: out.write_bytes(b"audio"))
    monkeypatch.setattr(mcp_server, "_lexicon_store", lambda: store)
    monkeypatch.setattr(mcp_server, "_voice_library", lambda: VoiceLibrary(tmp_path / "voices"))
    monkeypatch.setattr(mcp_server, "_voice_synthesizer", lambda: fake)
    monkeypatch.setattr("dmaker.pipeline.voices.SubprocessRunner", lambda quiet=True: runner)
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "cache")

    started = mcp_server.synthesize_speech("Meet the DMaker app today.", out=str(out), language="en")
    mcp_server.jobs.wait(mcp_server.jobs.get(started["job_id"]), 30)

    assert mcp_server.job_status(started["job_id"])["status"] == "done"
    assert fake.texts == ["Meet the DMaker app today."]
