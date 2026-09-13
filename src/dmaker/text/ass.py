"""Construtor de arquivos ASS (Advanced SubStation Alpha) para o libass.

Usamos ASS para tudo que é texto no vídeo: títulos, ganchos, CTA, legendas com
destaque palavra a palavra e até a barra de progresso (desenho vetorial).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.brand import normalize_hex


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR& (alpha 0 = opaco, 255 = transparente)."""
    h = normalize_hex(hex_color)[1:]
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}"


def ass_alpha(alpha: int) -> str:
    return f"&H{max(0, min(255, alpha)):02X}&"


def escape_text(text: str) -> str:
    """Remove o que o parser ASS interpretaria como tag e converte quebras de linha."""
    text = text.replace("\r", "")
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("\\", "/")
    return text.replace("\n", "\\N")


@dataclass
class Style:
    name: str
    fontname: str = "Arial"
    fontsize: float = 48
    primary: str = "&H00FFFFFF"
    secondary: str = "&H00FFFFFF"
    outline: str = "&H00000000"
    back: str = "&H80000000"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    scale_x: float = 100
    scale_y: float = 100
    spacing: float = 0
    angle: float = 0
    border_style: int = 1  # 1 = contorno+sombra, 3 = caixa opaca
    outline_w: float = 2
    shadow: float = 0
    alignment: int = 5  # numpad: 1..9
    margin_l: int = 20
    margin_r: int = 20
    margin_v: int = 20
    encoding: int = 1

    def line(self) -> str:
        b = lambda v: -1 if v else 0  # noqa: E731
        fields = [
            self.name,
            self.fontname,
            f"{self.fontsize:g}",
            self.primary,
            self.secondary,
            self.outline,
            self.back,
            b(self.bold),
            b(self.italic),
            b(self.underline),
            b(self.strikeout),
            f"{self.scale_x:g}",
            f"{self.scale_y:g}",
            f"{self.spacing:g}",
            f"{self.angle:g}",
            self.border_style,
            f"{self.outline_w:g}",
            f"{self.shadow:g}",
            self.alignment,
            self.margin_l,
            self.margin_r,
            self.margin_v,
            self.encoding,
        ]
        return "Style: " + ",".join(str(f) for f in fields)


@dataclass
class Event:
    start: float
    end: float
    style: str
    text: str
    layer: int = 0
    name: str = ""
    margin_l: int = 0
    margin_r: int = 0
    margin_v: int = 0
    effect: str = ""

    def line(self) -> str:
        return (
            f"Dialogue: {self.layer},{ass_time(self.start)},{ass_time(self.end)},{self.style},{self.name},"
            f"{self.margin_l},{self.margin_r},{self.margin_v},{self.effect},{self.text}"
        )


@dataclass
class AssDoc:
    width: int
    height: int
    title: str = "DMaker"
    styles: dict[str, Style] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def add_style(self, style: Style) -> Style:
        self.styles[style.name] = style
        return style

    def add(self, event: Event) -> Event:
        if event.end > event.start:
            self.events.append(event)
        return event

    def render(self) -> str:
        header = [
            "[Script Info]",
            f"Title: {self.title}",
            "ScriptType: v4.00+",
            f"PlayResX: {self.width}",
            f"PlayResY: {self.height}",
            f"LayoutResX: {self.width}",
            f"LayoutResY: {self.height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
        ]
        header += [s.line() for s in self.styles.values()]
        header += [
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        events = sorted(self.events, key=lambda e: (e.layer, e.start))
        header += [e.line() for e in events]
        return "\n".join(header) + "\n"

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8-sig")
        return path


# ---------- desenhos vetoriais (\p1) ----------


def rect_path(w: float, h: float) -> str:
    return f"m 0 0 l {w:.1f} 0 l {w:.1f} {h:.1f} l 0 {h:.1f}"


def rounded_rect_path(w: float, h: float, r: float) -> str:
    """Retângulo com cantos arredondados usando curvas de Bézier (comando b)."""
    r = max(0.0, min(r, w / 2, h / 2))
    if r <= 0.5:
        return rect_path(w, h)
    k = 0.5523 * r  # aproximação de quarto de círculo
    f = lambda v: f"{v:.1f}"  # noqa: E731
    return " ".join(
        [
            f"m {f(r)} 0",
            f"l {f(w - r)} 0",
            f"b {f(w - r + k)} 0 {f(w)} {f(r - k)} {f(w)} {f(r)}",
            f"l {f(w)} {f(h - r)}",
            f"b {f(w)} {f(h - r + k)} {f(w - r + k)} {f(h)} {f(w - r)} {f(h)}",
            f"l {f(r)} {f(h)}",
            f"b {f(r - k)} {f(h)} 0 {f(h - r + k)} 0 {f(h - r)}",
            f"l 0 {f(r)}",
            f"b 0 {f(r - k)} {f(r - k)} 0 {f(r)} 0",
        ]
    )
