"""O ducking no grafo de áudio: o compressor nunca vê o fim das entradas (DMK-47) e, sem ducking, nada mudou."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.spec import AudioSettings, Music, MusicSpan
from dmaker.filtergraph import Inputs, audio_graph
from dmaker.filtergraph.audio import sidechain_compress


def _graph(audio: AudioSettings, total: float = 12.0) -> tuple[list[str], list[str]]:
    inputs = Inputs()
    inputs.add("a.mov")
    lines: list[str] = []
    audio_graph(lines, inputs, "[ta0]", audio, Path("m.mp3"), total)
    return inputs.args, lines


COMPRESSOR = "sidechaincompress=threshold=0.0200:ratio=6:attack=20:release=350:makeup=1:level_sc=1"  # os padrões do Music


def test_the_compressor_reads_both_inputs_padded_with_endless_silence():
    """O `sidechaincompress` descarta o que sobra na fila de uma entrada quando a outra acaba, e quanto sobra
    depende de uma corrida entre threads. Com as duas entradas sem fim ele nunca chega a esse ponto."""
    _, lines = _graph(AudioSettings(music=Music(src="m.mp3", volume=0.2, ducking=True)))
    assert "[ta0]asplit=2[voice][sc]" in lines
    pad_sidechain = lines.index("[sc]apad[scp]")
    pad_music = lines.index("[mus0]apad[musp]")
    compressor = lines.index(f"[musp][scp]{COMPRESSOR}[musd]")
    assert max(pad_sidechain, pad_music) < compressor
    # cada rótulo original aparece só duas vezes (onde nasce e no preenchimento): o compressor não o lê direto
    text = ";".join(lines)
    assert text.count("[sc]") == 2 and text.count("[mus0]") == 2


def test_the_voice_still_decides_where_the_mix_ends():
    """Sem fim nas duas entradas do compressor, quem encerra a mistura é a voz: ela vem primeiro no amix, com
    `duration=first`, e não recebe silêncio."""
    _, lines = _graph(AudioSettings(music=Music(src="m.mp3", volume=0.2, ducking=True)))
    assert "[voice][musd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]" in lines
    assert not any("[voice]apad" in line or "apad[voice]" in line for line in lines)


def test_with_several_music_windows_the_padding_goes_on_the_mixed_music():
    music = Music(
        src="m.mp3",
        volume=0.2,
        ducking=True,
        spans=[MusicSpan(start=0, end=4), MusicSpan(start=6, end=12)],
    )
    _, lines = _graph(AudioSettings(music=music))
    assert "[mus]apad[musp]" in lines  # a mistura das janelas, não cada janela
    assert sum("apad" in line for line in lines) == 2


def test_sidechain_compress_writes_the_three_lines_with_the_music_settings():
    lines: list[str] = []
    music = Music(src="m.mp3", ducking=True, duck_threshold=0.05, duck_ratio=8, duck_release=500)
    sidechain_compress(lines, "[musbus]", "[voicebus]", music)
    assert lines == [
        "[voicebus]apad[scp]",
        "[musbus]apad[musp]",
        "[musp][scp]sidechaincompress=threshold=0.0500:ratio=8:attack=20:release=500:makeup=1:level_sc=1[musd]",
    ]


# O que o grafo era antes do DMK-47, colado como estava. Sem ducking, nada disso pode mudar.
OLD_MUSIC = (
    "[1:a]atrim=start=0.000:duration=12.000,asetpts=PTS-STARTPTS,aresample=48000,"
    "aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.200,afade=t=in:st=0:d=1.000,"
    "afade=t=out:st=10.000:d=2.000[mus0];"
)
OLD_TAIL = (
    "[amix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a_norm];"
    "[a_norm]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]"
)
WITHOUT_DUCKING = {
    "no_ducking": (
        AudioSettings(music=Music(src="m.mp3", volume=0.2, ducking=False), voice_gain=1.2),
        ["-i", "a.mov", "-stream_loop", "-1", "-i", "m.mp3"],
        "[ta0]volume=1.200[a_gain];" + OLD_MUSIC + "[a_gain][mus0]"
        "amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix];" + OLD_TAIL,
    ),
    "no_music": (
        AudioSettings(voice_gain=1.2),
        ["-i", "a.mov"],
        "[ta0]volume=1.200[a_gain];[a_gain]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a_norm];"
        "[a_norm]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]",
    ),
    "muted_clips_and_no_voice": (  # com ducking ligado, mas sem voz para abaixar: cai no amix simples
        AudioSettings(music=Music(src="m.mp3", volume=0.2, ducking=True), mute_clips=True),
        ["-i", "a.mov", "-stream_loop", "-1", "-i", "m.mp3"],
        "[ta0]volume=0[a_mute];" + OLD_MUSIC + "[a_mute][mus0]"
        "amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix];" + OLD_TAIL,
    ),
    "two_windows_no_ducking": (
        AudioSettings(
            music=Music(
                src="m.mp3",
                volume=0.2,
                ducking=False,
                spans=[MusicSpan(start=0, end=4), MusicSpan(start=6, end=12)],
            )
        ),
        ["-i", "a.mov", "-stream_loop", "-1", "-i", "m.mp3", "-stream_loop", "-1", "-i", "m.mp3"],
        "[1:a]atrim=start=0.000:duration=4.000,asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.200,afade=t=in:st=0:d=1.000,"
        "afade=t=out:st=2.000:d=2.000[mus0];"
        "[2:a]atrim=start=0.000:duration=6.000,asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.200,afade=t=in:st=0:d=1.000,"
        "afade=t=out:st=4.000:d=2.000,adelay=6000:all=1[mus1];"
        "[mus0][mus1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mus];"
        "[ta0][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix];" + OLD_TAIL,
    ),
}


@pytest.mark.parametrize("case", WITHOUT_DUCKING)
def test_without_ducking_the_audio_graph_is_exactly_what_it_was_before(case):
    audio, args, expected = WITHOUT_DUCKING[case]
    got_args, lines = _graph(audio)
    assert got_args == args
    assert ";".join(lines) == expected
    assert "apad" not in expected  # o preenchimento é só do ducking
