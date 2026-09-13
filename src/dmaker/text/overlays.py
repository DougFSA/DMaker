"""Texto na tela (gancho, título, CTA, lower-third), legendas e barra de progresso -> eventos ASS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..domain.brand import Theme
from ..domain.presets import SafeZone
from ..domain.spec import CaptionStyle, ProgressBar, TextOverlay
from ..media import fonts
from .ass import AssDoc, Event, Style, ass_alpha, ass_color, escape_text, rect_path, rounded_rect_path
from .captions import Cue


@dataclass
class Canvas:
    width: int
    height: int
    safe: SafeZone
    theme: Theme
    total: float

    @property
    def scale(self) -> float:
        """Fator para tamanhos definidos na base 1080 (lado menor)."""
        return min(self.width, self.height) / 1080

    def px(self, v: float) -> float:
        return v * self.scale

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width * 1.4


ROLE_DEFAULTS: dict[str, dict] = {
    "hook": dict(
        size=92,
        weight="bold",
        color="white",
        outline=5,
        shadow=2,
        box=False,
        uppercase=False,
        position="top",
        animation="pop",
        align="center",
        max_width=0.86,
        box_radius=24,
        box_padding=24,
    ),
    "title": dict(
        size=80,
        weight="bold",
        color="white",
        outline=4,
        shadow=2,
        box=False,
        uppercase=False,
        position="center",
        animation="fade",
        align="center",
        max_width=0.86,
        box_radius=24,
        box_padding=24,
    ),
    "subtitle": dict(
        size=50,
        weight="medium",
        color="white",
        outline=3,
        shadow=1,
        box=False,
        uppercase=False,
        position="center",
        animation="fade",
        align="center",
        max_width=0.8,
        box_radius=18,
        box_padding=18,
        offset_y=0.075,
    ),
    "cta": dict(
        size=54,
        weight="bold",
        color=None,
        outline=0,
        shadow=0,
        box=True,
        box_color=None,
        box_alpha=1.0,
        box_radius=30,
        box_padding=26,
        uppercase=False,
        position="bottom",
        animation="slide-up",
        align="center",
        max_width=0.86,
    ),
    "lower-third": dict(
        size=48,
        weight="bold",
        color="white",
        outline=0,
        shadow=0,
        box=True,
        box_color="#000000",
        box_alpha=0.55,
        box_radius=14,
        box_padding=22,
        uppercase=False,
        position="bottom",
        animation="slide-up",
        align="left",
        max_width=0.7,
    ),
    "custom": dict(
        size=64,
        weight="bold",
        color="white",
        outline=4,
        shadow=2,
        box=False,
        uppercase=False,
        position="center",
        animation="fade",
        align="center",
        max_width=0.86,
        box_radius=20,
        box_padding=20,
    ),
}


def effective_style(ov: TextOverlay, theme: Theme, tone: str | None = None) -> dict:
    """Estilo final: padrão do papel -> ajuste pelo tom do fundo (claro/escuro) -> estilo da spec."""
    st = dict(ROLE_DEFAULTS[ov.role])
    if tone == "light" and not st.get("box"):
        # sobre fundo claro do tema (cartões, modo brand): texto na cor principal, sem contorno
        st.update(color="primary", outline=0, shadow=0)
    elif tone == "dark" and not st.get("box"):
        st.update(color="white", outline=0, shadow=0)
    elif tone == "dark" and ov.role == "cta":
        # a pílula na cor principal sumiria no fundo escuro do tema: inverte para accent + texto principal
        st.update(box_color="accent", color="primary")
    for key, value in ov.style.model_dump().items():
        if value is not None:
            st[key] = value
    if ov.position:
        st["position"] = ov.position
    if ov.animation:
        st["animation"] = ov.animation
    st.setdefault("font", None)
    st.setdefault("spacing", 0)
    # cores: chave do tema ou hex
    if ov.role == "cta":
        st["color"] = theme.color(st.get("color") or theme.style.get("cta_text"), "#FFFFFF")
        st["box_color"] = theme.color(
            st.get("box_color") or theme.style.get("cta_box"), theme.colors["accent"]
        )
    else:
        st["color"] = theme.color(st.get("color"), "#FFFFFF")
        st["box_color"] = theme.color(st.get("box_color"), "#000000")
    st["outline_color"] = theme.color(
        st.get("outline_color") or theme.style.get("caption_outline"), "#000000"
    )
    st.setdefault("box_alpha", 0.6)
    return st


def wrap_lines(text: str, ref: fonts.FontRef, size: float, max_width: float, spacing: float = 0) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\r", "").split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for w in words[1:]:
            candidate = f"{current} {w}"
            if fonts.measure(candidate, ref, size, spacing)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = w
        lines.append(current)
    return lines


def _anchor(align: str) -> int:
    return {"left": 4, "center": 5, "right": 6}[align]


def _anim(animation: str, cx: float, cy: float, dy: float) -> tuple[str, str]:
    """(tag de posição, tags extras) para a animação pedida."""
    pos = f"\\pos({cx:.0f},{cy:.0f})"
    if animation == "fade":
        return pos, "\\fad(220,220)"
    if animation == "pop":
        return (
            pos,
            "\\fad(120,160)\\fscx82\\fscy82\\t(0,170,\\fscx104\\fscy104)\\t(170,270,\\fscx100\\fscy100)",
        )
    if animation == "slide-up":
        return f"\\move({cx:.0f},{cy + dy:.0f},{cx:.0f},{cy:.0f},0,320)", "\\fad(200,200)"
    if animation == "typewriter":
        return pos, "\\fad(0,200)"
    return pos, ""


def _typewriter(text: str, dur: float) -> str:
    chars = [c for c in text]
    n = max(len([c for c in chars if c != " "]), 1)
    per = min(5, max(2, int(dur * 100 * 0.55 / n)))  # centésimos por caractere
    out = []
    for c in chars:
        if c == " ":
            out.append(" ")
        else:
            out.append(f"{{\\k{per}}}{c}")
    return "".join(out)


def add_text_overlay(
    doc: AssDoc, canvas: Canvas, ov: TextOverlay, index: int, tone: str | None = None
) -> None:
    """`tone` = "light"/"dark" quando o texto fica sobre fundo gerado pelo tema; None sobre vídeo/foto."""
    theme = canvas.theme
    st = effective_style(ov, theme, tone)
    s = canvas.scale
    W, H, safe = canvas.width, canvas.height, canvas.safe
    ref = fonts.resolve(st["font"] or theme.font_family, st["weight"])
    size = st["size"] * s
    spacing = st["spacing"] * s
    text = ov.text.upper() if st["uppercase"] else ov.text
    max_w = W * st["max_width"] - 2 * st["box_padding"] * s
    lines = wrap_lines(text, ref, size, max_w, spacing)
    line_widths = [fonts.measure(ln, ref, size, spacing)[0] for ln in lines]
    block_w = max(line_widths) if line_widths else 0
    block_h = size * len(lines)

    secondary_size = size * 0.7
    if ov.secondary:
        sec_text = ov.secondary.upper() if st["uppercase"] else ov.secondary
        sec_ref = fonts.resolve(st["font"] or theme.font_family, "regular")
        sec_w = fonts.measure(sec_text, sec_ref, secondary_size)[0]
        block_w = max(block_w, sec_w)
        block_h += secondary_size

    start = ov.start
    end = ov.end if ov.end is not None else canvas.total
    end = min(end, canvas.total)
    if end <= start:
        return
    dur = end - start

    # posição da âncora
    align = st["align"]
    if ov.x is not None:
        cx = ov.x * W
    elif align == "left":
        cx = safe.left + canvas.px(st["box_padding"]) + canvas.px(28)
    elif align == "right":
        cx = W - safe.right - canvas.px(st["box_padding"]) - canvas.px(28)
    else:
        cx = W / 2
    if ov.y is not None:
        cy = ov.y * H
    else:
        position = st["position"]
        if position == "top":
            cy = safe.top + H * 0.10 + block_h / 2
        elif position == "bottom":
            cy = H - safe.bottom - H * 0.045 - block_h / 2
        else:
            cy = H * 0.5 + H * st.get("offset_y", 0)
    if ov.role == "subtitle" and ov.y is None and st["position"] == "center":
        cy = H * 0.5 + H * 0.075

    animation = st["animation"]
    an = _anchor(align)
    pos_tag, anim_tags = _anim(animation, cx, cy, canvas.px(60))

    style_name = f"T{index}"
    doc.add_style(
        Style(
            name=style_name,
            fontname=ref.ass_name,
            fontsize=size,
            primary=ass_color(st["color"]),
            secondary=ass_color(st["color"], 255 if animation == "typewriter" else 0),
            outline=ass_color(st["outline_color"]),
            back=ass_color("#000000", 110),
            bold=ref.bold,
            border_style=1,
            outline_w=st["outline"] * s,
            shadow=st["shadow"] * s,
            alignment=an,
            spacing=spacing,
            margin_l=10,
            margin_r=10,
            margin_v=10,
        )
    )

    layer = 10 + index * 3
    if st["box"]:
        pad = st["box_padding"] * s
        bw, bh = block_w + 2 * pad, block_h + 2 * pad
        radius = st["box_radius"] * s
        alpha = int(round(255 * (1 - st["box_alpha"])))
        # a caixa usa a mesma âncora do texto, deslocada pelo padding quando alinhada à esquerda
        if align == "left":
            box_pos, _ = _anim(animation, cx - pad, cy, canvas.px(60))
        elif align == "right":
            box_pos, _ = _anim(animation, cx + pad, cy, canvas.px(60))
        else:
            box_pos = pos_tag
        doc.add(
            Event(
                start,
                end,
                style_name,
                f"{{\\an{an}{box_pos}{anim_tags}\\1c{ass_color(st['box_color'])}\\1a{ass_alpha(alpha)}"
                f"\\bord0\\shad0\\p1}}{rounded_rect_path(bw, bh, radius)}{{\\p0}}",
                layer=layer,
            )
        )
        if ov.role == "lower-third":
            bar_w = canvas.px(9)
            accent = theme.colors["accent"]
            doc.add(
                Event(
                    start,
                    end,
                    style_name,
                    f"{{\\an{an}{box_pos}{anim_tags}\\1c{ass_color(accent)}\\bord0\\shad0\\p1}}"
                    f"{rect_path(bar_w, bh)}{{\\p0}}",
                    layer=layer + 1,
                )
            )
            if align == "left":
                pos_tag, _ = _anim(animation, cx + bar_w * 0.6, cy, canvas.px(60))

    body = escape_text("\n".join(lines))
    if animation == "typewriter":
        body = _typewriter(body, dur)
    if ov.secondary:
        sec_text = ov.secondary.upper() if st["uppercase"] else ov.secondary
        muted = theme.colors.get("mint" if ov.role != "lower-third" else "muted", "#CBD5E1")
        if ov.role == "lower-third":
            muted = theme.colors.get("accent", muted)
        body += f"\\N{{\\fs{secondary_size:.0f}\\b0\\1c{ass_color(muted)}}}{escape_text(sec_text)}"
    doc.add(Event(start, end, style_name, f"{{\\an{an}{pos_tag}{anim_tags}}}{body}", layer=layer + 2))


def default_caption_y(canvas: Canvas, size: float) -> float:
    H, safe = canvas.height, canvas.safe
    if canvas.is_vertical:
        return min(H * 0.70, H - safe.bottom - size)
    if canvas.width > canvas.height:
        return H - safe.bottom - size * 1.2
    return H * 0.82


def add_captions(
    doc: AssDoc,
    canvas: Canvas,
    cues: list[Cue],
    cs: CaptionStyle,
    tone_fn: Callable[[float, float], str | None] | None = None,
) -> None:
    """Legendas. Sobre fundo gerado pelo tema (`tone_fn` -> light/dark) o estilo muda: caixa na cor
    principal com texto branco sobre fundo claro; texto branco sem contorno sobre fundo escuro."""
    theme = canvas.theme
    s = canvas.scale
    ref = fonts.resolve(cs.font or theme.font_family, cs.weight)
    size = cs.size * s
    base_color = theme.color(cs.color, "#FFFFFF")
    highlight = theme.color(cs.highlight_color or theme.style.get("caption_highlight"), "#FACC15")
    outline_color = theme.color(cs.outline_color or theme.style.get("caption_outline"), "#000000")
    margins = dict(
        margin_l=int(canvas.safe.left + 40 * s), margin_r=int(canvas.safe.right + 40 * s), margin_v=10
    )

    def make_style(name: str, tone: str | None) -> tuple[str, str]:
        """Cria (se preciso) o estilo do tom e devolve (cor do texto, cor de destaque)."""
        if name in doc.styles:
            return doc.styles[name].primary, doc.styles[name].secondary
        boxed = cs.mode == "boxed"
        color, box_color, box_alpha = base_color, cs.box_color, cs.box_alpha
        outline_w, shadow = cs.outline * s, cs.shadow * s
        if tone == "light" and not boxed:
            boxed, color, box_color, box_alpha = True, theme.colors["white"], theme.colors["primary"], 1.0
        elif tone == "dark" and not boxed:
            color, outline_w, shadow = theme.colors["white"], 0, 0
        doc.add_style(
            Style(
                name=name,
                fontname=ref.ass_name,
                fontsize=size,
                primary=ass_color(color),
                secondary=ass_color(highlight),  # guardamos o destaque aqui só para consulta
                outline=ass_color(box_color if boxed else outline_color),
                back=ass_color(box_color, int(round(255 * (1 - box_alpha)))),
                bold=ref.bold,
                border_style=3 if boxed else 1,
                outline_w=(14 * s) if boxed else outline_w,
                shadow=0 if boxed else shadow,
                alignment=5,
                **margins,
            )
        )
        return ass_color(color), ass_color(highlight)

    y = cs.y * canvas.height if cs.y is not None else default_caption_y(canvas, size)
    pos = f"{{\\an5\\pos({canvas.width / 2:.0f},{y:.0f})}}"
    pop_on = "\\fscx105\\fscy105" if cs.pop else ""
    pop_off = "\\fscx100\\fscy100" if cs.pop else ""

    def fmt(word: str) -> str:
        return escape_text(word.upper() if cs.uppercase else word)

    for cue in cues:
        if cue.end <= cue.start:
            continue
        tone = tone_fn(cue.start, cue.end) if tone_fn else None
        style_name = {"light": "CapLight", "dark": "CapDark"}.get(tone or "", "Cap")
        color_tag, hl_tag = make_style(style_name, tone)
        hl_on = f"\\1c{hl_tag}{pop_on}"
        hl_off = f"\\1c{color_tag}{pop_off}"
        words = [w for w in cue.words if w.text.strip()]
        if cs.mode == "karaoke" and words:
            plain = " ".join(fmt(w.text) for w in words)
            first_start = max(words[0].start, cue.start)
            if first_start - cue.start > 0.05:
                doc.add(Event(cue.start, first_start, style_name, pos + plain, layer=5))
            for j, w in enumerate(words):
                t0 = max(w.start, cue.start)
                t1 = max(words[j + 1].start, t0) if j + 1 < len(words) else cue.end
                t1 = min(t1, cue.end)
                if t1 - t0 < 0.02:
                    continue
                parts = []
                for k, other in enumerate(words):
                    txt = fmt(other.text)
                    parts.append(f"{{{hl_on}}}{txt}{{{hl_off}}}" if k == j else txt)
                doc.add(Event(t0, t1, style_name, pos + " ".join(parts), layer=5))
        else:
            doc.add(Event(cue.start, cue.end, style_name, pos + fmt(cue.text), layer=5))


def add_progress_bar(doc: AssDoc, canvas: Canvas, pb: ProgressBar) -> None:
    theme = canvas.theme
    color = theme.color(pb.color or "accent", theme.colors["accent"])
    h = canvas.px(pb.height)
    W, H = canvas.width, canvas.height
    y = 0 if pb.position == "top" else H - h
    doc.add_style(Style(name="Bar", fontsize=20, border_style=1, outline_w=0, shadow=0, alignment=7))
    track_alpha = int(round(255 * (1 - pb.track_alpha)))
    total_ms = int(canvas.total * 1000)
    doc.add(
        Event(
            0,
            canvas.total,
            "Bar",
            f"{{\\an7\\pos(0,{y:.0f})\\1c{ass_color(color)}\\1a{ass_alpha(track_alpha)}\\bord0\\shad0\\p1}}"
            f"{rect_path(W, h)}{{\\p0}}",
            layer=90,
        )
    )
    doc.add(
        Event(
            0,
            canvas.total,
            "Bar",
            f"{{\\an7\\pos(0,{y:.0f})\\1c{ass_color(color)}\\bord0\\shad0\\fscx0\\t(0,{total_ms},\\fscx100)\\p1}}"
            f"{rect_path(W, h)}{{\\p0}}",
            layer=91,
        )
    )


def add_guides(doc: AssDoc, canvas: Canvas) -> None:
    """Zonas seguras em vermelho translúcido, para conferir posicionamento."""
    W, H, safe = canvas.width, canvas.height, canvas.safe
    doc.add_style(
        Style(
            name="Guide",
            fontname="Arial",
            fontsize=canvas.px(26),
            border_style=1,
            outline_w=0,
            shadow=0,
            alignment=7,
            primary=ass_color("#FFFFFF"),
        )
    )
    boxes = [
        (0, 0, W, safe.top),
        (0, H - safe.bottom, W, safe.bottom),
        (0, safe.top, safe.left, H - safe.top - safe.bottom),
        (W - safe.right, safe.top, safe.right, H - safe.top - safe.bottom),
    ]
    for x, y, w, h in boxes:
        if w <= 0 or h <= 0:
            continue
        doc.add(
            Event(
                0,
                canvas.total,
                "Guide",
                f"{{\\an7\\pos({x},{y})\\1c{ass_color('#FF2D55')}\\1a{ass_alpha(170)}\\bord0\\shad0\\p1}}"
                f"{rect_path(w, h)}{{\\p0}}",
                layer=100,
            )
        )
    doc.add(
        Event(
            0,
            canvas.total,
            "Guide",
            f"{{\\an7\\pos(12,12)}}zonas cobertas pela interface: {W}x{H}",
            layer=101,
        )
    )
