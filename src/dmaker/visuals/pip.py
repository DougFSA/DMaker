"""Máscara e moldura do picture-in-picture, geradas com Pillow.

A máscara (L) recorta o vídeo secundário (retângulo, cantos redondos ou círculo, com suavidade
opcional). A moldura (RGBA) carrega sombra e borda e vai por baixo do PiP, com o anel da borda
para fora do retângulo do vídeo, o que dispensa compor por cima.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from .cards import _rgba


@dataclass(frozen=True)
class PipAssets:
    mask: Image.Image  # tamanho do PiP, modo L
    frame: Image.Image | None  # RGBA, tamanho do PiP + 2*pad; None quando não há borda nem sombra
    pad: int  # quanto a moldura excede o PiP de cada lado


def _shape(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], shape: str, radius: int, fill) -> None:
    if shape == "circle":
        draw.ellipse(box, fill=fill)
    elif shape == "rounded" and radius > 0:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    else:
        draw.rectangle(box, fill=fill)


def pip_mask(
    width: int, height: int, shape: str, radius: int, softness: int, supersample: int = 4
) -> Image.Image:
    """Máscara antialiasada (desenhada em `supersample`x e reduzida)."""
    ss = supersample
    big = Image.new("L", (width * ss, height * ss), 0)
    _shape(ImageDraw.Draw(big), (0, 0, width * ss - 1, height * ss - 1), shape, radius * ss, 255)
    mask = big.resize((width, height), Image.Resampling.LANCZOS)
    if softness > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=softness))
    return mask


def pip_frame(
    width: int,
    height: int,
    shape: str,
    radius: int,
    border: int,
    border_color: str,
    shadow: bool,
) -> tuple[Image.Image | None, int]:
    """Sombra + anel de borda ao redor do retângulo (w x h). Devolve (imagem, pad)."""
    shadow_pad = int(round(min(width, height) * 0.08)) if shadow else 0
    pad = border + shadow_pad
    if pad == 0:
        return None, 0
    size = (width + 2 * pad, height + 2 * pad)
    frame = Image.new("RGBA", size, (0, 0, 0, 0))
    if shadow:
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        offset_y = int(round(shadow_pad * 0.4))
        box = (pad, pad + offset_y, pad + width - 1, pad + height - 1 + offset_y)
        _shape(ImageDraw.Draw(layer), box, shape, radius, (0, 0, 0, 150))
        frame.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius=shadow_pad * 0.6)))
    if border > 0:
        ring = Image.new("RGBA", size, (0, 0, 0, 0))
        box = (pad - border, pad - border, pad + width - 1 + border, pad + height - 1 + border)
        _shape(ImageDraw.Draw(ring), box, shape, radius + border, _rgba(border_color, 1.0))
        frame.alpha_composite(ring)
    return frame, pad


def render_pip_assets(
    width: int,
    height: int,
    shape: str = "rounded",
    radius: int = 0,
    softness: int = 0,
    border: int = 0,
    border_color: str = "#FFFFFF",
    shadow: bool = True,
) -> PipAssets:
    mask = pip_mask(width, height, shape, radius, softness)
    frame, pad = pip_frame(width, height, shape, radius, border, border_color, shadow)
    return PipAssets(mask, frame, pad)
