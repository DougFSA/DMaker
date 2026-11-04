"""Filtros IIR de áudio projetados em Python puro, como seções de segunda ordem (biquads).

Um filtro desta família (passa-alta, passa-baixa, notch, prateleira, Butterworth, Chebyshev) é uma lista de `Biquad` na
taxa dos efeitos. A MESMA lista serve a duas coisas: o ffmpeg a aplica seção por seção (`biquad`), e `response_db` desenha
a resposta de frequência do efeito sem rodar nada. Assim o gráfico da interface bate com o som por construção.

Os projetos seguem a matemática pública: a forma de biquad do "Audio EQ Cookbook" (notch e prateleiras) e os protótipos
analógicos clássicos passados à forma digital pela transformação bilinear com pré-distorção de frequência (Butterworth,
Chebyshev tipo I e tipo II). Sem scipy: o núcleo usa só a biblioteca padrão e numpy.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

Family = Literal["butterworth", "chebyshev1", "chebyshev2"]
Band = Literal["lowpass", "highpass"]

# Tolerância para dizer que um polo ou zero é real (parte imaginária desprezível) e para agrupar pares conjugados
_REAL_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Biquad:
    """Uma seção de segunda ordem, já dividida por a0 (que fica 1):
    y[n] = b0 x[n] + b1 x[n-1] + b2 x[n-2] - a1 y[n-1] - a2 y[n-2]."""

    b0: float
    b1: float
    b2: float
    a1: float
    a2: float

    def ffmpeg_filter(self) -> str:
        """O filtro `biquad` do ffmpeg com estes coeficientes. A precisão de 64 bits e a forma transposta direta II são
        cautela: um passa-alta de 48 dB por oitava em 20 Hz tem polos colados no círculo unitário, que é onde a
        aritmética de 32 bits perde mais. Medi o mesmo erro (0,12 dB) com a precisão padrão e com 32 bits, então hoje
        não corrige nada audível; custa pouco e segura o caso em que o ffmpeg mudar o padrão."""
        return (
            f"biquad=b0={self.b0:.17g}:b1={self.b1:.17g}:b2={self.b2:.17g}:a0=1:"
            f"a1={self.a1:.17g}:a2={self.a2:.17g}:transform=tdii:precision=f64"
        )

    def scaled(self, gain: float) -> Biquad:
        return Biquad(self.b0 * gain, self.b1 * gain, self.b2 * gain, self.a1, self.a2)


def response(sections: list[Biquad], hz: np.ndarray, rate: int) -> np.ndarray:
    """A resposta complexa da série de seções nas frequências `hz` (a função de transferência no círculo unitário)."""
    w = 2.0 * math.pi * np.asarray(hz, dtype=float) / rate
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    total = np.ones_like(z1)
    for s in sections:
        total = total * (s.b0 + s.b1 * z1 + s.b2 * z2) / (1.0 + s.a1 * z1 + s.a2 * z2)
    return total


def response_db(sections: list[Biquad], hz: np.ndarray, rate: int, gain_db: float = 0.0) -> np.ndarray:
    """O módulo da resposta em dB (mais um ganho fixo, o `volume` que acompanha o filtro). Zero exato vira -300 dB, para
    o gráfico não receber infinito."""
    magnitude = np.abs(response(sections, hz, rate))
    return 20.0 * np.log10(np.maximum(magnitude, 1e-15)) + gain_db


# ---------- seções do Audio EQ Cookbook ----------


def _omega(frequency: float, rate: int) -> float:
    if not 0 < frequency < rate / 2:
        raise ValueError(f"frequência fora do possível: {frequency:g} Hz (use de 0 a {rate / 2:g} Hz)")
    return 2.0 * math.pi * frequency / rate


def _normalized(b: tuple[float, float, float], a: tuple[float, float, float]) -> Biquad:
    return Biquad(b[0] / a[0], b[1] / a[0], b[2] / a[0], a[1] / a[0], a[2] / a[0])


def notch(frequency: float, q: float, rate: int) -> Biquad:
    """Rejeita uma frequência só (ganho zero nela): `q` alto é um corte estreito, que não mexe na voz em volta."""
    w0 = _omega(frequency, rate)
    alpha = math.sin(w0) / (2.0 * q)
    cos = math.cos(w0)
    return _normalized((1.0, -2.0 * cos, 1.0), (1.0 + alpha, -2.0 * cos, 1.0 - alpha))


def _shelf_alpha(w0: float, amplitude: float, slope: float) -> float:
    return math.sin(w0) / 2.0 * math.sqrt((amplitude + 1.0 / amplitude) * (1.0 / slope - 1.0) + 2.0)


def low_shelf(frequency: float, gain_db: float, slope: float, rate: int) -> Biquad:
    """Prateleira de graves: sobe ou desce em `gain_db` tudo abaixo de `frequency`. `slope` 1 é a mais íngreme sem
    ondulação; menores abrem a transição."""
    w0 = _omega(frequency, rate)
    a = 10.0 ** (gain_db / 40.0)
    cos = math.cos(w0)
    root = 2.0 * math.sqrt(a) * _shelf_alpha(w0, a, slope)
    return _normalized(
        (
            a * ((a + 1.0) - (a - 1.0) * cos + root),
            2.0 * a * ((a - 1.0) - (a + 1.0) * cos),
            a * ((a + 1.0) - (a - 1.0) * cos - root),
        ),
        (
            (a + 1.0) + (a - 1.0) * cos + root,
            -2.0 * ((a - 1.0) + (a + 1.0) * cos),
            (a + 1.0) + (a - 1.0) * cos - root,
        ),
    )


def high_shelf(frequency: float, gain_db: float, slope: float, rate: int) -> Biquad:
    """Prateleira de agudos: sobe ou desce em `gain_db` tudo acima de `frequency`."""
    w0 = _omega(frequency, rate)
    a = 10.0 ** (gain_db / 40.0)
    cos = math.cos(w0)
    root = 2.0 * math.sqrt(a) * _shelf_alpha(w0, a, slope)
    return _normalized(
        (
            a * ((a + 1.0) + (a - 1.0) * cos + root),
            -2.0 * a * ((a - 1.0) + (a + 1.0) * cos),
            a * ((a + 1.0) + (a - 1.0) * cos - root),
        ),
        (
            (a + 1.0) - (a - 1.0) * cos + root,
            2.0 * ((a - 1.0) - (a + 1.0) * cos),
            (a + 1.0) - (a - 1.0) * cos - root,
        ),
    )


# ---------- Butterworth e Chebyshev ----------


def _prototype(
    family: Family, order: int, ripple_db: float, stopband_db: float
) -> tuple[list[complex], list[complex], float]:
    """Zeros, polos e ganho do protótipo analógico passa-baixa com corte em 1 rad/s."""
    degrees = [(2 * k - order + 1) for k in range(order)]  # -n+1, -n+3, ..., n-1
    if family == "butterworth":
        poles = [-cmath.exp(1j * math.pi * m / (2 * order)) for m in degrees]
        return [], poles, 1.0
    if family == "chebyshev1":
        epsilon = math.sqrt(10.0 ** (ripple_db / 10.0) - 1.0)
        mu = math.asinh(1.0 / epsilon) / order
        poles = [-cmath.sinh(complex(mu, math.pi * m / (2 * order))) for m in degrees]
        gain = math.prod((-p for p in poles), start=1.0 + 0j).real
        if order % 2 == 0:  # a ondulação da banda passante começa em baixo no grau par
            gain /= math.sqrt(1.0 + epsilon**2)
        return [], poles, gain
    # chebyshev2: zeros no eixo imaginário (a banda de rejeição tem ondulação), polos deformados do círculo
    delta = 1.0 / math.sqrt(10.0 ** (stopband_db / 10.0) - 1.0)
    mu = math.asinh(1.0 / delta) / order
    zero_degrees = [m for m in degrees if m != 0]
    zeros = [-(1j / math.sin(m * math.pi / (2 * order))).conjugate() for m in zero_degrees]
    circle = [-cmath.exp(1j * math.pi * m / (2 * order)) for m in degrees]
    poles = [1.0 / complex(math.sinh(mu) * p.real, math.cosh(mu) * p.imag) for p in circle]
    gain = (
        math.prod((-p for p in poles), start=1.0 + 0j) / math.prod((-z for z in zeros), start=1.0 + 0j)
    ).real
    return zeros, poles, gain


def _digital(
    zeros: list[complex], poles: list[complex], gain: float, band: Band, frequency: float, rate: int
) -> tuple[list[complex], list[complex], float]:
    """O protótipo levado ao corte pedido (com a frequência pré-distorcida, para o corte cair no lugar certo depois da
    bilinear) e passado ao plano digital."""
    warped = 2.0 * rate * math.tan(math.pi * frequency / rate)
    extra = len(poles) - len(zeros)
    if band == "lowpass":
        zeros = [z * warped for z in zeros]
        poles = [p * warped for p in poles]
        gain *= warped**extra
    else:
        gain *= (
            math.prod((-z for z in zeros), start=1.0 + 0j) / math.prod((-p for p in poles), start=1.0 + 0j)
        ).real
        zeros = [warped / z for z in zeros] + [0j] * extra
        poles = [warped / p for p in poles]
        extra = 0
    k = 2.0 * rate
    gain *= (
        math.prod((k - z for z in zeros), start=1.0 + 0j) / math.prod((k - p for p in poles), start=1.0 + 0j)
    ).real
    digital_zeros = [(k + z) / (k - z) for z in zeros] + [complex(-1.0, 0.0)] * extra
    digital_poles = [(k + p) / (k - p) for p in poles]
    return digital_zeros, digital_poles, gain


def _pairs(values: list[complex]) -> tuple[list[complex], list[complex]]:
    """Separa em pares conjugados (devolvidos pelo membro de parte imaginária positiva, do menor ângulo ao maior) e
    reais."""
    complex_ones = sorted((v for v in values if v.imag > _REAL_TOLERANCE), key=lambda v: abs(cmath.phase(v)))
    real_ones = sorted(v.real for v in values if abs(v.imag) <= _REAL_TOLERANCE)
    return complex_ones, [complex(v) for v in real_ones]


def _sections(zeros: list[complex], poles: list[complex], gain: float) -> list[Biquad]:
    """Agrupa polos e zeros em seções de segunda ordem. Cada par conjugado de polos leva o par de zeros de ângulo mais
    perto (no Chebyshev II, o zero fica na frequência do polo que ele ajuda a cortar); o ganho se reparte por igual
    entre as seções para nenhuma estourar sozinha."""
    pole_pairs, pole_reals = _pairs(poles)
    zero_pairs, zero_reals = _pairs(zeros)
    count = len(pole_pairs) + (len(pole_reals) + 1) // 2
    per_section = abs(gain) ** (1.0 / count) if count else 1.0
    sign = -1.0 if gain < 0 else 1.0
    zero_groups: list[tuple[float, float]] = [(-2.0 * z.real, abs(z) ** 2) for z in zero_pairs]
    reals = [z.real for z in zero_reals]
    while len(reals) >= 2:
        first, second = reals.pop(0), reals.pop(0)
        zero_groups.append((-(first + second), first * second))
    if reals:
        zero_groups.append((-reals[0], 0.0))
    denominators: list[tuple[float, float]] = [(-2.0 * p.real, abs(p) ** 2) for p in pole_pairs]
    plain = [p.real for p in pole_reals]
    while len(plain) >= 2:
        first, second = plain.pop(0), plain.pop(0)
        denominators.append((-(first + second), first * second))
    if plain:
        denominators.append((-plain[0], 0.0))
    if len(zero_groups) != len(denominators):  # um filtro que perdeu zeros ou polos não deve chegar ao ffmpeg
        raise ValueError("projeto de filtro inconsistente: número de zeros e polos não casa")
    sections = []
    for index, ((b1, b2), (a1, a2)) in enumerate(zip(zero_groups, denominators, strict=True)):
        scale = per_section * (sign if index == 0 else 1.0)
        sections.append(Biquad(scale, scale * b1, scale * b2, a1, a2))
    return sections


def classic_sections(
    family: Family,
    band: Band,
    order: int,
    frequency: float,
    rate: int,
    ripple_db: float = 1.0,
    stopband_db: float = 30.0,
) -> list[Biquad]:
    """Passa-baixa ou passa-alta de `order` polos. No Butterworth `frequency` é o corte de -3 dB; no Chebyshev I, onde a
    ondulação da banda passante termina; no Chebyshev II, onde a rejeição mínima de `stopband_db` começa."""
    if not 1 <= order <= 20:
        raise ValueError(f"ordem do filtro fora do possível: {order} (use de 1 a 20)")
    _omega(frequency, rate)  # só valida a faixa
    zeros, poles, gain = _prototype(family, order, ripple_db, stopband_db)
    zeros, poles, gain = _digital(zeros, poles, gain, band, frequency, rate)
    return _sections(zeros, poles, gain)


def slope_sections(band: Band, slope_db_per_octave: int, frequency: float, rate: int) -> list[Biquad]:
    """O passa-alta ou passa-baixa de `slope_db_per_octave` (6 a 48, de 6 em 6): um Butterworth cuja ordem é a
    inclinação dividida por 6, o que o Audacity faz."""
    return classic_sections("butterworth", band, slope_db_per_octave // 6, frequency, rate)
