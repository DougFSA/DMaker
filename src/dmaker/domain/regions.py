"""Regiões nomeadas do quadro: resolvem `region: "<nome>"` das sobreposições em x/y/width concretos.

Tudo aqui é conta pura, sem disco nem ffmpeg. A resolução roda uma vez, antes dos construtores de
sobreposição (`pipeline/textlayer.py`, QA), e devolve cópias sem `region`: o resto do pipeline continua
recebendo x/y/width, sem saber que existem regiões. Quem desenha dentro de uma região (infográficos,
composições) pede os pixels dela por `region_pixels`, sem repetir a conta de fração para pixel.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from .spec import ImageOverlay, Region, TextOverlay, VideoOverlay, parse_aspect

# folga em px na largura devolvida: o ffmpeg trunca `largura * fração` para par, e sem ela uma divisão
# que desse 971.9999 viraria 970 e deixaria uma fresta entre o quadro e a borda da região
_WIDTH_SLACK_PX = 0.01


class RegionError(ValueError):
    """Sobreposição aponta para uma região que o projeto não declara."""


@dataclass(frozen=True)
class Fit:
    """Onde um conteúdo cai dentro de uma região: centro (fração do quadro) e largura (fração da largura)."""

    x: float
    y: float
    width: float


def region_pixels(region: Region, width: int, height: int) -> tuple[int, int, int, int]:
    """(esquerda, topo, largura, altura) da região, em pixels de um quadro `width` x `height`."""
    box_w, box_h = region.width * width, region.height * height
    left = region.x * width - box_w / 2
    top = region.y * height - box_h / 2
    return round(left), round(top), round(box_w), round(box_h)


def fit_in_region(region: Region, content_aspect: float, width: int, height: int) -> Fit:
    """Conteúdo de proporção `content_aspect` (largura/altura) o maior possível dentro da região,
    centrado e sem distorcer. A conta é em pixels porque a região é em fração do quadro."""
    box_w, box_h = region.width * width, region.height * height
    fit_w = box_w if content_aspect >= box_w / box_h else box_h * content_aspect
    return Fit(region.x, region.y, (fit_w + _WIDTH_SLACK_PX) / width)


def _lookup(name: str, regions: Mapping[str, Region]) -> Region:
    try:
        return regions[name]
    except KeyError:
        known = ", ".join(sorted(regions)) or "nenhuma declarada"
        raise RegionError(f"região desconhecida: {name!r} (regiões do projeto: {known})") from None


def _resolve_text(overlay: TextOverlay, region: Region, width: int, height: int, aspect: float | None):
    """Texto centrado na região (ou encostado na borda, com `align` left/right), quebrando na largura dela."""
    align = overlay.style.align or "center"
    edge = {"left": -0.5, "center": 0.0, "right": 0.5}[align]
    max_width = region.width
    if overlay.style.max_width is not None:
        max_width = min(overlay.style.max_width, region.width)
    style = overlay.style.model_copy(update={"align": align, "max_width": max_width})
    return overlay.model_copy(
        update={"x": region.x + edge * region.width, "y": region.y, "region": None, "style": style}
    )


def _resolve_image(overlay: ImageOverlay, region: Region, width: int, height: int, aspect: float | None):
    """Imagem inteira dentro da região; sem a proporção da imagem, ocupa a proporção da própria região."""
    if not aspect:
        aspect = (region.width * width) / (region.height * height)
    fit = fit_in_region(region, aspect, width, height)
    return overlay.model_copy(update={"x": fit.x, "y": fit.y, "width": fit.width, "region": None})


def _resolve_video(overlay: VideoOverlay, region: Region, width: int, height: int, aspect: float | None):
    """Quadro do vídeo: a região inteira (o vídeo preenche cortando o excesso) ou, com `aspect` (ou no
    círculo, que é 1:1), o maior quadro dessa proporção que cabe nela."""
    if overlay.aspect is None and overlay.shape != "circle":
        box_w, box_h = region.width * width, region.height * height
        fit = Fit(region.x, region.y, (box_w + _WIDTH_SLACK_PX) / width)
        frame_aspect = f"{round(box_w)}:{round(box_h)}"  # a proporção da própria região, em px inteiros
    else:
        frame_aspect = overlay.aspect or "1:1"
        fit = fit_in_region(region, parse_aspect(frame_aspect), width, height)
    return overlay.model_copy(
        update={"x": fit.x, "y": fit.y, "width": fit.width, "aspect": frame_aspect, "region": None}
    )


Resolver = Callable[..., object]
Overlay = TypeVar("Overlay")

# Como cada tipo de sobreposição se encaixa numa região. Um tipo novo com `region` entra aqui.
RESOLVERS: dict[type, Resolver] = {
    TextOverlay: _resolve_text,
    ImageOverlay: _resolve_image,
    VideoOverlay: _resolve_video,
}


def resolve_region(
    overlay: Overlay,
    regions: Mapping[str, Region],
    width: int,
    height: int,
    content_aspect: float | None = None,
) -> Overlay:
    """`overlay` com x/y/width concretos no lugar de `region`; devolve o próprio objeto se não tem região.
    `content_aspect` (largura/altura do arquivo) só é necessário para imagem: sem ele, ela ocupa a
    proporção da região."""
    name = getattr(overlay, "region", None)
    if not name:
        return overlay
    resolver = RESOLVERS[type(overlay)]
    return resolver(overlay, _lookup(name, regions), width, height, content_aspect)
