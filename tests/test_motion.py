"""Movimento sub-pixel: plano de câmera e suavidade real dos quadros renderizados."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from dmaker.visuals.geometry import cover_box
from dmaker.visuals.motion import Box, plan_motion, render_frames, smoothstep, source_size_for


def test_smoothstep_easing():
    assert smoothstep(0) == 0 and smoothstep(1) == 1 and smoothstep(0.5) == 0.5
    assert smoothstep(0.25) < 0.25 and smoothstep(0.75) > 0.75  # começa e termina devagar


def test_cover_box_respects_aspect_and_focus():
    x0, y0, x1, y1 = cover_box(1920, 1080, 9 / 16, focus=(0.0, 0.5))
    assert x0 == 0 and abs((x1 - x0) / (y1 - y0) - 9 / 16) < 1e-9 and y1 - y0 == 1080
    x0, *_ = cover_box(1920, 1080, 9 / 16, focus=(1.0, 0.5))
    assert abs(x0 - (1920 - 1080 * 9 / 16)) < 1e-9


def test_plan_zoom_in_is_monotonic_and_inside_source():
    plan = plan_motion(2160, 3840, 1080, 1920, "zoom-in", 0.12, 120)
    assert plan.frames == 120
    widths = [b.width for b in plan.boxes]
    assert widths[0] == pytest.approx(2160) and widths[-1] == pytest.approx(2160 / 1.12)
    assert all(a >= b for a, b in zip(widths, widths[1:], strict=False))
    for b in plan.boxes:
        assert 0 <= b.x0 <= b.x1 <= 2160 and 0 <= b.y0 <= b.y1 <= 3840
        assert b.width / b.height == pytest.approx(1080 / 1920)
        assert b.center == pytest.approx((1080, 1920))


def test_plan_pan_moves_across_available_travel():
    plan = plan_motion(2160, 3840, 1080, 1920, "pan-left", 0.1, 50)
    first, last = plan.boxes[0], plan.boxes[-1]
    assert first.width == pytest.approx(last.width)  # zoom constante
    assert first.x0 > last.x0  # a janela anda para a esquerda
    assert last.x0 == pytest.approx(0) and first.x1 == pytest.approx(2160)
    right = plan_motion(2160, 3840, 1080, 1920, "pan-right", 0.1, 50)
    assert right.boxes[0].x0 < right.boxes[-1].x0


def test_plan_none_and_invalid():
    plan = plan_motion(200, 200, 100, 100, "none", 0.5, 3)
    assert all(b == Box(0, 0, 200, 200) for b in plan.boxes)
    with pytest.raises(ValueError):
        plan_motion(200, 200, 100, 100, "orbit", 0.1, 3)


def test_source_size_for():
    assert source_size_for(1080, 1920, 0.12) == (2419, 4301)


def test_render_frames_size_and_order():
    img = Image.new("RGB", (400, 300), "white")
    plan = plan_motion(400, 300, 40, 30, "zoom-in", 0.2, 5)
    frames = list(render_frames(img, plan, workers=2))
    assert len(frames) == 5 and all(len(f) == 40 * 30 * 3 for f in frames)


def _tracked_edge(frames: list[bytes], w: int, h: int) -> list[float]:
    """Posição sub-pixel de uma borda horizontal em cada quadro (centro de massa do gradiente)."""
    ys = []
    last = None
    for raw in frames:
        a = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).mean(axis=2)
        g = np.abs(np.diff(a[:, w // 4 : 3 * w // 4].mean(axis=1)))
        i = (
            int(np.argmax(g))
            if last is None
            else int(last) - 4 + int(np.argmax(g[int(last) - 4 : int(last) + 5]))
        )
        lo, hi = max(i - 2, 0), min(i + 3, len(g))
        weights, idx = g[lo:hi], np.arange(lo, hi)
        last = float((weights * idx).sum() / weights.sum())
        ys.append(last)
    return ys


def test_rendered_zoom_is_smooth_without_jitter():
    """O zoompan do FFmpeg produzia deltas com sinal trocado (tremor). Aqui o movimento tem que ser
    monotônico e com aceleração suave."""
    w, h = 240, 426
    src = Image.new("RGB", (w * 2, h * 2), "white")
    ImageDraw.Draw(src).rectangle([0, 300, w * 2, h * 2], fill="black")  # borda horizontal nítida em y=300
    plan = plan_motion(w * 2, h * 2, w, h, "zoom-in", 0.12, 60)
    frames = list(render_frames(src, plan, workers=2))
    ys = np.array(_tracked_edge(frames, w, h))
    deltas = np.diff(ys)
    # a borda está acima do centro: com o zoom ela sobe (deltas <= 0) sem nunca voltar
    assert np.all(deltas <= 0.05), deltas
    assert ys[0] - ys[-1] > 3  # houve movimento de verdade
    # aceleração suave: variação entre deltas consecutivos pequena frente ao passo médio
    accel = np.abs(np.diff(deltas))
    assert accel.max() < 0.25, accel
