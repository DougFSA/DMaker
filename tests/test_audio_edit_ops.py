"""Edição de onda no `edit_project`: o que cada operação põe na spec, sem ffmpeg (a sonda é falsa).

O tempo dos pedidos é o da linha do tempo final (aceita `marker:<texto>`); a spec guarda o tempo do item. Os testes de
som de verdade, com tons gerados e medidos, estão em `test_audio_edit_integration.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.audio_edits import rebase_effects, stitch_effects
from dmaker.domain.audio_effects import parse_effect
from dmaker.domain.edits import EditError
from dmaker.domain.spec import Project
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.edits import apply_edit, apply_edit_report

DURATIONS = {"video.mp4": 10.0, "fala.wav": 6.0, "musica.wav": 30.0, "mesa.wav": 40.0}


def prober(path: Path) -> MediaInfo:
    video = path.suffix == ".mp4"
    return MediaInfo(
        path,
        DURATIONS.get(path.name, 5.0),
        1280 if video else 0,
        720 if video else 0,
        30.0,
        video,
        True,
        False,
    )


@pytest.fixture
def folder(tmp_path) -> Path:
    for name in DURATIONS:
        (tmp_path / name).write_bytes(b"\x00" * 16)
    return tmp_path


def make(folder: Path, **parts) -> Project:
    data = {
        "name": "edicao-de-onda",
        "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 10}],
        **parts,
    }
    project = Project.model_validate(data)
    project.base_dir = folder
    return project


def edit(project: Project, **op) -> Project:
    return apply_edit(project, op, prober=prober)


def chain(items) -> list[tuple]:
    return [(effect.type, effect.start, effect.end) for effect in items]


# ---------- silenciar ----------


def test_silencing_two_seconds_of_a_clip_adds_a_silence_with_the_interval_in_item_time(folder):
    project = make(folder)
    edited = edit(project, type="audio_silence", target="timeline.0", start=4, end=6)
    assert chain(edited.timeline[0].effects) == [("silence", 4.0, 6.0)]
    assert project.timeline[0].effects == []  # a spec original não muda


def test_the_interval_of_a_sped_up_clip_is_converted_to_source_time(folder):
    project = make(folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 10, "speed": 2}])
    edited = edit(project, type="audio_silence", target="timeline.0", start=1, end=2)
    assert chain(edited.timeline[0].effects) == [("silence", 2.0, 4.0)]  # 1 s de vídeo são 2 s de fonte


def test_the_interval_of_the_second_clip_counts_from_where_that_clip_starts(folder):
    project = make(
        folder,
        timeline=[
            {"type": "clip", "src": "video.mp4", "start": 0, "end": 5},
            {"type": "clip", "src": "video.mp4", "start": 5, "end": 10},
        ],
    )
    edited = edit(project, type="audio_silence", target="timeline.1", start=6, end=7.5)
    assert chain(edited.timeline[1].effects) == [("silence", 1.0, 2.5)]
    assert edited.timeline[0].effects == []


def test_the_instants_accept_marker_references_and_regions(folder):
    project = make(
        folder,
        markers=[
            {"at": 2.0, "text": "início"},
            {"at": 3.5, "text": "fim"},
            {"start": 7.0, "end": 8.0, "text": "tosse"},
        ],
    )
    edited = edit(project, type="audio_silence", target="timeline.0", start="marker:início", end="marker:fim")
    assert chain(edited.timeline[0].effects) == [("silence", 2.0, 3.5)]
    by_region = edit(project, type="audio_silence", target="timeline.0", region="marker:tosse")
    assert chain(by_region.timeline[0].effects) == [("silence", 7.0, 8.0)]
    with pytest.raises(EditError, match="é um instante"):
        edit(project, type="audio_silence", target="timeline.0", region="marker:início")


def test_silencing_does_not_move_the_markers_because_the_video_time_does_not_change(folder):
    project = make(folder, markers=[{"at": 5.0, "text": "A"}])
    report = apply_edit_report(
        project, {"type": "audio_silence", "target": "timeline.0", "start": 1, "end": 2}, prober
    )
    assert report.project.markers == project.markers and report.warnings == []


@pytest.mark.parametrize(
    ("op", "message"),
    [
        ({"target": "timeline.0", "start": 6, "end": 4}, "maior que"),
        ({"target": "timeline.0", "start": 20, "end": 22}, "não pega"),
        ({"target": "timeline.5", "start": 1, "end": 2}, "fora do intervalo"),
        ({"target": "audio.voiceover.0", "start": 1, "end": 2}, "fora do intervalo"),
        ({"target": "oi", "start": 1, "end": 2}, "alvo de áudio inválido"),
        ({"start": 1, "end": 2}, "precisa do campo `target`"),
        ({"target": "timeline.0", "start": 1}, "precisa do campo `end`"),
    ],
)
def test_a_bad_silence_request_is_refused_in_portuguese(folder, op, message):
    with pytest.raises(EditError, match=message):
        edit(make(folder), type="audio_silence", **op)


def test_a_clip_from_a_source_with_parts_refuses_interval_edits_and_says_why(folder):
    project = make(
        folder,
        sources={"cam": {"parts": ["video.mp4", "video.mp4"]}},
        timeline=[{"type": "clip", "source": "cam", "start": 0, "end": 8}],
    )
    with pytest.raises(EditError, match="várias partes"):
        edit(project, type="audio_silence", target="timeline.0", start=1, end=2)
    mono = edit(
        project, type="audio_channels", target="timeline.0", mode="left"
    )  # o item inteiro segue valendo
    assert [e.type for e in mono.timeline[0].effects] == ["channels"]


# ---------- cortar ----------


def voice_project(folder: Path, **voice) -> Project:
    return make(folder, audio={"voiceover": [{"src": "fala.wav", "start": 2.0, **voice}], "normalize": "off"})


def test_cutting_a_clip_keeps_its_length_and_completes_with_silence(folder):
    edited = edit(make(folder), type="audio_cut", target="timeline.0", start=3, end=5)
    cut = edited.timeline[0].effects[0]
    assert (cut.type, cut.start, cut.end, cut.keep_length) == ("cut", 3.0, 5.0, True)


def test_cutting_a_recorded_voice_shrinks_it_and_pulls_the_next_ones_of_the_track_back(folder):
    project = make(
        folder,
        audio={
            "voiceover": [
                {"src": "fala.wav", "start": 2.0},
                {"src": "fala.wav", "start": 10.0},
                {"src": "fala.wav", "start": 4.0},
            ],
            "normalize": "off",
        },
    )
    edited = edit(
        project, type="audio_cut", target="audio.voiceover.0", start=3, end=4.5
    )  # 1 a 2,5 s do item
    cut = edited.audio.voiceover[0].effects[0]
    assert (cut.type, cut.start, cut.end, cut.keep_length) == ("cut", 1.0, 2.5, False)
    # o que começa depois do corte recua 1,5 s; o que começa dentro do trecho cortado (4 s) fica onde estava
    assert [clip.start for clip in edited.audio.voiceover] == [2.0, 8.5, 4.0]


def test_cutting_the_whole_item_is_refused(folder):
    with pytest.raises(EditError, match="inteiro"):
        edit(voice_project(folder), type="audio_cut", target="audio.voiceover.0", start=0, end=20)


def test_the_external_track_and_the_master_do_not_accept_cuts(folder):
    project = make(
        folder,
        sources={"cam": {"src": "video.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
        timeline=[{"type": "clip", "source": "cam", "start": 0, "end": 8}],
        audio={"tracks": [{"source": "mesa"}]},
    )
    with pytest.raises(EditError, match="não aceita cortar"):
        edit(project, type="audio_cut", target="audio.tracks.0", start=1, end=2)
    with pytest.raises(EditError, match="não aceita cortar"):
        edit(project, type="audio_cut", target="audio.master", start=1, end=2)


# ---------- envelope ----------


def test_an_envelope_takes_points_in_timeline_time_and_stores_them_in_item_time(folder):
    project = make(folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 10}])
    edited = edit(
        project, type="audio_envelope", target="timeline.0", points=[{"at": 6, "db": 0}, {"at": 8, "db": -12}]
    )
    envelope = edited.timeline[0].effects[0]
    assert envelope.type == "envelope"
    assert [(point.at, point.db) for point in envelope.points] == [(6.0, 0.0), (8.0, -12.0)]
    assert envelope.gain_db_at(7.0) == pytest.approx(-6.0)  # reta em dB


def test_new_envelope_points_merge_into_the_existing_curve_replacing_the_same_stretch(folder):
    first = edit(
        make(folder),
        type="audio_envelope",
        target="timeline.0",
        points=[{"at": 1, "db": 0}, {"at": 3, "db": -6}, {"at": 9, "db": -6}],
    )
    merged = edit(
        first, type="audio_envelope", target="timeline.0", points=[{"at": 2, "db": -20}, {"at": 4, "db": 0}]
    )
    envelopes = [e for e in merged.timeline[0].effects if e.type == "envelope"]
    assert len(envelopes) == 1
    assert [(p.at, p.db) for p in envelopes[0].points] == [(1.0, 0.0), (2.0, -20.0), (4.0, 0.0), (9.0, -6.0)]


def test_an_envelope_on_the_music_raises_it_at_the_end_in_file_time(folder):
    project = make(folder, audio={"music": {"src": "musica.wav", "start_at": 5.0}, "normalize": "off"})
    edited = edit(
        project,
        type="audio_envelope",
        target="audio.music",
        points=[{"at": 6, "db": -12}, {"at": 9, "db": 0}],
    )
    points = edited.audio.music.effects[0].points
    assert [(p.at, p.db) for p in points] == [(11.0, -12.0), (14.0, 0.0)]  # 5 s de entrada na música somados


def test_a_bad_envelope_is_refused(folder):
    with pytest.raises(EditError, match="precisa de `at`"):
        edit(make(folder), type="audio_envelope", target="timeline.0", points=[{"at": 1}])
    with pytest.raises(EditError, match="lista de pontos"):
        edit(make(folder), type="audio_envelope", target="timeline.0", points=[])
    with pytest.raises(EditError, match="mesmo instante"):
        edit(
            make(folder),
            type="audio_envelope",
            target="timeline.0",
            points=[{"at": 1, "db": 0}, {"at": 1, "db": -3}],
        )


# ---------- canais ----------


def test_channels_on_the_whole_item_or_on_an_interval(folder):
    project = make(folder)
    whole = edit(project, type="audio_channels", target="timeline.0", mode="left")
    assert [(e.type, e.mode, e.start, e.end) for e in whole.timeline[0].effects] == [
        ("channels", "left", None, None)
    ]
    part = edit(project, type="audio_channels", target="timeline.0", mode="mono", start=2, end=4)
    assert part.timeline[0].effects[0].start == 2.0
    with pytest.raises(EditError, match="modo de canais desconhecido"):
        edit(project, type="audio_channels", target="timeline.0", mode="surround")


def test_splitting_the_stereo_of_an_external_track_makes_two_tracks_panned_to_each_side(folder):
    project = make(
        folder,
        sources={"cam": {"src": "video.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
        timeline=[{"type": "clip", "source": "cam", "start": 0, "end": 8}],
        audio={"tracks": [{"source": "mesa"}]},
    )
    edited = edit(project, type="audio_split_stereo", target="audio.tracks.0")
    assert [t.effects[0].mode for t in edited.audio.tracks] == ["left", "right"]
    assert (edited.tracks["A2"].pan, edited.tracks["A3"].pan) == (-1.0, 1.0)


def test_splitting_the_stereo_of_a_recorded_voice_makes_two_items_of_the_same_stretch(folder):
    edited = edit(voice_project(folder), type="audio_split_stereo", target="audio.voiceover.0")
    assert [clip.effects[0].mode for clip in edited.audio.voiceover] == ["left", "right"]
    assert edited.audio.voiceover[0].src == edited.audio.voiceover[1].src
    with pytest.raises(EditError, match="vale para a voz gravada"):
        edit(make(folder), type="audio_split_stereo", target="timeline.0")


# ---------- copiar, colar, duplicar ----------


def test_pasting_a_recorded_voice_stretch_makes_a_new_item_on_the_same_file(folder):
    project = voice_project(folder)  # 6 s de fala começando em 2 s
    pasted = edit(project, type="audio_paste", target="audio.voiceover.0", start=3, end=6, at=20)
    assert len(pasted.audio.voiceover) == 2
    new = pasted.audio.voiceover[1]
    assert (new.src, new.start, new.offset, new.end) == ("fala.wav", 20.0, 1.0, 4.0)  # 1 a 4 s do arquivo


def test_the_pasted_stretch_carries_the_effects_cut_down_to_it(folder):
    project = voice_project(
        folder,
        effects=[{"type": "silence", "start": 2, "end": 3.5}, {"type": "silence", "start": 5.5, "end": 6}],
    )
    pasted = edit(
        project, type="audio_paste", target="audio.voiceover.0", start=3, end=6, at=20
    )  # item 1 a 4 s
    assert chain(pasted.audio.voiceover[1].effects) == [
        ("silence", 1.0, 2.5)
    ]  # o silêncio anda 1 s; o outro cai fora


def test_pasting_accepts_a_marker_for_where_it_goes(folder):
    project = make(folder, audio={"voiceover": [{"src": "fala.wav"}]}, markers=[{"at": 12.0, "text": "aqui"}])
    pasted = edit(project, type="audio_paste", target="audio.voiceover.0", start=1, end=2, at="marker:aqui")
    assert pasted.audio.voiceover[1].start == 12.0


def test_the_sound_of_a_video_clip_can_be_pasted_as_a_recorded_voice(folder):
    project = make(
        folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 2, "end": 9, "volume": 0.8}]
    )
    pasted = edit(project, type="audio_paste", target="timeline.0", start=1, end=4, at=0)
    new = pasted.audio.voiceover[0]
    assert (new.src, new.offset, new.end, new.volume) == (
        "video.mp4",
        3.0,
        6.0,
        0.8,
    )  # o clipe começa em 2 s da fonte


def test_a_shifted_clip_pastes_the_sound_that_is_heard_there(folder):
    project = make(
        folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 2, "end": 9, "audio_offset": 0.5}]
    )
    pasted = edit(project, type="audio_paste", target="timeline.0", start=1, end=4, at=0)
    new = pasted.audio.voiceover[0]
    assert (new.offset, new.end) == (2.5, 5.5)  # o som atrasado 0,5 s vem de 0,5 s antes na fonte


def test_a_paste_that_starts_before_the_file_waits_for_the_missing_stretch(folder):
    project = make(
        folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 9, "audio_offset": 1.0}]
    )
    pasted = edit(project, type="audio_paste", target="timeline.0", start=0, end=3, at=10)
    new = pasted.audio.voiceover[0]
    assert (new.start, new.offset, new.end) == (11.0, 0.0, 2.0)  # 1 s de silêncio antes de a fonte começar


def test_duplicating_pastes_right_after_the_original(folder):
    project = voice_project(folder)
    whole = edit(project, type="audio_duplicate", target="audio.voiceover.0")
    assert (whole.audio.voiceover[1].start, whole.audio.voiceover[1].offset) == (8.0, 0.0)  # 2 s + 6 s
    part = edit(project, type="audio_duplicate", target="audio.voiceover.0", start=3, end=5)
    assert part.audio.voiceover[1].start == 5.0


@pytest.mark.parametrize(
    ("audio", "target", "message"),
    [
        ({"narration": [{"text": "oi"}]}, "audio.narration.0", "sintetizada"),
        ({"music": {"src": "musica.wav"}}, "audio.master", "mistura"),
    ],
)
def test_what_has_no_file_to_copy_is_refused(folder, audio, target, message):
    with pytest.raises(EditError, match=message):
        edit(make(folder, audio=audio), type="audio_paste", target=target, start=1, end=2, at=0)


def test_a_sped_up_clip_cannot_be_copied_because_the_new_item_would_play_at_normal_speed(folder):
    project = make(folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 10, "speed": 2}])
    with pytest.raises(EditError, match="velocidade"):
        edit(project, type="audio_paste", target="timeline.0", start=0, end=1, at=0)


# ---------- dividir e juntar ----------


def test_splitting_a_recorded_voice_makes_two_items_that_meet_at_the_point(folder):
    project = voice_project(folder, effects=[{"type": "silence", "start": 1, "end": 5}])
    edited = edit(project, type="audio_split", target="audio.voiceover.0", at=5)  # 3 s do item
    first, second = edited.audio.voiceover
    assert (first.start, first.offset, first.end) == (2.0, 0.0, 3.0)
    assert (second.start, second.offset, second.end) == (5.0, 3.0, None)
    assert chain(first.effects) == [("silence", 1.0, None)] and chain(second.effects) == [
        ("silence", None, 2.0)
    ]


def test_joining_what_was_split_gives_back_the_original_item(folder):
    project = voice_project(
        folder, effects=[{"type": "silence", "start": 1, "end": 5}, {"type": "amplify", "gain_db": 3}]
    )
    again = edit(
        edit(project, type="audio_split", target="audio.voiceover.0", at=5),
        type="audio_join",
        target="audio.voiceover.0",
    )
    assert again.to_bytes() == project.to_bytes()


def test_joining_refuses_pieces_that_do_not_continue_each_other_and_says_which_condition_failed(folder):
    two = make(
        folder,
        audio={
            "voiceover": [
                {"src": "fala.wav", "start": 0, "offset": 0, "end": 2},
                {"src": "fala.wav", "start": 2, "offset": 3, "end": 5},
            ]
        },
    )
    with pytest.raises(EditError, match="não são seguidos"):
        edit(two, type="audio_join", target="audio.voiceover.0")
    apart = make(
        folder,
        audio={
            "voiceover": [
                {"src": "fala.wav", "start": 0, "offset": 0, "end": 2},
                {"src": "fala.wav", "start": 9, "offset": 2, "end": 5},
            ]
        },
    )
    with pytest.raises(EditError, match="não se encostam"):
        edit(apart, type="audio_join", target="audio.voiceover.0")
    other = make(
        folder,
        audio={
            "voiceover": [
                {"src": "fala.wav", "start": 0, "offset": 0, "end": 2},
                {"src": "musica.wav", "start": 2, "offset": 2, "end": 5},
            ]
        },
    )
    with pytest.raises(EditError, match="mesmo arquivo"):
        edit(other, type="audio_join", target="audio.voiceover.0")


def test_splitting_and_joining_only_apply_to_the_recorded_voice(folder):
    with pytest.raises(EditError, match="só vale para a voz gravada"):
        edit(make(folder), type="audio_split", target="timeline.0", at=3)
    with pytest.raises(EditError, match="troca o tempo do som de lugar"):
        edit(
            voice_project(folder, effects=[{"type": "reverse"}]),
            type="audio_split",
            target="audio.voiceover.0",
            at=4,
        )


# ---------- aparar fora da seleção ----------


def test_trimming_a_recorded_voice_shrinks_the_stretch_of_the_file_and_keeps_it_in_place(folder):
    project = voice_project(folder, effects=[{"type": "silence", "start": 2, "end": 3}])
    edited = edit(project, type="audio_trim", target="audio.voiceover.0", start=3, end=6)  # 1 a 4 s do item
    clip = edited.audio.voiceover[0]
    assert (clip.start, clip.offset, clip.end) == (3.0, 1.0, 4.0)
    assert chain(clip.effects) == [("silence", 1.0, 2.0)]


def test_trimming_a_clip_silences_what_is_outside_the_selection(folder):
    edited = edit(make(folder), type="audio_trim", target="timeline.0", start=3, end=7)
    assert chain(edited.timeline[0].effects) == [("silence", 0.0, 3.0), ("silence", 7.0, None)]


# ---------- deslocar no tempo ----------


def test_shifting_a_clip_sets_the_audio_offset_and_the_effects_follow_the_sound(folder):
    project = edit(make(folder), type="audio_silence", target="timeline.0", start=4, end=5)
    edited = edit(project, type="audio_shift", target="timeline.0", delta=0.5)
    assert edited.timeline[0].audio_offset == 0.5
    assert chain(edited.timeline[0].effects) == [("silence", 4.5, 5.5)]  # o silêncio acompanha a tosse
    back = edit(edited, type="audio_shift", target="timeline.0", to=0)
    assert chain(back.timeline[0].effects) == [("silence", 4.0, 5.0)]
    assert b"audio_offset" not in back.to_bytes()  # no padrão fica fora do arquivo


def test_shifting_the_pip_the_track_and_the_free_items(folder):
    project = make(
        folder,
        sources={"cam": {"src": "video.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
        timeline=[{"type": "clip", "source": "cam", "start": 0, "end": 8}],
        overlays=[{"type": "video", "src": "video.mp4"}],
        audio={
            "tracks": [{"source": "mesa"}],
            "voiceover": [{"src": "fala.wav", "start": 1.0}],
            "narration": [{"text": "oi", "start": 2.0}],
            "music": {"src": "musica.wav"},
        },
    )
    assert edit(project, type="audio_shift", target="overlays.0", delta=-0.2).overlays[0].audio_offset == -0.2
    assert (
        edit(project, type="audio_shift", target="audio.tracks.0", delta=1.5).audio.tracks[0].audio_offset
        == 1.5
    )
    assert (
        edit(project, type="audio_shift", target="audio.voiceover.0", delta=2).audio.voiceover[0].start == 3.0
    )
    assert edit(project, type="audio_shift", target="audio.narration.0", to=5).audio.narration[0].start == 5.0
    spans = edit(project, type="audio_shift", target="audio.music", delta=3).audio.music.spans
    assert [(s.start, s.end, s.start_at) for s in spans] == [(3.0, None, 0.0)]
    early = edit(project, type="audio_shift", target="audio.music", delta=-2).audio.music.spans
    assert [(s.start, s.start_at) for s in early] == [(0.0, 2.0)]  # pula o começo da faixa
    with pytest.raises(EditError, match="antes do começo"):
        edit(project, type="audio_shift", target="audio.voiceover.0", delta=-2)
    with pytest.raises(EditError, match="não se desloca"):
        edit(project, type="audio_shift", target="audio.master", delta=1)
    with pytest.raises(EditError, match="um dos dois"):
        edit(project, type="audio_shift", target="timeline.0")


# ---------- estado da trilha ----------


def test_the_track_state_takes_gain_pan_mute_and_solo_and_returns_to_the_default(folder):
    project = make(folder, audio={"music": {"src": "musica.wav"}})
    edited = edit(project, type="track_set", track="MUS", gain_db=-6, pan=-1, solo=True)
    state = edited.tracks["MUS"]
    assert (state.gain_db, state.pan, state.solo, state.muted) == (-6.0, -1.0, True, False)
    back = edit(edited, type="track_set", track="MUS", gain_db=0, pan=0, solo=False)
    assert back.tracks == {}
    assert back.to_bytes() == project.to_bytes()


def test_a_bad_track_request_is_refused(folder):
    project = make(folder)
    with pytest.raises(EditError, match="trilha desconhecida"):
        edit(project, type="track_set", track="XYZ", gain_db=1)
    with pytest.raises(EditError, match="campo\\(s\\) de trilha"):
        edit(project, type="track_set", track="A1", volume=1)
    with pytest.raises(EditError, match="informe o que mudar"):
        edit(project, type="track_set", track="A1")
    with pytest.raises(EditError):
        edit(project, type="track_set", track="A1", pan=3)


# ---------- as contas puras ----------


def test_rebase_and_stitch_are_inverse_for_interval_effects():
    chain_ = [
        parse_effect({"type": "silence", "start": 1, "end": 5}),
        parse_effect({"type": "amplify", "gain_db": 3}),
    ]
    first, second = rebase_effects(chain_, 0.0, 3.0), rebase_effects(chain_, 3.0, 5.0)
    assert [(e.type, e.start, e.end) for e in first] == [("silence", 1.0, None), ("amplify", None, None)]
    assert [(e.type, e.start, e.end) for e in second] == [("silence", None, 2.0), ("amplify", None, None)]
    assert stitch_effects(first, second, 3.0) == chain_


def test_stitching_chains_that_differ_is_refused():
    first = [parse_effect({"type": "amplify", "gain_db": 3})]
    second = [parse_effect({"type": "amplify", "gain_db": 4})]
    assert stitch_effects(first, second, 3.0) is None


def test_the_envelope_rebase_keeps_the_sound_of_the_stretch_the_same():
    envelope = parse_effect({"type": "envelope", "points": [{"at": 2, "db": 0}, {"at": 6, "db": -12}]})
    piece = envelope.rebased(3.0, 2.0)  # de 3 a 5 s do item
    assert [(p.at, p.db) for p in piece.points] == [(0.0, -3.0), (2.0, -9.0)]
    assert piece.gain_db_at(1.0) == pytest.approx(envelope.gain_db_at(4.0))


# ---------- projeto só de áudio (sem imagem) ----------


def audio_only(folder: Path) -> Project:
    project = Project.model_validate(
        {
            "name": "so-audio",
            "output": {"preset": "audio/mp3"},
            "timeline": [],
            "audio": {"voiceover": [{"src": "fala.wav", "start": 2.0}], "music": {"src": "musica.wav"}},
        }
    )
    project.base_dir = folder
    return project


def test_the_wave_edits_work_in_a_project_that_has_no_picture_at_all(folder):
    project = audio_only(folder)
    silenced = edit(project, type="audio_silence", target="audio.voiceover.0", start=3, end=4)
    assert chain(silenced.audio.voiceover[0].effects) == [("silence", 1.0, 2.0)]
    cut = edit(silenced, type="audio_cut", target="audio.voiceover.0", start=5, end=6)
    assert [e.type for e in cut.audio.voiceover[0].effects] == ["silence", "cut"]
    pasted = edit(project, type="audio_paste", target="audio.voiceover.0", start=3, end=5, at=20)
    assert (pasted.audio.voiceover[1].start, pasted.audio.voiceover[1].offset) == (20.0, 1.0)
    assert edit(project, type="track_set", track="MUS", gain_db=-6).tracks["MUS"].gain_db == -6.0
    enveloped = edit(
        project, type="audio_envelope", target="audio.music", points=[{"at": 1, "db": -6}, {"at": 5, "db": 0}]
    )
    assert enveloped.audio.music.effects[0].type == "envelope"
    mono = edit(project, type="audio_channels", target="audio.voiceover.0", mode="mono")
    assert mono.audio.voiceover[0].effects[0].mode == "mono"
