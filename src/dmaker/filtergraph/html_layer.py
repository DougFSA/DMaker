"""A composição em HTML na montagem final: o vídeo com alfa que o renderizador gerou, posto sobre o quadro.

O arquivo da composição (`pipeline/html_layer.py`) é um .mov de PNG com alfa que começa no instante 0; aqui ele é
alinhado à grade de quadros do vídeo final e entra por `overlay`, na frente das imagens ou, com
`layer: "behind-person"`, na pilha de trás da pessoa (`behind_person.py`)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from .behind_person import BehindLayer
from .common import Inputs
from .person_layer import person_layer_command


@dataclass(frozen=True)
class ResolvedHtmlLayer:
    """O vídeo com alfa de uma composição e onde ele entra: `start` é o instante do primeiro quadro e `stop` o do
    quadro seguinte ao último, na grade de quadros do vídeo final; `x` e `y` são as expressões do `overlay` (o
    canto de cima da área) e `scale_to` é o tamanho da área quando a página foi desenhada em outro (`size`)."""

    path: Path
    start: float
    stop: float
    x: str
    y: str
    scale_to: tuple[int, int] | None = None
    behind: bool = False


def html_layer_command(
    frames: Iterable[bytes],
    size: tuple[int, int],
    fps: float,
    frame_count: int,
    out: Path,
    label: str = "composição html",
) -> FFmpegCommand:
    """Escreve os quadros RGBA da composição (pelo stdin) como vídeo com alfa, do mesmo jeito que a camada da
    pessoa: PNG dentro do .mov, sem perdas e sem conversão para YUV na escrita."""
    return person_layer_command(frames, size[0], size[1], fps, frame_count, out, label=label)


def attach_html_layer(
    lines: list[str], inputs: Inputs, source: str, layer: ResolvedHtmlLayer, fps: float, tag: str
) -> str:
    """Acrescenta ao grafo a composição sobre `source` e devolve o rótulo do resultado.

    O alinhamento é o da pessoa recortada (`behind_person_graph`), pelos mesmos três motivos:
    - o vídeo começa 1/4 de quadro antes do quadro de fundo correspondente: o `overlay` escolhe o quadro de
      instante menor ou igual ao do fundo, e o arredondamento da base de tempo poderia atrasar um quadro inteiro;
    - o último quadro é repetido uma vez (`tpad`, já fora do `enable`): sem um quadro seguinte que diga até quando
      ele vale, o `overlay` o descartava;
    - o `enable` é medido meio quadro antes dos limites, porque o instante do quadro tem a mesma imprecisão.

    O `overlay` trabalha em `yuv420`: o fundo passa intacto onde a composição é transparente, e só muda o que ela
    de fato cobre."""
    quarter, half = 0.25 / fps, 0.5 / fps
    index = inputs.add(layer.path)
    chain = []
    if layer.scale_to is not None:
        chain.append(f"scale={layer.scale_to[0]}:{layer.scale_to[1]}:flags=lanczos")
    chain += ["tpad=stop_mode=clone:stop=1", f"setpts=PTS-STARTPTS{layer.start - quarter:+.6f}/TB"]
    lines.append(f"[{index}:v]{','.join(chain)}[{tag}_src]")
    window = f"gte(t,{layer.start - half:.6f})*lt(t,{layer.stop - half:.6f})"
    lines.append(
        f"{source}[{tag}_src]overlay=x={layer.x}:y={layer.y}:eof_action=pass:enable='{window}':format=yuv420[{tag}]"
    )
    return f"[{tag}]"


def html_overlay_graph(
    lines: list[str], inputs: Inputs, cur_v: str, layers: Sequence[ResolvedHtmlLayer], fps: float
) -> str:
    """Encadeia um `overlay` por composição da frente sobre `cur_v` e devolve o rótulo final."""
    for k, layer in enumerate(layers):
        cur_v = attach_html_layer(lines, inputs, cur_v, layer, fps, f"v_html{k}")
    return cur_v


@dataclass(frozen=True)
class HtmlBehindLayer(BehindLayer):
    """Composição que fica entre o fundo e a pessoa: entra na pilha de `behind_person_graph` como mais uma camada
    de trás, com o mesmo alinhamento das de frente."""

    layer: ResolvedHtmlLayer
    fps: float

    def attach(self, lines: list[str], inputs: Inputs, source: str, tag: str) -> str:
        return attach_html_layer(lines, inputs, source, self.layer, self.fps, tag)
