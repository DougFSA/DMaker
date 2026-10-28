"""Gerador de vazamento de luz: um feixe colorido e translúcido que cruza o quadro, gerado pelo próprio DMaker.

Sem arquivo de terceiros: o feixe é calculado por expressão (`geq`) num quadro pequeno e ampliado com
interpolação suave, e a luz é difusa por natureza, então a ampliação não aparece. A saída é um fluxo com canal
alfa (yuva420p) para sobrepor ao vídeo; a intensidade e a posição do feixe vêm de uma tabela por quadro, o que deixa
quem usa (as transições de queima de filme e de vazamento, e depois o acabamento visual) dirigir o efeito com a
curva e o envelope que quiser. Função pura: devolve linhas de grafo, não executa nada.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .common import even
from .expressions import lookup, number

Rgb = tuple[int, int, int]

# O feixe é calculado em um quadro 16 vezes menor em cada lado: 1080x1920 vira 66x120, 8 mil pixels em vez de 2
# milhões (a expressão do `geq` roda por pixel e por plano, e era o maior custo da troca: 26 ms por quadro com
# 8 vezes menor). Como a luz é um gradiente suave, a ampliação bicúbica não perde nada que se veja.
DOWNSCALE = 16


@dataclass(frozen=True)
class LeakLook:
    """Aparência do vazamento: cores da borda ao miolo e a forma do feixe."""

    edge: Rgb  # cor onde o feixe termina (mais fria)
    mid: Rgb  # cor intermediária
    core: Rgb  # cor do miolo (mais quente e clara)
    width: float  # largura do feixe, fração da largura do quadro
    tilt: float  # inclinação do feixe, fração da altura (0 = faixa vertical)
    floor: float  # parte da intensidade que vale no quadro todo, mesmo longe do feixe (exposição geral)
    gain: float = (
        1.0  # superexposição: acima de 1 a luz cobre mais (a opacidade satura antes da intensidade 1)
    )


def _channel(look: LeakLook, index: int, beam: str) -> str:
    """Cor do canal `index` ao longo do feixe: da borda ao miolo em duas rampas lineares (borda para meio com
    `beam` de 0 a 0,5; meio para miolo de 0,5 a 1)."""
    edge, mid, core = look.edge[index], look.mid[index], look.core[index]
    return f"{edge}+({mid}-{edge})*min(1,2*{beam})+({core}-{mid})*max(0,2*{beam}-1)"


def leak_expressions(look: LeakLook, intensity: Sequence[float], position: Sequence[float]) -> dict[str, str]:
    """Expressões do `geq` (r, g, b, a) de um quadro do vazamento.

    `position` é onde o centro do feixe está (0 = borda esquerda, 1 = direita; fora disso o feixe está fora do
    quadro) e `intensity` (0 a 1) quanto da luz aparece, ambos por quadro. O feixe é uma gaussiana na
    coordenada inclinada `X/W + tilt * (Y/H - 0,5)`.
    """
    centre = lookup(position, "N", 4)
    strength = lookup(intensity, "N", 4)
    coordinate = f"(X/W+{number(look.tilt)}*(Y/H-0.5))"
    beam = f"exp(-pow(({coordinate}-({centre}))/{number(look.width)},2))"
    floor = number(look.floor)
    alpha = f"255*clip({number(look.gain)}*({strength})*({floor}+(1-{floor})*{beam}),0,1)"
    return {
        "r": f"clip({_channel(look, 0, beam)},0,255)",
        "g": f"clip({_channel(look, 1, beam)},0,255)",
        "b": f"clip({_channel(look, 2, beam)},0,255)",
        "a": alpha,
    }


def light_leak_source(
    out: str,
    size: tuple[int, int],
    fps: float,
    look: LeakLook,
    intensity: Sequence[float],
    position: Sequence[float],
) -> list[str]:
    """Linhas que geram o vazamento em `out` (yuva420p, tamanho `size`, um quadro por entrada das tabelas).

    Os timestamps são 0, 1/fps, 2/fps..., os mesmos que as janelas de transição usam, para o `overlay` emparelhar
    cada quadro do vazamento com o seu quadro de vídeo.
    """
    if len(intensity) != len(position):
        raise ValueError("intensity e position precisam ter um valor por quadro")
    frames = len(intensity)
    width, height = size
    small_w, small_h = even(width / DOWNSCALE), even(height / DOWNSCALE)  # par: o yuv420p subamostra o croma
    expressions = ":".join(
        f"{plane}='{expression}'" for plane, expression in leak_expressions(look, intensity, position).items()
    )
    return [
        f"color=c=black@0:s={small_w}x{small_h}:r={fps:g}:d={frames / fps + 1 / fps:.4f},"
        f"format=gbrap,geq={expressions},trim=end_frame={frames},"
        # converte no quadro pequeno (barato) e amplia; o `format` final fixa o alfa na saída do scale
        f"format=yuva420p,scale={width}:{height}:flags=bicubic,format=yuva420p,"
        f"settb=AVTB,setpts=N/{fps:g}/TB{out}"
    ]
