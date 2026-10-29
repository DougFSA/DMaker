"""Fonte ausente no disco: a vista de linha do tempo, as edições e os proxies abrem o projeto e marcam o
trecho como "fonte não encontrada" em vez de falhar. O render e a validação continuam exigindo os arquivos."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.edits import apply_edit
from dmaker.pipeline.layout import project_layout
from dmaker.pipeline.missing import STAND_IN_DURATION_S, MissingMedia
from dmaker.pipeline.proxies import ProxyBuilder
from dmaker.pipeline.timeline_service import project_timeline_view
from dmaker.ui import server


def prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 20.0, 1920, 1080, 30.0, True, True, False)


def never_called(*args, **kwargs):
    raise AssertionError("sem o arquivo não há o que correlacionar")


def project_with(tmp_path: Path, present: list[str], spec: dict) -> Project:
    for name in present:
        (tmp_path / name).write_bytes(b"x")
    project = Project.model_validate({"name": "ausente", **spec})
    project.base_dir = tmp_path
    return project


CLIPS = {
    "timeline": [
        {"type": "clip", "src": "presente.mp4", "start": 0, "end": 4},
        {"type": "clip", "src": "sumiu.mp4", "start": 0, "end": 6},
        {"type": "clip", "src": "sumiu-sem-fim.mp4"},
    ]
}


# ---------- MissingMedia.scan ----------


def test_scan_lists_only_the_files_the_disk_lacks(tmp_path):
    project = project_with(tmp_path, ["presente.mp4"], CLIPS)
    missing = MissingMedia.scan(project)
    assert missing.paths == {tmp_path / "sumiu.mp4", tmp_path / "sumiu-sem-fim.mp4"}
    assert missing.covers(tmp_path / "sumiu.mp4") and not missing.covers(tmp_path / "presente.mp4")
    assert not MissingMedia.scan(project_with(tmp_path, ["sumiu.mp4", "sumiu-sem-fim.mp4"], CLIPS))


def test_scan_finds_sources_overlays_music_and_voice_files(tmp_path):
    project = project_with(
        tmp_path,
        [],
        {
            "sources": {"cam": {"parts": ["a.mp4", "b.mp4"]}, "mesa": {"src": "mesa.wav"}},
            "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 10}],
            "overlays": [
                {"type": "video", "src": "pip.mp4"},
                {"type": "image", "src": "logo"},
                {"type": "image", "src": "selo.png"},
            ],
            "audio": {"music": {"src": "musica.mp3"}, "voiceover": [{"src": "voz.wav"}]},
        },
    )
    names = {path.name for path in MissingMedia.scan(project).paths}
    assert names == {"a.mp4", "b.mp4", "mesa.wav", "pip.mp4", "selo.png", "musica.mp3", "voz.wav"}


def test_stand_in_lasts_as_long_as_the_spec_asks(tmp_path):
    project = project_with(tmp_path, [], CLIPS)
    missing = MissingMedia.scan(project)
    assert (
        missing.stand_in(tmp_path / "sumiu.mp4").duration == STAND_IN_DURATION_S
    )  # end = 6, abaixo do mínimo
    long_clip = project_with(tmp_path, [], {"timeline": [{"type": "clip", "src": "longo.mp4", "end": 90}]})
    assert MissingMedia.scan(long_clip).stand_in(tmp_path / "longo.mp4").duration == 90
    info = missing.stand_in(tmp_path / "sumiu.mp4")
    assert info.has_video and not info.has_audio and not info.is_image


# ---------- layout e vista ----------


def test_strict_layout_still_demands_every_file(tmp_path):
    project = project_with(tmp_path, ["presente.mp4"], CLIPS)
    with pytest.raises(FileNotFoundError, match="sumiu.mp4"):
        project_layout(project, prober=prober)


def test_view_opens_with_the_missing_clips_marked(tmp_path):
    project = project_with(tmp_path, ["presente.mp4"], CLIPS)
    view = project_timeline_view(project, prober=prober)
    v1 = next(track for track in view.tracks if track.id == "V1")
    assert [item.missing for item in v1.items] == [False, True, True]
    assert [(item.start, item.end) for item in v1.items][:2] == [
        (0.0, 4.0),
        (4.0, 10.0),
    ]  # a duração da spec vale
    assert v1.items[2].end - v1.items[2].start == STAND_IN_DURATION_S  # sem `end`: a duração de reserva
    a1 = next(track for track in view.tracks if track.id == "A1")
    assert [item.missing for item in a1.items] == [False, True, True]
    assert view.warnings == [
        f"Fonte não encontrada: {tmp_path / name}" for name in ("sumiu-sem-fim.mp4", "sumiu.mp4")
    ]
    assert view.to_dict()["tracks"][-2]["items"][0]["missing"] is False


def test_view_marks_a_missing_overlay_music_and_image(tmp_path):
    spec = {
        "timeline": [{"type": "clip", "src": "presente.mp4", "end": 5}],
        "overlays": [
            {"type": "video", "src": "pip.mp4", "start": 0, "end": 2},
            {"type": "image", "src": "selo.png"},
        ],
        "audio": {"music": {"src": "musica.mp3"}},
    }
    view = project_timeline_view(project_with(tmp_path, ["presente.mp4"], spec), prober=prober)
    flagged = {track.id: [item.missing for item in track.items] for track in view.tracks}
    assert flagged["V2"] == [True] and flagged["GR"] == [True] and flagged["MUS"] == [True]
    assert flagged["V1"] == [False]


def test_view_with_everything_present_has_no_warning(tmp_path):
    view = project_timeline_view(
        project_with(tmp_path, ["presente.mp4"], CLIPS | {"timeline": CLIPS["timeline"][:1]}), prober=prober
    )
    assert view.warnings == []
    assert all(not item.missing for track in view.tracks for item in track.items)


def test_a_missing_synced_source_keeps_its_clips_and_skips_the_correlation(tmp_path):
    spec = {
        "sources": {"cam": {"src": "cam.mp4"}, "mesa": {"src": "mesa.wav", "sync": "auto"}},
        "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 8}],
        "audio": {"tracks": [{"source": "mesa"}]},
    }
    project = project_with(tmp_path, ["cam.mp4"], spec)
    view = project_timeline_view(project, prober=prober, offset_finder=never_called)
    assert view.sources["mesa"]["missing"] is True and view.sources["cam"]["missing"] is False
    assert view.sources["mesa"]["offset"] == 0.0  # sem o arquivo e sem cálculo guardado, fica em zero
    v1 = next(track for track in view.tracks if track.id == "V1")
    assert v1.items[0].missing is False


def test_a_missing_synced_source_reuses_the_stored_offset(tmp_path):
    spec = {
        "sources": {"cam": {"src": "cam.mp4"}, "mesa": {"src": "mesa.wav", "sync": "auto"}},
        "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 8}],
    }
    project = project_with(tmp_path, ["cam.mp4"], spec)
    (tmp_path / "sync.json").write_text(
        '{"mesa": {"key": ["x"], "offset": 2.5, "confidence": 9}}', encoding="utf-8"
    )
    view = project_timeline_view(project, prober=prober, offset_finder=never_called)
    assert view.sources["mesa"]["offset"] == 2.5


def test_a_missing_part_of_a_source_stands_in_and_stays_out_of_the_correlation(tmp_path):
    spec = {
        "sources": {"cam": {"parts": ["a.mp4", "b.mp4"]}},
        "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 15}],
    }
    project = project_with(tmp_path, ["a.mp4"], spec)
    pairs = []

    def finder(a, b, sa, sb):
        pairs.append((a.name, b.name))
        return SyncResult(20.0, 1.0)

    view = project_timeline_view(project, prober=prober, offset_finder=finder)
    assert view.sources["cam"]["missing"] is True  # a parte b.mp4 não está no disco
    assert all("b.mp4" not in pair for pair in pairs)  # sem o arquivo não há o que correlacionar


# ---------- edições ----------


def test_edits_work_on_a_project_with_a_missing_source(tmp_path):
    project = project_with(tmp_path, ["presente.mp4"], CLIPS)
    edited = apply_edit(project, {"type": "split", "index": 1, "at": 3.0}, prober=prober)
    assert [seg.src for seg in edited.timeline[:3]] == ["presente.mp4", "sumiu.mp4", "sumiu.mp4"]


# ---------- proxies ----------


class WritingRunner(RecordingRunner):
    """Grava o comando e cria o arquivo de saída, como o ffmpeg faria."""

    def run(self, command):
        Path(command.args[-1]).write_bytes(b"proxy")
        return super().run(command)


def test_proxy_status_flags_the_missing_original_and_never_tries_to_build_it(tmp_path):
    project = project_with(tmp_path, ["presente.mp4"], CLIPS)
    builder = ProxyBuilder(WritingRunner(), prober=prober)
    statuses = builder.status(project)
    by_name = {item.src.name: item for item in statuses}
    assert (
        by_name["sumiu.mp4"].missing and by_name["sumiu.mp4"].proxy is None and not by_name["sumiu.mp4"].ready
    )
    assert not by_name["presente.mp4"].missing
    built = builder.build(project)
    assert {item.src.name: item.ready for item in built} == {
        "presente.mp4": True,
        "sumiu.mp4": False,
        "sumiu-sem-fim.mp4": False,
    }


# ---------- API ----------

PROJECT = "ui-ausente"


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


def create(client, spec: dict) -> None:
    resp = client.put(f"/api/projects/{PROJECT}", json=spec)
    assert resp.status_code == 200, resp.text
    (config.PROJECTS_DIR / PROJECT).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def broken_project(client):
    """Um projeto salvo cujo único clipe não existe mais no disco (o probe nem chega a ser chamado)."""
    create(
        client,
        {
            "output": {"preset": "instagram/stories"},
            "timeline": [{"type": "clip", "src": "sumiu.mp4", "start": 0, "end": 5}],
            "audio": {"normalize": "off"},
        },
    )


def test_timeline_endpoint_answers_with_the_missing_clip_marked(client, broken_project):
    resp = client.post(f"/api/projects/{PROJECT}/timeline", json={})
    assert resp.status_code == 200, resp.text
    view = resp.json()
    v1 = next(track for track in view["tracks"] if track["id"] == "V1")
    assert v1["items"][0]["missing"] is True
    assert view["warnings"] and "sumiu.mp4" in view["warnings"][0]


def test_edit_endpoint_keeps_working_with_the_missing_clip(client, broken_project):
    spec = client.get(f"/api/projects/{PROJECT}").json()["spec"]
    resp = client.post(
        f"/api/projects/{PROJECT}/edit", json={"spec": spec, "op": {"type": "split", "index": 0, "at": 2}}
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["spec"]["timeline"]) == 2
    assert all(
        item["missing"]
        for item in next(t for t in resp.json()["timeline"]["tracks"] if t["id"] == "V1")["items"]
    )


def test_proxies_endpoints_report_the_missing_original_without_failing(client, broken_project):
    listing = client.get(f"/api/projects/{PROJECT}/proxies")
    assert listing.status_code == 200, listing.text
    assert listing.json() == [
        {
            "src": str(config.PROJECTS_DIR / PROJECT / "sumiu.mp4"),
            "proxy": None,
            "ready": False,
            "missing": True,
            "url": None,
        }
    ]
    started = client.post(f"/api/projects/{PROJECT}/proxies")
    assert started.status_code == 200 and started.json()["job"] is None  # nada a gerar: o original não existe
