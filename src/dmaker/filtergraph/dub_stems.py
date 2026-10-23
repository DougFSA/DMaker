"""Comando ffmpeg das trilhas separadas da dublagem: voz dublada, fundo e voz original, para remixar em outro editor.

As três saem de um só ffmpeg e de um só grafo (função pura, gravada em arquivo como o da mixagem). A voz dublada
usa as mesmas cadeias de fala da mixagem (`dub_clip_lines`: posição, ganho, encaixe), então somada ao fundo ela
reproduz a mixagem do vídeo antes do acabamento. Não há loudnorm nem limitador: o acabamento é de quem remixa.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from .dub import MIX_SAMPLE_RATE, DubClip, dub_clip_lines, stereo_48k

# WAV PCM 16 bits: abre em qualquer editor (Premiere, DaVinci, CapCut) sem codec e sem perda sobre o que o
# pipeline já guarda; estéreo porque a mixagem do vídeo é estéreo e a fala mono duplicada nos dois lados soma igual.
STEM_CODEC_ARGS = ["-c:a", "pcm_s16le", "-ar", str(MIX_SAMPLE_RATE), "-ac", "2"]


def exact_samples(duration: float) -> str:
    """Completa com silêncio e corta no quadro de áudio exato do vídeo (a mixagem arredonda para o milissegundo)."""
    total = round(duration * MIX_SAMPLE_RATE)
    return f"apad=whole_len={total},atrim=end_sample={total},asetpts=PTS-STARTPTS"


@dataclass(frozen=True)
class StemOutputs:
    """Onde gravar cada trilha."""

    voice_dubbed: Path
    background: Path
    voice_original: Path


@dataclass(frozen=True)
class DubStemsCommand:
    command: FFmpegCommand
    graph: str  # quem executa o grava em `graph_file` antes de rodar o comando


def dub_stems_graph(clips: list[DubClip], duration: float) -> str:
    """Grafo das três trilhas. Entradas: 0 = fundo, 1 = voz original, 2 em diante = as falas.

    A voz dublada soma as falas com `amix` `normalize=0` (como a mixagem) e `duration=longest`: o `first` da
    mixagem acompanha o fundo, mas aqui a primeira entrada é uma fala curta que cortaria as seguintes.
    """
    fixed = exact_samples(duration)
    lines = [
        f"[0:a]{stereo_48k()},{fixed}[background]",
        f"[1:a]{stereo_48k()},{fixed}[original]",
    ]
    clip_lines, clip_labels = dub_clip_lines(clips, first_clip_input=2)
    lines += clip_lines
    lines.append(
        f"{''.join(clip_labels)}amix=inputs={len(clip_labels)}:duration=longest:normalize=0,{fixed}[voice]"
    )
    return ";".join(lines)


def dub_stems_command(
    background: Path,
    voice_original: Path,
    clips: list[DubClip],
    outputs: StemOutputs,
    graph_file: Path,
    duration: float,
) -> DubStemsCommand:
    """Grava as três trilhas WAV com a duração do vídeo, todas começando no zero."""
    if not clips:
        raise ValueError("Sem falas dubladas para exportar a trilha de voz.")
    args: list[str] = []
    for path in [background, voice_original, *(clip.path for clip in clips)]:
        args += ["-i", str(path)]
    args += ["-/filter_complex", str(graph_file)]
    for label, path in (
        ("[voice]", outputs.voice_dubbed),
        ("[background]", outputs.background),
        ("[original]", outputs.voice_original),
    ):
        args += ["-map", label, *STEM_CODEC_ARGS, str(path)]
    return DubStemsCommand(
        FFmpegCommand(args, label="trilhas", total=duration), dub_stems_graph(clips, duration)
    )
