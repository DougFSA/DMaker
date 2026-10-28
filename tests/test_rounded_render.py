"""A caixa arredondada abraça o texto no render real (libass): a medida do código tem que bater com o que
o libass desenha, em 1080x1920 e no tamanho do preview. Pula se o ffmpeg não estiver instalado."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaker.config import FONTS_DIR
from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import CaptionStyle, TextOverlay
from dmaker.filtergraph.common import ffq
from dmaker.media import ffmpeg
from dmaker.text.ass import AssDoc
from dmaker.text.captions import Cue, Word
from dmaker.text.overlays import Canvas, add_captions, add_text_overlay

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

BACKGROUND = (74, 111, 165)  # azul liso: nada do que é desenhado se confunde com ele


def _canvas(preview: bool) -> Canvas:
    preset = get_preset("instagram/reels")
    if preview:
        preset = preset.preview()
    return Canvas(preset.width, preset.height, preset.safe, load_theme("default"), total=6.0)


def _frame(doc: AssDoc, tmp_path: Path, at: float) -> np.ndarray:
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
            str(at),
            "-frames:v",
            "1",
            str(png),
        ],
        quiet=True,
    )
    return np.array(Image.open(png).convert("RGB")).astype(int)


def _mask(frame: np.ndarray, color: tuple[int, int, int], tolerance: int = 24) -> np.ndarray:
    return np.abs(frame - np.array(color)).sum(axis=2) <= tolerance


def _extent(mask: np.ndarray, top: int, bottom: int) -> tuple[int, int]:
    """Primeira e última coluna marcadas entre as linhas `top` e `bottom`."""
    columns = np.where(mask[top:bottom].any(axis=0))[0]
    return int(columns.min()), int(columns.max())


@pytest.mark.parametrize("preview", [False, True], ids=["1080x1920", "preview 540x960"])
def test_rounded_caption_box_hugs_each_line_in_the_real_render(tmp_path, preview):
    canvas = _canvas(preview)
    scale = canvas.scale
    words = "agenda inteligente para clinica pequena e rapida".split()
    cue = Cue(0.0, 4.0, " ".join(words), [Word(i * 0.5, (i + 1) * 0.5, w) for i, w in enumerate(words)])
    style = CaptionStyle(
        mode="rounded",
        color="#FFFFFF",
        highlight_color="#FFFF00",
        box_color="#000000",
        box_alpha=1.0,
        max_words=8,
        max_chars=60,
        y=0.7,
    )
    doc = AssDoc(canvas.width, canvas.height)
    add_captions(doc, canvas, [cue], style)
    frame = _frame(doc, tmp_path, at=1.75)  # no meio de "clinica", a quarta palavra

    black = _mask(frame, (0, 0, 0), 30)
    white, yellow = _mask(frame, (255, 255, 255), 60), _mask(frame, (255, 255, 0), 60)
    ink = white | yellow
    rows = np.where(black.any(axis=1))[0]
    top, bottom = int(rows.min()), int(rows.max()) + 1
    line = 72 * scale
    assert (bottom - top) == pytest.approx(2 * line, abs=2)  # duas linhas de caixa, uma por linha de texto
    assert (top + bottom) / 2 == pytest.approx(0.7 * canvas.height, abs=2)

    padding = canvas.theme.rounded_box_padding * scale
    widths = []
    for index in range(2):
        # só o miolo da linha: perto das emendas a concordância côncava alarga a caixa de propósito
        middle = top + (index + 0.5) * line
        low, high = round(middle - 3 * scale), round(middle + 3 * scale)
        box_left, box_right = _extent(black | ink, low, high)
        ink_left, ink_right = _extent(ink, low, high)
        widths.append(box_right - box_left)
        # margem igual dos dois lados (a diferença é só o respiro natural das letras) e a da marca
        assert (ink_left - box_left) == pytest.approx(padding, abs=5 * scale)
        assert (box_right - ink_right) == pytest.approx(padding, abs=5 * scale)
        assert (ink_left - box_left) == pytest.approx(box_right - ink_right, abs=3 * scale)
        # e as duas linhas ficam centradas no mesmo eixo do quadro
        assert (box_left + box_right) / 2 == pytest.approx(canvas.width / 2, abs=2)
    assert widths[0] > widths[1] + 20 * scale  # linhas de larguras diferentes, cada uma com a sua caixa

    # o destaque da palavra ativa está por cima da caixa, dentro dela
    yellow_columns = np.where(yellow.any(axis=0))[0]
    assert len(yellow_columns) > 40 * scale
    assert yellow[:top].sum() == 0 and yellow[bottom:].sum() == 0
    covered = black | yellow
    assert covered[top:bottom, yellow_columns.min() : yellow_columns.max() + 1].any()


def test_rounded_title_box_hugs_each_line_in_the_real_render(tmp_path):
    canvas = _canvas(False)
    doc = AssDoc(canvas.width, canvas.height)
    overlay = TextOverlay(
        text="Sua agenda em um clique, sem complicacao",
        role="title",
        start=0,
        end=5,
        animation="none",
        y=0.3,
        style={"box_shape": "rounded", "box_color": "#000000", "box_alpha": 1.0, "color": "#FFFFFF"},
    )
    add_text_overlay(doc, canvas, overlay, 0)
    frame = _frame(doc, tmp_path, at=1.0)
    black = _mask(frame, (0, 0, 0), 30)
    ink = _mask(frame, (255, 255, 255), 60)
    rows = np.where(black.any(axis=1))[0]
    top, bottom = int(rows.min()), int(rows.max()) + 1
    assert (bottom - top) == pytest.approx(2 * 80, abs=2)  # o título quebra em duas linhas de 80 px
    assert (top + bottom) / 2 == pytest.approx(0.3 * canvas.height, abs=2)
    padding = canvas.theme.rounded_box_padding
    for index in range(2):
        middle = top + (index + 0.5) * 80
        low, high = round(middle - 3), round(middle + 3)
        box_left, box_right = _extent(black | ink, low, high)
        ink_left, ink_right = _extent(ink, low, high)
        assert (ink_left - box_left) == pytest.approx(padding, abs=6)
        assert (box_right - ink_right) == pytest.approx(padding, abs=6)
        assert (box_left + box_right) / 2 == pytest.approx(canvas.width / 2, abs=2)
