"""Imagens estáticas do audiograma, geradas com numpy e Pillow (como as máscaras do PiP).

O ffmpeg compara a altura de cada barra (que muda a cada quadro) com uma imagem fixa que diz, em cada pixel,
até que altura a barra precisa chegar para cobri-lo. Como a imagem não muda, ela é gerada uma vez, com
antialias, e entra no grafo como uma entrada em loop. Cada função recebe só a geometria e devolve imagens:
nada aqui toca o disco; quem salva é o pipeline (`pipeline/textlayer.py`).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PIL import Image

from ..domain.audiogram import BAR_COUNT, GAP_RATIO, BarsLayout, RingLayout, bars_layout


def bars_ramp(layout: BarsLayout) -> Image.Image:
    """Rampa das barras simétricas: em cada pixel, a distância ao centro em fração da meia altura (0 no
    meio, 255 nas bordas), e 255 nos vãos entre as barras (nenhuma altura os alcança).

    O `lut2` do grafo desenha o pixel quando a altura da barra passa desse valor, e a diferença entre as
    duas dá a cobertura do pixel de borda: é o antialias do topo da barra."""
    centre = (layout.height - 1) / 2
    distance = np.abs(np.arange(layout.height) - centre) / layout.half_height * 255.0
    ramp = np.repeat(distance[:, None], layout.width, axis=1)
    column = np.arange(layout.width) % layout.pitch
    left_gap = layout.gap // 2
    in_gap = (column < left_gap) | (column >= layout.pitch - (layout.gap - left_gap))
    ramp[:, in_gap] = 255.0
    return Image.fromarray(np.clip(ramp, 0, 255).astype(np.uint8))


def ring_assets(layout: RingLayout) -> dict[str, Image.Image]:
    """As três imagens do círculo, todas `size` x `size`:

    - `xmap` (16 bits): em cada pixel, o número da barra que passa por ali (o ângulo, de 0 no topo, no
      sentido horário). O `remap` a usa como coordenada da imagem das alturas, e como essa imagem tem
      linhas iguais, a mesma imagem serve de mapa vertical;
    - `radial` (8 bits): a distância ao raio interno em fração do comprimento da maior barra, como a rampa
      das barras retas (255 fora do anel);
    - `ring` (8 bits): a cobertura do pixel pelo anel, com os vãos entre as barras e as bordas interna e
      externa, calculada com antialias, porque o `remap` copia pixels e não os mistura.
    """
    size = layout.size
    rows, cols = np.mgrid[0:size, 0:size].astype(np.float32)
    centre = (size - 1) / 2
    dx, dy = cols - centre, rows - centre
    radius = np.hypot(dx, dy)
    theta = np.mod(np.arctan2(dx, -dy), 2 * np.pi)  # 0 no topo, cresce no sentido horário
    sector = theta / (2 * np.pi) * BAR_COUNT
    index = np.floor(sector).astype(np.int64) % BAR_COUNT
    phase = sector - np.floor(sector)

    # distância (px) até as duas bordas da barra dentro do setor; positiva dentro dela
    sector_arc = 2 * np.pi * radius / BAR_COUNT  # comprimento do arco de um setor, em px
    gap = GAP_RATIO / 2
    from_left = (phase - gap) * sector_arc
    from_right = (1 - gap - phase) * sector_arc
    angular = np.clip(from_left + 0.5, 0, 1) * np.clip(from_right + 0.5, 0, 1)
    ring = angular * np.clip(radius - layout.inner + 0.5, 0, 1) * np.clip(layout.outer + 0.5 - radius, 0, 1)

    radial = np.clip((radius - layout.inner) / layout.span, 0, 1) * 255.0
    return {
        "xmap": Image.fromarray(index.astype(np.uint16)),
        "radial": Image.fromarray(np.clip(radial, 0, 255).astype(np.uint8)),
        "ring": Image.fromarray(np.clip(ring * 255, 0, 255).astype(np.uint8)),
    }


# As imagens estáticas de cada estilo, pelo nome do estilo (um estilo novo registra a sua aqui, como em
# `filtergraph.audiogram.STYLES`); a onda não precisa de nenhuma.
STYLE_ASSETS: dict[str, Callable[[int, int, float], dict[str, Image.Image]]] = {
    "wave": lambda width, height, inner_radius: {},
    "bars": lambda width, height, inner_radius: {"ramp": bars_ramp(bars_layout(width, height))},
    "circle": lambda width, height, inner_radius: ring_assets(RingLayout(width, inner_radius)),
}


def style_assets(style: str, width: int, height: int, inner_radius: float) -> dict[str, Image.Image]:
    """As imagens estáticas do estilo para um desenho de `width` x `height` px."""
    return STYLE_ASSETS[style](width, height, inner_radius)
