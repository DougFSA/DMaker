"""Efeitos sonoros no grafo de áudio: instante exato, nível contra a voz, fora do ducking e antes do loudnorm."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pytest

from dmaker.domain.spec import AudioSettings, Music
from dmaker.filtergraph import Inputs, audio_graph
from dmaker.filtergraph.common import LOUDNORM_TRUE_PEAK_DB
from dmaker.filtergraph.sfx import (
    BELOW_VOICE_DB,
    LIBRARY_PEAK_DB,
    delay_samples,
    sfx_gain_db,
    sfx_streams,
    voice_reference_db,
)


@dataclass(frozen=True)
class _Narration:
    path: Path
    start: float = 0.0
    volume: float = 1.0


@dataclass(frozen=True)
class _Sfx:
    path: Path
    at: float
    gain_db: float = -9.0


MEASURED = {
    "input_i": "-20.1",
    "input_tp": "-3.0",
    "input_lra": "6.0",
    "input_thresh": "-30.5",
    "target_offset": "0.2",
}


def _rich_graph(measured=None, sfx=()):
    """Voz + PiP + duas narrações + música com ducking: o caso mais cheio da mixagem."""
    inputs = Inputs()
    inputs.add("a.mov")
    lines: list[str] = []
    audio = AudioSettings(music=Music(src="m.mp3", volume=0.2, ducking=True), voice_gain=1.2)
    narrations = [_Narration(Path("n1.wav"), start=0.5, volume=1.5), _Narration(Path("n2.wav"), start=4.0)]
    audio_graph(
        lines,
        inputs,
        "[ta0]",
        audio,
        Path("m.mp3"),
        12.0,
        measured=measured,
        extra_voices=["[pip0]"],
        narrations=narrations,
        sfx=sfx,
    )
    return inputs.args, lines


# O grafo que a `develop` gerava para este caso antes dos efeitos sonoros (DMK-25), colado como estava.
BEFORE_ARGS = ["-i", "a.mov", "-i", "n1.wav", "-i", "n2.wav", "-stream_loop", "-1", "-i", "m.mp3"]
BEFORE_NO_MEASURE = (
    "[ta0][pip0]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a_voices];"
    "[a_voices]volume=1.200[a_gain];"
    "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=1.500,adelay=500:all=1[nar0];"
    "[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=1.000,adelay=4000:all=1[nar1];"
    "[a_gain][nar0][nar1]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[a_narrated];"
    "[3:a]atrim=start=0.000:duration=12.000,asetpts=PTS-STARTPTS,aresample=48000,"
    "aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.200,afade=t=in:st=0:d=1.000,"
    "afade=t=out:st=10.000:d=2.000[mus0];"
    "[a_narrated]asplit=2[voice][sc];"
    "[mus0][sc]sidechaincompress=threshold=0.0200:ratio=6:attack=20:release=350:makeup=1:level_sc=1[musd];"
    "[voice][musd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix];"
    "[amix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a_norm];"
    "[a_norm]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]"
)
BEFORE_MEASURED = BEFORE_NO_MEASURE.replace(
    "loudnorm=I=-14:TP=-1.5:LRA=11,",
    "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=-20.1:measured_TP=-3.0:measured_LRA=6.0:measured_thresh=-30.5"
    ":offset=0.2:linear=true,",
)


def test_a_project_without_sfx_gets_exactly_the_graph_it_had_before():
    for measured, expected in ((None, BEFORE_NO_MEASURE), (MEASURED, BEFORE_MEASURED)):
        args, lines = _rich_graph(measured)
        assert args == BEFORE_ARGS
        assert ";".join(lines) == expected
        assert _rich_graph(measured, sfx=())[1] == lines  # `sfx=()` explícito é o mesmo que omitir


def test_each_effect_is_delayed_in_exact_samples_and_leveled():
    sfx = [_Sfx(Path("whoosh.wav"), 12.4, -11.3), _Sfx(Path("pop.wav"), 0.0, -6.5)]
    args, lines = _rich_graph(sfx=sfx)
    text = ";".join(lines)
    assert args[-4:] == ["-i", "whoosh.wav", "-i", "pop.wav"]  # entram depois das narrações e da música
    assert (
        "[4:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=-11.30dB,"
        "adelay=595200S:all=1[sfx0]"
    ) in text  # 12,40 s * 48000 = 595200 amostras
    assert "[5:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=-6.50dB[sfx1]" in text
    assert "adelay=0" not in text  # efeito em 0 s não ganha atraso


def test_effects_are_summed_after_the_ducking_and_before_the_loudnorm():
    _, lines = _rich_graph(MEASURED, sfx=[_Sfx(Path("a.wav"), 1.0), _Sfx(Path("b.wav"), 2.0)])
    text = ";".join(lines)
    assert "[amix][sfx0][sfx1]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[a_fx]" in text
    assert text.index("sidechaincompress") < text.index("[a_fx]") < text.index("loudnorm")
    assert "[a_fx]loudnorm" in text  # o que o loudnorm mede e normaliza já inclui os efeitos


def test_the_music_does_not_duck_for_the_effects():
    """O sidechain (e o `asplit` que o alimenta) fica exatamente como era: os efeitos não chegam a ele."""
    _, with_sfx = _rich_graph(sfx=[_Sfx(Path("a.wav"), 1.0)])
    side_lines = [
        line for line in with_sfx if "sidechaincompress" in line or "asplit" in line or "[musd]" in line
    ]
    assert side_lines == [
        line
        for line in BEFORE_NO_MEASURE.split(";")
        if "sidechaincompress" in line or "asplit" in line or "[musd]" in line
    ]
    assert not any("sfx" in line for line in side_lines)


def test_effects_without_music_or_narration_still_join_the_bus_before_the_loudnorm():
    lines: list[str] = []
    audio_graph(lines, Inputs(), "[ta0]", AudioSettings(), None, 5.0, sfx=[_Sfx(Path("a.wav"), 1.0)])
    text = ";".join(lines)
    assert "[ta0][sfx0]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a_fx]" in text
    assert "[a_fx]loudnorm" in text


def test_effects_follow_the_clip_mute_because_they_are_not_the_clips_audio():
    lines: list[str] = []
    audio_graph(
        lines, Inputs(), "[ta0]", AudioSettings(mute_clips=True), None, 5.0, sfx=[_Sfx(Path("a.wav"), 1.0)]
    )
    text = ";".join(lines)
    assert "[ta0]volume=0[a_mute]" in text and "[a_mute][sfx0]amix=inputs=2" in text


def test_the_same_sound_twice_is_two_inputs_with_their_own_labels():
    inputs = Inputs()
    lines: list[str] = []
    labels = sfx_streams(lines, inputs, [_Sfx(Path("pop.wav"), 1.0), _Sfx(Path("pop.wav"), 2.0)])
    assert labels == ["[sfx0]", "[sfx1]"] and inputs.args == ["-i", "pop.wav", "-i", "pop.wav"]


# ---------- contas ----------


def test_delay_is_counted_in_samples_not_rounded_to_milliseconds():
    assert delay_samples(12.4) == 595_200
    assert delay_samples(0.0) == 0
    assert delay_samples(1 / 48_000) == 1 and delay_samples(2.00002) == 96_001  # 1 amostra = 0,02 ms


def test_effect_peak_sits_below_the_voice_peak_by_the_standard_margin():
    for reference in (-3.0, -6.0, -12.0):
        gain = sfx_gain_db(1.0, reference)
        assert LIBRARY_PEAK_DB + gain == pytest.approx(reference - BELOW_VOICE_DB)


def test_volume_scales_the_effect_in_decibels_and_stays_under_the_voice():
    base = sfx_gain_db(1.0, -6.0)
    assert sfx_gain_db(0.5, -6.0) == pytest.approx(base - 6.0206, abs=1e-3)
    assert sfx_gain_db(1.5, -6.0) == pytest.approx(base + 3.5218, abs=1e-3)
    loudest = LIBRARY_PEAK_DB + sfx_gain_db(1.5, -6.0)  # o maior volume que a spec aceita
    assert loudest < -6.0  # ainda abaixo do pico da voz
    assert sfx_gain_db(1.0, -6.0) == pytest.approx(-6.0 - BELOW_VOICE_DB - LIBRARY_PEAK_DB)
    assert math.isfinite(sfx_gain_db(0.01, -6.0))


def test_voice_reference_is_the_measured_peak_when_the_gain_leaves_room():
    # voz a -18 LUFS com pico em -12: o ganho para -14 é +4 dB, e -12 + 4 = -8 ainda cabe sob -1,5
    assert voice_reference_db(-18.0, -12.0, -14.0) == -12.0


def test_voice_reference_follows_the_limiter_when_the_peak_would_not_fit():
    """Voz com pico alto para o ganho: o loudnorm a achata em -1,5 dBTP, e o efeito (mais baixo) passa inteiro.
    A régua tem de ser o pico que a voz terá na saída, senão o efeito sairia perto do pico da voz."""
    # voz a -24 LUFS com pico em -8: o ganho é +10 dB, o pico iria a +2 e o teto é -1,5: a régua é -1,5 - 10
    reference = voice_reference_db(-24.0, -8.0, -14.0)
    assert reference == pytest.approx(LOUDNORM_TRUE_PEAK_DB - 10.0)
    assert reference < -8.0
    # na saída (com o ganho de +10 dB) o efeito fica BELOW_VOICE_DB abaixo do pico limitado da voz
    effect_out = LIBRARY_PEAK_DB + sfx_gain_db(1.0, reference) + 10.0
    assert effect_out == pytest.approx(LOUDNORM_TRUE_PEAK_DB - BELOW_VOICE_DB)


def test_voice_reference_without_normalization_is_the_measured_peak():
    assert voice_reference_db(-24.0, -8.0, None) == -8.0
