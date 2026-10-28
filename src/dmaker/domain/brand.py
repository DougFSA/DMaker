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
    "card_layouts": {},
}


# Caixa arredondada por linha (legendas `rounded` e textos com `box_shape: rounded`), px na base 1080. O raio
# acompanha a altura de uma linha de legenda sem virar pílula; a margem dá folga lateral ao texto.
DEFAULT_ROUNDED_BOX_RADIUS = 28.0
DEFAULT_ROUNDED_BOX_PADDING = 28.0


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
    card_layouts: dict[str, dict] = field(default_factory=dict)
    base_dir: Path | None = None  # pasta da marca, para resolver fundos, imagens e fontes de layout
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

    def _rounded_box_metric(self, key: str, default: float) -> float:
        value = self.style.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ValueError(f"{key} da marca precisa ser um número maior ou igual a zero, veio {value!r}")
        return float(value)

    @property
    def rounded_box_radius(self) -> float:
        """Raio dos cantos da caixa arredondada, em px na base 1080 (`style.rounded_box_radius` da marca)."""
        return self._rounded_box_metric("rounded_box_radius", DEFAULT_ROUNDED_BOX_RADIUS)

    @property
    def rounded_box_padding(self) -> float:
        """Margem lateral entre o texto e a borda da caixa arredondada (`style.rounded_box_padding`)."""
        return self._rounded_box_metric("rounded_box_padding", DEFAULT_ROUNDED_BOX_PADDING)

    def resolve_asset(self, rel: str | Path) -> Path:
        """Caminho de um arquivo da marca (fundo ou imagem de um layout de cartão); absoluto passa direto."""
        p = Path(rel)
        if p.is_absolute():
            return p
        if self.base_dir is None:
            raise FileNotFoundError(f"caminho relativo {str(rel)!r} sem pasta de marca para resolver")
        return self.base_dir / p


def _from_dict(data: dict, base: Path | None, key: str) -> Theme:
    merged = json.loads(json.dumps(DEFAULT_THEME))
    for section in ("colors", "fonts", "rules", "cta", "style", "captions", "card_layouts"):
        merged[section].update(data.get(section, {}))
    merged["name"] = data.get("name", merged["name"])
    logos = {}
    for k, v in data.get("logos", {}).items():
        p = Path(v)
        if not p.is_absolute() and base is not None:
            p = base / p
        logos[k] = p
    # arquivo .ttf por papel de fonte (script, date, serif...): caminho candidato na pasta da marca;
    # media.fonts.resolve_file cai para as fontes do Windows se não existir ali
    font_files = {}
    for role, filename in data.get("fonts", {}).get("files", {}).items():
        p = Path(filename)
        if not p.is_absolute() and base is not None:
            p = base / "fonts" / p
        font_files[role] = p
    merged["fonts"]["files"] = font_files
    return Theme(
        name=merged["name"],
        colors={k: normalize_hex(v) for k, v in merged["colors"].items()},
        fonts=merged["fonts"],
        logos=logos,
        rules=merged["rules"],
        cta=merged["cta"],
        style=merged["style"],
        captions=merged["captions"],
        card_layouts=merged["card_layouts"],
        base_dir=base,
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
