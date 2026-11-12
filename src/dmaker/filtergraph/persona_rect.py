"""O retângulo da persona sobreposta no quadro: a conta única do render, da caixa da interface e do QA."""

from __future__ import annotations

from ..domain.presets import SafeZone
from ..domain.spec import PersonaOverlay, parse_aspect
from .common import even
from .pip import pip_origin

BOTTOM_POSITIONS = ("bottom-left", "bottom-right", "bottom")


def persona_size(overlay: PersonaOverlay, W: int) -> tuple[int, int]:
    """Largura e altura (px, pares) do quadro da persona; o círculo com fundo força 1:1."""
    width = even(W * overlay.width)
    aspect = 1.0 if overlay.shape == "circle" and overlay.background else parse_aspect(overlay.aspect)
    return width, even(width / aspect)


def persona_overlay_rect(
    overlay: PersonaOverlay,
    W: int,
    H: int,
    scale: float,
    safe: SafeZone,
    caption_band: tuple[float, float] | None = None,
) -> tuple[int, int, int, int]:
    """(esquerda, topo, largura, altura) da persona. Com legenda queimada (`caption_band`, topo e base em px) e
    uma posição nomeada de baixo, a borda de baixo sobe para acima do topo da faixa, com o `margin` de folga: o
    texto da legenda perde o contorno sobre o fundo claro do cartão. Se não couber, o topo encosta na zona segura
    de cima (e o QA avisa). `x`/`y` e as posições de cima e do centro ficam onde estão."""
    width, height = persona_size(overlay, W)
    left, top = pip_origin(overlay, width, height, W, H, scale, safe)
    if caption_band is not None and overlay.x is None and overlay.position in BOTTOM_POSITIONS:
        bottom = caption_band[0] - overlay.margin * scale
        top = max(min(top, int(round(bottom - height))), int(round(safe.top)))
    return left, top, width, height
