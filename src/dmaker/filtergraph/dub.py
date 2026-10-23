"""Comando ffmpeg da dublagem: o fundo inteiro, cada fala dublada na sua posição e, opcionalmente, a voz original.

O grafo é uma função pura. Como um vídeo longo tem dezenas de falas (uma entrada e uma cadeia de filtros para
cada), o grafo vai para um arquivo lido com `-/filter_complex`, e a linha de comando não estoura o limite de
32 mil caracteres do Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from .speech_edit import FASTSTART_CONTAINERS, VIDEO_AUDIO_ARGS
from .voice import encoder_args

MIX_SAMPLE_RATE = 48000  # mesma taxa do resto do pipeline (ver filtergraph/audio.py)
FADE_OUT_SECONDS = 0.08  # o corte de uma fala que não coube cai num fade curto, sem estalo
# Limitador a -1 dBFS (0,891 linear), o mesmo da narração: fundo e fala somados podem passar de 0 dBFS, e o
# `level=disabled` impede que ele renormalize o volume sozinho.
LIMITER = "alimiter=limit=0.891:level=disabled"


@dataclass(frozen=True)
class DubClip:
    """Uma fala dublada já sintetizada e onde ela entra no arquivo."""

    path: Path
    start: float  # segundos no arquivo
    gain_db: float = 0.0  # iguala o volume da fala ao da voz original
    tempo: float = 1.0  # aceleração sem mudar o tom, quando a fala passou do espaço
    max_seconds: float | None = None  # corta (com fade) o que passar disso: a fala não cabia


@dataclass(frozen=True)
class DubMix:
    command: FFmpegCommand
    graph: str  # texto do filtergraph; quem executa o grava em `graph_file` antes de rodar o comando


def _stereo_48k() -> str:
    """Mesma taxa, formato e canais em todos os ramos, que o amix exige iguais (a fala mono vira estéreo)."""
    return f"aresample={MIX_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"


def _clip_chain(clip: DubClip) -> str:
    """Cadeia de uma fala: acelera se preciso, ajusta o volume, corta com fade se não coube e atrasa até a posição."""
    chain: list[str] = []
    if abs(clip.tempo - 1.0) > 1e-4:
        chain.append(f"atempo={clip.tempo:.4f}")
    chain.append(f"volume={clip.gain_db:.2f}dB")
    if clip.max_seconds is not None:
        fade_start = max(0.0, clip.max_seconds - FADE_OUT_SECONDS)
        chain.append(f"atrim=duration={clip.max_seconds:.3f}")
        chain.append(f"afade=t=out:st={fade_start:.3f}:d={FADE_OUT_SECONDS}")
    chain.append(_stereo_48k())
    chain.append(f"adelay=delays={max(0, round(clip.start * 1000))}:all=1")  # em ms; all=1: todos os canais
    return ",".join(chain)


def dub_mix_graph(
    clips: list[DubClip],
    first_clip_input: int,
    background_input: int,
    duration: float,
    original_voice_input: int | None = None,
    original_voice_db: float = -18.0,
) -> str:
    """Grafo da mixagem. A saída é `[out]`, com a duração do arquivo original.

    `amix` com `normalize=0` soma sem dividir pelo número de entradas (o padrão baixaria o fundo e as falas a
    cada fala nova); `duration=first` acompanha o fundo, que é a entrada mais longa; `apad` e `atrim` fixam
    a duração no original para a imagem e o som terminarem juntos.
    """
    lines = [f"[{background_input}:a]{_stereo_48k()}[background]"]
    labels = ["[background]"]
    if original_voice_input is not None:
        lines.append(f"[{original_voice_input}:a]volume={original_voice_db:.1f}dB,{_stereo_48k()}[original]")
        labels.append("[original]")
    for index, clip in enumerate(clips):
        lines.append(f"[{first_clip_input + index}:a]{_clip_chain(clip)}[dub{index}]")
        labels.append(f"[dub{index}]")
    lines.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0,{LIMITER},"
        f"apad=whole_dur={duration:.3f},atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[out]"
    )
    return ";".join(lines)


def dub_mix_command(
    source: Path,
    background: Path,
    clips: list[DubClip],
    out: Path,
    graph_file: Path,
    duration: float,
    has_video: bool,
    original_voice: Path | None = None,
    original_voice_db: float = -18.0,
) -> DubMix:
    """Grava `out` com o fundo, as falas dubladas e (se pedida) a voz original atenuada; com vídeo, copia a imagem.

    Entradas: [0 = vídeo de origem, se houver], fundo, [voz original], falas. A imagem passa sem recodificar
    (rápido e sem perda); o áudio sai em AAC 192 kb/s, transparente para fala com música.
    """
    inputs: list[Path] = [source] if has_video else []
    background_input = len(inputs)
    inputs.append(background)
    original_input = None
    if original_voice is not None:
        original_input = len(inputs)
        inputs.append(original_voice)
    first_clip = len(inputs)
    inputs += [clip.path for clip in clips]

    graph = dub_mix_graph(clips, first_clip, background_input, duration, original_input, original_voice_db)
    args: list[str] = []
    for path in inputs:
        args += ["-i", str(path)]
    args += ["-/filter_complex", str(graph_file)]
    if has_video:
        args += ["-map", "0:v:0", "-c:v", "copy", "-map", "[out]", *VIDEO_AUDIO_ARGS]
        if out.suffix.lower() in FASTSTART_CONTAINERS:
            args += [
                "-movflags",
                "+faststart",
            ]  # o índice no começo deixa o arquivo tocar antes de baixar inteiro
    else:
        args += ["-map", "[out]", *encoder_args(out)]
    return DubMix(FFmpegCommand([*args, str(out)], label="dublagem", total=duration), graph)
