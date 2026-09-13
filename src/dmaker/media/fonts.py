"""Resolução de fontes: arquivos em assets/fonts (Poppins) com fallback para fontes do Windows.

libass identifica a fonte pelo nome de família gravado no TTF. Para pesos que não são
"regular/bold" (Medium, Light...), o nome de família do arquivo é "Poppins Medium" etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from ..config import FONTS_DIR, WINDOWS_FONTS_DIR

# família -> peso -> (arquivo, nome de família que o libass enxerga, flag bold)
FAMILIES: dict[str, dict[str, tuple[str, str, bool]]] = {
    "Poppins": {
        "light": ("Poppins-Light.ttf", "Poppins Light", False),
        "regular": ("Poppins-Regular.ttf", "Poppins", False),
        "italic": ("Poppins-Italic.ttf", "Poppins", False),
        "medium": ("Poppins-Medium.ttf", "Poppins Medium", False),
        "semibold": ("Poppins-SemiBold.ttf", "Poppins SemiBold", False),
        "bold": ("Poppins-Bold.ttf", "Poppins", True),
        "extrabold": ("Poppins-ExtraBold.ttf", "Poppins ExtraBold", False),
    },
    "Arial": {
        "light": ("arial.ttf", "Arial", False),
        "regular": ("arial.ttf", "Arial", False),
        "italic": ("ariali.ttf", "Arial", False),
        "medium": ("arial.ttf", "Arial", False),
        "semibold": ("arialbd.ttf", "Arial", True),
        "bold": ("arialbd.ttf", "Arial", True),
        "extrabold": ("arialbd.ttf", "Arial", True),
    },
    "Bahnschrift": {
        "light": ("bahnschrift.ttf", "Bahnschrift", False),
        "regular": ("bahnschrift.ttf", "Bahnschrift", False),
        "italic": ("bahnschrift.ttf", "Bahnschrift", False),
        "medium": ("bahnschrift.ttf", "Bahnschrift", False),
        "semibold": ("bahnschrift.ttf", "Bahnschrift", True),
        "bold": ("bahnschrift.ttf", "Bahnschrift", True),
        "extrabold": ("bahnschrift.ttf", "Bahnschrift", True),
    },
}

FALLBACK_ORDER = ["Poppins", "Bahnschrift", "Arial"]


@dataclass(frozen=True)
class FontRef:
    family: str  # família efetivamente usada (ex.: Poppins)
    weight: str
    file: Path
    ass_name: str  # Fontname para o estilo ASS
    bold: bool


def _find_file(filename: str) -> Path | None:
    for d in (FONTS_DIR, WINDOWS_FONTS_DIR):
        p = d / filename
        if p.exists():
            return p
    return None


def family_available(family: str) -> bool:
    table = FAMILIES.get(family)
    if not table:
        return False
    return _find_file(table["regular"][0]) is not None


@lru_cache(maxsize=64)
def resolve(family: str, weight: str = "regular") -> FontRef:
    """Devolve a fonte pedida ou a primeira disponível na ordem de fallback."""
    weight = weight.lower()
    order = [family] + [f for f in FALLBACK_ORDER if f != family]
    for fam in order:
        table = FAMILIES.get(fam)
        if not table:
            continue
        entry = table.get(weight) or table["regular"]
        file = _find_file(entry[0])
        if file:
            return FontRef(fam, weight, file, entry[1], entry[2])
    raise FileNotFoundError("Nenhuma fonte encontrada (nem Poppins em assets/fonts nem Arial do Windows).")


@lru_cache(maxsize=64)
def _cell_ratio(file: str) -> float:
    """(ascent+descent)/tamanho: o libass trata Fontsize como altura da célula, não como corpo (em)."""
    f = ImageFont.truetype(file, 100)
    asc, desc = f.getmetrics()
    return (asc + desc) / 100.0


def em_px(ref: FontRef, ass_size: float) -> float:
    """Corpo (em) em pixels equivalente a um Fontsize ASS, para medir texto com Pillow."""
    return ass_size / _cell_ratio(str(ref.file))


def pil_font(ref: FontRef, ass_size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ref.file), max(1, int(round(em_px(ref, ass_size)))))


def measure(text: str, ref: FontRef, ass_size: float, spacing: float = 0) -> tuple[float, float]:
    """Largura e altura (célula) do texto como o libass renderiza, em px."""
    font = pil_font(ref, ass_size)
    width = font.getlength(text) + spacing * max(len(text) - 1, 0)
    return width, ass_size


def fontsdir() -> Path:
    return FONTS_DIR
