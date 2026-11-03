"""O quadro de um instante: a linha do tempo reduzida à janela em volta dele, no relógio do vídeo final.

Para mostrar um quadro do projeto não se monta o vídeo inteiro: só os trechos que aparecem no instante entram (o
anterior também, se uma transição o mistura com o seguinte ali), o primeiro aberto no quadro certo. O resto do
grafo (imagens, composições, PiP, texto) é o da montagem final e fala em tempo absoluto; por isso o relógio da
janela é levado ao instante pedido, e o quadro que sai é o primeiro. Funções puras: nada aqui executa ffmpeg.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..domain.timeline import TimelineWindow
from .common import Inputs
from .person_layer import floor_seconds
from .timeline import timeline_graph

# Um quadro só, sem áudio, em PNG RGB: é o quadro que o render faria, sem a perda de um JPEG (que mudaria os pixels
# que o editor confere) nem o alfa, que o vídeo final não tem. Para um quadro de prévia o arquivo fica em
# algumas centenas de KB, que o navegador baixa da própria máquina em poucos milissegundos.
FRAME_ENCODE = ["-an", "-frames:v", "1"]


def add_window_inputs(inputs: Inputs, mezzanines: Sequence[Path], window: TimelineWindow) -> None:
    """Os mezaninos da janela como entradas. O primeiro é aberto com `-ss` no quadro em que a janela começa, para
    o ffmpeg não decodificar a gravação inteira até lá; o recorte é por quadro (`window.seek` é múltiplo dele)."""
    for index, path in enumerate(mezzanines):
        pre = ["-ss", f"{floor_seconds(window.seek):.6f}"] if index == 0 and window.seek > 0 else []
        inputs.add(path, *pre)


def instant_timeline_lines(
    window: TimelineWindow, fps: float, size: tuple[int, int], index: int
) -> tuple[list[str], str]:
    """Linhas do grafo da janela, sem áudio, e o rótulo de um único quadro (o `index` do vídeo final) já no relógio
    dele.

    O grafo é o da linha do tempo (`timeline_graph`) sobre os trechos da janela, com `lead_in` igual ao início
    dela no tempo final, para as transições durarem o mesmo que no render completo. Do que sai fica só o quadro
    pedido (`trim`), com o relógio do vídeo final (`setpts`): sem isso o quadro sairia no instante 0 e as imagens,
    o PiP e o texto, que contam do começo do vídeo, não casariam."""
    position = index - window.first_frame
    if not 0 <= position < window.frame_count:
        raise ValueError(
            f"o quadro {index} não está na janela ({window.first_frame} a {window.first_frame + window.frame_count - 1})"
        )
    graph = timeline_graph(
        len(window.durations),
        list(window.durations),
        list(window.transitions),
        fps,
        want_video=True,
        size=size,
        lead_in=window.origin,
        want_audio=False,
    )
    assert graph.video is not None
    lines = [
        *graph.lines,
        f"{graph.video}trim=start_frame={position}:end_frame={position + 1},"
        f"setpts=PTS-STARTPTS+{index / fps:.6f}/TB[vclock]",
    ]
    return lines, "[vclock]"


def display_line(cur_v: str) -> str:
    """O quadro em RGB, como a tela mostra o vídeo renderizado.

    A codificação final do render converte o quadro da matriz de cor que ele traz (sem etiqueta, a BT.601) para a
    BT.709 que a etiqueta de cor da saída declara, e o player decodifica com essa matriz. As duas conversões, em
    4:2:0, mexem na cor das bordas: refazê-las aqui dá o quadro que o vídeo mostra (medido: byte a byte igual ao
    quadro extraído do render sem perdas), e não o RGB direto do grafo. Forçar a BT.709 na entrada trocaria as cores
    (um vermelho puro saía (255, 23, 0) em vez de (250, 0, 0)). O rótulo da saída é `[vout]`."""
    return (
        f"{cur_v}format=yuv420p,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
        "scale=in_color_matrix=bt709:in_range=tv,format=rgb24[vout]"
    )
