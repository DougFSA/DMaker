"""Caixa arredondada por linha: geometria pura (sem ffmpeg), medida contra o contorno que ela desenha."""

from __future__ import annotations

import pytest

from dmaker.text.rounded_box import rounded_box

H = 72.0  # altura de uma linha, como uma legenda de 72 px
PAD = 28.0
RADIUS = 30.0


def _commands(path: str) -> list[tuple[str, list[float]]]:
    tokens = path.split()
    out: list[tuple[str, list[float]]] = []
    for token in tokens:
        if token in ("m", "l", "b"):
            out.append((token, []))
        else:
            out[-1][1].append(float(token))
    return out


def _outline(path: str, steps: int = 24) -> list[tuple[float, float]]:
    """O contorno como polígono: cada Bézier cúbica amostrada em `steps` pontos."""
    points: list[tuple[float, float]] = []
    for name, nums in _commands(path):
        if name in ("m", "l"):
            points.append((nums[0], nums[1]))
            continue
        x0, y0 = points[-1]
        x1, y1, x2, y2, x3, y3 = nums
        for i in range(1, steps + 1):
            t = i / steps
            u = 1 - t
            points.append(
                (
                    u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                    u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
                )
            )
    return points


def _inside(path: str, x: float, y: float) -> bool:
    """Par-ímpar: o ponto está dentro do contorno?"""
    inside = False
    points = _outline(path)
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1], strict=True):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def _arcs(path: str) -> list[float]:
    """Raio de cada curva do contorno (todas são quartos de círculo, então dx == dy)."""
    sizes = []
    previous = (0.0, 0.0)
    for name, nums in _commands(path):
        if name == "b":
            dx, dy = abs(nums[4] - previous[0]), abs(nums[5] - previous[1])
            assert dx == pytest.approx(dy, abs=0.02), "a curva não é um quarto de círculo"
            sizes.append(round(dx, 2))
        previous = (nums[-2], nums[-1])
    return sorted(sizes)


def test_one_line_is_a_rounded_rectangle():
    box = rounded_box([300], H, align="center", radius=RADIUS, padding=PAD)
    assert (box.width, box.height) == (300 + 2 * PAD, H)
    assert _arcs(box.path) == [RADIUS] * 4
    assert _inside(box.path, box.width / 2, H / 2)
    assert not _inside(box.path, 1, 1)  # a quina de fora foi arredondada


def test_two_lines_of_different_width_share_one_outline_without_a_step():
    box = rounded_box([400, 200], H, align="center", radius=RADIUS, padding=PAD)
    assert (box.width, box.height) == (400 + 2 * PAD, 2 * H)
    wide, narrow = 400 + 2 * PAD, 200 + 2 * PAD
    inset = (wide - narrow) / 2
    # o miolo de cada linha está dentro e o vão ao lado da linha curta está fora
    assert _inside(box.path, wide / 2, H / 2)
    assert _inside(box.path, wide / 2, 1.5 * H)
    assert not _inside(box.path, inset / 2, 1.5 * H)
    # concordância côncava: logo abaixo da linha larga, junto à linha curta, a curva preenche a quina
    assert _inside(box.path, inset + 2, H + 2)
    assert _inside(box.path, wide - inset - 2, H + 2)
    # e cada degrau é uma curva só, sem trecho reto horizontal sobrando entre os dois cantos
    assert _arcs(box.path) == sorted([RADIUS] * 4 + [RADIUS] * 4)


def test_three_lines_have_convex_and_concave_joints():
    box = rounded_box([400, 200, 320], H, align="center", radius=RADIUS, padding=PAD)
    assert box.height == 3 * H
    assert _arcs(box.path) == [RADIUS] * 12  # 4 cantos de fora + 2 emendas com 2 curvas em cada lado
    wide = 400 + 2 * PAD
    # a linha do meio é a mais curta: as duas emendas a deixam mais estreita que as vizinhas
    assert not _inside(box.path, 10, 1.5 * H)
    assert _inside(box.path, wide / 2, 1.5 * H)
    assert _inside(box.path, wide / 2, 2.5 * H)


def test_equal_lines_merge_into_one_straight_edge():
    box = rounded_box([300, 300, 300], H, align="center", radius=RADIUS, padding=PAD)
    assert _arcs(box.path) == [RADIUS] * 4  # só os cantos de fora: nenhuma emenda
    assert _inside(box.path, box.width / 2, H)  # e nada de vinco entre as linhas


def test_step_smaller_than_two_radii_shrinks_the_corner_radius():
    # a linha de baixo é 20 px mais estreita: 10 px de degrau de cada lado, menos que dois raios de 30
    box = rounded_box([400, 380], H, align="center", radius=RADIUS, padding=PAD)
    assert _arcs(box.path) == sorted([RADIUS] * 4 + [5.0] * 4)  # raio do degrau = metade dele


def test_tiny_step_is_snapped_to_a_straight_edge():
    box = rounded_box([400, 399.4], H, align="center", radius=RADIUS, padding=PAD)
    assert _arcs(box.path) == [RADIUS] * 4  # 0,3 px de cada lado não vira um arco microscópico


def test_left_alignment_keeps_the_left_edge_straight():
    box = rounded_box([400, 200, 300], H, align="left", radius=RADIUS, padding=PAD)
    xs = [x for x, _ in _outline(box.path)]
    assert min(xs) == 0
    # só a borda direita tem emendas: o lado esquerdo é uma reta de cima a baixo (entre os cantos de fora)
    assert _inside(box.path, 1.5, 1.5 * H)
    assert not _inside(box.path, 400 + 2 * PAD - 5, 1.5 * H)  # vão à direita da linha curta
    assert _arcs(box.path) == [RADIUS] * 8  # 4 cantos de fora + 2 emendas de 2 curvas no lado direito


def test_right_alignment_mirrors_left():
    left = rounded_box([400, 200, 300], H, align="left", radius=RADIUS, padding=PAD)
    right = rounded_box([400, 200, 300], H, align="right", radius=RADIUS, padding=PAD)
    assert right.width == left.width
    for y in (H / 2, 1.5 * H, 2.5 * H):
        for x in (3, 60, 150, 300, 440):
            assert _inside(right.path, x, y) == _inside(left.path, left.width - x, y)


def test_every_point_stays_inside_the_bounding_box():
    box = rounded_box([400, 120, 360, 200], H, align="center", radius=RADIUS, padding=PAD)
    points = _outline(box.path)
    assert min(x for x, _ in points) == pytest.approx(0, abs=1e-6)
    assert max(x for x, _ in points) == pytest.approx(box.width, abs=1e-6)
    assert min(y for _, y in points) == pytest.approx(0, abs=1e-6)
    assert max(y for _, y in points) == pytest.approx(box.height, abs=1e-6)


def test_radius_never_exceeds_half_the_line_height():
    box = rounded_box([300, 200], H, align="center", radius=500, padding=PAD)
    assert max(_arcs(box.path)) <= H / 2 + 1e-6


def test_zero_radius_gives_a_plain_polygon():
    box = rounded_box([400, 200], H, align="center", radius=0, padding=PAD)
    assert _arcs(box.path) == []
    assert _inside(box.path, 5, 5)  # sem arredondar, a quina de cima fica cheia


def test_each_line_can_have_its_own_height():
    box = rounded_box([400, 200], [H, 0.7 * H], align="center", radius=RADIUS, padding=PAD)
    assert box.height == pytest.approx(1.7 * H)
    # a linha baixa limita os cantos que são dela (os dois de baixo e os de cima, côncavos); os outros seguem o raio
    assert _arcs(box.path) == sorted([round(0.35 * H, 2)] * 4 + [RADIUS] * 4)


def test_no_lines_gives_an_empty_box():
    box = rounded_box([], H, align="center", radius=RADIUS, padding=PAD)
    assert (box.path, box.width, box.height) == ("", 0.0, 0.0)


def test_outline_is_closed_and_every_curve_stays_inside_its_own_corner():
    box = rounded_box([400, 200, 300], H, align="center", radius=RADIUS, padding=PAD)
    commands = _commands(box.path)
    assert commands[0][0] == "m"
    start = tuple(commands[0][1])
    assert (commands[-1][1][-2], commands[-1][1][-1]) == start  # fecha onde começou
    previous = start
    for name, nums in commands[1:]:
        if name == "b":
            x1, y1, x2, y2, x3, y3 = nums
            low_x, high_x = sorted((previous[0], x3))
            low_y, high_y = sorted((previous[1], y3))
            # as alças ficam no quadrado do canto: sem bico, sem laço, sem a curva invadir a linha vizinha
            assert low_x - 1e-6 <= min(x1, x2) and max(x1, x2) <= high_x + 1e-6
            assert low_y - 1e-6 <= min(y1, y2) and max(y1, y2) <= high_y + 1e-6
        previous = (nums[-2], nums[-1])
