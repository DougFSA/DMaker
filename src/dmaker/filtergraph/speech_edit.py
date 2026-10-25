"""Comandos ffmpeg da regravação de fala: a emenda no áudio original e o recorte da referência do falante.

A emenda troca só a região regravada. Antes e depois dela, o áudio é o do arquivo original (nada de
passar o arquivo inteiro pela separação de voz, que o colore); dentro da região entram o fundo isolado
(música, ambiente) e a fala nova. Funções puras: recebem dados e devolvem o comando.
"""

from __future__ import annotations

from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from ..voice.speech_edit import SplicePlan
from .voice import encoder_args

VIDEO_CONTAINERS = (".mp4", ".mov", ".mkv", ".m4v")
AUDIO_CONTAINERS = (".wav", ".mp3", ".m4a")
FASTSTART_CONTAINERS = (".mp4", ".mov", ".m4v")

# O vídeo é copiado sem recodificar (rápido e sem perda); só o áudio é recodificado. AAC a 192 kb/s é
# transparente para fala com música e é o que o resto do DMaker usa para o m4a.
VIDEO_AUDIO_ARGS = ["-c:a", "aac", "-b:a", "192k"]

REFERENCE_SAMPLE_RATE = 24000  # taxa nativa do OmniVoice (ver voice/library.py)

# Fade com curva de potência constante (qsin): a fala nova e o original não são o mesmo sinal, então os
# dois lados da emenda somam em potência e o volume não afunda no meio do fade.
CROSSFADE_CURVE = "qsin"


def corrected_suffix(source_suffix: str, has_video: bool) -> str:
    """Extensão do arquivo corrigido: a do original quando o ffmpeg a grava com o áudio novo; senão mp4 ou wav."""
    suffix = source_suffix.lower()
    if has_video:
        return suffix if suffix in VIDEO_CONTAINERS else ".mp4"
    return suffix if suffix in AUDIO_CONTAINERS else ".wav"


def _normalized(sample_rate: int, layout: str) -> str:
    """Mesma taxa, formato e canais em todos os ramos, que o acrossfade e o amix exigem iguais."""
    return f"aresample={sample_rate},aformat=sample_fmts=fltp:channel_layouts={layout}"


def speech_splice_graph(
    plan: SplicePlan,
    background_offset: float,
    gain_db: float = 0.0,
    sample_rate: int = 48000,
    layout: str = "stereo",
    has_head: bool = True,
    has_tail: bool = True,
) -> str:
    """Grafo da emenda. Entradas: 0 = arquivo original, 1 = fundo isolado (começa em `background_offset`
    no arquivo), 2 = fala nova, que já vem na velocidade final (o `atempo` é aplicado antes da marca d'água).

    O remendo (fundo + fala nova, com o ganho que iguala o volume do falante) tem o tamanho da região.
    Cada emenda cruza `plan.crossfade` segundos: o original sai na primeira ponta do remendo e volta na
    última, e o comprimento total não muda (o vídeo continua em sincronia).
    """
    norm = _normalized(sample_rate, layout)
    crossfade = plan.crossfade
    region = plan.region_end - plan.region_start
    delay_ms = max(0, round((plan.speech_start - plan.region_start) * 1000))
    speech_chain = [f"volume={gain_db:.2f}dB", norm, f"adelay=delays={delay_ms}:all=1"]
    lines = [
        # fundo da região: o tempo no arquivo menos o início da janela isolada
        f"[1:a]atrim=start={plan.region_start - background_offset:.3f}:duration={region:.3f},"
        f"asetpts=PTS-STARTPTS,{norm}[background]",
        f"[2:a]{','.join(speech_chain)}[speech]",
        # normalize=0: soma sem dividir por 2 (o amix padrão baixaria o fundo e a fala pela metade)
        f"[background][speech]amix=inputs=2:duration=longest:normalize=0,"
        f"atrim=duration={region:.3f},asetpts=PTS-STARTPTS[patch]",
    ]
    fade = f"acrossfade=d={crossfade:.3f}:c1={CROSSFADE_CURVE}:c2={CROSSFADE_CURVE}"
    if has_head and has_tail:
        lines.append("[0:a:0]asplit=2[whole_head][whole_tail]")
        head_source, tail_source = "[whole_head]", "[whole_tail]"
    else:
        head_source = tail_source = "[0:a:0]"
    current = "[patch]"
    if has_head:
        lines.append(
            f"{head_source}atrim=end={plan.region_start + crossfade:.3f},asetpts=PTS-STARTPTS,{norm}[head]"
        )
        lines.append(f"[head]{current}{fade}[joined_head]")
        current = "[joined_head]"
    if has_tail:
        lines.append(
            f"{tail_source}atrim=start={plan.region_end - crossfade:.3f},asetpts=PTS-STARTPTS,{norm}[tail]"
        )
        lines.append(f"{current}[tail]{fade}[out]")
    else:
        lines.append(f"{current}anull[out]")
    return ";".join(lines)


def speech_splice_command(
    source: Path,
    background: Path,
    speech: Path,
    out: Path,
    plan: SplicePlan,
    background_offset: float,
    gain_db: float = 0.0,
    sample_rate: int = 48000,
    layout: str = "stereo",
    has_video: bool = False,
    source_duration: float | None = None,
) -> FFmpegCommand:
    """Grava `out` com o áudio de `source` trocado na região do plano; com vídeo, copia a imagem."""
    has_head = plan.region_start > 0.0
    has_tail = source_duration is None or plan.region_end < source_duration - 0.01
    graph = speech_splice_graph(
        plan, background_offset, gain_db, sample_rate, layout, has_head=has_head, has_tail=has_tail
    )
    args = ["-i", str(source), "-i", str(background), "-i", str(speech), "-filter_complex", graph]
    if has_video:
        args += ["-map", "0:v:0", "-c:v", "copy", "-map", "[out]", *VIDEO_AUDIO_ARGS]
        if out.suffix.lower() in FASTSTART_CONTAINERS:
            args += [
                "-movflags",
                "+faststart",
            ]  # o índice no começo deixa o arquivo tocar antes de baixar inteiro
    else:
        args += ["-map", "[out]", *encoder_args(out)]
    return FFmpegCommand([*args, str(out)], label="correção de fala", total=source_duration)


def speaker_reference_command(stem: Path, start: float, end: float, out: Path) -> FFmpegCommand:
    """Recorta a referência do falante (mono, 24 kHz) do stem de voz; `start` e `end` são tempos do stem."""
    args = [
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{end - start:.3f}",
        "-i",
        str(stem),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(REFERENCE_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    return FFmpegCommand(args, label="referência do falante", total=end - start)
