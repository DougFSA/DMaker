"""Mixagem de áudio: voz, música com ducking e normalização de loudness."""

from __future__ import annotations

from pathlib import Path

from ..domain.spec import AudioSettings, Music, MusicSpan
from .common import Inputs


def resolve_span(
    span: MusicSpan, total: float, music_duration: float | None = None
) -> tuple[float, float | None, float]:
    """Converte um `MusicSpan` para (start, end, start_at) absolutos: aplica `from_end` (contado a
    partir do fim do vídeo, usando `total`) e, quando dá para resolver, `tail` (ancora `start_at` no
    final da música, usando `music_duration`). Sem `music_duration`, um span com `tail` sai com
    `start_at` igual à folga bruta, sem ancorar (uso em contextos que só têm a linha do tempo, como a
    vista multitrilha)."""
    if span.from_end:
        start = max(total - span.start, 0.0)
        end = None if span.end is None else max(total - span.end, 0.0)
    else:
        start, end = span.start, span.end
    start_at = span.start_at
    if span.tail and music_duration is not None:
        window_end = total if end is None else end
        length = max(window_end - start, 0.0)
        start_at = max(music_duration - length - span.start_at, 0.0)
    return start, end, start_at


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
    extra_voices: list[str] | None = None,
    music_duration: float | None = None,
) -> str:
    """Encadeia ganho de voz, música (ducking) e loudnorm sobre `cur_a`; devolve o rótulo final.
    `extra_voices` são rótulos de áudio já alinhados à linha do tempo (PiP) somados à voz.
    `music_duration` é a duração da música, só necessária quando algum span usa `tail`."""
    a = cur_a
    if extra_voices:
        lines.append(
            f"{a}{''.join(extra_voices)}amix=inputs={1 + len(extra_voices)}:duration=first"
            ":dropout_transition=0:normalize=0[a_voices]"
        )
        a = "[a_voices]"
    if audio.mute_clips:
        lines.append(f"{a}volume=0[a_mute]")
        a = "[a_mute]"
    elif audio.voice_gain != 1:
        lines.append(f"{a}volume={audio.voice_gain:.3f}[a_gain]")
        a = "[a_gain]"

    music: Music | None = audio.music
    if music and music_path and include_music and music.volume > 0:
        mus = music_stream(lines, inputs, music, music_path, total, music_duration)
        if music.ducking and not audio.mute_clips:
            lines.append(f"{a}asplit=2[voice][sc]")
            lines.append(
                f"{mus}[sc]sidechaincompress=threshold={music.duck_threshold:.4f}:ratio={music.duck_ratio:g}"
                f":attack=20:release={music.duck_release:g}:makeup=1:level_sc=1[musd]"
            )
            lines.append("[voice][musd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]")
        else:
            lines.append(f"{a}{mus}amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]")
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


def music_stream(
    lines: list[str],
    inputs: Inputs,
    music: Music,
    music_path: Path,
    total: float,
    music_duration: float | None = None,
) -> str:
    """Música alinhada à linha do tempo: uma entrada por janela (`spans`), cada uma aparada, com
    ganho e fades, atrasada até o instante em que entra; sem janelas, uma só cobrindo o vídeo
    inteiro. Devolve o rótulo da mistura das janelas. `music_duration` é obrigatória quando algum
    span usa `tail` (só assim dá para ancorar `start_at` no final da faixa)."""
    spans = music.spans or [
        MusicSpan(
            start=0.0, end=None, start_at=music.start_at, fade_in=music.fade_in, fade_out=music.fade_out
        )
    ]
    if any(span.tail for span in spans) and music_duration is None:
        raise ValueError("música: span com tail=true precisa da duração da música (music_duration)")
    labels = []
    for k, span in enumerate(spans):
        start, span_end, start_at = resolve_span(span, total, music_duration)
        end = total if span_end is None else min(span_end, total)
        length = max(end - start, 0.0)
        pre = ["-stream_loop", "-1"] if music.loop else []
        idx = inputs.add(music_path, *pre)
        chain = [
            f"[{idx}:a]atrim=start={start_at:.3f}:duration={length:.3f}",
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            f"volume={music.volume:.3f}",
        ]
        if span.fade_in:
            chain.append(f"afade=t=in:st=0:d={span.fade_in:.3f}")
        if span.fade_out:
            chain.append(f"afade=t=out:st={max(length - span.fade_out, 0):.3f}:d={span.fade_out:.3f}")
        if start > 0:
            chain.append(f"adelay={int(round(start * 1000))}:all=1")
        label = f"[mus{k}]"
        lines.append(",".join(chain) + label)
        labels.append(label)
    if len(labels) == 1:
        return labels[0]
    lines.append(
        "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[mus]"
    )
    return "[mus]"
