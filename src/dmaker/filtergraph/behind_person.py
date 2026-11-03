"""Pilha de profundidade da montagem final: o vídeo, depois o que fica atrás da pessoa (hoje o texto em ASS) e a
pessoa recortada por cima, só nos intervalos em que há algo atrás dela.

A pilha é uma função pura que recebe uma lista de camadas "de trás": o texto atrás da pessoa é a primeira e uma
composição em HTML entra como mais uma, sem reescrever o resto."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .common import Inputs, ffq


@dataclass(frozen=True)
class ResolvedPersonLayer:
    """Vídeo com alfa da pessoa e o trecho da linha do tempo final que ele cobre: `start` é o instante do
    primeiro quadro e `stop` o do quadro seguinte ao último, ambos na grade de quadros do vídeo final."""

    path: Path
    start: float
    stop: float


class BehindLayer(Protocol):
    """Uma camada que fica entre o fundo e a pessoa."""

    def attach(self, lines: list[str], inputs: Inputs, source: str, tag: str) -> str:
        """Acrescenta os filtros que desenham a camada sobre `source` e devolve o rótulo do resultado."""


@dataclass(frozen=True)
class AssBehindLayer(BehindLayer):
    """Texto em ASS: o arquivo vai por caminho relativo ao diretório do job, como o ASS da frente."""

    filename: str
    fonts_dir: str

    def attach(self, lines: list[str], inputs: Inputs, source: str, tag: str) -> str:
        lines.append(f"{source}ass=filename={ffq(self.filename)}:fontsdir={ffq(self.fonts_dir)}[{tag}]")
        return f"[{tag}]"


def behind_person_graph(
    lines: list[str],
    inputs: Inputs,
    cur_v: str,
    behind: Sequence[BehindLayer],
    people: Sequence[ResolvedPersonLayer],
    fps: float,
) -> str:
    """Camadas de trás sobre `cur_v` e, por cima, a pessoa de cada intervalo; devolve o rótulo final.

    A pessoa entra com `overlay` limitado ao intervalo dela (`enable`): fora dele a saída é o quadro de antes,
    sem passar pelo vídeo da pessoa. Três ajustes evitam um quadro de erro:
    - o vídeo da pessoa começa 1/4 de quadro antes do quadro de fundo correspondente. O `overlay` escolhe o
      quadro da pessoa de instante menor ou igual ao do fundo, e o arredondamento da base de tempo poderia
      deixar o dela um microssegundo depois, atrasando a pessoa um quadro inteiro;
    - um quadro repetido no fim do vídeo da pessoa (`tpad`, já fora do `enable`): o último quadro não tem um
      seguinte que diga até quando ele vale, e o `overlay` o descartava (medido: o último quadro do intervalo
      saía sem a pessoa);
    - o `enable` é medido meio quadro antes dos limites, porque o instante do quadro tem a mesma imprecisão e
      os limites caem exatamente sobre quadros (a pessoa e o texto começam no mesmo quadro).

    O `overlay` trabalha em `yuv420` (a pessoa entra como yuva420p): com `format=auto` o quadro de fundo é
    convertido para yuva420p e de volta, e mesmo um alfa zero muda os pixels em 1 nível (medido); em `yuv420` o
    fundo passa intacto onde a pessoa é transparente, que é a garantia de que só a pessoa muda a imagem."""
    for k, layer in enumerate(behind):
        cur_v = layer.attach(lines, inputs, cur_v, f"v_behind{k}")
    quarter, half = 0.25 / fps, 0.5 / fps
    for k, person in enumerate(people):
        index = inputs.add(person.path)
        lines.append(
            f"[{index}:v]tpad=stop_mode=clone:stop=1,setpts=PTS-STARTPTS{person.start - quarter:+.6f}/TB[person{k}]"
        )
        window = f"gte(t,{person.start - half:.6f})*lt(t,{person.stop - half:.6f})"
        lines.append(
            f"{cur_v}[person{k}]overlay=eof_action=pass:enable='{window}':format=yuv420[v_person{k}]"
        )
        cur_v = f"[v_person{k}]"
    return cur_v
