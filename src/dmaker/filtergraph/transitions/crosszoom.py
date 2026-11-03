"""Zoom de passagem (cross-zoom): a imagem amplia e desfoca, e a próxima entra do mesmo zoom e assenta."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...domain import curves
from ...domain.curves import smoothstep
from ..expressions import lookup, sendcmd_table
from .registry import TransitionRequest, register
from .window import close_window, monotone, no_undershoot, open_window, paced_crossfade

# Quanto o quadro amplia além do enquadramento normal no meio da troca: 1,6x é o bastante para ler como
# "passagem" por dentro da imagem sem estourar a resolução do mezanino (a ampliação é interpolada, não
# inventa detalhe, e o desfoque do meio esconde isso).
ZOOM_GAIN = 0.6
# Desfoque máximo (sigma do gblur) como fração da largura do quadro: 3% (32 px em 1080) apaga o detalhe fino
# no meio da troca, onde as duas imagens se sobrepõem, e some nas pontas, que têm de ser nítidas.
BLUR_FRACTION = 0.03
# Faixa do progresso em que as duas imagens se misturam: a de saída some até 30% e a de entrada já é a única
# a partir de 70%, de modo que o encontro acontece no pico do desfoque, onde nada denuncia a emenda.
MIX_START, MIX_END = 0.3, 0.7
# A mola faz a imagem de entrada passar do enquadramento (zoom abaixo de 1); o `perspective` repete a borda
# e este limite impede que o recuo mostre mais do que uma faixa fina dela.
MIN_ZOOM = 0.94


@dataclass(frozen=True)
class CrossZoomPlan:
    """Parâmetros de cada quadro da janela."""

    zoom_out: list[float]  # ampliação da imagem que sai
    zoom_in: list[float]  # ampliação da imagem que entra
    mix: list[float]  # peso da imagem que entra na mistura
    blur: list[float]  # sigma do desfoque em fração da largura


def plan_crosszoom(curve: str, frames: int) -> CrossZoomPlan:
    """A curva dirige tudo: o progresso `p` amplia a imagem que sai, reduz a ampliação da que entra (em p=0,5
    as duas têm o mesmo zoom, então a emenda é contínua) e põe o pico do desfoque no meio da troca."""
    p = no_undershoot(curves.samples(curve, frames))
    return CrossZoomPlan(
        zoom_out=[1.0 + ZOOM_GAIN * x for x in p],
        zoom_in=[max(MIN_ZOOM, 1.0 + ZOOM_GAIN * (1.0 - x)) for x in p],
        mix=monotone([smoothstep((x - MIX_START) / (MIX_END - MIX_START)) for x in p]),
        blur=[BLUR_FRACTION * math.sin(math.pi * min(max(x, 0.0), 1.0)) for x in p],
    )


def zoom_filter(zooms: list[float]) -> str:
    """`perspective` que amplia o quadro em torno do centro: o quadro de saída mostra o retângulo central da
    fonte menor em 1/zoom. Usa `perspective` (e não scale + crop) porque ele reamostra com precisão de subpixel,
    sem o degrau de 1 px do corte inteiro (o tremor do `zoompan`), e mantém o tamanho do quadro fixo."""
    margins = [(1.0 - 1.0 / z) / 2.0 for z in zooms]
    # `in` do perspective conta a partir de 1 (o do crop e o do geq, a partir de 0): `in-1` é o índice do quadro
    margin = lookup(margins, "in-1", 5)
    left, right = f"W*({margin})", f"W*(1-({margin}))"
    top, bottom = f"H*({margin})", f"H*(1-({margin}))"
    corners = {
        "x0": left,
        "y0": top,
        "x1": right,
        "y1": top,
        "x2": left,
        "y2": bottom,
        "x3": right,
        "y3": bottom,
    }
    options = ":".join(f"{key}='{value}'" for key, value in corners.items())
    return f"perspective={options}:eval=frame:interpolation=cubic"


@register("crosszoom")
def crosszoom(request: TransitionRequest) -> list[str]:
    width, _ = request.require_size()
    plan = plan_crosszoom(request.curve, request.frames)
    t = request.tag
    lines, window = open_window(request)
    lines += [
        f"{window.tail}{zoom_filter(plan.zoom_out)}[{t}_zo]",
        f"{window.head}{zoom_filter(plan.zoom_in)}[{t}_zi]",
    ]
    lines += paced_crossfade(request, f"[{t}_zo]", f"[{t}_zi]", f"[{t}_mix]", plan.mix, t)
    sigmas = [fraction * width for fraction in plan.blur]
    blur = f"gblur@{t}blur"
    lines.append(
        f"[{t}_mix]sendcmd=c='{sendcmd_table(blur, 'sigma', sigmas, request.fps)}',{blur}=sigma=0:steps=2[{t}_mid]"
    )
    return lines + close_window(request, window, f"[{t}_mid]")
