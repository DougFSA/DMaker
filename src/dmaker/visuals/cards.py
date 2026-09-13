"""Cartões gerados com Pillow (abertura, CTA, encerramento) no visual do tema.

Segue a identidade do MedlyCare quando o tema é o da marca: fundo nunca chapado
(blobs orgânicos nos cantos, linhas finas de rede com nós, brilhos em losango),
Poppins, "Medly" em teal escuro e "Care" em verde. Renderiza em 2x e reduz com LANCZOS.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ..domain.brand import Theme
from ..domain.presets import SafeZone
from ..media import fonts
from .geometry import fit_rect


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgba(hex_color: str, alpha: float) -> tuple[int, int, int, int]:
    r, g, b = _rgb(hex_color)
    return r, g, b, int(round(255 * alpha))


def _blob_points(
    cx: float, cy: float, r: float, rng: random.Random, n: int = 90
) -> list[tuple[float, float]]:
    p1, p2, p3 = rng.uniform(0, 6.28), rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    a1, a2, a3 = rng.uniform(0.10, 0.2), rng.uniform(0.05, 0.12), rng.uniform(0.02, 0.06)
    stretch = rng.uniform(0.85, 1.25)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        rr = r * (1 + a1 * math.sin(3 * t + p1) + a2 * math.sin(5 * t + p2) + a3 * math.sin(8 * t + p3))
        pts.append((cx + rr * math.cos(t) * stretch, cy + rr * math.sin(t)))
    return pts


def _draw_background(img: Image.Image, theme: Theme, dark: bool, rng: random.Random) -> None:
    w, h = img.size
    base = min(w, h)
    colors = theme.colors
    if dark:
        blob_colors = [(colors["accent"], 0.32), (colors["mint"], 0.22), (colors["icon"], 0.28)]
        line_color = _rgba(colors["mint"], 0.55)
        spark_colors = [colors["mint"], colors["accent"]]
    else:
        blob_colors = [(colors["mint"], 0.75), (colors["accent"], 0.55), (colors["mint"], 0.6)]
        line_color = _rgba(colors["icon"], 0.5)
        spark_colors = [colors["accent"], colors["icon"]]

    # blobs orgânicos nos cantos
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    spots = [
        (-0.04 * w, -0.03 * h, 0.42 * base),
        (1.04 * w, 1.02 * h, 0.48 * base),
        (1.02 * w, 0.12 * h, 0.2 * base),
    ]
    for (cx, cy, r), (color, alpha) in zip(spots, blob_colors, strict=False):
        d.polygon(_blob_points(cx, cy, r, rng), fill=_rgba(color, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=base * 0.012))
    img.alpha_composite(layer)

    # rede: nós ligados por linhas finas, numa região de canto
    net = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    nd = ImageDraw.Draw(net)
    region = (
        (0.62 * w, 0.06 * h, 0.96 * w, 0.30 * h)
        if rng.random() < 0.5
        else (0.04 * w, 0.66 * h, 0.4 * w, 0.92 * h)
    )
    nodes = [(rng.uniform(region[0], region[2]), rng.uniform(region[1], region[3])) for _ in range(7)]
    lw = max(2, int(base * 0.0022))
    for i, a in enumerate(nodes):
        dists = sorted(((math.dist(a, b), j) for j, b in enumerate(nodes) if j != i), key=lambda x: x[0])
        for _, j in dists[:2]:
            nd.line([a, nodes[j]], fill=line_color, width=lw)
    r = base * 0.006
    for x, y in nodes:
        nd.ellipse([x - r, y - r, x + r, y + r], fill=line_color)
    img.alpha_composite(net)

    # brilhos em losango (estrela de 4 pontas)
    sp = ImageDraw.Draw(img)
    for _ in range(5):
        x, y = rng.uniform(0.05 * w, 0.95 * w), rng.uniform(0.05 * h, 0.95 * h)
        size = rng.uniform(0.012, 0.03) * base
        inner = size * 0.22
        pts = [
            (x, y - size),
            (x + inner, y - inner),
            (x + size, y),
            (x + inner, y + inner),
            (x, y + size),
            (x - inner, y + inner),
            (x - size, y),
            (x - inner, y - inner),
        ]
        sp.polygon(pts, fill=_rgba(rng.choice(spark_colors), rng.uniform(0.6, 0.95)))


def _wrap(text: str, font, max_w: float) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for wd in words[1:]:
            cand = f"{cur} {wd}"
            if font.getlength(cand) <= max_w:
                cur = cand
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
    return lines


def _draw_rich_line(
    draw: ImageDraw.ImageDraw, x: float, y: float, line: str, font, color, theme: Theme, dark: bool
):
    """Desenha a linha; a palavra MedlyCare sai com Medly/Care nas cores da marca."""
    tokens = line.split(" ")
    cx = x
    for i, tok in enumerate(tokens):
        piece = tok + (" " if i < len(tokens) - 1 else "")
        if tok.rstrip(".,!?:;").lower() == "medlycare":
            tail = tok[len("MedlyCare") :]
            medly_color = "#FFFFFF" if dark else theme.colors["primary"]
            care_color = theme.colors["accent"]
            draw.text((cx, y), "Medly", font=font, fill=_rgb(medly_color))
            cx += font.getlength("Medly")
            draw.text((cx, y), "Care", font=font, fill=_rgb(care_color))
            cx += font.getlength("Care")
            rest = tail + (" " if i < len(tokens) - 1 else "")
            if rest:
                draw.text((cx, y), rest, font=font, fill=color)
                cx += font.getlength(rest)
        else:
            draw.text((cx, y), piece, font=font, fill=color)
            cx += font.getlength(piece)


def render_card(
    theme: Theme,
    width: int,
    height: int,
    title: str,
    subtitle: str | None = None,
    variant: str | None = None,
    logo: bool = True,
    background: str | None = None,
    safe: SafeZone | None = None,
    seed: int | None = None,
    supersample: int = 2,
) -> Image.Image:
    """Cartão RGB de `width` x `height`. Desenha em `supersample`x e reduz com LANCZOS."""
    ss = max(1, supersample)
    w, h = width * ss, height * ss
    safe = safe or SafeZone()
    variant = variant or theme.style.get("card_variant", "light")
    dark = variant == "dark"
    bg = background or (theme.colors["bg_dark"] if dark else theme.colors["bg"])
    rng = random.Random(seed if seed is not None else hash(title) & 0xFFFF)
    img = Image.new("RGBA", (w, h), _rgba(bg, 1.0))
    _draw_background(img, theme, dark, rng)

    base = min(w, h)
    draw = ImageDraw.Draw(img)
    title_ref = fonts.resolve(theme.font_family, theme.weight("title"))
    body_ref = fonts.resolve(theme.font_family, theme.weight("body"))
    title_size = int(base * 0.085)
    sub_size = int(base * 0.042)
    from PIL import ImageFont

    title_font = ImageFont.truetype(str(title_ref.file), title_size)
    sub_font = ImageFont.truetype(str(body_ref.file), sub_size)
    max_w = w * 0.84 - (safe.left + safe.right) * ss
    title_lines = _wrap(title, title_font, max_w)
    sub_lines = _wrap(subtitle, sub_font, max_w) if subtitle else []

    title_lh = title_size * 1.18
    sub_lh = sub_size * 1.35
    block_h = len(title_lines) * title_lh + (sub_size * 0.6 + len(sub_lines) * sub_lh if sub_lines else 0)

    title_color = _rgb("#FFFFFF" if dark else theme.colors["primary"])
    sub_color = _rgb(theme.colors["mint"] if dark else theme.colors["text"])
    if theme.key == "default":
        title_color = _rgb(theme.colors["text"])
        sub_color = _rgb(theme.colors["muted"])

    y = h * 0.46 - block_h / 2 + (safe.top - safe.bottom) * ss * 0.25
    for line in title_lines:
        lw = title_font.getlength(line)
        _draw_rich_line(draw, (w - lw) / 2, y, line, title_font, title_color, theme, dark)
        y += title_lh
    if sub_lines:
        y += sub_size * 0.6
        for line in sub_lines:
            lw = sub_font.getlength(line)
            draw.text(((w - lw) / 2, y), line, font=sub_font, fill=sub_color)
            y += sub_lh

    if logo:
        logo_path = theme.logo("horizontal_dark" if dark else "horizontal")
        if logo_path:
            lg = Image.open(logo_path).convert("RGBA")
            target_w = int(w * (0.40 if h > w else 0.24))
            ratio = target_w / lg.width
            lg = lg.resize((target_w, int(lg.height * ratio)), Image.LANCZOS)
            ly = int(h - safe.bottom * ss - h * 0.05 - lg.height)
            ly = max(ly, int(y + sub_size))
            img.alpha_composite(lg, ((w - lg.width) // 2, ly))

    out = img.convert("RGB").resize((width, height), Image.LANCZOS)
    return out


def save_card(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return path


# ---------- fundo de marca para o modo de enquadramento "brand" ----------


def _backdrop_rgba(
    theme: Theme,
    width: int,
    height: int,
    variant: str | None,
    seed: int,
    fg_rect: tuple[int, int, int, int] | None,
    background: str | None,
    ss: int = 2,
) -> Image.Image:
    w, h = width * ss, height * ss
    variant = variant or theme.style.get("card_variant", "light")
    dark = variant == "dark"
    bg = background or (theme.colors["bg_dark"] if dark else theme.colors["bg"])
    rng = random.Random(seed)
    img = Image.new("RGBA", (w, h), _rgba(bg, 1.0))
    _draw_background(img, theme, dark, rng)
    if fg_rect:
        x, y, fw, fh = (v * ss for v in fg_rect)
        base = min(w, h)
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        off = base * 0.012
        sd.rounded_rectangle(
            [x, y + off, x + fw, y + fh + off],
            radius=base * 0.02,
            fill=(0, 0, 0, int(255 * (0.45 if dark else 0.28))),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=base * 0.02))
        img.alpha_composite(shadow)
    return img


def render_backdrop(
    theme: Theme,
    width: int,
    height: int,
    variant: str | None = None,
    seed: int = 0,
    fg_rect: tuple[int, int, int, int] | None = None,
    background: str | None = None,
) -> Image.Image:
    """Fundo com o visual do tema (sem texto) e sombra suave sob o retângulo da fonte."""
    img = _backdrop_rgba(theme, width, height, variant, seed, fg_rect, background)
    return img.convert("RGB").resize((width, height), Image.LANCZOS)


def render_framed_image(
    theme: Theme,
    width: int,
    height: int,
    src: Path | Image.Image,
    variant: str | None = None,
    seed: int = 0,
    margin: float = 0.05,
    radius: float = 0.018,
    background: str | None = None,
    supersample: int = 2,
) -> Image.Image:
    """Imagem inteira (print, foto) com cantos redondos e sombra sobre o fundo do tema, já no tamanho do vídeo."""
    ss = max(1, supersample)
    w, h = width * ss, height * ss
    fg = (Image.open(src) if isinstance(src, Path) else src).convert("RGBA")
    x, y, fw, fh = fit_rect(fg.width, fg.height, width, height, margin)
    canvas = _backdrop_rgba(theme, width, height, variant, seed, (x, y, fw, fh), background, ss)
    fg = fg.resize((fw * ss, fh * ss), Image.LANCZOS)
    r = int(min(w, h) * radius)
    if r > 0:
        mask = Image.new("L", fg.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fg.width - 1, fg.height - 1], radius=r, fill=255)
        fg.putalpha(mask)
    canvas.alpha_composite(fg, (x * ss, y * ss))
    return canvas.convert("RGB").resize((width, height), Image.LANCZOS)
