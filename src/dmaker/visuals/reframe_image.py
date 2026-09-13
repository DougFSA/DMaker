"""Reenquadramento de imagens paradas (fotos, prints, cartões) com Pillow.

Os mesmos modos do vídeo (crop, pad, blur, brand, stretch), mas resolvidos aqui porque as imagens
seguem para o renderizador de movimento sub-pixel, não para o FFmpeg.
"""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter

from ..domain.brand import Theme
from ..domain.spec import Reframe
from .cards import render_framed_image
from .geometry import cover_box


def _hex_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _crop_cover(
    img: Image.Image, width: int, height: int, focus: tuple[float, float], zoom: float
) -> Image.Image:
    aspect = width / height
    x0, y0, x1, y1 = cover_box(img.width, img.height, aspect, focus)
    if zoom > 1:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = (x1 - x0) / zoom, (y1 - y0) / zoom
        x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    return img.resize((width, height), Image.Resampling.LANCZOS, box=(x0, y0, x1, y1))


def _fit(img: Image.Image, width: int, height: int) -> Image.Image:
    k = min(width / img.width, height / img.height)
    return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.Resampling.LANCZOS)


def reframe_image(
    img: Image.Image,
    width: int,
    height: int,
    reframe: Reframe,
    mode: str,
    theme: Theme | None = None,
    seed: int = 0,
) -> Image.Image:
    """Imagem RGB de exatamente `width` x `height` no modo já resolvido (ver resolve_reframe_mode)."""
    img = img.convert("RGB")
    if mode == "stretch":
        return img.resize((width, height), Image.Resampling.LANCZOS)
    if mode == "crop":
        return _crop_cover(img, width, height, reframe.focus, reframe.zoom)
    if mode == "pad":
        canvas = Image.new("RGB", (width, height), _hex_rgb(reframe.pad_color))
        fg = _fit(img, width, height)
        canvas.paste(fg, ((width - fg.width) // 2, (height - fg.height) // 2))
        return canvas
    if mode == "brand":
        if theme is None:
            raise ValueError("modo brand precisa de um tema")
        return render_framed_image(
            theme, width, height, img, reframe.variant, seed, reframe.margin, reframe.radius
        )
    # blur: fundo desfocado preenchendo o quadro, imagem inteira por cima
    small_w, small_h = max(2, width // 4), max(2, height // 4)
    bg = _crop_cover(img, small_w, small_h, (0.5, 0.5), 1.0)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=max(reframe.blur / 4, 1)))
    bg = ImageEnhance.Brightness(bg).enhance(0.94)
    bg = ImageEnhance.Color(bg).enhance(0.85)
    bg = bg.resize((width, height), Image.Resampling.BICUBIC)
    fg = _fit(img, width, height)
    bg.paste(fg, ((width - fg.width) // 2, (height - fg.height) // 2))
    return bg
