"""O Auto Duck como linhas de grafo do ffmpeg: a curva de ganho da trilha de fundo vira um `volume` por expressão.

A curva (`domain/auto_duck.py`) são pontos `(instante, dB)` ligados por retas em dB. Para o ffmpeg ela é UMA expressão
em `t` (o instante do fluxo), avaliada a cada quadro de `DUCK_FRAME_SAMPLES` amostras. O `envelope_gain_expression` do
Envelope monta os `if` aninhados de trás para a frente, o que serve a uma curva desenhada à mão (até 100 pontos) mas não a
300 regiões de uma hora de fala (1.200 pontos): a profundidade do aninhamento seria 1.200. Aqui os `if` formam uma
árvore equilibrada (a busca pelo intervalo do instante é uma busca binária, com profundidade de uns 11 para 1.200 pontos),
e a conta por quadro custa o mesmo para uma regra ou para trezentas. Funções puras.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..domain.auto_duck import Point, is_flat

# O `volume` reavalia a expressão uma vez por quadro. 256 amostras (5,3 ms a 48 kHz) movem uma rampa de 12 dB em 0,5 s em
# degraus de 0,13 dB, abaixo do que o ouvido separa; o quadro padrão (1024 amostras, 21 ms) daria 0,5 dB por degrau. `p=0`
# não completa o último quadro com silêncio, que alongaria a trilha.
DUCK_FRAME_SAMPLES = 256


@dataclass(frozen=True)
class DuckCurve:
    """A curva de ganho que uma regra impõe à trilha `background`, em segundos do projeto (`points` vazio: sem efeito)."""

    background: str
    points: tuple[Point, ...]


def _number(value: float) -> str:
    """Número para dentro de uma expressão do ffmpeg, entre parênteses para o sinal negativo não colar no operador."""
    return f"({value:.6f})"


def _segment(before: Point, after: Point) -> str:
    """O ganho entre dois pontos: a reta em dB (ou o valor fixo, se os dois têm o mesmo)."""
    if abs(after[1] - before[1]) < 1e-9:
        return _number(before[1])
    slope = (after[1] - before[1]) / (after[0] - before[0])
    return f"({_number(before[1])}+{_number(slope)}*(t-{_number(before[0])}))"


def gain_expression(points: Sequence[Point]) -> str:
    """O ganho em dB da curva como expressão em `t`: o ganho do primeiro ponto antes dele, a reta entre cada par e o do
    último depois dele. Os `if` formam uma árvore equilibrada em vez de uma escada, para a profundidade crescer com o
    logaritmo do número de pontos."""
    if not points:
        return _number(0.0)
    # um intervalo por trecho entre pontos, mais o de antes do primeiro e o de depois do último
    pieces: list[str] = [_number(points[0][1])]
    pieces += [_segment(before, after) for before, after in zip(points, points[1:], strict=False)]
    pieces.append(_number(points[-1][1]))
    bounds = [point[0] for point in points]  # bounds[k] separa pieces[k] de pieces[k + 1]

    def tree(low: int, high: int) -> str:
        if low == high:
            return pieces[low]
        mid = (low + high) // 2  # pieces[low..mid] ficam antes de bounds[mid]
        return f"if(lt(t,{_number(bounds[mid])}),{tree(low, mid)},{tree(mid + 1, high)})"

    return tree(0, len(pieces) - 1)


def duck_filters(points: Sequence[Point]) -> list[str]:
    """Os filtros que aplicam a curva ao fluxo: nenhum para uma curva vazia, um `volume` fixo para uma reta, e o quadro de
    `DUCK_FRAME_SAMPLES` amostras com o `volume` por expressão para o resto."""
    if not points:
        return []
    if is_flat(points):
        return [f"volume={points[0][1]:.6f}dB"]
    return [
        f"asetnsamples=n={DUCK_FRAME_SAMPLES}:p=0",
        f"volume='pow(10,({gain_expression(points)})/20)':eval=frame:precision=float",
    ]


def duck_chain(curves: Sequence[DuckCurve]) -> list[str]:
    """Os filtros de todas as curvas de uma trilha, um `volume` por regra (onde duas regras agem ao mesmo tempo os ganhos
    se somam em dB, como rodar o Auto Duck duas vezes)."""
    filters: list[str] = []
    for curve in curves:
        filters += duck_filters(curve.points)
    return filters


def curves_for(curves: Sequence[DuckCurve], background: str) -> list[DuckCurve]:
    """As curvas que abaixam a trilha `background`, na ordem das regras."""
    return [curve for curve in curves if curve.background == background and curve.points]


def duck_streams(lines: list[str], labels: list[str], curves: Sequence[DuckCurve], prefix: str) -> list[str]:
    """Abaixa cada fluxo de `labels` (as narrações, as vozes gravadas, os efeitos sonoros: cada um já atrasado até o seu
    instante, então `t` é o instante do projeto) pelas `curves` da trilha, e devolve os rótulos novos. Sem curva devolve os
    mesmos rótulos e não acrescenta linha."""
    chain = duck_chain(curves)
    if not chain:
        return labels
    ducked = []
    for position, label in enumerate(labels):
        new = f"[{prefix}{position}]"
        lines.append(f"{label}{','.join(chain)}{new}")
        ducked.append(new)
    return ducked
