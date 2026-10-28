"""Curvas de tempo das transições: quanto da transição já aconteceu (0 a 1) em cada instante da janela.

Funções puras. A transição em si anda sempre com o mesmo desenho; a curva só decide o ritmo: constante
(`linear`), com partida e chegada suaves (`ease`) ou como uma mola, que passa um pouco do ponto final e assenta
(`spring`).
"""

from __future__ import annotations

import math
from typing import Literal, get_args

Curve = Literal["linear", "ease", "spring"]
CURVES: tuple[str, ...] = get_args(Curve)

# Mola amortecida (resposta ao degrau): razão de amortecimento 0,6 passa cerca de 9,5% do ponto final, o bastante
# para o olho ler "mola" sem a imagem balançar; 13 rad por janela assenta (resíduo abaixo de 0,1%) antes de a
# janela acabar, para o último quadro da transição já coincidir com o trecho seguinte.
SPRING_DAMPING = 0.6
SPRING_FREQUENCY = 13.0


def _spring(u: float) -> float:
    decay = SPRING_DAMPING * SPRING_FREQUENCY
    damped = SPRING_FREQUENCY * math.sqrt(1.0 - SPRING_DAMPING**2)
    return 1.0 - math.exp(-decay * u) * (math.cos(damped * u) + decay / damped * math.sin(damped * u))


def _ease(u: float) -> float:
    """Cúbica de entrada e saída suaves: simétrica, vale 0,5 no meio da janela."""
    return 4.0 * u**3 if u < 0.5 else 1.0 - (-2.0 * u + 2.0) ** 3 / 2.0


def progress(curve: str, u: float) -> float:
    """Progresso da transição no instante `u` (0 a 1) da janela. A mola ultrapassa 1 antes de assentar."""
    u = min(max(u, 0.0), 1.0)
    if curve == "ease":
        return _ease(u)
    if curve == "spring":
        return _spring(u)
    if curve == "linear":
        return u
    raise ValueError(f"Curva desconhecida: {curve!r}. Use {', '.join(CURVES)}.")


def samples(curve: str, frames: int) -> list[float]:
    """Progresso de cada quadro da janela: o quadro k mostra o instante k/frames, então a janela termina um
    quadro antes de 1 e o primeiro quadro do trecho seguinte é quem vale exatamente 1."""
    return [progress(curve, k / frames) for k in range(frames)]
