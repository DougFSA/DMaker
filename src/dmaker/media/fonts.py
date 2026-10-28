"""Resolução de fontes: arquivos em assets/fonts (Poppins) com fallback para fontes do Windows.

libass identifica a fonte pelo nome de família gravado no TTF. Para pesos que não são
"regular/bold" (Medium, Light...), o nome de família do arquivo é "Poppins Medium" etc.
"""

from __future__ import annotations

import struct
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


# Corpo de referência para medir: em corpos pequenos o FreeType arredonda cada avanço para pixel inteiro
# (hinting) e a soma sai até 4% maior do que o libass desenha; medir grande e escalar elimina isso.
_REFERENCE_EM = 2000


def _sfnt_table(file: Path, tag: bytes) -> bytes | None:
    """Bytes de uma tabela do TrueType/OpenType (cabeçalho sfnt), ou None se não existir ou não for sfnt."""
    with file.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            return None
        (table_count,) = struct.unpack(">H", header[4:6])
        directory = handle.read(16 * table_count)
        for index in range(table_count):
            entry_tag, _checksum, offset, length = struct.unpack(
                ">4sIII", directory[16 * index : 16 * index + 16]
            )
            if entry_tag == tag:
                handle.seek(offset)
                return handle.read(length)
    return None


@lru_cache(maxsize=64)
def _libass_cell_ratio(file: str) -> float:
    """(winAscent+winDescent)/unitsPerEm: o libass dimensiona o Fontsize pela célula do OS/2, como o VSFilter.

    Na Poppins isso dá 1,76 (a hhea que o Pillow expõe dá 1,40), então o corpo real é 20% menor do que
    `em_px` supõe e a largura que `measure` devolve sai 26% maior que a desenhada. Sem a tabela OS/2 o
    libass cai na hhea, e nós também.
    """
    try:
        os2 = _sfnt_table(Path(file), b"OS/2")
        head = _sfnt_table(Path(file), b"head")
        if os2 is not None and head is not None and len(os2) >= 78 and len(head) >= 20:
            (units_per_em,) = struct.unpack(">H", head[18:20])
            win_ascent, win_descent = struct.unpack(">HH", os2[74:78])
            if units_per_em and win_ascent + win_descent:
                return (win_ascent + win_descent) / units_per_em
    except (OSError, struct.error):
        pass
    return _cell_ratio(file)


@lru_cache(maxsize=64)
def _reference_font(file: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(file, _REFERENCE_EM)


def measure_rendered(text: str, ref: FontRef, ass_size: float, spacing: float = 0) -> tuple[float, float]:
    """Largura e altura (célula) do texto exatamente como o libass o desenha, em px.

    Serve para desenhar uma caixa que abraça o texto: `measure` supõe uma célula menor do que a do libass
    e superestima a largura da Poppins em cerca de 26%. O espaçamento entra a cada caractere, como no libass.
    """
    em = ass_size / _libass_cell_ratio(str(ref.file))
    width = _reference_font(str(ref.file)).getlength(text) * em / _REFERENCE_EM + spacing * len(text)
    return width, ass_size


def fontsdir() -> Path:
    return FONTS_DIR


def resolve_file(theme_font_files: dict[str, Path], role: str) -> Path:
    """Arquivo .ttf de um papel de fonte de layout de cartão da marca (script, date, serif...).

    `theme_font_files` é `theme.fonts["files"]`: papel -> caminho candidato dentro da pasta da marca
    (`assets/brands/<marca>/fonts/<arquivo>`). Quando o arquivo não está na marca (ex.: uma fonte do
    sistema como Georgia), cai para a mesma fonte em `C:\\Windows\\Fonts` pelo nome do arquivo.
    """
    candidate = theme_font_files.get(role)
    if candidate is None:
        raise FileNotFoundError(f"Papel de fonte desconhecido na marca: {role!r}")
    if candidate.exists():
        return candidate
    fallback = WINDOWS_FONTS_DIR / candidate.name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Fonte não encontrada para o papel {role!r}: nem {candidate} nem {fallback}")
