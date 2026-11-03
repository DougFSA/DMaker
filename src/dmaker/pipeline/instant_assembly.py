"""Montagem do quadro de um instante: a janela da linha do tempo com as mesmas camadas da montagem final.

É a `build_assembly` reduzida a um quadro de imagem: o mesmo empilhamento (atrás da pessoa, pessoa, imagens,
composições, PiP, texto), mas sobre a janela de trechos que o instante pede e sem nada de áudio, que um quadro
não tem: a mixagem, o loudness e o audiograma (que precisa do som) ficam de fora.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from ..domain.timeline import TimelineWindow
from ..filtergraph.behind_person import ResolvedPersonLayer
from ..filtergraph.common import Inputs
from ..filtergraph.html_layer import ResolvedHtmlLayer
from ..filtergraph.instant import FRAME_ENCODE, add_window_inputs, display_line, instant_timeline_lines
from ..media.ffmpeg import FFmpegCommand, filter_complex_file_args
from .assembly import Assembly, compose_front_layers, text_layer_line
from .context import RenderContext
from .textlayer import TextLayer


def build_instant_assembly(
    ctx: RenderContext,
    window: TimelineWindow,
    mezzanines: Sequence[Path],
    index: int,
    total: float,
    layer: TextLayer,
    html_layers: Sequence[ResolvedHtmlLayer],
    person_layers: Sequence[ResolvedPersonLayer],
    out_path: Path,
) -> Assembly:
    """Comando que grava em `out_path` o quadro `index` do vídeo final. O grafo vai em arquivo
    (`graph.txt`, na pasta do trabalho, que é o `cwd` do comando), como na montagem final, e o ASS é referenciado
    por caminho relativo a ela. `total` é a duração do vídeo inteiro, que as imagens e os PiP usam para saber se
    vão até o fim."""
    inputs = Inputs()
    add_window_inputs(inputs, mezzanines, window)
    lines, cur_v = instant_timeline_lines(window, ctx.fps, (ctx.width, ctx.height), index)
    # o PiP entra mudo: não há áudio neste grafo, e uma saída de áudio solta o ffmpeg recusa
    silent_pips = [replace(pip, has_audio=False) for pip in layer.video_overlays]
    cur_v, _ = compose_front_layers(
        ctx, lines, inputs, cur_v, layer, html_layers, person_layers, total, video_overlays=silent_pips
    )
    if layer.has_text:
        lines.append(text_layer_line(ctx, cur_v))
        cur_v = "[v_ass]"
    lines.append(display_line(cur_v))
    args = (
        inputs.args + filter_complex_file_args("graph.txt") + ["-map", "[vout]", *FRAME_ENCODE, str(out_path)]
    )
    return Assembly(FFmpegCommand(args, label="quadro do instante", cwd=ctx.job_dir), lines)
