"""A caixa comum (`box`) abraça o texto no render real (libass) com a margem configurada, igual dos dois lados.

Antes a caixa era medida com a célula do Pillow e sobrava uns 77 px de cada lado (DMK-45). Pula se o ffmpeg
não estiver instalado.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaker.config import FONTS_DIR
from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import TextOverlay
from dmaker.filtergraph.common import ffq
from dmaker.media import ffmpeg
from dmaker.text.ass import AssDoc
from dmaker.text.overlays import Canvas, add_text_overlay, effective_style

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

# preto e branco, sem confusão com o fundo azul
BOX = {"box_color": "#000000", "box_alpha": 1.0, "color": "#FFFFFF"}


def _canvas(preview: bool) -> Canvas:
    preset = get_preset("instagram/reels")
    if preview:
        preset = preset.preview()
    return Canvas(preset.width, preset.height, preset.safe, load_theme("default"), total=6.0)


def _frame(doc: AssDoc, tmp_path: Path) -> np.ndarray:
    ass = doc.write(tmp_path / "quadro.ass")
    png = tmp_path / "quadro.png"
    ffmpeg.run(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x4a6fa5:s={doc.width}x{doc.height}:d=6,format=yuv420p",
            "-vf",
            f"ass=filename={ffq(ass)}:fontsdir={ffq(FONTS_DIR)}",
            "-ss",
            "1.0",
            "-frames:v",
            "1",
            str(png),
        ],
        quiet=True,
    )
    return np.array(Image.open(png).convert("RGB")).astype(int)


def _mask(frame: np.ndarray, color: tuple[int, int, int], tolerance: int) -> np.ndarray:
    return np.abs(frame - np.array(color)).sum(axis=2) <= tolerance


def _extent(mask: np.ndarray) -> tuple[int, int]:
    columns = np.where(mask.any(axis=0))[0]
    return int(columns.min()), int(columns.max()) + 1


def _rows(mask: np.ndarray) -> tuple[int, int]:
    rows = np.where(mask.any(axis=1))[0]
    return int(rows.min()), int(rows.max()) + 1


@pytest.mark.parametrize("preview", [False, True], ids=["1080x1920", "preview 540x960"])
@pytest.mark.parametrize(
    ("role", "text", "lines"),
    [
        ("cta", "medlycare.com.br", 1),
        ("cta", "Sua agenda em um clique com muito texto para quebrar linhas", 2),
        ("title", "Fale com a gente pelo WhatsApp hoje", 1),
    ],
    ids=["cta curto", "cta em duas linhas", "titulo de uma linha justa"],
)
def test_block_box_margin_is_the_configured_one_on_both_sides(tmp_path, preview, role, text, lines):
    canvas = _canvas(preview)
    scale = canvas.scale
    overlay = TextOverlay(
        text=text, role=role, start=0, end=5, animation="none", y=0.5, style={"box": True, **BOX}
    )
    doc = AssDoc(canvas.width, canvas.height)
    add_text_overlay(doc, canvas, overlay, 0)
    frame = _frame(doc, tmp_path)

    box = _mask(frame, (0, 0, 0), 30)
    ink = _mask(frame, (255, 255, 255), 60)
    box_left, box_right = _extent(box | ink)
    ink_left, ink_right = _extent(ink)
    top, bottom = _rows(box)
    padding = effective_style(overlay, canvas.theme, None)["box_padding"] * scale

    # a margem é a da configuração (o respiro natural das letras soma uns 1 a 5 px) e igual dos dois lados
    assert (ink_left - box_left) == pytest.approx(padding, abs=5 * scale)
    assert (box_right - ink_right) == pytest.approx(padding, abs=5 * scale)
    assert (ink_left - box_left) == pytest.approx(box_right - ink_right, abs=3 * scale)
    assert (box_left + box_right) / 2 == pytest.approx(canvas.width / 2, abs=2)
    # e a quebra é a da largura real: o título justo fica em uma linha, o CTA longo em duas
    size = effective_style(overlay, canvas.theme, None)["size"] * scale
    assert (bottom - top) == pytest.approx(lines * size + 2 * padding, abs=2)
