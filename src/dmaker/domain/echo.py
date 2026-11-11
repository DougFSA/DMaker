"""As contas do Atraso e do Eco: quando cada repetição soa, com que ganho e com quanto tom a mais. Puras, sem ffmpeg.

O Eco do Audacity tem realimentação (cada repetição é a anterior vezes o decaimento) e o Atraso tem um número fixo de
repetições, que podem vir regulares, encurtando (bola quicando) ou alongando (bola quicando ao contrário).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# O Eco para quando a repetição cai abaixo disto (-60 dB): o resto está abaixo de qualquer som audível
ECHO_FLOOR_DB = -60.0
# Teto da cauda que o Eco acrescenta ao item (`extend_tail`): um decaimento perto de 1 não acabaria nunca
MAX_ECHO_TAIL_SECONDS = 30.0
# A razão entre um intervalo e o seguinte na bola quicando: cada quique dura 70% do anterior (uma bola de borracha perde
# cerca de 30% do tempo a cada quique)
BOUNCE_RATIO = 0.7


def echo_repeats(decay: float) -> int | None:
    """Quantas repetições o Eco tem até cair a `ECHO_FLOOR_DB`, ou None quando o decaimento é 1 (não cai nunca). Decaimento
    0 não tem repetição."""
    if decay <= 0.0:
        return 0
    if decay >= 1.0:
        return None
    return math.ceil(ECHO_FLOOR_DB / (20.0 * math.log10(decay)))


def echo_tail_seconds(delay: float, decay: float) -> float:
    """Quanto o Eco ainda soa depois do fim do item, limitado a `MAX_ECHO_TAIL_SECONDS`."""
    repeats = echo_repeats(decay)
    if repeats is None:
        return MAX_ECHO_TAIL_SECONDS
    return min(repeats * delay, MAX_ECHO_TAIL_SECONDS)


def doubling_stages(repeats: int) -> int:
    """Quantos estágios de dobra o Eco precisa para `repeats` repetições. O sinal com a repetição de 0 a `2^m - 1` vezes (a soma
    geométrica do pente) sai de `m` dobras: o estágio `j` soma ao sinal uma cópia dele atrasada `2^j` atrasos e com ganho `d^(2^j)`.
    As `repeats + 1` parcelas (o som e as repetições) se juntam em potências de dois, e o maior bloco é o que dá `m`."""
    return (repeats + 1).bit_length() - 1


def doubling_blocks(repeats: int) -> list[tuple[int, int]]:
    """Os blocos de potência de dois que somam as `repeats + 1` parcelas do Eco, do maior para o menor: cada par é o estágio
    `j` (o bloco com `2^j` parcelas) e quantas parcelas vêm antes dele (o deslocamento, em atrasos). Com 10 repetições são 11
    parcelas: o bloco de 8 sem deslocamento, o de 2 deslocado 8 e o de 1 deslocado 10, que é exatamente a soma até -60 dB."""
    terms = repeats + 1
    blocks = []
    offset = 0
    for stage in range(terms.bit_length() - 1, -1, -1):
        if terms >> stage & 1:
            blocks.append((stage, offset))
            offset += 1 << stage
    return blocks


@dataclass(frozen=True)
class DelayEcho:
    """Uma repetição do Atraso: quando ela soa (segundos depois do som), o ganho em dB e o tom a mais, em semitons."""

    at: float
    gain_db: float
    semitones: float


def delay_echoes(
    kind: str, delay: float, count: int, decay_db: float, pitch_semitones: float, pitch_every: int
) -> list[DelayEcho]:
    """As repetições do Atraso. `regular`: a k-ésima soa em k vezes o atraso. `bouncing`: os intervalos encurtam por
    `BOUNCE_RATIO` a cada repetição, a partir de `delay`. `reverse_bouncing`: os mesmos intervalos, na ordem inversa (o último é
    `delay`). O ganho cai `decay_db` por repetição, e o tom sobe `pitch_semitones` a cada `pitch_every` repetições."""
    if kind == "regular":
        gaps = [delay] * count
    elif kind == "bouncing":
        gaps = [delay * BOUNCE_RATIO**j for j in range(count)]
    elif kind == "reverse_bouncing":
        gaps = [delay * BOUNCE_RATIO**j for j in reversed(range(count))]
    else:
        raise ValueError(f"tipo de atraso desconhecido: {kind!r}")
    echoes = []
    moment = 0.0
    for k, gap in enumerate(gaps, start=1):
        moment += gap
        steps = math.ceil(k / pitch_every)
        echoes.append(DelayEcho(moment, decay_db * k, pitch_semitones * steps))
    return echoes
