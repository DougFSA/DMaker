"""Proxies 540p H.264 para a prévia ao vivo: grafo puro, caminho de cache, resolução de fontes,
`ProxyBuilder` com dependências falsas e a API da interface."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.filtergraph.proxy import PROXY_HEIGHT, proxy_command
from dmaker.media.ffmpeg import FFmpegCommand, FFmpegError, RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import proxies as proxies_module
from dmaker.pipeline.proxies import ProxyBuilder, ProxyStatus, project_video_sources, proxy_path
from dmaker.ui import server


def _info(w=1920, h=1080, dur=10.0, audio=True) -> MediaInfo:
    return MediaInfo(Path("x.mp4"), dur, w, h, 30.0, True, audio, False)


# ---------- filtergraph/proxy.py (puro) ----------


def test_proxy_command_scales_large_source():
    cmd = proxy_command(Path("in.mp4"), Path("out.mp4"), _info(1920, 1080))
    assert isinstance(cmd, FFmpegCommand)
    assert "-vf" in cmd.args
    assert cmd.args[cmd.args.index("-vf") + 1] == f"scale=-2:{PROXY_HEIGHT}"
    assert "-i" in cmd.args and cmd.args[cmd.args.index("-i") + 1] == "in.mp4"
    assert cmd.args[-1] == "out.mp4"
    assert ["-c:v", "libx264"] == cmd.args[cmd.args.index("-c:v") : cmd.args.index("-c:v") + 2]
    assert "-preset" in cmd.args and cmd.args[cmd.args.index("-preset") + 1] == "ultrafast"
    assert "-crf" in cmd.args and cmd.args[cmd.args.index("-crf") + 1] == "26"
    assert "-pix_fmt" in cmd.args and cmd.args[cmd.args.index("-pix_fmt") + 1] == "yuv420p"
    assert "-movflags" in cmd.args and cmd.args[cmd.args.index("-movflags") + 1] == "+faststart"
    assert cmd.total == 10.0


def test_proxy_command_keeps_audio_settings_when_present():
    cmd = proxy_command(Path("in.mp4"), Path("out.mp4"), _info(audio=True))
    assert "-c:a" in cmd.args and cmd.args[cmd.args.index("-c:a") + 1] == "aac"
    assert cmd.args[cmd.args.index("-b:a") + 1] == "96k"
    assert cmd.args[cmd.args.index("-ac") + 1] == "2"
    assert cmd.args[cmd.args.index("-ar") + 1] == "48000"
    assert "-an" not in cmd.args


def test_proxy_command_no_audio_track_when_source_is_mute():
    cmd = proxy_command(Path("in.mp4"), Path("out.mp4"), _info(audio=False))
    assert "-an" in cmd.args
    assert "-c:a" not in cmd.args


@pytest.mark.parametrize("height", [540, 480, 360])
def test_proxy_command_no_scale_when_already_small_enough(height):
    cmd = proxy_command(Path("in.mp4"), Path("out.mp4"), _info(h=height))
    assert "-vf" not in cmd.args


# ---------- pipeline/proxies.py: proxy_path ----------


def test_proxy_path_is_stable_and_lives_in_cache(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"conteudo")
    first = proxy_path(src)
    assert proxy_path(src) == first
    assert first.parent == config.PROXY_DIR
    assert first.suffix == ".mp4"


def test_proxy_path_changes_when_source_changes(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"conteudo")
    before = proxy_path(src)
    future = time.time() + 5
    os.utime(src, (future, future))
    after = proxy_path(src)
    assert before != after


# ---------- pipeline/proxies.py: project_video_sources ----------


def _project(
    tmp_path: Path, timeline: list, overlays: list | None = None, sources: dict | None = None
) -> Project:
    project = Project.model_validate(
        {"name": "px", "timeline": timeline, "overlays": overlays or [], "sources": sources or {}}
    )
    project.base_dir = tmp_path
    return project


def test_project_video_sources_dedupes_resolves_and_ignores_non_video(tmp_path):
    project = _project(
        tmp_path,
        timeline=[
            {"type": "clip", "src": "video.mp4"},
            {"type": "clip", "src": "video.mp4"},  # duplicado: não repete
            {"type": "clip", "src": "cena.gif"},  # não é extensão de vídeo
            {"type": "clip", "source": "cam1"},
            {"type": "image", "src": "foto.jpg", "duration": 2},  # imagem: ignorada
            {"type": "card", "title": "Abertura", "duration": 2},  # cartão: ignorado
        ],
        overlays=[
            {"type": "video", "src": "pip.mp4"},
            {"type": "video", "source": "cam1"},  # mesma fonte do clipe: não repete
            {"type": "progress-bar"},
        ],
        sources={"cam1": {"src": "cam1.mov"}},
    )
    result = project_video_sources(project)
    assert sorted(p.name for p in result) == ["cam1.mov", "pip.mp4", "video.mp4"]
    assert len(result) == 3  # sem duplicatas
    assert all(p.parent == tmp_path.resolve() for p in result)  # resolvidos pelo base_dir


def test_project_video_sources_includes_every_part_of_a_source_with_parts(tmp_path):
    """O trecho pode cair em qualquer parte e a prévia toca a que grava o instante: todas ganham proxy."""
    project = _project(
        tmp_path,
        timeline=[{"type": "clip", "source": "cam1"}],
        overlays=[{"type": "video", "source": "cam1"}],  # a mesma fonte no PiP: sem repetir as partes
        sources={"cam1": {"parts": ["cam1_a.mp4", "cam1_b.mp4", "cam1_c.mp4"]}},
    )
    result = project_video_sources(project)
    assert [p.name for p in result] == ["cam1_a.mp4", "cam1_b.mp4", "cam1_c.mp4"]


# ---------- pipeline/proxies.py: ProxyBuilder ----------


def _create_output(command: FFmpegCommand) -> None:
    Path(command.args[-1]).write_bytes(b"\x00" * 16)


def test_proxy_builder_builds_only_missing_and_status_reflects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_DIR", tmp_path / "proxy")
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mp4").write_bytes(b"b")
    project = _project(
        tmp_path, timeline=[{"type": "clip", "src": "a.mp4"}, {"type": "clip", "src": "b.mp4"}]
    )

    def fake_prober(path: Path) -> MediaInfo:
        return MediaInfo(path, 2.0, 1920, 1080, 30.0, True, True, False)

    runner = RecordingRunner(on_run=_create_output)
    builder = ProxyBuilder(runner, prober=fake_prober)

    before = builder.status(project)
    assert {s.ready for s in before} == {False}
    ready_a = next(s for s in before if s.src.name == "a.mp4")
    ready_a.proxy.parent.mkdir(parents=True, exist_ok=True)
    ready_a.proxy.write_bytes(b"ja pronto")  # simula que "a" já tem proxy

    built = builder.build(project)
    assert {s.src.name: s.ready for s in built} == {"a.mp4": True, "b.mp4": True}
    assert len(runner.commands) == 1  # só gerou o que faltava (b)
    built_b = next(s for s in built if s.src.name == "b.mp4")
    assert built_b.proxy.exists()
    assert not list(built_b.proxy.parent.glob("*.tmp.mp4"))  # nada de proxy parcial sobrando

    after = builder.status(project)
    assert {s.ready for s in after} == {True}


def test_proxy_builder_uses_a_unique_tmp_name_per_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_DIR", tmp_path / "proxy")
    (tmp_path / "a.mp4").write_bytes(b"a")
    project = _project(tmp_path, timeline=[{"type": "clip", "src": "a.mp4"}])
    tmp_names = []

    def on_run(command: FFmpegCommand) -> None:
        tmp_names.append(Path(command.args[-1]).name)
        _create_output(command)

    builder = ProxyBuilder(
        RecordingRunner(on_run=on_run),
        prober=lambda path: MediaInfo(path, 1.0, 1920, 1080, 30.0, True, True, False),
    )
    builder.build(project)
    assert len(tmp_names) == 1
    name = tmp_names[0]
    assert f".tmp-{os.getpid()}-" in name
    assert list((tmp_path / "proxy").glob("*.tmp-*")) == []  # nada de tmp sobrando


def test_proxy_builder_discards_tmp_when_another_process_already_finished_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_DIR", tmp_path / "proxy")
    (tmp_path / "a.mp4").write_bytes(b"a")
    project = _project(tmp_path, timeline=[{"type": "clip", "src": "a.mp4"}])
    final_path = proxy_path(tmp_path / "a.mp4")

    def on_run(command: FFmpegCommand) -> None:
        # simula outro job de proxies terminando o mesmo proxy enquanto este ainda rodava
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"proxy do outro processo")
        Path(command.args[-1]).write_bytes(b"\x00" * 16)  # o nosso tmp tambem fica pronto

    builder = ProxyBuilder(
        RecordingRunner(on_run=on_run),
        prober=lambda path: MediaInfo(path, 1.0, 1920, 1080, 30.0, True, True, False),
    )
    built = builder.build(project)
    assert built[0].ready is True
    assert built[0].proxy.read_bytes() == b"proxy do outro processo"  # não sobrescreveu o do outro
    assert list((tmp_path / "proxy").glob("*.tmp-*")) == []  # o nosso tmp foi descartado


def test_proxy_builder_leaves_no_tmp_when_the_runner_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_DIR", tmp_path / "proxy")
    (tmp_path / "a.mp4").write_bytes(b"a")
    project = _project(tmp_path, timeline=[{"type": "clip", "src": "a.mp4"}])

    def on_run(command: FFmpegCommand) -> None:
        Path(command.args[-1]).write_bytes(b"\x00" * 16)  # ffmpeg chegou a escrever algo...
        raise FFmpegError("ffmpeg explodiu")  # ...mas falhou antes do fim

    builder = ProxyBuilder(
        RecordingRunner(on_run=on_run),
        prober=lambda path: MediaInfo(path, 1.0, 1920, 1080, 30.0, True, True, False),
    )
    with pytest.raises(FFmpegError):
        builder.build(project)
    assert list((tmp_path / "proxy").glob("**/*.tmp-*")) == []


def test_replace_with_retry_survives_a_transient_permission_error(tmp_path, monkeypatch):
    proxy = tmp_path / "out.mp4"
    tmp = tmp_path / "out.tmp-1-aaaaaaaa.mp4"
    tmp.write_bytes(b"conteudo")
    real_replace = Path.replace
    calls = {"n": 0}

    def flaky_replace(self, target):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("[WinError 32] arquivo em uso por outro processo")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(proxies_module.time, "sleep", lambda seconds: None)

    ProxyBuilder(RecordingRunner())._replace_with_retry(tmp, proxy)
    assert calls["n"] == 3
    assert proxy.read_bytes() == b"conteudo"


def test_replace_with_retry_gives_up_after_max_attempts(tmp_path, monkeypatch):
    proxy = tmp_path / "out.mp4"
    tmp = tmp_path / "out.tmp-1-aaaaaaaa.mp4"
    tmp.write_bytes(b"conteudo")

    def always_fails(self, target):
        raise PermissionError("[WinError 32] arquivo em uso por outro processo")

    monkeypatch.setattr(Path, "replace", always_fails)
    monkeypatch.setattr(proxies_module.time, "sleep", lambda seconds: None)

    with pytest.raises(PermissionError):
        ProxyBuilder(RecordingRunner())._replace_with_retry(tmp, proxy)


def test_proxy_builder_reports_progress_per_source(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_DIR", tmp_path / "proxy")
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mp4").write_bytes(b"b")
    project = _project(
        tmp_path, timeline=[{"type": "clip", "src": "a.mp4"}, {"type": "clip", "src": "b.mp4"}]
    )
    builder = ProxyBuilder(
        RecordingRunner(on_run=_create_output),
        prober=lambda path: MediaInfo(path, 1.0, 1920, 1080, 30.0, True, True, False),
    )

    class RecordingSink:
        def __init__(self) -> None:
            self.events: list[tuple] = []

        def start(self, label, total):
            self.events.append(("start", label, total))

        def update(self, done):
            self.events.append(("update", done))

        def finish(self):
            self.events.append(("finish",))

    sink = RecordingSink()
    builder.build(project, sink=sink)
    assert sink.events[0] == ("start", "proxies de prévia", 2)
    assert ("update", 1) in sink.events and ("update", 2) in sink.events
    assert sink.events[-1] == ("finish",)


# ---------- API (ui/server.py) ----------

PROXY_PROJECT = "ui-proxies"
PROXY_SPEC = {"output": {"preset": "instagram/stories"}, "timeline": [{"type": "clip", "src": "clip.mp4"}]}


class _MissingProxyBuilder:
    """Dublê: uma fonte ainda sem proxy; `build` simula a geração marcando como pronta."""

    def __init__(self, runner, prober=None, log=None):
        pass

    def status(self, project: Project) -> list[ProxyStatus]:
        return [ProxyStatus(Path("clip.mp4"), config.PROXY_DIR / "fake.mp4", False)]

    def build(self, project: Project, sink=None) -> list[ProxyStatus]:
        return [ProxyStatus(Path("clip.mp4"), config.PROXY_DIR / "fake.mp4", True)]


class _AllReadyProxyBuilder:
    """Dublê: já tudo pronto; `build` não deveria ser chamado pelo endpoint."""

    def __init__(self, runner, prober=None, log=None):
        pass

    def status(self, project: Project) -> list[ProxyStatus]:
        return [ProxyStatus(Path("clip.mp4"), config.PROXY_DIR / "fake.mp4", True)]

    def build(self, project: Project, sink=None) -> list[ProxyStatus]:
        raise AssertionError("build não deveria rodar quando não há nada por fazer")


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c
    folder = config.PROJECTS_DIR / PROXY_PROJECT
    for f in folder.glob("*"):
        f.unlink()
    if folder.exists():
        folder.rmdir()


def test_get_proxies_returns_status(client, monkeypatch):
    client.put(f"/api/projects/{PROXY_PROJECT}", json=PROXY_SPEC)
    monkeypatch.setattr(proxies_module, "ProxyBuilder", _MissingProxyBuilder)
    body = client.get(f"/api/projects/{PROXY_PROJECT}/proxies").json()
    assert body == [
        {
            "src": "clip.mp4",
            "proxy": str(config.PROXY_DIR / "fake.mp4"),
            "ready": False,
            "missing": False,
            "url": None,
        }
    ]
    assert client.get("/api/projects/nao-existe/proxies").status_code == 404


def test_post_proxies_starts_job_when_something_is_missing(client, monkeypatch):
    client.put(f"/api/projects/{PROXY_PROJECT}", json=PROXY_SPEC)
    monkeypatch.setattr(proxies_module, "ProxyBuilder", _MissingProxyBuilder)
    resp = client.post(f"/api/projects/{PROXY_PROJECT}/proxies").json()
    assert resp["job"] is not None and resp["proxies"][0]["ready"] is False
    job = server.jobs.get(resp["job"]["job_id"])
    server.jobs.wait(job, 5)
    assert job.status == "done", job.error
    assert job.result[0]["ready"] is True
    assert job.result[0]["url"] == server._file_url(config.PROXY_DIR / "fake.mp4")


def test_post_proxies_skips_job_when_everything_is_ready(client, monkeypatch):
    client.put(f"/api/projects/{PROXY_PROJECT}", json=PROXY_SPEC)
    monkeypatch.setattr(proxies_module, "ProxyBuilder", _AllReadyProxyBuilder)
    resp = client.post(f"/api/projects/{PROXY_PROJECT}/proxies").json()
    assert resp["job"] is None
    assert resp["proxies"] == [
        {
            "src": "clip.mp4",
            "proxy": str(config.PROXY_DIR / "fake.mp4"),
            "ready": True,
            "missing": False,
            "url": server._file_url(config.PROXY_DIR / "fake.mp4"),
        }
    ]


def _slow_missing_builder(gate: threading.Event):
    """Como `_MissingProxyBuilder`, mas `build` só termina quando o teste libera `gate`: dá tempo de
    disparar um segundo POST /proxies enquanto o primeiro job ainda está rodando."""

    class _SlowMissingProxyBuilder:
        def __init__(self, runner, prober=None, log=None):
            pass

        def status(self, project: Project) -> list[ProxyStatus]:
            return [ProxyStatus(Path("clip.mp4"), config.PROXY_DIR / "fake.mp4", False)]

        def build(self, project: Project, sink=None) -> list[ProxyStatus]:
            gate.wait(5)
            return [ProxyStatus(Path("clip.mp4"), config.PROXY_DIR / "fake.mp4", True)]

    return _SlowMissingProxyBuilder


def test_post_proxies_reuses_running_job_for_the_same_project(client, monkeypatch):
    """Abrir o projeto duas vezes (ex.: pelo hash e por um clique) não deve disparar dois jobs de
    proxies para a mesma fonte, o que fazia os dois escreverem o mesmo .tmp e o segundo `replace`
    falhar com PermissionError."""
    client.put(f"/api/projects/{PROXY_PROJECT}", json=PROXY_SPEC)
    gate = threading.Event()
    monkeypatch.setattr(proxies_module, "ProxyBuilder", _slow_missing_builder(gate))
    try:
        first = client.post(f"/api/projects/{PROXY_PROJECT}/proxies").json()
        second = client.post(f"/api/projects/{PROXY_PROJECT}/proxies").json()
        assert first["job"] is not None and second["job"] is not None
        assert first["job"]["job_id"] == second["job"]["job_id"]
    finally:
        gate.set()
        job = server.jobs.get(first["job"]["job_id"])
        if job:
            server.jobs.wait(job, 5)
