"""Chicote (whip pan) e desfoque deslizando: a próxima imagem empurra a anterior numa tira, com desfoque."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...domain import curves
from ..expressions import lookup, sendcmd_table
from .registry import TransitionRequest, register
from .window import close_window, no_undershoot, open_window

# Desfoque de movimento do chicote: o traço de cada quadro tem o comprimento do deslocamento daquele quadro
# (obturador de 360 graus, mais que uma câmera real, para o chicote se ler como chicote) e um gaussiano de
# sigma L / sqrt(12) tem a mesma variância de um traço reto uniforme de comprimento L.
WHIP_SHUTTER = 1.0
STREAK_SIGMA = WHIP_SHUTTER / math.sqrt(12.0)
# Pico do desfoque gaussiano do desfoque deslizando, em fração do lado menor do quadro: no meio do
# deslocamento as duas imagens perdem o detalhe fino, e nas pontas voltam nítidas.
SLIDE_BLUR_FRACTION = 0.03


@dataclass(frozen=True)
class PushPlan:
    """Parâmetros de cada quadro da janela."""

    shift: list[float]  # deslocamento da tira, em frações do lado do quadro (1 = a próxima imagem chegou)
    blur: list[float]  # sigma do desfoque, em frações do lado do quadro


def plan_whippan(curve: str, frames: int) -> PushPlan:
    """O desfoque acompanha a velocidade do deslocamento: parado, nítido; no pico da curva, um traço longo. Com
    a mola o pico vem logo depois da partida e o quadro assenta nítido depois de passar do ponto.

    A velocidade de cada quadro é a diferença central entre o quadro anterior e o seguinte, e a conta enxerga
    os dois vizinhos de fora da janela (antes dela o progresso é 0, depois dela é 1): assim o primeiro quadro
    sai do repouso e o último chega nele, em vez de herdar a velocidade média dos quadros de dentro. O primeiro
    quadro não tem desfoque, para a janela começar exatamente onde o clipe parou."""
    around = no_undershoot([curves.progress(curve, k / frames) for k in range(-1, frames + 1)])
    shift = around[1:-1]
    speeds = [abs(around[k + 2] - around[k]) / 2.0 for k in range(frames)]
    speeds[0] = 0.0  # o primeiro quadro da janela sai igual ao último do clipe: o corte de entrada é limpo
    return PushPlan(shift=shift, blur=[STREAK_SIGMA * speed for speed in speeds])


def plan_blurslide(curve: str, frames: int) -> PushPlan:
    """O desfoque tem a forma de um sino sobre o progresso: zero nas pontas, máximo com as duas imagens
    meio a meio. Passar do ponto (mola) não desfoca de novo: o sino usa o progresso limitado a [0, 1]."""
    shift = no_undershoot(curves.samples(curve, frames))
    return PushPlan(
        shift=shift,
        blur=[SLIDE_BLUR_FRACTION * math.sin(math.pi * min(max(p, 0.0), 1.0)) for p in shift],
    )


def _strip_lines(
    request: TransitionRequest, window_tail: str, window_head: str, vertical: bool, overshoot: bool
) -> list[str]:
    """Monta a tira [saída | entrada] (e, se a mola passa do ponto, um espelho da entrada para o quadro não
    mostrar o vazio depois dela). Devolve as linhas e o rótulo da tira."""
    t = request.tag
    stack = "vstack" if vertical else "hstack"
    flip = "vflip" if vertical else "hflip"
    if not overshoot:
        return [f"{window_tail}{window_head}{stack}=inputs=2[{t}_strip]"]
    return [
        f"{window_head}split=2[{t}_h0][{t}_h1]",
        f"[{t}_h1]{flip}[{t}_mirror]",
        f"{window_tail}[{t}_h0][{t}_mirror]{stack}=inputs=3[{t}_strip]",
    ]


def _push(request: TransitionRequest, plan: PushPlan, vertical: bool, isotropic_blur: bool) -> list[str]:
    width, height = request.require_size()
    side = height if vertical else width
    t = request.tag
    lines, window = open_window(request)
    lines += _strip_lines(request, window.tail, window.head, vertical, max(plan.shift) > 1.0 + 1e-6)
    offsets = lookup([s * side for s in plan.shift], "n", 2)
    axis = f"x=0:y='{offsets}'" if vertical else f"x='{offsets}':y=0"
    lines.append(f"[{t}_strip]crop=w={width}:h={height}:{axis}[{t}_view]")
    blur = f"gblur@{t}blur"
    sigmas = [fraction * min(width, height) if isotropic_blur else fraction * width for fraction in plan.blur]
    # o chicote só borra no sentido do movimento (sigmaV=0); o desfoque deslizando borra nos dois
    options = "sigma=0:steps=2" if isotropic_blur else "sigma=0:sigmaV=0:steps=2"
    commands = sendcmd_table(blur, "sigma", sigmas, request.fps, 2)
    lines.append(f"[{t}_view]sendcmd=c='{commands}',{blur}={options}[{t}_mid]")
    return lines + close_window(request, window, f"[{t}_mid]")


@register("whippan")
def whippan(request: TransitionRequest) -> list[str]:
    return _push(request, plan_whippan(request.curve, request.frames), vertical=False, isotropic_blur=False)


@register("blurslide")
def blurslide(request: TransitionRequest) -> list[str]:
    return _push(request, plan_blurslide(request.curve, request.frames), vertical=True, isotropic_blur=True)
