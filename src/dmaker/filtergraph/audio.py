"""Mixagem de áudio: voz, música com ducking e normalização de loudness."""

from __future__ import annotations

from pathlib import Path

from ..domain.spec import AudioSettings, Music
from .common import Inputs


def audio_graph(
    lines: list[str],
    inputs: Inputs,
    cur_a: str,
    audio: AudioSettings,
    music_path: Path | None,
    total: float,
    measured: dict | None = None,
    include_music: bool = True,
    include_norm: bool = True,
) -> str:
    """Encadeia ganho de voz, música (ducking) e loudnorm sobre `cur_a`; devolve o rótulo final."""
    a = cur_a
    if audio.mute_clips:
        lines.append(f"{a}volume=0[a_mute]")
        a = "[a_mute]"
    elif audio.voice_gain != 1:
        lines.append(f"{a}volume={audio.voice_gain:.3f}[a_gain]")
        a = "[a_gain]"

    music: Music | None = audio.music
    if music and music_path and include_music and music.volume > 0:
        pre = ["-stream_loop", "-1"] if music.loop else []
        idx = inputs.add(music_path, *pre)
        chain = [
            f"[{idx}:a]atrim=start={music.start_at:.3f}:duration={total:.3f}",
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            f"volume={music.volume:.3f}",
        ]
        if music.fade_in:
            chain.append(f"afade=t=in:st=0:d={music.fade_in:.3f}")
        if music.fade_out:
            chain.append(f"afade=t=out:st={max(total - music.fade_out, 0):.3f}:d={music.fade_out:.3f}")
        lines.append(",".join(chain) + "[mus]")
        if music.ducking and not audio.mute_clips:
            lines.append(f"{a}asplit=2[voice][sc]")
            lines.append(
                f"[mus][sc]sidechaincompress=threshold={music.duck_threshold:.4f}:ratio={music.duck_ratio:g}"
                f":attack=20:release={music.duck_release:g}:makeup=1:level_sc=1[musd]"
            )
            lines.append("[voice][musd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]")
        else:
            lines.append(f"{a}[mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]")
        a = "[amix]"

    if audio.normalize != "off" and include_norm:
        ln = f"loudnorm=I={audio.target_lufs:g}:TP=-1.5:LRA=11"
        if measured:
            ln += (
                f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                f":offset={measured['target_offset']}:linear=true"
            )
        # o loudnorm entrega 192 kHz; volta para 48 kHz
        lines.append(f"{a}{ln},aresample=48000[a_norm]")
        a = "[a_norm]"
    lines.append(f"{a}aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]")
    return "[aout]"


def loudnorm_measure_graph(cur_a: str, target_lufs: float, out: str = "[ameas]") -> str:
    return f"{cur_a}loudnorm=I={target_lufs:g}:TP=-1.5:LRA=11:print_format=json{out}"
