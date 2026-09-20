"""Cartões definidos por layout no brand.json da marca (fundo em imagem, elementos de texto e
imagem posicionados), para marcas com identidade própria (ex.: cartões florais de casamento da
PASCOM), em vez do visual genérico de `visuals.cards`. Puro: recebe dados, devolve uma imagem.

Layout: `{"background": "cards/placa.png", "elements": [...]}`, com posições e tamanhos em px na
base 1920x1080 (escalados para a resolução pedida). Elementos, por `kind`:
- `text`: `text` (com `{{campo}}` interpolado de `fields`), `font` (papel em `theme.fonts.files`),
  `size`, `y`, `x` (opcional, centro do quadro), `color`, `shadow`, `align`. Vazio após interpolar
  = omitido.
- `lines`: `field` (lista em `fields`) quebrada em linhas de `per_line` itens, unidas por `join`;
  lista de 1 item usa `single_size`/`single_y` se definidos.
- `blocks`: `items` (cada um com `title` e `text`, `text` pode ter `\\n`) empilhados e centralizados
  verticalmente (`center_y`); item com texto vazio é omitido.
- `image`: `src` (`logo:<nome>` de `theme.logos` ou caminho relativo à marca), `width`, `x`, `y`
  (canto superior esquerdo), `blend` (`multiply` para logo de fundo branco sobre placa clara, ou
  `alpha`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from ..domain.brand import Theme
from ..media import fonts

BASE_W, BASE_H = 1920, 1080

_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")

FieldValue = str | list[str]


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _interpolate(template: str, fields: Mapping[str, FieldValue]) -> str:
    def repl(m: re.Match[str]) -> str:
        value = fields.get(m.group(1), "")
        return value if isinstance(value, str) else " ".join(value)

    return _TOKEN_RE.sub(repl, template)


def _font(theme: Theme, role: str, size: float, scale: float) -> ImageFont.FreeTypeFont:
    path = fonts.resolve_file(theme.fonts.get("files", {}), role)
    return ImageFont.truetype(str(path), max(1, int(round(size * scale))))


def _draw_shadow(
    img: Image.Image, x: float, y: float, text: str, font: ImageFont.FreeTypeFont, scale: float
) -> None:
    """Sombra suave: texto preto a 43% deslocado (4, 5) com blur 4, na base 1920x1080."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((x + 4 * scale, y + 5 * scale), text, font=font, fill=(0, 0, 0, 110))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=max(0.1, 4 * scale)))
    img.alpha_composite(layer)


def _anchor_x(img_width: int, text_width: float, x: float | None, align: str, scale: float) -> float:
    if x is None:
        return (img_width - text_width) / 2
    cx = x * scale
    if align == "left":
        return cx
    if align == "right":
        return cx - text_width
    return cx - text_width / 2  # center


def _render_text(
    img: Image.Image, theme: Theme, element: dict[str, Any], fields: Mapping[str, FieldValue], scale: float
) -> None:
    text = _interpolate(str(element["text"]), fields)
    if not text.strip():
        return
    font = _font(theme, element["font"], element["size"], scale)
    color = _rgb(element.get("color", "#000000"))
    align = element.get("align", "center")
    x = _anchor_x(img.width, font.getlength(text), element.get("x"), align, scale)
    y = element["y"] * scale
    if element.get("shadow"):
        _draw_shadow(img, x, y, text, font, scale)
    ImageDraw.Draw(img).text((x, y), text, font=font, fill=color)


def _render_lines(
    img: Image.Image, theme: Theme, element: dict[str, Any], fields: Mapping[str, FieldValue], scale: float
) -> None:
    values = fields.get(element["field"], [])
    if isinstance(values, str):
        values = [values] if values else []
    values = [v for v in values if v]
    if not values:
        return
    color = _rgb(element.get("color", "#000000"))
    align = element.get("align", "center")
    x = element.get("x")
    if len(values) == 1 and ("single_size" in element or "single_y" in element):
        lines = [values[0]]
        size = element.get("single_size", element["size"])
        y = element.get("single_y", element["y"])
    else:
        per_line = element.get("per_line", len(values))
        join = element.get("join", "  ")
        lines = [join.join(values[i : i + per_line]) for i in range(0, len(values), per_line)]
        size = element["size"]
        y = element["y"]
    font = _font(theme, element["font"], size, scale)
    line_gap = element.get("line_gap", size * 1.2) * scale
    yy = y * scale
    for line in lines:
        lx = _anchor_x(img.width, font.getlength(line), x, align, scale)
        if element.get("shadow"):
            _draw_shadow(img, lx, yy, line, font, scale)
        ImageDraw.Draw(img).text((lx, yy), line, font=font, fill=color)
        yy += line_gap


def _render_blocks(
    img: Image.Image, theme: Theme, group: dict[str, Any], fields: Mapping[str, FieldValue], scale: float
) -> None:
    title_role = group.get("title_font")
    text_role = group.get("text_font", title_role)
    title_size = group.get("title_size", 48)
    text_size = group.get("text_size", 34)
    title_gap = group.get("title_gap", 60)
    line_gap = group.get("line_gap", 44)
    block_gap = group.get("block_gap", 30)
    color = _rgb(group.get("color", "#000000"))
    shadow = bool(group.get("shadow"))

    blocks: list[tuple[str, list[str]]] = []
    for item in group.get("items", []):
        text = _interpolate(str(item.get("text", "")), fields)
        if not text.strip():
            continue
        blocks.append((_interpolate(str(item.get("title", "")), fields), text.split("\n")))
    if not blocks:
        return

    title_font = _font(theme, title_role, title_size, scale)
    text_font = _font(theme, text_role, text_size, scale)
    heights = [(title_gap + line_gap * len(lines)) * scale for _, lines in blocks]
    total = sum(heights) + block_gap * scale * (len(blocks) - 1)
    y = (img.height - total) / 2 if group.get("center_y", True) else group.get("y", 0) * scale

    for (title, lines), block_h in zip(blocks, heights, strict=True):
        if title:
            w = title_font.getlength(title)
            x = (img.width - w) / 2
            if shadow:
                _draw_shadow(img, x, y, title, title_font, scale)
            ImageDraw.Draw(img).text((x, y), title, font=title_font, fill=color)
        yy = y + title_gap * scale
        for line in lines:
            w = text_font.getlength(line)
            x = (img.width - w) / 2
            if shadow:
                _draw_shadow(img, x, yy, line, text_font, scale)
            ImageDraw.Draw(img).text((x, yy), line, font=text_font, fill=color)
            yy += line_gap * scale
        y += block_h + block_gap * scale


def _resolve_image_src(theme: Theme, src: str):
    if src.startswith("logo:"):
        name = src.split(":", 1)[1]
        path = theme.logos.get(name)
        if path is None:
            raise FileNotFoundError(f"logo desconhecido na marca {theme.name!r}: {name!r}")
        return path
    return theme.resolve_asset(src)


def _render_image(img: Image.Image, theme: Theme, element: dict[str, Any], scale: float) -> None:
    path = _resolve_image_src(theme, element["src"])
    logo = Image.open(path).convert("RGBA")
    target_w = max(1, int(round(element["width"] * scale)))
    ratio = target_w / logo.width
    target_h = max(1, int(round(logo.height * ratio)))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)
    x = int(round(element.get("x", 0) * scale))
    y = int(round(element.get("y", 0) * scale))
    if element.get("blend") == "multiply":
        # logo com fundo branco (ou transparente) sobre a placa clara: mistura por multiplicação,
        # como no gerador de referência da PASCOM (make_cards.py)
        opaque = Image.new("RGBA", logo.size, (255, 255, 255, 255))
        opaque.alpha_composite(logo)
        region = img.crop((x, y, x + logo.width, y + logo.height)).convert("RGB")
        mixed = ImageChops.multiply(region, opaque.convert("RGB"))
        img.paste(mixed.convert("RGBA"), (x, y))
    else:
        img.alpha_composite(logo, (x, y))


_RENDERERS = {
    "text": _render_text,
    "lines": _render_lines,
    "blocks": _render_blocks,
}


def render_layout_card(
    theme: Theme,
    layout_name: str,
    fields: Mapping[str, FieldValue],
    width: int,
    height: int,
    supersample: int = 1,
) -> Image.Image:
    """Cartão RGB de `width` x `height` a partir de um layout de `theme.card_layouts`."""
    layout = theme.card_layouts.get(layout_name)
    if layout is None:
        raise KeyError(f"layout de cartão desconhecido na marca {theme.name!r}: {layout_name!r}")
    ss = max(1, supersample)
    w, h = width * ss, height * ss
    scale = w / BASE_W

    bg_path = theme.resolve_asset(layout["background"])
    img = Image.open(bg_path).convert("RGBA").resize((w, h), Image.LANCZOS)

    for element in layout.get("elements", []):
        kind = element["kind"]
        if kind == "image":
            _render_image(img, theme, element, scale)
            continue
        renderer = _RENDERERS.get(kind)
        if renderer is None:
            raise ValueError(f"elemento de layout de cartão desconhecido: {kind!r}")
        renderer(img, theme, element, fields, scale)

    if ss > 1:
        img = img.resize((width, height), Image.LANCZOS)
    return img.convert("RGB")
