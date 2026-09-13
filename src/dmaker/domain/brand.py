"""Temas de marca: cores, fonte, logos e regras de texto."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import BRANDS_DIR

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")

DEFAULT_THEME = {
    "name": "Padrão",
    "colors": {
        "primary": "#111827",
        "accent": "#FACC15",
        "icon": "#FACC15",
        "mint": "#FDE68A",
        "text": "#FFFFFF",
        "muted": "#CBD5E1",
        "white": "#FFFFFF",
        "bg": "#0B1220",
        "bg_dark": "#0B1220",
    },
    "fonts": {
        "family": "Poppins",
        "title": "bold",
        "body": "regular",
        "highlight": "medium",
        "light": "light",
    },
    "logos": {},
    "rules": {"no_dash": False},
    "cta": {"url": "", "text": ""},
    "captions": {"vocabulary": [], "replacements": {}},
    "style": {
        "caption_highlight": "accent",
        "caption_outline": "#000000",
        "cta_box": "accent",
        "cta_text": "primary",
        "card_variant": "dark",
    },
}


def normalize_hex(value: str) -> str:
    m = HEX_RE.match(value.strip())
    if not m:
        raise ValueError(f"Cor inválida: {value!r} (use #RRGGBB)")
    return "#" + m.group(1).upper()


@dataclass
class Theme:
    name: str
    colors: dict[str, str]
    fonts: dict[str, str]
    logos: dict[str, Path] = field(default_factory=dict)
    rules: dict = field(default_factory=dict)
    cta: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    captions: dict = field(default_factory=dict)
    key: str = "default"

    @property
    def font_family(self) -> str:
        return self.fonts.get("family", "Poppins")

    def weight(self, role: str) -> str:
        return self.fonts.get(role, "regular")

    def color(self, key_or_hex: str | None, default: str = "#FFFFFF") -> str:
        """Aceita chave do tema ("accent") ou hex direto ("#75B9A2")."""
        if not key_or_hex:
            return normalize_hex(default)
        if key_or_hex.startswith("#"):
            return normalize_hex(key_or_hex)
        if key_or_hex in self.colors:
            return normalize_hex(self.colors[key_or_hex])
        return normalize_hex(default)

    def style_color(self, style_key: str, default: str) -> str:
        return self.color(self.style.get(style_key), default)

    def logo(self, kind: str = "horizontal") -> Path | None:
        p = self.logos.get(kind)
        return p if p and p.exists() else None

    @property
    def no_dash(self) -> bool:
        return bool(self.rules.get("no_dash"))


def _from_dict(data: dict, base: Path | None, key: str) -> Theme:
    merged = json.loads(json.dumps(DEFAULT_THEME))
    for section in ("colors", "fonts", "rules", "cta", "style", "captions"):
        merged[section].update(data.get(section, {}))
    merged["name"] = data.get("name", merged["name"])
    logos = {}
    for k, v in data.get("logos", {}).items():
        p = Path(v)
        if not p.is_absolute() and base is not None:
            p = base / p
        logos[k] = p
    return Theme(
        name=merged["name"],
        colors={k: normalize_hex(v) for k, v in merged["colors"].items()},
        fonts=merged["fonts"],
        logos=logos,
        rules=merged["rules"],
        cta=merged["cta"],
        style=merged["style"],
        captions=merged["captions"],
        key=key,
    )


def available_brands() -> list[str]:
    names = ["default"]
    if BRANDS_DIR.exists():
        names += sorted(p.name for p in BRANDS_DIR.iterdir() if (p / "brand.json").exists())
    return names


def load_theme(name: str | None = None, overrides: dict | None = None) -> Theme:
    """`name` pode ser None/"default", o nome de uma pasta em assets/brands, ou um caminho para brand.json."""
    if not name or name == "default":
        theme = _from_dict({}, None, "default")
    else:
        p = Path(name)
        if p.suffix == ".json" and p.exists():
            theme = _from_dict(json.loads(p.read_text(encoding="utf-8")), p.parent, p.stem)
        else:
            folder = BRANDS_DIR / name
            spec = folder / "brand.json"
            if not spec.exists():
                raise FileNotFoundError(
                    f"Marca desconhecida: {name!r}. Disponíveis: {', '.join(available_brands())}"
                )
            theme = _from_dict(json.loads(spec.read_text(encoding="utf-8")), folder, name)
    if overrides:
        for section in ("colors", "fonts", "rules", "cta", "style", "captions"):
            if section in overrides:
                getattr(theme, section).update(overrides[section])
        theme.colors = {k: normalize_hex(v) for k, v in theme.colors.items()}
    return theme
