"""Geometria compartilhada entre o Pillow e os grafos do FFmpeg."""

from __future__ import annotations


def fit_rect(src_w: int, src_h: int, width: int, height: int, margin: float) -> tuple[int, int, int, int]:
    """Retângulo (x, y, w, h) da fonte encaixada no quadro com margem, centralizada. Lados pares."""
    max_w = width * (1 - 2 * margin)
    max_h = height * (1 - 2 * margin)
    k = min(max_w / src_w, max_h / src_h)
    w = max(2, int(src_w * k) // 2 * 2)
    h = max(2, int(src_h * k) // 2 * 2)
    return (width - w) // 2, (height - h) // 2, w, h


def cover_box(
    src_w: float, src_h: float, aspect: float, focus: tuple[float, float] = (0.5, 0.5)
) -> tuple[float, float, float, float]:
    """Maior caixa com a proporção `aspect` dentro da fonte, posicionada pelo ponto de foco (0..1)."""
    if src_w / src_h > aspect:
        h = src_h
        w = h * aspect
    else:
        w = src_w
        h = w / aspect
    fx, fy = focus
    x0 = (src_w - w) * fx
    y0 = (src_h - h) * fy
    return x0, y0, x0 + w, y0 + h
