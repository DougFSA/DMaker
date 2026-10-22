"""`domain.tracks`: mudo/oculto por trilha aplicado à spec antes do render (paridade com o Shotcut:
o que a interface muda/oculta também some do vídeo final, não só da prévia)."""

from __future__ import annotations

from dmaker.domain.spec import ImageOverlay, ProgressBar, Project, TextOverlay, VideoOverlay
from dmaker.domain.tracks import apply_track_state, known_track_ids, video_overlay_lanes

BASE = {
    "name": "trilhas-teste",
    "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 4}],
}


def make_project(**overrides) -> Project:
    return Project.model_validate({**BASE, **overrides})


def test_apply_track_state_without_tracks_returns_same_project():
    project = make_project()
    assert apply_track_state(project) is project


def test_a1_muted_sets_mute_clips():
    project = make_project(tracks={"A1": {"muted": True}})
    new = apply_track_state(project)
    assert new.audio.mute_clips is True
    assert new is not project and project.audio.mute_clips is False  # original intocado


def test_a2_muted_removes_matching_audio_track():
    project = make_project(
        sources={"rec": {"src": "rec.wav"}},
        audio={"tracks": [{"source": "rec", "volume": 0.5}]},
        tracks={"A2": {"muted": True}},
    )
    new = apply_track_state(project)
    assert new.audio.tracks == []


def test_a2_muted_only_removes_its_own_track():
    project = make_project(
        sources={"rec1": {"src": "r1.wav"}, "rec2": {"src": "r2.wav"}},
        audio={"tracks": [{"source": "rec1"}, {"source": "rec2"}]},
        tracks={"A3": {"muted": True}},  # segunda faixa (índice 1) = A3
    )
    new = apply_track_state(project)
    assert [t.source for t in new.audio.tracks] == ["rec1"]


def test_mus_muted_clears_music():
    project = make_project(audio={"music": {"src": "trilha.mp3"}}, tracks={"MUS": {"muted": True}})
    new = apply_track_state(project)
    assert new.audio.music is None


def test_cc_hidden_disables_captions():
    project = make_project(captions={"source": "auto", "enabled": True}, tracks={"CC": {"hidden": True}})
    new = apply_track_state(project)
    assert new.captions.enabled is False


def test_tx_hidden_removes_text_overlays_only():
    project = make_project(
        overlays=[
            {"type": "text", "text": "Oi", "start": 0, "end": 1},
            {"type": "image", "src": "logo", "start": 0, "end": 1},
        ],
        tracks={"TX": {"hidden": True}},
    )
    new = apply_track_state(project)
    assert not any(isinstance(ov, TextOverlay) for ov in new.overlays)
    assert any(isinstance(ov, ImageOverlay) for ov in new.overlays)


def test_gr_hidden_removes_image_and_progress_bar():
    project = make_project(
        overlays=[
            {"type": "image", "src": "logo", "start": 0, "end": 1},
            {"type": "progress-bar"},
            {"type": "text", "text": "Oi", "start": 0, "end": 1},
        ],
        tracks={"GR": {"hidden": True}},
    )
    new = apply_track_state(project)
    assert not any(isinstance(ov, (ImageOverlay, ProgressBar)) for ov in new.overlays)
    assert any(isinstance(ov, TextOverlay) for ov in new.overlays)


def test_v2_hidden_removes_only_overlays_in_that_lane():
    # dois PiPs que não se sobrepõem no tempo dividem a mesma faixa (V2); um terceiro que cruza
    # com o segundo abre uma faixa nova (V3).
    project = make_project(
        overlays=[
            {"type": "video", "src": "a.mp4", "start": 0, "end": 2, "offset": 0},
            {"type": "video", "src": "b.mp4", "start": 2, "end": 4, "offset": 0},
            {"type": "video", "src": "c.mp4", "start": 3, "end": 5, "offset": 0},
        ],
        tracks={"V2": {"hidden": True}},
    )
    lanes = video_overlay_lanes(project)
    assert lanes == {0: 0, 1: 0, 2: 1}
    new = apply_track_state(project)
    remaining = [ov.src for ov in new.overlays if isinstance(ov, VideoOverlay)]
    assert remaining == ["c.mp4"]


def test_v1_hidden_is_ignored():
    project = make_project(tracks={"V1": {"hidden": True}})
    new = apply_track_state(project)
    assert new.timeline == project.timeline


def test_locked_never_changes_render():
    project = make_project(tracks={"A1": {"locked": True}, "V1": {"locked": True}})
    new = apply_track_state(project)
    assert new is project  # nada muda: locked é só da interface


def test_known_track_ids_covers_fixed_and_dynamic_ids():
    project = make_project(
        sources={"rec": {"src": "rec.wav"}},
        audio={"tracks": [{"source": "rec"}], "music": {"src": "trilha.mp3"}},
        captions={"source": "auto"},
        overlays=[{"type": "video", "src": "b.mp4", "start": 0, "end": 2, "offset": 0}],
    )
    ids = known_track_ids(project)
    assert {"V1", "A1", "A2", "TX", "GR", "CC", "MUS", "V2"} <= ids


def test_known_track_ids_minimal_project_has_no_dynamic_ids():
    ids = known_track_ids(make_project())
    assert ids == {"V1", "A1", "TX", "GR", "CC", "MUS"}


def test_nar_track_exists_only_with_narration_and_muting_it_removes_the_narrations():
    assert "NAR" not in known_track_ids(make_project())
    project = make_project(audio={"narration": [{"text": "Olá"}]}, tracks={"NAR": {"muted": True}})
    assert "NAR" in known_track_ids(project)
    new = apply_track_state(project)
    assert new.audio.narration == [] and len(project.audio.narration) == 1  # original intocado
