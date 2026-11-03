"""A edição de onda na spec e nos grafos, sem ffmpeg: os efeitos novos, os campos novos (que ficam fora do dump no
padrão), o estado da trilha (ganho, pan, mudo e solo) e as contas puras do deslocamento e do equilíbrio."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmaker.domain.audio_effects import EFFECT_CLASSES, catalog_payload, chain_duration, parse_effect
from dmaker.domain.audio_effects.editing import Channels, Cut, Envelope
from dmaker.domain.audio_shift import shifted_window
from dmaker.domain.spec import AudioTrack, ClipSegment, Project, TrackState, VideoOverlay
from dmaker.domain.tracks import apply_track_state, audio_track_ids, known_track_ids, silenced_audio_tracks
from dmaker.filtergraph import Inputs, ResolvedVideoOverlay, pip_audio_graph
from dmaker.filtergraph.audio import audio_graph
from dmaker.filtergraph.audio_effects import EffectRequest, build_effect, builder_types
from dmaker.filtergraph.audio_effects.editing import envelope_gain_expression
from dmaker.filtergraph.mezzanine import TrackSlice, clip_audio_lines
from dmaker.filtergraph.mix import pan_filter, pan_gains
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.preview_audio import mix_recipe, piece_recipe
from dmaker.pipeline.sfx import level_tracks
from dmaker.pipeline.timeline_service import project_timeline_view
from dmaker.pipeline.track_slices import source_covers, track_slice


def project(**parts) -> Project:
    data = {"name": "onda", "timeline": [{"type": "clip", "src": "a.mp4", "start": 0, "end": 10}], **parts}
    return Project.model_validate(data)


# ---------- o catálogo e as classes ----------


def test_the_new_effects_have_a_builder_each_and_the_catalog_tells_the_interface_which_need_a_selection():
    assert {"silence", "cut", "envelope", "channels"} <= set(EFFECT_CLASSES) == builder_types()
    payload = catalog_payload()
    json.dumps(payload)  # serializável: a rota da API e o MCP devolvem isto
    by_type = {effect["type"]: effect for effect in payload["effects"]}
    assert by_type["cut"]["needs_selection"] and by_type["envelope"]["needs_selection"]
    assert not by_type["silence"]["needs_selection"] and not by_type["channels"]["needs_selection"]
    points = by_type["envelope"]["parameters"][0]
    assert (points["name"], points["kind"], points["default"]) == (
        "points",
        "points",
        [{"at": 0.0, "db": 0.0}, {"at": 1.0, "db": 0.0}],
    )
    assert by_type["channels"]["parameters"][0]["options"] == ["mono", "swap", "left", "right"]
    assert (by_type["silence"]["audacity_name"], by_type["cut"]["audacity_name"]) == (
        "Silence Audio",
        "Delete",
    )


def test_the_envelope_sorts_its_points_and_refuses_what_makes_no_sense():
    envelope = parse_effect({"type": "envelope", "points": [{"at": 4, "db": -6}, {"at": 1, "db": 0}]})
    assert [point.at for point in envelope.points] == [1.0, 4.0]
    for bad in (
        {"type": "envelope", "points": []},
        {"type": "envelope", "points": [{"at": 1, "db": 0}, {"at": 1, "db": -3}]},
        {"type": "envelope", "points": [{"at": 1, "db": 30}]},
        {"type": "envelope", "points": [{"at": -1, "db": 0}]},
        {"type": "envelope", "start": 1, "points": [{"at": 1, "db": 0}]},
        {"type": "envelope", "points": [{"at": i, "db": 0} for i in range(101)]},
    ):
        with pytest.raises((ValidationError, ValueError)):
            parse_effect(bad)


def test_the_envelope_interpolates_in_db_and_holds_the_ends():
    envelope = Envelope(points=[{"at": 10, "db": 0}, {"at": 12, "db": -12}])
    assert [envelope.gain_db_at(t) for t in (0, 10, 11, 12, 20)] == [0, 0, -6, -12, -12]


def test_the_envelope_expression_is_a_nested_if_that_matches_the_points():
    envelope = Envelope(points=[{"at": 10, "db": 0}, {"at": 12, "db": -12}])
    expression = envelope_gain_expression(envelope.points)
    assert expression.startswith("if(lt(t,(10.000000)),(0.000000),") and expression.endswith(")")
    assert "(-6.000000)*(t-(10.000000))" in expression  # a inclinação: -6 dB por segundo
    request = EffectRequest(envelope, "[in]", "[out]", "t", 20.0)
    (line,) = build_effect(request)
    assert line.startswith("[in]asetnsamples=n=64:p=0,volume='pow(10,(if(") and line.endswith(
        ":precision=float[out]"
    )
    flat = build_effect(
        EffectRequest(Envelope(points=[{"at": 0, "db": -3}, {"at": 5, "db": -3}]), "[in]", "[out]", "t", 5.0)
    )
    assert flat == ["[in]volume=-3.000000dB[out]"]  # curva reta: um ganho só


def test_cut_needs_an_interval_and_shrinks_the_item_only_without_the_silence_fill():
    with pytest.raises(ValidationError, match="start. e .end"):
        Cut()
    keeps = Cut(start=2, end=5)
    shrinks = Cut(start=2, end=5, keep_length=False)
    assert chain_duration([keeps], 10.0) == 10.0 and chain_duration([shrinks], 10.0) == 7.0
    assert (
        chain_duration([Cut(start=8, end=20, keep_length=False)], 10.0) == 8.0
    )  # o que passa do fim não conta
    assert not keeps.alters_duration() and shrinks.alters_duration()


def test_a_cut_that_shrinks_the_item_is_only_accepted_where_the_item_may_grow():
    ClipSegment(src="a.mp4", effects=[{"type": "cut", "start": 1, "end": 2}])
    with pytest.raises(ValidationError, match="muda a duração"):
        ClipSegment(src="a.mp4", effects=[{"type": "cut", "start": 1, "end": 2, "keep_length": False}])
    Project.model_validate(
        {
            "name": "x",
            "timeline": [{"type": "card", "title": "t"}],
            "audio": {
                "voiceover": [
                    {"src": "v.wav", "effects": [{"type": "cut", "start": 1, "end": 2, "keep_length": False}]}
                ]
            },
        }
    )


def test_the_cut_and_the_channels_graphs_are_pure_and_correct():
    cut = Cut(start=1.0, end=2.0)  # um item de 4 s: 48000 a 96000
    middle = build_effect(EffectRequest(cut, "[in]", "[out]", "t", 4.0))
    text = ";".join(middle)
    assert "atrim=end_sample=48000" in text and "atrim=start_sample=96000" in text
    assert "concat=n=2:v=0:a=1,apad=whole_len=192000[out]" in text  # completa até o tamanho de antes
    shrink = ";".join(
        build_effect(EffectRequest(Cut(start=1.0, end=2.0, keep_length=False), "[in]", "[out]", "t", 4.0))
    )
    assert "apad" not in shrink and "concat=n=2:v=0:a=1[out]" in shrink
    head_only = build_effect(EffectRequest(Cut(start=3.0, end=4.0), "[in]", "[out]", "t", 4.0))
    assert head_only == ["[in]atrim=end_sample=144000,asetpts=PTS-STARTPTS,apad=whole_len=192000[out]"]
    outside = build_effect(EffectRequest(Cut(start=9.0, end=10.0), "[in]", "[out]", "t", 4.0))
    assert outside == ["[in]anull[out]"]
    for mode, pan in (
        ("mono", "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1"),
        ("swap", "pan=stereo|c0=c1|c1=c0"),
        ("left", "pan=stereo|c0=c0|c1=c0"),
        ("right", "pan=stereo|c0=c1|c1=c1"),
    ):
        assert build_effect(EffectRequest(Channels(mode=mode), "[in]", "[out]", "t", 4.0)) == [
            f"[in]{pan}[out]"
        ]


def test_silence_inside_an_interval_uses_the_seam_and_the_interval_is_the_effect_s_own_for_cut_and_envelope():
    from dmaker.filtergraph.audio_effects import chain_lines

    lines = chain_lines("[in]", "[out]", [parse_effect({"type": "silence", "start": 1, "end": 2})], 4.0)
    text = ";".join(lines)
    assert "volume=0" in text and "afade=t=in" in text and "amix=inputs=3" in text  # a emenda de 10 ms
    cut = chain_lines("[in]", "[out]", [parse_effect({"type": "cut", "start": 1, "end": 2})], 4.0)
    assert "amix" not in ";".join(cut) and "afade" not in ";".join(
        cut
    )  # o corte não leva emenda: ele é o intervalo


# ---------- projeto antigo igual: campo no padrão fica fora do dump ----------


def test_the_new_fields_stay_out_of_the_dump_and_the_saved_spec_while_they_have_the_default():
    plain = project(
        audio={"music": {"src": "m.wav"}, "narration": [{"text": "oi"}], "voiceover": [{"src": "v.wav"}]},
        overlays=[{"type": "video", "src": "p.mp4"}],
        tracks={"A1": {"muted": True}},
    )
    dumped = json.loads(plain.to_bytes())
    saved = plain.to_bytes().decode("utf-8")
    for blocked in ("audio_offset", "pan", "gain_db", "solo", "sfx_gain_db", "sfx_pan"):
        assert f'"{blocked}"' not in saved
    assert dumped["tracks"]["A1"] == {"muted": True, "hidden": False, "locked": False}
    moved = project(
        timeline=[{"type": "clip", "src": "a.mp4", "audio_offset": 0.25, "pan": -1}],
        audio={"tracks": [{"source": "m", "audio_offset": -1.5, "pan": 0.5}], "sfx_gain_db": -3},
        sources={"m": {"src": "m.wav"}},
        overlays=[{"type": "video", "src": "p.mp4", "audio_offset": 0.1}],
        tracks={"MUS": {"gain_db": -6, "pan": 1, "solo": True}},
    )
    back = Project.from_bytes(moved.to_bytes(), Path("."))
    assert (back.timeline[0].audio_offset, back.timeline[0].pan) == (0.25, -1.0)
    assert (back.audio.tracks[0].audio_offset, back.audio.tracks[0].pan) == (-1.5, 0.5)
    assert back.overlays[0].audio_offset == 0.1 and back.audio.sfx_gain_db == -3
    assert back.tracks["MUS"] == TrackState(gain_db=-6, pan=1, solo=True)


def test_the_cache_keys_of_a_clip_and_of_the_mix_follow_the_new_fields_only_when_they_are_set():
    plain, shifted = ClipSegment(src="a.mp4"), ClipSegment(src="a.mp4", audio_offset=0.2)
    panned = ClipSegment(src="a.mp4", pan=0.4)
    assert piece_recipe(plain) == piece_recipe(ClipSegment(src="a.mp4", audio_offset=0.0, pan=0.0))
    assert piece_recipe(plain) != piece_recipe(shifted) != piece_recipe(panned)
    assert plain.model_dump(mode="json") != shifted.model_dump(mode="json")


def test_the_preview_mix_recipe_follows_the_item_pan_and_the_track_state_through_the_applied_spec():
    base = project(audio={"music": {"src": "m.wav"}})
    keys = {
        json.dumps(mix_recipe(apply_track_state(variant)), sort_keys=True)
        for variant in (
            base,
            project(audio={"music": {"src": "m.wav"}}, tracks={"MUS": {"gain_db": -6}}),
            project(audio={"music": {"src": "m.wav"}}, tracks={"MUS": {"pan": 0.5}}),
            project(audio={"music": {"src": "m.wav", "pan": 0.6}}),
            project(audio={"music": {"src": "m.wav"}}, tracks={"A1": {"solo": True}}),
        )
    }
    assert len(keys) == 5


# ---------- o estado da trilha ----------


def test_track_gain_and_pan_are_embedded_in_the_items_and_the_original_is_left_alone():
    original = project(
        audio={
            "music": {"src": "m.wav", "volume": 0.5},
            "narration": [{"text": "oi", "pan": 0.5}],
            "voiceover": [{"src": "v.wav", "volume": 2.0}],
            "tracks": [{"source": "mesa", "volume": 1.0}],
        },
        sources={"mesa": {"src": "mesa.wav"}},
        tracks={
            "A1": {"gain_db": 6.0206, "pan": -0.5},
            "A2": {"gain_db": -6.0206},
            "MUS": {"gain_db": -6.0206, "pan": 1},
            "NAR": {"pan": 0.75},
            "VO": {"gain_db": 6.0206},
            "SFX": {"gain_db": -3, "pan": -1},
        },
    )
    applied = apply_track_state(original)
    assert applied.timeline[0].volume == pytest.approx(2.0, rel=1e-4) and applied.timeline[0].pan == -0.5
    assert applied.audio.tracks[0].volume == pytest.approx(0.5, rel=1e-4)
    assert applied.audio.music.volume == pytest.approx(0.25, rel=1e-4) and applied.audio.music.pan == 1.0
    assert applied.audio.narration[0].pan == 1.0  # 0,5 do item + 0,75 da trilha, preso a 1
    assert applied.audio.voiceover[0].volume == pytest.approx(4.0, rel=1e-4)
    assert (applied.audio.sfx_gain_db, applied.audio.sfx_pan) == (-3.0, -1.0)
    assert (
        original.timeline[0].volume == 1.0 and original.audio.music.volume == 0.5
    )  # a spec original não muda


def test_a_state_that_changes_nothing_returns_the_same_project():
    neutral = project(
        audio={"music": {"src": "m.wav"}}, tracks={"MUS": {"locked": True}, "A1": {"hidden": True}}
    )
    assert apply_track_state(neutral) is neutral


def test_solo_silences_every_other_audio_track_through_the_same_path_as_mute():
    base = {
        "audio": {
            "music": {"src": "m.wav"},
            "narration": [{"text": "oi"}],
            "voiceover": [{"src": "v.wav"}],
            "tracks": [{"source": "mesa"}, {"source": "mesa"}],
        },
        "sources": {"mesa": {"src": "mesa.wav"}},
    }
    soloed_music = project(**base, tracks={"MUS": {"solo": True}})
    assert silenced_audio_tracks(soloed_music) == {"A1", "A2", "A3", "NAR", "VO", "SFX"}
    applied = apply_track_state(soloed_music)
    assert applied.audio.mute_clips and applied.audio.tracks == [] and applied.audio.narration == []
    assert (
        applied.audio.voiceover == []
        and applied.audio.music is not None
        and applied.audio.sfx_gain_db == -120.0
    )
    two = project(**base, tracks={"MUS": {"solo": True}, "VO": {"solo": True}})
    assert silenced_audio_tracks(two) == {
        "A1",
        "A2",
        "A3",
        "NAR",
        "SFX",
    }  # solo em duas trilhas: só essas soam
    assert (
        silenced_audio_tracks(project(**base, tracks={"V1": {"solo": True}})) == set()
    )  # solo de vídeo não vale
    muted_and_soloed = project(**base, tracks={"MUS": {"solo": True, "muted": True}})
    assert apply_track_state(muted_and_soloed).audio.music is None  # mudo ganha do solo


def test_the_audio_track_ids_follow_the_project_and_the_sfx_bus_is_a_known_track():
    minimal = project()
    assert audio_track_ids(minimal) == ["A1", "SFX"] and "SFX" in known_track_ids(minimal)
    full = project(
        audio={
            "music": {"src": "m.wav"},
            "narration": [{"text": "oi"}],
            "voiceover": [{"src": "v.wav"}],
            "tracks": [{"source": "m"}],
        },
        sources={"m": {"src": "m.wav"}},
    )
    assert audio_track_ids(full) == ["A1", "A2", "NAR", "VO", "MUS", "SFX"]


def test_the_timeline_view_carries_the_mix_state_and_marks_what_does_not_sound():
    view = project_timeline_view(
        project(
            audio={"music": {"src": "m.wav", "pan": 0.5}, "voiceover": [{"src": "v.wav", "pan": -0.5}]},
            timeline=[{"type": "card", "title": "t", "duration": 5}],
            tracks={"MUS": {"gain_db": -6, "pan": 0.25, "solo": True}},
        ),
        prober=lambda path: MediaInfo(path, 3.0, 0, 0, 30.0, False, True, False),
    ).to_dict()
    tracks = {track["id"]: track for track in view["tracks"]}
    assert (tracks["MUS"]["gain_db"], tracks["MUS"]["pan"], tracks["MUS"]["solo"]) == (-6.0, 0.25, True)
    assert tracks["MUS"]["silenced"] is False and tracks["VO"]["silenced"] is True
    assert tracks["VO"]["items"][0]["muted"] is True  # o solo da música cala a voz
    assert (
        tracks["MUS"]["items"][0]["extra"]["pan"] == 0.5 and tracks["VO"]["items"][0]["extra"]["pan"] == -0.5
    )


# ---------- equilíbrio e deslocamento ----------


def test_the_pan_gains_follow_the_audacity_law_the_side_it_goes_to_stays_and_the_other_falls():
    assert pan_gains(0.0) == (1.0, 1.0)
    assert pan_gains(-1.0) == (1.0, 0.0) and pan_gains(1.0) == (0.0, 1.0)
    assert pan_gains(-0.25) == (1.0, 0.75) and pan_gains(0.5) == (0.5, 1.0)
    assert pan_filter(0.0) is None
    assert pan_filter(-1.0) == "pan=stereo|c0=1.000000*c0|c1=0.000000*c1"


def test_the_shifted_window_reads_older_sound_to_delay_and_newer_sound_to_advance():
    delayed = shifted_window(10.0, 1.0, 0.5)
    assert (delayed.read_from, delayed.lead) == (9.5, 0.0)
    advanced = shifted_window(10.0, 1.0, -0.5)
    assert (advanced.read_from, advanced.lead) == (10.5, 0.0)
    before_the_file = shifted_window(0.2, 1.0, 1.0)
    assert (before_the_file.read_from, round(before_the_file.lead, 6)) == (
        0.0,
        0.8,
    )  # 0,8 s de silêncio antes
    fast = shifted_window(10.0, 2.0, 0.5)
    assert fast.read_from == 9.0  # 0,5 s da linha do tempo são 1 s de fonte


# ---------- os grafos ----------


def info() -> MediaInfo:
    return MediaInfo(Path("a.mp4"), 10.0, 1280, 720, 30.0, True, True, False)


def audio_lines(segment: ClipSegment, **kwargs) -> tuple[list[str], list[str]]:
    inputs, lines = Inputs(), []
    index = inputs.add(Path("a.mp4"), "-ss", "2.000", "-t", "5.000")
    clip_audio_lines(inputs, lines, segment, info(), 5.0, 5.0, source_index=index, **kwargs)
    return inputs.args, lines


def test_a_clip_without_offset_or_pan_builds_the_same_audio_branch_as_before():
    args, lines = audio_lines(ClipSegment(src="a.mp4", start=2, end=7), src=Path("a.mp4"), in_point=2.0)
    assert args == [
        "-ss",
        "2.000",
        "-t",
        "5.000",
        "-i",
        "a.mp4",
    ]  # a entrada compartilhada com o vídeo, só uma
    assert lines[0] == (
        "[0:a:0]asetpts=PTS-STARTPTS,atrim=0:5.000,aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo[mz_cam]"
    )
    assert lines[1] == "[mz_cam]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo[aout]"


def test_a_clip_with_offset_reads_the_file_from_the_shifted_point_in_its_own_input_and_pads_the_end():
    segment = ClipSegment(src="a.mp4", start=2, end=7, audio_offset=0.5)
    args, lines = audio_lines(segment, src=Path("a.mp4"), in_point=2.0)
    assert args[6:] == ["-ss", "1.500", "-t", "5.000", "-i", "a.mp4"]  # a segunda entrada, lida 0,5 s antes
    assert (
        "[1:a:0]asetpts=PTS-STARTPTS,apad,atrim=0:5.000" in lines[0]
    )  # a entrada própria, completada com silêncio
    early = ClipSegment(src="a.mp4", start=0.2, end=5, audio_offset=1.0)
    _, lines = audio_lines(early, src=Path("a.mp4"), in_point=0.2)
    assert "adelay=800:all=1" in lines[0]  # 0,8 s de silêncio antes de o arquivo começar


def test_a_clip_with_pan_filters_the_balance_after_the_gain():
    _, lines = audio_lines(
        ClipSegment(src="a.mp4", start=2, end=7, volume=0.5, pan=-1), src=Path("a.mp4"), in_point=2.0
    )
    assert "volume=0.500,pan=stereo|c0=1.000000*c0|c1=0.000000*c1,atrim=0:5.000" in lines[0]


def test_an_external_track_slice_carries_the_pan():
    inputs, lines = Inputs(), []
    piece = TrackSlice(Path("mesa.wav"), 3.0, 0.8, 0, 0.5)
    clip_audio_lines(
        inputs, lines, ClipSegment(src="a.mp4", mute=True), info(), 5.0, 5.0, source_index=-1, tracks=(piece,)
    )
    assert any("volume=0.800,pan=stereo|c0=0.500000*c0|c1=1.000000*c1" in line for line in lines)


def test_a_track_slice_moves_with_the_track_offset_and_the_coverage_follows():
    from dmaker.pipeline.sources import Source

    source = Source(
        Path("mesa.wav"), MediaInfo(Path("mesa.wav"), 40.0, 0, 0, 0.0, False, True, False), 5.0, 0, "mesa"
    )
    segment = ClipSegment(source="mesa", start=10, end=20)
    plain = track_slice(AudioTrack(source="mesa"), source, segment)
    delayed = track_slice(AudioTrack(source="mesa", audio_offset=2.0, pan=-0.5), source, segment)
    assert plain.in_point == 5.0 and delayed.in_point == 3.0 and delayed.pan == -0.5
    late = ClipSegment(source="mesa", start=46, end=50)  # a gravação acaba em 45 s da sessão
    assert source_covers(source, late, 0.0) is False
    assert source_covers(source, late, 2.0) is True  # atrasada 2 s, o trecho toca o que ela gravou 2 s antes


def test_a_pip_with_offset_opens_its_own_audio_input_and_delays_by_the_lead():
    overlay = VideoOverlay(src="cam.mp4", start=2.0, end=6.0, audio_offset=0.5)
    pip = ResolvedVideoOverlay(overlay, Path("cam.mp4"), 1.0, 2.0, 6.0, 300, 200, Path("m.png"), None, 0)
    inputs, lines = Inputs(), []
    labels = pip_audio_graph(lines, inputs, [pip])
    assert labels == ["[pipaud0]"] and inputs.args[:2] == [
        "-ss",
        "0.500",
    ]  # lê 0,5 s antes do ponto da imagem
    early = VideoOverlay(src="cam.mp4", start=2.0, end=6.0, audio_offset=2.0)
    pip = ResolvedVideoOverlay(early, Path("cam.mp4"), 1.0, 2.0, 6.0, 300, 200, Path("m.png"), None, 0)
    lines = []
    pip_audio_graph(lines, Inputs(), [pip])
    assert "adelay=3000:all=1" in lines[0]  # 2 s de entrada + 1 s de silêncio antes de o arquivo começar


def test_the_music_the_narration_and_the_voice_files_filter_their_pan_in_the_mix():
    from dmaker.pipeline.voicefiles import PreparedVoiceFile
    from dmaker.pipeline.voiceover import PreparedVoiceover

    audio = project(audio={"music": {"src": "m.wav", "pan": 0.5, "ducking": False}}).audio
    lines: list[str] = []
    audio_graph(
        lines,
        Inputs(),
        "[a]",
        audio,
        Path("m.wav"),
        10.0,
        narrations=[PreparedVoiceover(Path("n.wav"), 1.0, 1.0, 2.0, pan=-1.0)],
        voice_files=[PreparedVoiceFile(Path("v.wav"), 0.0, 0.0, 2.0, 1.0, "v.wav", 0.25)],
    )
    text = ";".join(lines)
    assert "volume=0.180,pan=stereo|c0=0.500000*c0|c1=1.000000*c1" in text  # a música
    assert "pan=stereo|c0=1.000000*c0|c1=0.000000*c1,adelay" in text  # a narração
    assert "pan=stereo|c0=0.750000*c0|c1=1.000000*c1,adelay" not in text  # a voz sem atraso não leva adelay
    assert "pan=stereo|c0=0.750000*c0|c1=1.000000*c1[vf0]" in text


def test_the_sfx_levels_carry_the_bus_gain_and_pan():
    from dmaker.domain.sfx import SfxItem

    resolved = [(SfxItem("pop", 1.0, 1.0, "audio.sfx[0]"), Path("pop.wav"))]
    plain = level_tracks(resolved, -6.0)
    louder = level_tracks(resolved, -6.0, bus_gain_db=-3.0, bus_pan=0.5)
    assert (
        louder[0].gain_db == pytest.approx(plain[0].gain_db - 3.0)
        and louder[0].pan == 0.5
        and plain[0].pan == 0.0
    )
