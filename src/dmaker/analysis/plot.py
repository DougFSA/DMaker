"""O gráfico do espectro como imagem, desenhado com o Pillow por uma função pura: dados em, imagem fora.

Não toca disco nem decide onde a imagem vai parar: quem exporta (o serviço de análise) grava o PNG. O gráfico tem a
grade de frequência e de dB, o eixo linear ou logarítmico e a curva; é o mesmo desenho, em miniatura, que a interface
faz em SVG com o cursor de frequência.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = "#ffffff"
PLOT_BACKGROUND = "#f6f8fb"
GRID = "#d6dbe3"
AXIS_TEXT = "#374151"
CURVE = "#1f6feb"

# Os pontos de grade do eixo logarítmico: a sequência 1-2-5 de 20 Hz a 20 kHz, a que o ouvido está acostumado.
LOG_TICKS = (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)
MIN_LOG_HZ = 20.0  # abaixo disso não há som audível, e o logaritmo de 0 Hz (o DC) não existe

MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 62, 18, 30, 44
DEFAULT_DB_SPAN = 100.0  # quantos dB o eixo vertical mostra, a partir do pico arredondado para cima


def hz_label(frequency: float) -> str:
    """5000 -> "5k", 440 -> "440": o rótulo curto de uma frequência na grade."""
    if frequency >= 1000:
        thousands = frequency / 1000
        return f"{thousands:g}k"
    return f"{frequency:g}"


def frequency_range(frequencies: Sequence[float], axis: str) -> tuple[float, float]:
    """O trecho de frequência que o eixo mostra: no linear de 0 ao Nyquist, no logarítmico de 20 Hz ao Nyquist."""
    top = max(float(frequencies[-1]), MIN_LOG_HZ * 2) if frequencies else 20000.0
    return (MIN_LOG_HZ, top) if axis == "log" else (0.0, top)


def db_range(levels: Sequence[float], span: float = DEFAULT_DB_SPAN) -> tuple[float, float]:
    """O trecho de dB que o eixo vertical mostra: `span` dB abaixo do pico, com o topo arredondado para a dezena."""
    peak = max(levels) if len(levels) else 0.0
    top = min(math.ceil(peak / 10.0) * 10.0, 20.0)
    return top - span, top


def spectrum_image(
    frequencies: Sequence[float],
    levels_db: Sequence[float],
    *,
    axis: str = "log",
    width: int = 900,
    height: int = 420,
    span_db: float = DEFAULT_DB_SPAN,
    title: str = "",
) -> Image.Image:
    """A curva (frequência × dB) num gráfico com grade e rótulos. `axis` é `log` ou `linear`."""
    if len(frequencies) != len(levels_db):
        raise ValueError("frequencies e levels_db precisam ter o mesmo tamanho")
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=12)
    left, top = MARGIN_LEFT, MARGIN_TOP
    right, bottom = width - MARGIN_RIGHT, height - MARGIN_BOTTOM
    draw.rectangle((left, top, right, bottom), fill=PLOT_BACKGROUND)

    low_hz, high_hz = frequency_range(frequencies, axis)
    low_db, high_db = db_range(levels_db, span_db)

    def x_of(frequency: float) -> float:
        if axis == "log":
            position = (math.log10(max(frequency, low_hz)) - math.log10(low_hz)) / (
                math.log10(high_hz) - math.log10(low_hz)
            )
        else:
            position = (frequency - low_hz) / (high_hz - low_hz)
        return left + position * (right - left)

    def y_of(level: float) -> float:
        clamped = min(max(level, low_db), high_db)
        return bottom - (clamped - low_db) / (high_db - low_db) * (bottom - top)

    ticks = [t for t in LOG_TICKS if low_hz <= t <= high_hz] if axis == "log" else _linear_ticks(high_hz)
    for tick in ticks:
        x = x_of(tick)
        draw.line((x, top, x, bottom), fill=GRID)
        draw.text((x, bottom + 6), hz_label(tick), fill=AXIS_TEXT, font=font, anchor="mt")
    level = math.ceil(low_db / 10.0) * 10.0
    while level <= high_db:
        y = y_of(level)
        draw.line((left, y, right, y), fill=GRID)
        draw.text((left - 6, y), f"{level:g}", fill=AXIS_TEXT, font=font, anchor="rm")
        level += 10.0
    draw.text(((left + right) / 2, height - 6), "Frequência (Hz)", fill=AXIS_TEXT, font=font, anchor="ms")
    draw.text((6, (top + bottom) / 2), "dB", fill=AXIS_TEXT, font=font, anchor="lm")
    if title:
        draw.text((left, 8), title, fill=AXIS_TEXT, font=font, anchor="lt")

    points = [
        (x_of(frequency), y_of(level))
        for frequency, level in zip(frequencies, levels_db, strict=True)
        if low_hz <= frequency <= high_hz
    ]
    if len(points) >= 2:
        draw.line(points, fill=CURVE, width=2, joint="curve")
    draw.rectangle((left, top, right, bottom), outline=GRID)
    return image


def _linear_ticks(high_hz: float) -> list[float]:
    """Cinco pontos de grade igualmente espaçados do eixo linear, em números redondos."""
    step = 10 ** math.floor(math.log10(high_hz / 5)) if high_hz > 0 else 1
    for multiple in (1, 2, 5, 10):
        if high_hz / (multiple * step) <= 8:
            step *= multiple
            break
    return [step * n for n in range(0, int(high_hz // step) + 1)]


def png_bytes(image: Image.Image) -> bytes:
    """A imagem codificada em PNG."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
