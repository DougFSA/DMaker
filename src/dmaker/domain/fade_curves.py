"""As curvas de ganho dos fades e dos crossfades de áudio, como funções puras do tempo normalizado.

Tudo aqui recebe `u` (0 no começo do fade, 1 no fim) e devolve um ganho em amplitude (1 = o nível original). Não
executa nada e não conhece ffmpeg: quem monta o grafo (`filtergraph.audio_effects.fades`, `filtergraph.crossfade`) lê
estas funções, e os testes comparam o que o ffmpeg faz com elas.

Há três famílias:
- as cinco curvas do Fade In e do Fade Out (`fade_in_gain`), que são as do filtro `afade` do ffmpeg com nomes em português;
- o Fade Ajustável (`adjustable_gain`): ganho inicial, ganho final e uma forma entre eles (subida, descida, S), com o
  ajuste do meio;
- os quatro tipos de crossfade (`crossfade_gains`), que são pares de Fade Ajustável casados.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# ---------- as cinco curvas do Fade In / Fade Out ----------

FADE_CURVES: tuple[str, ...] = ("linear", "logarithmic", "exponential", "sine", "quadratic")

# Correspondência com a curva do `afade` do ffmpeg (parâmetro `curve`), que é quem aplica o fade no grafo:
#   linear      -> tri   (u)
#   logarítmica -> log   (1 + 0,2 * log10(u): sobe depressa logo no começo e achata)
#   exponencial -> exp   (0,1 elevado a 5 * (1 - u): fica quase mudo e só abre no fim, 100 dB de faixa)
#   seno (S)    -> hsin  ((1 - cos(pi * u)) / 2: suave nas duas pontas)
#   quadrática  -> qua   (u ao quadrado)
AFADE_CURVE: dict[str, str] = {
    "linear": "tri",
    "logarithmic": "log",
    "exponential": "exp",
    "sine": "hsin",
    "quadratic": "qua",
}

# o `afade` log chega a zero em u = 1e-5 (1 + 0,2 * log10(1e-5) = 0)
_LOG_FLOOR = 1e-5


def fade_in_gain(curve: str, u: float) -> float:
    """O ganho de um fade de entrada em `u` (0 a 1), igual ao do `afade` com a curva correspondente."""
    u = min(max(u, 0.0), 1.0)
    if curve == "linear":
        return u
    if curve == "logarithmic":
        return max(1.0 + 0.2 * math.log10(max(u, _LOG_FLOOR / 10)), 0.0)
    if curve == "exponential":
        return 0.1 ** (5.0 * (1.0 - u))
    if curve == "sine":
        return (1.0 - math.cos(math.pi * u)) / 2.0
    if curve == "quadratic":
        return u * u
    raise ValueError(f"curva de fade desconhecida: {curve!r}. Use uma de: {', '.join(FADE_CURVES)}")


def fade_out_gain(curve: str, u: float) -> float:
    """O ganho de um fade de saída em `u` (0 no começo do fade, 1 no fim): a curva de entrada de trás para a frente."""
    return fade_in_gain(curve, 1.0 - u)


# ---------- Fade Ajustável ----------

ADJUSTABLE_SHAPES: tuple[str, ...] = ("up", "down", "s_up", "s_down", "sine_up", "sine_down")

# O ajuste do meio (de -100 a 100) entorta a forma com um expoente k = 2^(ajuste / 50): 0 deixa a forma como é, +100
# leva k a 4 (a subida demora a abrir) e -100 leva k a 1/4 (a subida abre logo).
MID_ADJUST_RANGE = 100.0
_MID_SCALE = 50.0


def _warp_exponent(mid_adjust: float) -> float:
    return 2.0 ** (mid_adjust / _MID_SCALE)


def _rising(family: str, u: float, k: float) -> float:
    """A forma de subida de cada família, de 0 a 1: `power` é a potência u^k; `s` é o S suave (cosseno elevado)
    aplicado ao tempo já entortado; `sine` é o quarto de seno."""
    warped = u**k
    if family == "power":
        return warped
    if family == "s":
        return (1.0 - math.cos(math.pi * warped)) / 2.0
    return math.sin(math.pi / 2.0 * warped)


_SHAPE_FAMILY = {
    "up": ("power", False),
    "down": ("power", True),
    "s_up": ("s", False),
    "s_down": ("s", True),
    "sine_up": ("sine", False),
    "sine_down": ("sine", True),
}


def shape_position(shape: str, mid_adjust: float, u: float) -> float:
    """Quanto do caminho entre o ganho inicial e o final já foi percorrido em `u` (0 a 1), pela forma escolhida.
    A forma `_down` é a `_up` espelhada (sobe depressa no começo e achata no fim)."""
    try:
        family, mirrored = _SHAPE_FAMILY[shape]
    except KeyError:
        raise ValueError(
            f"forma de fade desconhecida: {shape!r}. Use uma de: {', '.join(ADJUSTABLE_SHAPES)}"
        ) from None
    u = min(max(u, 0.0), 1.0)
    k = _warp_exponent(mid_adjust)
    if mirrored:
        return 1.0 - _rising(family, 1.0 - u, k)
    return _rising(family, u, k)


def adjustable_gain(shape: str, mid_adjust: float, start_gain: float, end_gain: float, u: float) -> float:
    """O ganho do Fade Ajustável em `u`: vai do ganho inicial ao final (em amplitude) pela forma escolhida."""
    return start_gain + (end_gain - start_gain) * shape_position(shape, mid_adjust, u)


def gain_from_unit(value: float, unit: str) -> float:
    """O ganho em amplitude de um valor em porcentagem (100 = nível original) ou em dB (0 = nível original)."""
    return value / 100.0 if unit == "percent" else 10.0 ** (value / 20.0)


# ---------- crossfade ----------

CROSSFADE_TYPES: tuple[str, ...] = ("constant_gain", "constant_power_1", "constant_power_2", "custom")


@dataclass(frozen=True)
class FadeLaw:
    """Um fade casado de um crossfade: a forma, o ajuste do meio e os ganhos das pontas (amplitude)."""

    shape: str
    mid_adjust: float
    start_gain: float
    end_gain: float

    def gain(self, u: float) -> float:
        return adjustable_gain(self.shape, self.mid_adjust, self.start_gain, self.end_gain, u)


def crossfade_laws(kind: str, shape: str = "s_up", mid_adjust: float = 0.0) -> tuple[FadeLaw, FadeLaw]:
    """O par (saída, entrada) de um crossfade, cada um como um Fade Ajustável:
    - `constant_gain`: retas que somam 1 (a soma das amplitudes fica constante: o certo para sons iguais e em fase);
    - `constant_power_1`: cosseno e seno (cos² + sen² = 1: a soma das potências fica constante, o certo para sons
      diferentes, que não se correlacionam);
    - `constant_power_2`: raiz de (1 - u) e raiz de u (também de potência constante, mas a entrada abre mais depressa);
    - `custom`: a forma `shape` com o ajuste do meio, e a saída é o complemento a 1 da entrada (soma 1)."""
    if kind == "constant_gain":
        return FadeLaw("up", 0.0, 1.0, 0.0), FadeLaw("up", 0.0, 0.0, 1.0)
    if kind == "constant_power_1":
        return FadeLaw("sine_down", 0.0, 1.0, 0.0), FadeLaw("sine_up", 0.0, 0.0, 1.0)
    if kind == "constant_power_2":
        return FadeLaw("down", -50.0, 1.0, 0.0), FadeLaw("up", -50.0, 0.0, 1.0)
    if kind == "custom":
        return FadeLaw(shape, mid_adjust, 1.0, 0.0), FadeLaw(shape, mid_adjust, 0.0, 1.0)
    raise ValueError(f"tipo de crossfade desconhecido: {kind!r}. Use um de: {', '.join(CROSSFADE_TYPES)}")


def crossfade_gains(kind: str, u: float, shape: str = "s_up", mid_adjust: float = 0.0) -> tuple[float, float]:
    """Os ganhos (saída, entrada) de um crossfade em `u` (0 a 1)."""
    leaving, entering = crossfade_laws(kind, shape, mid_adjust)
    return leaving.gain(u), entering.gain(u)


# ---------- da curva ao filtro ----------

# O `volume` do ffmpeg lê o ganho como uma expressão em `t`; a curva vira pontos (instante, dB) que o
# `envelope_gain_expression` liga por retas em dB. 48 trechos bastam para o erro ficar abaixo de 0,2 dB onde o som é
# audível (acima de -40 dB), e a expressão fica com uns 5 KB (a linha de comando do Windows aceita 32 KB).
CURVE_POINTS = 48
# O Envelope aceita até -120 dB: abaixo disso o ganho é silêncio
FLOOR_DB = -120.0


def gain_db(value: float) -> float:
    """Um ganho em amplitude como dB, com o piso do Envelope."""
    return FLOOR_DB if value <= 10 ** (FLOOR_DB / 20) else max(20.0 * math.log10(value), FLOOR_DB)


def curve_db_points(
    gain: Callable[[float], float], length: float, count: int = CURVE_POINTS
) -> list[tuple[float, float]]:
    """A curva `gain(u)` amostrada em pontos (instante em segundos, ganho em dB) para um fade de `length` segundos. Os
    instantes ficam mais juntos nas duas pontas (espaçamento de cosseno), onde o ganho em dB muda mais depressa, para a
    reta em dB entre dois pontos não errar o começo de um fade que parte do silêncio."""
    points: list[tuple[float, float]] = []
    for step in range(count + 1):
        u = (1.0 - math.cos(math.pi * step / count)) / 2.0
        points.append((round(u * length, 6), round(gain_db(gain(u)), 4)))
    return points


def monotonic(values: Sequence[float], rising: bool = True) -> bool:
    """Se a sequência só sobe (ou só desce), sem recuo: o teste das envoltórias dos fades usa."""
    pairs = zip(values, values[1:], strict=False)
    return all(b >= a - 1e-12 for a, b in pairs) if rising else all(b <= a + 1e-12 for a, b in pairs)
