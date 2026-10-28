"""Queima de filme e vazamento de luz: a troca acontece escondida sob uma luz colorida que cruza o quadro."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...domain import curves
from ..lightleak import LeakLook, light_leak_source
from .registry import TransitionRequest, register
from .window import close_window, monotone, open_window, paced_crossfade


@dataclass(frozen=True)
class BurnPlan:
    """Parâmetros de cada quadro da janela."""

    mix: list[float]  # peso da imagem que entra na mistura
    intensity: list[float]  # intensidade da luz (0 a 1)
    position: list[float]  # posição do centro do feixe (0 = borda esquerda, 1 = borda direita)


# Vazamento de luz: uma faixa estreita e inclinada, de rosa a laranja com miolo quente, que atravessa o quadro de
# fora a fora (centro de -0,35 a 1,35) sem cobrir a imagem toda; a mistura acontece durante a travessia.
LIGHT_LEAK_LOOK = LeakLook(
    edge=(214, 40, 150), mid=(255, 138, 40), core=(255, 238, 190), width=0.24, tilt=0.35, floor=0.0
)
LIGHT_LEAK_SPAN = (-0.35, 1.35)
LIGHT_LEAK_PEAK = 0.9
LIGHT_LEAK_MIX = (0.25, 0.75)

# Queima de filme: um feixe largo, laranja-avermelhado nas bordas e quase branco no miolo, com exposição geral
# alta (`floor`): no pico a imagem inteira queima. O pico fica por trás da troca, que é rápida e escondida.
FILM_BURN_LOOK = LeakLook(
    edge=(232, 62, 12), mid=(255, 152, 32), core=(255, 246, 214), width=0.55, tilt=0.15, floor=0.45, gain=1.7
)
FILM_BURN_SPAN = (-0.1, 0.6)
FILM_BURN_MIX = (0.42, 0.58)
# Oscilação de brilho, como a luz de um projetor: pequena e fixa (sem sorteio), para o resultado ser o mesmo a cada
# render.
FILM_FLICKER = 0.08


def _smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def _bell(progress: float) -> float:
    """Sino de 0 a 1 sobre o progresso (0 nas pontas, 1 no meio); a mola passa de 1 sem acender a luz de novo."""
    return math.sin(math.pi * min(max(progress, 0.0), 1.0))


def _soft_bell(progress: float) -> float:
    """Sino de 0 a 1 com inclinação zero nas pontas e no pico: a luz entra, queima e sai sem degrau (o `sin`
    puro tem pico pontudo, que no vazamento de luz é bom, mas a queima precisa ficar cheia um instante)."""
    edge = min(max(progress, 0.0), 1.0)
    return _smoothstep(2.0 * min(edge, 1.0 - edge))


def plan_lightleak(curve: str, frames: int) -> BurnPlan:
    """A curva dirige a travessia do feixe e o sino da intensidade."""
    p = curves.samples(curve, frames)
    start, end = LIGHT_LEAK_SPAN
    low, high = LIGHT_LEAK_MIX
    return BurnPlan(
        mix=monotone([_smoothstep((x - low) / (high - low)) for x in p]),
        intensity=[LIGHT_LEAK_PEAK * _bell(x) for x in p],
        position=[start + (end - start) * min(max(x, 0.0), 1.0) for x in p],
    )


def plan_filmburn(curve: str, frames: int) -> BurnPlan:
    """A intensidade chega a 1 no meio da troca, onde a mistura das imagens é curta e fica escondida."""
    p = curves.samples(curve, frames)
    start, end = FILM_BURN_SPAN
    low, high = FILM_BURN_MIX
    flicker = [1.0 - FILM_FLICKER * ((k * 7919) % 13) / 12.0 for k in range(frames)]
    return BurnPlan(
        mix=monotone([_smoothstep((x - low) / (high - low)) for x in p]),
        intensity=[_soft_bell(x) * flicker[k] for k, x in enumerate(p)],
        position=[start + (end - start) * min(max(x, 0.0), 1.0) for x in p],
    )


def _burn(request: TransitionRequest, plan: BurnPlan, look: LeakLook) -> list[str]:
    size = request.require_size()
    t = request.tag
    lines, window = open_window(request)
    lines += paced_crossfade(request, window.tail, window.head, f"[{t}_mix]", plan.mix, t)
    lines += light_leak_source(f"[{t}_leak]", size, request.fps, look, plan.intensity, plan.position)
    lines.append(f"[{t}_mix][{t}_leak]overlay=format=yuv420[{t}_mid]")
    return lines + close_window(request, window, f"[{t}_mid]")


@register("lightleak")
def lightleak(request: TransitionRequest) -> list[str]:
    return _burn(request, plan_lightleak(request.curve, request.frames), LIGHT_LEAK_LOOK)


@register("filmburn")
def filmburn(request: TransitionRequest) -> list[str]:
    return _burn(request, plan_filmburn(request.curve, request.frames), FILM_BURN_LOOK)
