"""`domain.tracks`: mudo/oculto por trilha aplicado à spec antes do render (paridade com o Shotcut:
o que a interface muda/oculta também some do vídeo final, não só da prévia)."""

from __future__ import annotations

import pytest

from dmaker.domain.spec import ImageOverlay, ProgressBar, Project, TextOverlay, VideoOverlay
from dmaker.domain.tracks import (
    apply_track_state,
    known_track_ids,
    silenced_carrier_warnings,
    video_overlay_lanes,
)

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


def test_gr_hidden_removes_the_html_composition_too():
    """A composição HTML mora na trilha GR: ocultá-la na interface também a tira do render."""
    project = make_project(
        overlays=[
            {"type": "html", "src": "comp.html", "start": 0, "end": 1},
            {"type": "text", "text": "Oi", "start": 0, "end": 1},
        ],
        tracks={"GR": {"hidden": True}},
    )
    new = apply_track_state(project)
    assert [ov.type for ov in new.overlays] == ["text"]


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
    assert ids == {"V1", "A1", "TX", "GR", "CC", "MUS", "SFX"}


def test_nar_track_exists_only_with_narration_and_muting_it_removes_the_narrations():
    assert "NAR" not in known_track_ids(make_project())
    project = make_project(audio={"narration": [{"text": "Olá"}]}, tracks={"NAR": {"muted": True}})
    assert "NAR" in known_track_ids(project)
    new = apply_track_state(project)
    assert new.audio.narration == [] and len(project.audio.narration) == 1  # original intocado


# ---------- a portadora do Vocoder acompanha o mudo e o solo (DMK-70) ----------


def vocoder_on(track: str | None) -> dict:
    return {"type": "vocoder", **({"carrier_track": track} if track else {})}


def carrier_project(carrier: str | None = "A3", states: dict | None = None, **audio) -> Project:
    """Três faixas externas (A2 = a, A3 = b, A4 = d) e uma voz gravada cujo Vocoder ouve `carrier`."""
    return Project.model_validate(
        {
            "name": "portadora-mudo",
            "sources": {name: {"src": f"{name}.wav", "sync": 0} for name in "abd"},
            "timeline": [{"type": "clip", "source": "a", "start": 0, "end": 4}],
            "audio": {
                "tracks": [{"source": name} for name in "abd"],
                "voiceover": [{"src": "fala.wav", "effects": [vocoder_on(carrier)]}],
                **audio,
            },
            "tracks": states or {},
        }
    )


def voice_carrier(project: Project) -> str | None:
    return project.audio.voiceover[0].effects[0].carrier_track_id()


def test_the_carrier_follows_the_renumbering_when_another_external_track_is_muted():
    state = apply_track_state(carrier_project("A3", {"A2": {"muted": True}}))
    assert [track.source for track in state.audio.tracks] == ["b", "d"]
    assert voice_carrier(state) == "A2"  # a A3 virou a A2 e continua sendo a fonte b
    assert state.audio.tracks[int(voice_carrier(state)[1:]) - 2].source == "b"


def test_the_carrier_is_dropped_when_it_is_the_muted_track_itself():
    state = apply_track_state(carrier_project("A3", {"A3": {"muted": True}}))
    assert voice_carrier(state) is None  # sem isto o A3 passaria a ser a fonte d


def test_the_carrier_is_dropped_when_another_track_is_in_solo():
    state = apply_track_state(carrier_project("A3", {"VO": {"solo": True}}))
    assert voice_carrier(state) is None  # só a voz soa, e a A3 ficou fora do solo
    kept = apply_track_state(carrier_project("A3", {"A3": {"solo": True}, "VO": {"solo": True}}))
    assert voice_carrier(kept) == "A2"  # a única que soa é a b, que passa a ser a A2


@pytest.mark.parametrize("carrier", ["MUS", "NAR", "SFX", "A1"])
def test_the_carrier_of_any_silenced_track_kind_falls_back_to_the_generated_one(carrier):
    extra = {"music": {"src": "m.mp3"}, "narration": [{"text": "oi"}]}
    state = apply_track_state(carrier_project(carrier, {carrier: {"muted": True}}, **extra))
    assert voice_carrier(state) is None


def test_the_vo_carrier_on_another_host_is_dropped_when_the_voice_track_is_muted():
    audio = {"music": {"src": "m.mp3", "effects": [vocoder_on("VO")]}}
    state = apply_track_state(carrier_project(None, {"VO": {"muted": True}}, **audio))
    assert state.audio.voiceover == []
    assert state.audio.music.effects[0].carrier_track_id() is None


def test_the_renumbering_holds_on_every_host_that_can_listen_to_an_external_track():
    audio = {
        "tracks": [{"source": "a"}, {"source": "b"}, {"source": "d", "effects": [vocoder_on("A3")]}],
        "music": {"src": "m.mp3", "effects": [vocoder_on("A3")]},
        "narration": [{"text": "oi", "effects": [vocoder_on("A3")]}],
        "generated": [{"generator": "tone", "duration": 1, "effects": [vocoder_on("A3")]}],
    }
    state = apply_track_state(carrier_project("A3", {"A2": {"muted": True}}, **audio)).audio
    assert state.tracks[1].effects[0].carrier_track_id() == "A2"  # a faixa d, agora A3, ouve a b, agora A2
    assert state.music.effects[0].carrier_track_id() == "A2"
    assert state.narration[0].effects[0].carrier_track_id() == "A2"
    assert state.generated[0].effects[0].carrier_track_id() == "A2"
    assert state.voiceover[0].effects[0].carrier_track_id() == "A2"


def test_the_clip_host_drops_a_silenced_carrier():
    project = Project.model_validate(
        {
            "name": "clipe",
            "timeline": [
                {"type": "clip", "src": "a.mp4", "start": 0, "end": 4, "effects": [vocoder_on("MUS")]}
            ],
            "audio": {"music": {"src": "m.mp3"}},
            "tracks": {"MUS": {"muted": True}},
        }
    )
    assert apply_track_state(project).timeline[0].effects[0].carrier_track_id() is None


def test_a_host_that_was_removed_by_the_mute_does_not_break_the_carrier_pass():
    audio = {"tracks": [{"source": "a"}, {"source": "b", "effects": [vocoder_on("A2")]}, {"source": "d"}]}
    state = apply_track_state(carrier_project(None, {"A3": {"muted": True}}, **audio))
    assert [track.source for track in state.audio.tracks] == ["a", "d"]
    assert apply_track_state(carrier_project("A3", {"VO": {"muted": True}})).audio.voiceover == []


def test_an_effect_that_does_not_change_keeps_the_same_objects():
    project = carrier_project("A2", {"A4": {"muted": True}})
    state = apply_track_state(project)
    assert state.audio.voiceover is project.audio.voiceover  # a A2 não anda quando a A4 sai
    assert state.audio.tracks[0] is project.audio.tracks[0]


def test_without_a_carrier_track_a_muted_track_gives_the_same_result_as_before():
    project = carrier_project(None, {"A2": {"muted": True}})
    state = apply_track_state(project)
    assert state.audio.voiceover is project.audio.voiceover
    expected = project.model_copy(
        update={"audio": project.audio.model_copy(update={"tracks": project.audio.tracks[1:]})}
    )
    assert state.model_dump() == expected.model_dump()
    assert silenced_carrier_warnings(project) == []


def test_the_warning_names_the_item_and_the_track_and_is_empty_when_nothing_is_silenced():
    muted = carrier_project("A3", {"A3": {"muted": True}})
    assert silenced_carrier_warnings(muted) == [
        "audio.voiceover[0]: o Vocoder pede a portadora da trilha A3, que está muda ou fora do solo; "
        "usa a portadora gerada."
    ]
    assert silenced_carrier_warnings(carrier_project("A3", {"VO": {"solo": True}}))  # fora do solo também
    assert silenced_carrier_warnings(carrier_project("A3", {"A2": {"muted": True}})) == []  # só renumerou
    assert silenced_carrier_warnings(carrier_project("A3")) == []
