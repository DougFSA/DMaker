"""Pré-mixagem das falas dubladas em blocos, para a mixagem e as trilhas caberem na linha de comando do Windows.

A mixagem do vídeo e as trilhas separadas têm uma entrada por fala (`-i`), e uma dublagem de centenas de falas
passa dos 32.767 caracteres. Aqui as falas viram blocos que o mesmo planejador da narração (`blocks.py`) monta
em WAVs intermediários: cada bloco soma as suas falas com as mesmas cadeias de `dub_clip_lines` (volume, corte,
atraso) e o resultado volta como uma fala só, já na posição, para `dub_mix_command` e `dub_stems_command`
seguirem como estão. Com poucas falas não há bloco, e os comandos são os de sempre.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from ..voice.watermark import delay_on_detector_grid
from .blocks import (
    INTERMEDIATE_CODEC_ARGS,
    MAX_INPUTS,
    BlockReduction,
    BlockSlot,
    GraphStep,
    graph_file_args,
    reduce_in_blocks,
)
from .dub import DubClip, dub_clip_lines


def dub_block_step(clips: Sequence[DubClip], slot: BlockSlot) -> tuple[GraphStep, DubClip]:
    """Soma as falas de um bloco num WAV float estéreo e devolve a fala que o representa no nível seguinte.

    O WAV começa na primeira fala do bloco, não no zero do arquivo (senão cada bloco carregaria minutos de
    silêncio), e a fala que o representa entra no atraso da primeira. Os atrasos de dentro do bloco são a
    diferença entre os atrasos já arredondados à grade de 20 ms do detector da marca d'água: cada fala cai
    no mesmo milissegundo de quando entra sozinha na mixagem, sem arredondar duas vezes.
    `amix` com `normalize=0` soma sem dividir (como a mixagem) e `duration=longest` não corta a fala mais longa.
    """
    delays = [delay_on_detector_grid(clip.start) for clip in clips]
    origin = min(delays)
    local = [replace(clip, start=(delay - origin) / 1000) for clip, delay in zip(clips, delays, strict=True)]
    lines, labels = dub_clip_lines(local, first_clip_input=0)
    lines.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[out]")
    args: list[str] = []
    for clip in clips:
        args += ["-i", str(clip.path)]
    args += [*graph_file_args(slot.graph_file), "-map", "[out]", *INTERMEDIATE_CODEC_ARGS, str(slot.out)]
    step = GraphStep(FFmpegCommand(args, label=f"dublagem, {slot.label}"), ";".join(lines), slot.graph_file)
    return step, DubClip(slot.out, start=origin / 1000)


def premix_dub_clips(
    clips: Sequence[DubClip], work_dir: Path, limit: int = MAX_INPUTS
) -> BlockReduction[DubClip]:
    """Os passos que pré-misturam as falas em blocos e as falas que sobram para o comando de mixagem ou de trilhas.

    Até `limit` falas não há passo nenhum e as falas voltam intactas.
    """
    return reduce_in_blocks(clips, work_dir, dub_block_step, limit)
