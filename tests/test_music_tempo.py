"""A música no andamento do projeto, sem ffmpeg: o esticamento derivado, o loop de tempos inteiros, a entrada na batida da
grade, o grafo que isso gera e a garantia de que um projeto sem `audio.tempo` segue exatamente como antes."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.music_tempo import (
    SEAM_FADE_SECONDS,
    MusicGrid,
    music_chain,
    music_grid,
    stretch_effect,
    tempo_warnings,
)
from dmaker.domain.spec import AudioSettings, Music, MusicSpan, Project
from dmaker.filtergraph.audio import audio_graph
from dmaker.filtergraph.common import Inputs
from dmaker.pipeline.preview_audio import mix_recipe
from dmaker.pipeline.timeline_view import tempo_view


def settings(**music) -> AudioSettings:
    base = {"src": "m.wav", "bpm": 100.0, "stretch_to_tempo": True}
    return AudioSettings(music=Music(**{**base, **music}), tempo={"bpm": 120.0}, normalize="off")


# ---------- o efeito derivado ----------


def test_the_derived_effect_takes_the_music_from_its_bpm_to_the_project_bpm():
    effect = stretch_effect(settings())
    assert effect is not None and effect.type == "change_tempo"
    assert (effect.mode, effect.bpm_from, effect.bpm_to) == ("bpm", 100.0, 120.0)
    assert effect.output_duration(9.6) == pytest.approx(8.0)  # 100/120 da duração, sem mudar o tom


def test_the_derived_effect_goes_in_front_of_the_users_chain_and_is_never_saved_in_it():
    audio = settings(effects=[{"type": "amplify", "gain_db": 3}])
    chain = music_chain(audio)
    assert [effect.type for effect in chain] == ["change_tempo", "amplify"]
    assert [effect.type for effect in audio.music.effects] == ["amplify"]  # a spec não ganhou o efeito
    assert "change_tempo" not in audio.model_dump_json()


@pytest.mark.parametrize(
    "audio",
    [
        AudioSettings(music=Music(src="m.wav", bpm=100.0, stretch_to_tempo=True)),  # sem andamento do projeto
        AudioSettings(music=Music(src="m.wav", bpm=100.0), tempo={"bpm": 120.0}),  # esticamento desligado
        AudioSettings(music=Music(src="m.wav"), tempo={"bpm": 120.0}),  # música sem andamento
        AudioSettings(tempo={"bpm": 120.0}),  # sem música
    ],
)
def test_without_a_tempo_a_bpm_or_the_switch_there_is_no_stretch(audio):
    assert music_grid(audio) is None and stretch_effect(audio) is None
    assert music_chain(audio) == tuple(audio.music.effects if audio.music else ())


def test_changing_the_project_tempo_changes_the_derived_effect():
    audio = settings()
    faster = audio.model_copy(update={"tempo": audio.tempo.model_copy(update={"bpm": 150.0})})
    assert music_chain(faster)[0].bpm_to == 150.0 and music_chain(audio)[0].bpm_to == 120.0


# ---------- o loop em tempos inteiros e a entrada na batida ----------


def grid(**kwargs) -> MusicGrid:
    return music_grid(settings(**kwargs))  # type: ignore[return-value]


def test_the_loop_is_the_stretched_file_rounded_to_a_whole_number_of_beats():
    g = grid()
    assert g.period == pytest.approx(0.5) and g.ratio == pytest.approx(100 / 120)
    assert g.loop_length(8.0) == pytest.approx(8.0) and not g.needs_seam_fade(8.0)
    assert g.loop_length(8.04) == pytest.approx(8.0) and g.needs_seam_fade(
        8.04
    )  # aparado: leva o fade da emenda
    assert g.loop_length(8.3) == pytest.approx(8.5) and g.needs_seam_fade(8.3)  # completado com silêncio
    assert g.loop_length(0.1) == pytest.approx(0.5)  # pelo menos um tempo
    assert not g.needs_seam_fade(8.0005)  # meio milissegundo de sobra não pede emenda


def test_the_first_beat_of_the_music_is_stretched_with_it():
    assert grid(beat_offset=0.12).first_beat == pytest.approx(0.12 * 100 / 120)


def test_the_entry_is_delayed_until_the_first_beat_falls_on_the_grid():
    g = grid(beat_offset=0.12)  # estica para 0,1 s: o tempo cai em 0,1 s do arquivo
    delay = g.entry_delay(window_start=0.0, start_at=0.0)
    assert delay == pytest.approx(0.4)  # 0,1 + 0,4 = 0,5, o tempo 2 da grade
    assert (delay + g.first_beat) % g.period == pytest.approx(0.0, abs=1e-9) or (
        delay + g.first_beat
    ) % g.period == pytest.approx(g.period)


def test_a_music_already_on_the_grid_is_not_delayed():
    assert grid().entry_delay(0.0, 0.0) == 0.0
    assert grid(beat_offset=0.6).entry_delay(0.0, 0.0) == 0.0  # 0,6 x 100/120 = 0,5 s: um tempo inteiro


def test_the_entry_counts_where_the_window_starts_and_where_it_enters_the_file():
    g = grid()
    assert g.entry_delay(window_start=2.0, start_at=0.0) == 0.0  # a janela entra num tempo
    assert g.entry_delay(window_start=2.1, start_at=0.0) == pytest.approx(0.4)
    assert g.entry_delay(window_start=0.0, start_at=0.25) == pytest.approx(0.25)


def test_the_project_grid_offset_moves_the_entry():
    audio = AudioSettings(
        music=Music(src="m.wav", bpm=100.0, stretch_to_tempo=True), tempo={"bpm": 120.0, "offset": 0.2}
    )
    assert music_grid(audio).entry_delay(0.0, 0.0) == pytest.approx(0.2)


# ---------- o grafo ----------


def build(audio: AudioSettings, total: float = 30.0, music_duration: float | None = None):
    inputs, lines = Inputs(), []
    inputs.add("clips.mov")
    lines.append("[0:a]aresample=48000[ta0]")
    audio_graph(lines, inputs, "[ta0]", audio, Path("m.wav"), total, music_duration=music_duration)
    return ";".join(lines), inputs.args


def graph(audio: AudioSettings, *, total: float = 30.0, music_duration: float | None = None) -> str:
    return build(audio, total, music_duration)[0]


def test_the_stretched_loop_is_made_by_aloop_in_whole_beats_and_not_by_the_input():
    text = graph(settings(), music_duration=8.0)
    assert "aloop=loop=-1:size=384000:start=0" in text  # 8,0 s x 48000
    assert "atrim=duration=8.000000,apad=whole_dur=8.000000" in text
    assert "-stream_loop" not in build(settings(), music_duration=8.0)[1]  # o loop saiu da entrada
    assert "afade=t=in:d=0.003" not in text  # o arquivo fecha tempos inteiros: sem fade


def test_a_file_that_does_not_close_whole_beats_gets_the_short_fade_on_the_seam():
    text = graph(settings(), music_duration=8.04)
    assert f"afade=t=in:d={SEAM_FADE_SECONDS:g}" in text
    assert f"afade=t=out:st=7.997000:d={SEAM_FADE_SECONDS:g}" in text


def test_the_entry_delay_shortens_the_window_by_the_same_amount():
    text = graph(settings(beat_offset=0.12), total=10.0, music_duration=8.0)
    assert "adelay=400:all=1" in text
    assert "atrim=start=0.000:duration=9.600" in text  # 10 s - 0,4 s


def test_a_music_that_does_not_loop_is_only_delayed():
    text = graph(settings(beat_offset=0.12, loop=False), total=10.0, music_duration=8.0)
    assert "aloop" not in text and "adelay=400:all=1" in text


def test_a_window_of_the_music_still_enters_where_it_starts():
    audio = settings(spans=[MusicSpan(start=2.0, end=8.0, start_at=0.0)])
    text = graph(audio, music_duration=8.0)
    assert "adelay=2000:all=1" in text  # a janela entra num tempo: nenhum atraso a mais


class Voice:
    def __init__(self, name: str, start: float = 0.0):
        self.path, self.start, self.volume = Path(name), start, 1.0
        self.offset, self.duration = 0.5, 5.0


def test_without_a_tempo_the_graph_is_the_same_string_as_before():
    """Projeto sem `audio.tempo` (ou com o andamento mas sem esticar): o grafo é o de antes, linha por linha."""
    plain = AudioSettings(music=Music(src="m.wav", spans=[MusicSpan(start=0, end=10, fade_out=2)]))
    with_tempo = plain.model_copy(update={"tempo": settings().tempo})
    with_bpm = AudioSettings(
        music=Music(src="m.wav", bpm=100.0, spans=[MusicSpan(start=0, end=10, fade_out=2)]),
        tempo={"bpm": 120.0},
    )
    base = graph(plain)
    assert graph(with_tempo) == base and graph(with_bpm) == base
    assert "aloop" not in base and "-stream_loop" in build(plain)[1]


# ---------- a spec, a receita da prévia e a vista ----------


def project_with(**audio) -> Project:
    return Project.model_validate(
        {
            "name": "antigo",
            "timeline": [{"type": "card", "title": "a", "duration": 10.0}],
            "audio": {"music": {"src": "m.wav"}, **audio},
        }
    )


def test_the_preview_recipe_changes_with_the_tempo_and_the_stretch_but_not_without_them():
    plain = mix_recipe(project_with())
    assert "tempo" not in plain["audio"] and "bpm" not in plain["audio"]["music"]
    tempo = mix_recipe(project_with(tempo={"bpm": 120}))
    stretched = mix_recipe(
        project_with(music={"src": "m.wav", "bpm": 100, "stretch_to_tempo": True}, tempo={"bpm": 120})
    )
    faster = mix_recipe(
        project_with(music={"src": "m.wav", "bpm": 100, "stretch_to_tempo": True}, tempo={"bpm": 130})
    )
    assert (
        len({repr(plain), repr(tempo), repr(stretched), repr(faster)}) == 4
    )  # a prévia se invalida a cada mudança


def test_the_view_carries_the_tempo_only_when_the_project_has_one():
    assert tempo_view(project_with()) is None
    view = tempo_view(project_with(tempo={"bpm": 120, "time_signature": "3/4", "offset": 0.5}))
    assert view == {"bpm": 120.0, "time_signature": "3/4", "beats_per_bar": 3, "offset": 0.5, "period": 0.5}


def test_the_warnings_catch_a_stretch_that_cannot_work_and_one_that_sounds_artificial():
    assert tempo_warnings(settings()) == []  # 100 para 120: 20%
    inert = AudioSettings(music=Music(src="m.wav", bpm=100.0, stretch_to_tempo=True))
    assert "não tem andamento" in tempo_warnings(inert)[0]
    big = settings(bpm=60.0)  # 60 para 120: o dobro
    assert "artificial" in tempo_warnings(big)[0] and "100%" in tempo_warnings(big)[0]
    assert tempo_warnings(AudioSettings(music=Music(src="m.wav"), tempo={"bpm": 120.0})) == []
    assert tempo_warnings(AudioSettings(tempo={"bpm": 120.0})) == []
