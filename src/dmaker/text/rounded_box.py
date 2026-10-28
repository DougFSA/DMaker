"""Caixa de fundo arredondada que abraça cada linha de texto, no estilo TikTok/Reels.

Cada linha ganha uma caixa do tamanho dela e as caixas vizinhas se emendam com curvas: convexas nos cantos
externos e côncavas onde uma linha é mais curta que a outra. O contorno da união sai como desenho vetorial
do ASS (tag p1), nítido em qualquer resolução e sem imagem rasterizada. Função pura: recebe medidas, devolve
texto, não toca disco nem ffmpeg.

A geometria segue o algoritmo do pacote @remotion/rounded-text-box (o raio do canto na emenda é a metade do
degrau entre as linhas, limitado ao raio pedido e à metade da altura da linha), reescrito aqui em Python:
o contorno vira um polígono retilíneo cujos cantos são arredondados por Bézier cúbica, já que o ASS não
tem o arco do SVG. Só a pasta MIT do Remotion foi consultada, nada do núcleo (Remotion License).

    Original: https://github.com/remotion-dev/remotion/tree/main/packages/rounded-text-box
    Licença: MIT (campo "license" do package.json do pacote), reproduzida abaixo.

    MIT License

    Copyright (c) Remotion (Jonny Burger)

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
    associated documentation files (the "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
    following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial
    portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
    LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
    EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
    IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR
    THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Align = Literal["left", "center", "right"]

# Quarto de círculo por Bézier cúbica: as alças ficam a 0,5523 do raio de cada ponta do arco.
_ARC_HANDLE = 0.5523

# Degrau lateral menor que isto (px) vira borda reta: um desnível de meio pixel só criaria um arco
# microscópico entre duas linhas que o olho lê como iguais.
_SNAP = 1.0

# Raio menor que isto não aparece na tela; fica canto vivo em vez de uma curva degenerada.
_MIN_RADIUS = 0.5


@dataclass(frozen=True)
class RoundedBox:
    """Contorno em comandos de desenho do ASS, com origem no canto superior esquerdo do retângulo envolvente."""

    path: str
    width: float
    height: float


@dataclass(frozen=True)
class _Corner:
    x: float
    y: float
    limit: float  # raio máximo do canto: metade da altura da linha a que ele pertence


def rounded_box(
    line_widths: Sequence[float],
    line_heights: float | Sequence[float],
    *,
    align: Align,
    radius: float,
    padding: float,
) -> RoundedBox:
    """Contorno arredondado da união das caixas de cada linha, alinhadas como o texto.

    `line_widths` são as larguras do texto de cada linha; a caixa de cada uma ganha `padding` dos dois
    lados. `line_heights` é uma altura para todas ou uma por linha. Quando o degrau entre duas linhas é
    menor que dois raios, o raio da emenda encolhe para a metade do degrau: sem bico nem quina.
    """
    count = len(line_widths)
    if count == 0:
        return RoundedBox("", 0.0, 0.0)
    if isinstance(line_heights, int | float):
        heights = [float(line_heights)] * count
    else:
        heights = [float(h) for h in line_heights]
    row_widths = [w + 2 * padding for w in line_widths]
    box_width = max(row_widths)
    lefts = _snapped([_row_left(align, box_width, width) for width in row_widths])
    rights = _snapped([left + width for left, width in zip(lefts, row_widths, strict=True)])

    tops: list[float] = []
    cursor = 0.0
    for height in heights:
        tops.append(cursor)
        cursor += height
    corners = _outline(lefts, rights, tops, heights)
    return RoundedBox(_path(corners, radius), box_width, cursor)


def _row_left(align: Align, box_width: float, row_width: float) -> float:
    if align == "center":
        return (box_width - row_width) / 2
    if align == "right":
        return box_width - row_width
    return 0.0


def _snapped(edges: list[float]) -> list[float]:
    """Iguala bordas de linhas vizinhas que diferem menos que `_SNAP`, para a emenda sair reta."""
    out = list(edges)
    for index in range(1, len(out)):
        if abs(out[index] - out[index - 1]) < _SNAP:
            out[index] = out[index - 1]
    return out


def _outline(
    lefts: list[float], rights: list[float], tops: list[float], heights: list[float]
) -> list[_Corner]:
    """Vértices do polígono retilíneo, no sentido horário: lado direito descendo, lado esquerdo subindo."""
    corners: list[_Corner] = []
    for index in range(len(tops)):
        limit = heights[index] / 2
        corners.append(_Corner(rights[index], tops[index], limit))
        corners.append(_Corner(rights[index], tops[index] + heights[index], limit))
    for index in reversed(range(len(tops))):
        limit = heights[index] / 2
        corners.append(_Corner(lefts[index], tops[index] + heights[index], limit))
        corners.append(_Corner(lefts[index], tops[index], limit))
    return _without_straight_vertices(corners)


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


def _without_straight_vertices(corners: list[_Corner]) -> list[_Corner]:
    """Tira vértices repetidos e os que só prolongam uma reta (bordas iguais de linhas vizinhas)."""
    unique: list[_Corner] = []
    for corner in corners:
        if unique and _same(corner.x, unique[-1].x) and _same(corner.y, unique[-1].y):
            continue
        unique.append(corner)
    if len(unique) > 1 and _same(unique[0].x, unique[-1].x) and _same(unique[0].y, unique[-1].y):
        unique.pop()
    index = 0
    while index < len(unique) and len(unique) > 4:
        before, here, after = unique[index - 1], unique[index], unique[(index + 1) % len(unique)]
        if (_same(before.x, here.x) and _same(here.x, after.x)) or (
            _same(before.y, here.y) and _same(here.y, after.y)
        ):
            del unique[index]
            index = max(index - 1, 0)
        else:
            index += 1
    return unique


def _toward(origin: _Corner, target: _Corner, distance: float) -> tuple[float, float]:
    """Ponto a `distance` de `origin` na direção de `target` (as arestas são sempre horizontais ou verticais)."""
    span = math.hypot(target.x - origin.x, target.y - origin.y)
    if span == 0:
        return origin.x, origin.y
    return (
        origin.x + (target.x - origin.x) * distance / span,
        origin.y + (target.y - origin.y) * distance / span,
    )


def _path(corners: list[_Corner], radius: float) -> str:
    """Comandos m/l/b: reta até o começo de cada curva e Bézier cúbica no lugar de cada quina."""
    fmt = lambda v: f"{v:.2f}"  # noqa: E731
    count = len(corners)
    segments: list[list[str]] = []
    ends: list[tuple[float, float]] = []
    for index, here in enumerate(corners):
        before, after = corners[index - 1], corners[(index + 1) % count]
        reach = min(
            radius,
            here.limit,
            math.hypot(here.x - before.x, here.y - before.y) / 2,
            math.hypot(after.x - here.x, after.y - here.y) / 2,
        )
        if reach < _MIN_RADIUS:
            segments.append([f"l {fmt(here.x)} {fmt(here.y)}"])
            ends.append((here.x, here.y))
            continue
        ax, ay = _toward(here, before, reach)
        bx, by = _toward(here, after, reach)
        # as alças seguem as arestas rumo à quina, o que serve igual para cantos convexos e côncavos
        c1x, c1y = ax + (here.x - ax) * _ARC_HANDLE, ay + (here.y - ay) * _ARC_HANDLE
        c2x, c2y = bx + (here.x - bx) * _ARC_HANDLE, by + (here.y - by) * _ARC_HANDLE
        segments.append(
            [f"l {fmt(ax)} {fmt(ay)}", f"b {fmt(c1x)} {fmt(c1y)} {fmt(c2x)} {fmt(c2y)} {fmt(bx)} {fmt(by)}"]
        )
        ends.append((bx, by))
    # começa ao fim da curva do primeiro canto e fecha com ela, para o desenho não abrir uma quina no início
    start_x, start_y = ends[0]
    body = [command for segment in segments[1:] + segments[:1] for command in segment]
    return " ".join([f"m {fmt(start_x)} {fmt(start_y)}", *body])
