"""A Distorção: curvas de transferência puras, aplicadas amostra a amostra, mais o filtro de corrente contínua.

Cada tipo é uma função `y = f(u)` do sinal depois do ganho de entrada, registrada pelo nome (`@transfer`): tipo novo entra por
extensão, sem `if/elif`. As curvas são por elemento, então rodam em blocos e a memória não cresce com o item. Todas levam o
nível de entrada de -1 a 1 (o fundo de escala) a uma saída de no máximo 1: o ganho de entrada que passa disso é cortado por
cada curva do jeito dela (o limite digital), e o `nível de saída` depois dela é que sobe o som, por conta de quem o pede.

O que cada tipo faz está na docstring da função; os nomes seguem os da Distorção do Audacity, e o bit crusher (que o Audacity
não tem) reduz a resolução e a taxa do som.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

# Quadros por bloco: 1 M amostras em ponto flutuante de 64 bits são 8 MB por canal, o suficiente para a conta ser vetorial e
# pouco para o item não pesar na memória
BLOCK = 1 << 20
# O teto do `hard_limiter`: o limiar sobe até -1 dBFS (a mesma folga do Limitador), em vez de bater em 0 dBFS
HARD_LIMITER_CEILING_DB = -1.0
# Os três overdrives: o quanto a curva `1 - exp(-k |v|)` aperta (k maior: mais cedo ela satura, mais dura a distorção)
OVERDRIVE_SHARPNESS = {"soft_overdrive": 2.0, "medium_overdrive": 4.0, "hard_overdrive": 8.0}
# O Soft Clip vai de um joelho largo (quantidade 0) a quase um corte seco (100): o expoente da curva sobe de 2 a 8
SOFT_KNEE_MIN, SOFT_KNEE_MAX = 2.0, 8.0
# O filtro de corrente contínua é um passa-alta de um polo em 10 Hz: tira o desvio sem tocar na voz mais grave (80 Hz)
DC_CUTOFF_HZ = 10.0
DC_BLOCK = 1 << 15
# O chiado somado depois da curva é ruído branco de semente fixa (o mesmo pedido dá o mesmo som); este valor o desliga
HISS_OFF_DB = -100.0
HISS_SEED = 11

Transfer = Callable[[np.ndarray, "DistortionSettings"], np.ndarray]
TRANSFERS: dict[str, Transfer] = {}


@dataclass(frozen=True)
class DistortionSettings:
    """Os parâmetros da Distorção, na forma que as contas usam (limiar linear, não em dB)."""

    kind: str
    drive_db: float = 0.0
    threshold_db: float = -6.0
    amount: float = 50.0
    repeats: int = 1
    bits: int = 8
    downsample: int = 1
    dc_filter: bool = True
    hiss_db: float = HISS_OFF_DB
    output_db: float = 0.0

    @property
    def threshold(self) -> float:
        return 10.0 ** (self.threshold_db / 20.0)


def transfer(name: str) -> Callable[[Transfer], Transfer]:
    """Registra a curva do tipo `name`."""

    def decorator(function: Transfer) -> Transfer:
        if name in TRANSFERS:
            raise ValueError(f"curva de distorção já registrada: {name}")
        TRANSFERS[name] = function
        return function

    return decorator


def transfer_types() -> set[str]:
    return set(TRANSFERS)


@transfer("hard_clip")
def hard_clip(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Corte seco no limiar: o que passa dele vira o próprio limiar. Soa áspero, com muitos harmônicos ímpares."""
    return np.clip(u, -s.threshold, s.threshold)


@transfer("soft_clip")
def soft_clip(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Corte arredondado: `t u / (1 + |u/t|^n)^(1/n)` encosta no limiar sem quina. A quantidade vai do joelho largo (0) ao
    quase seco (100)."""
    t = s.threshold
    n = SOFT_KNEE_MIN + (SOFT_KNEE_MAX - SOFT_KNEE_MIN) * s.amount / 100.0
    return u / (1.0 + np.abs(u / t) ** n) ** (1.0 / n)


def _overdrive(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    t = s.threshold
    k = OVERDRIVE_SHARPNESS[s.kind]
    return t * np.sign(u) * (1.0 - np.exp(-k * np.abs(u) / t))


for _name in OVERDRIVE_SHARPNESS:
    TRANSFERS[_name] = _overdrive


@transfer("cubic")
def cubic(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Curva cúbica `1,5 v - 0,5 v³` (v é o sinal em relação ao limiar): satura com harmônicos ímpares, de um jeito macio, e
    segura o que passa do limiar."""
    t = s.threshold
    v = np.clip(u / t, -1.0, 1.0)
    return t * (1.5 * v - 0.5 * v**3)


@transfer("even_harmonics")
def even_harmonics(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Soma o quadrado do sinal a ele: dá o segundo harmônico e os outros pares, o calor de uma válvula. A quantidade é a
    parte do quadrado; o desvio de corrente contínua que isso cria o filtro tira."""
    amount = s.amount / 100.0
    v = np.clip(u, -1.0, 1.0)
    return (v + amount * v * v) / (1.0 + amount)


@transfer("expand_compress")
def expand_compress(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Eleva o nível a uma potência, mantendo o sinal: acima de 50 comprime (o baixo sobe, `|v|^p` com p<1), abaixo de 50
    expande (o baixo desce); 50 deixa o som como está."""
    power = 2.0 ** ((50.0 - s.amount) / 50.0)
    v = np.clip(u, -1.0, 1.0)
    return np.sign(v) * np.abs(v) ** power


@transfer("leveller")
def leveller(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Nivelador: a curva `2v - v|v|` sobe o que é baixo e achata o que é alto, e cada repetição a aplica de novo."""
    v = np.clip(u, -1.0, 1.0)
    return 2.0 * v - v * np.abs(v)


@transfer("rectifier")
def rectifier(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Retificador: mistura o sinal com o valor absoluto dele. 100 é a onda completa (o som sobe uma oitava); a
    corrente contínua que sobra o filtro tira."""
    mix = s.amount / 100.0
    v = np.clip(u, -1.0, 1.0)
    return (1.0 - mix) * v + mix * np.abs(v)


@transfer("hard_limiter")
def hard_limiter(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Limitador seco: corta no limiar e sobe o limiar a `HARD_LIMITER_CEILING_DB`, então tudo acima do limiar vira um
    platô de pico igual e o som inteiro ganha o que sobrava de espaço."""
    t = s.threshold
    return np.clip(u, -t, t) * (10.0 ** (HARD_LIMITER_CEILING_DB / 20.0) / t)


@transfer("bit_crusher")
def bit_crusher(u: np.ndarray, s: DistortionSettings) -> np.ndarray:
    """Reduz a resolução a `bits` bits (arredonda para o degrau mais próximo) e, com `downsample` maior que 1, repete cada
    amostra por esse tanto de quadros, que é a taxa mais baixa dos videogames antigos."""
    steps = 2.0 ** (s.bits - 1)
    v = np.clip(u, -1.0, 1.0)
    crushed = np.round(v * steps) / steps
    if s.downsample > 1:
        held = crushed[:: s.downsample]
        crushed = np.repeat(held, s.downsample, axis=0)[: len(crushed)]
    return crushed


def _shaped(block: np.ndarray, settings: DistortionSettings) -> np.ndarray:
    curve = TRANSFERS[settings.kind]
    shaped = block * 10.0 ** (settings.drive_db / 20.0)
    for _ in range(settings.repeats):
        shaped = curve(shaped, settings)
    return shaped


def remove_dc(samples: np.ndarray, rate: int) -> np.ndarray:
    """O passa-alta de um polo em `DC_CUTOFF_HZ` (`y[n] = a y[n-1] + x[n] - x[n-1]`), em blocos: a recorrência de um polo é uma
    convolução com `a^k` mais o que sobrou do bloco anterior, e a convolução se faz por FFT. Mesmo tamanho e forma da entrada."""
    pole = math.exp(-2.0 * math.pi * DC_CUTOFF_HZ / rate)
    kernel = pole ** np.arange(DC_BLOCK)
    spectrum = np.fft.rfft(kernel, 2 * DC_BLOCK)
    result = np.empty_like(samples)
    previous_in = np.zeros(samples.shape[1])
    previous_out = np.zeros(samples.shape[1])
    for first in range(0, len(samples), DC_BLOCK):
        block = np.asarray(samples[first : first + DC_BLOCK], dtype=np.float64)
        steps = np.diff(block, axis=0, prepend=previous_in[None, :])
        filtered = np.fft.irfft(
            np.fft.rfft(steps, 2 * DC_BLOCK, axis=0) * spectrum[:, None], 2 * DC_BLOCK, axis=0
        )
        decay = pole ** np.arange(1, len(block) + 1)
        filtered = filtered[: len(block)] + decay[:, None] * previous_out[None, :]
        result[first : first + len(block)] = filtered
        previous_in, previous_out = block[-1], filtered[-1]
    return result


def distort(samples: np.ndarray, settings: DistortionSettings, rate: int) -> np.ndarray:
    """O sinal `(amostras, canais)` depois da Distorção: ganho de entrada, curva (repetida `repeats` vezes), filtro de
    corrente contínua, chiado e nível de saída. O chiado é ruído branco com o desvio-padrão dado em dBFS (o pico passa disso). Mesmo tamanho e forma da entrada, em ponto flutuante de 32 bits."""
    if settings.kind not in TRANSFERS:
        raise ValueError(f"distorção desconhecida: {settings.kind!r}")
    data = samples if samples.ndim == 2 else samples[:, None]
    shaped = np.empty(data.shape, dtype=np.float64)
    # as curvas por bloco; o bit crusher com repetição de amostras alinha os blocos ao `downsample`
    step = BLOCK - BLOCK % max(settings.downsample, 1)
    for first in range(0, len(data), step):
        shaped[first : first + step] = _shaped(
            np.asarray(data[first : first + step], dtype=np.float64), settings
        )
    if settings.dc_filter and len(shaped):
        shaped = remove_dc(shaped, rate)
    if settings.hiss_db > HISS_OFF_DB and len(shaped):
        hiss = np.random.default_rng(HISS_SEED).standard_normal(shaped.shape)
        shaped += hiss * 10.0 ** (settings.hiss_db / 20.0)
    shaped *= 10.0 ** (settings.output_db / 20.0)
    result = shaped.astype(np.float32)
    return result[:, 0] if samples.ndim == 1 else result
