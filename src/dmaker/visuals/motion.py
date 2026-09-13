"""Movimento de câmera sobre imagens (Ken Burns) com precisão sub-pixel.

O `zoompan` do FFmpeg recorta em pixels inteiros e por isso a imagem "treme" em zooms lentos.
Aqui o plano de movimento é calculado em ponto flutuante e cada quadro é reamostrado pelo Pillow
(`Image.resize` com `box` fracionário e filtro LANCZOS), com easing suave nas pontas.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PIL import Image

from .geometry import cover_box

Easing = Callable[[float], float]

MOTIONS = ("none", "zoom-in", "zoom-out", "pan-left", "pan-right")


def smoothstep(t: float) -> float:
    """Aceleração e desaceleração suaves (Hermite), o movimento "de cinema"."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def linear(t: float) -> float:
    return min(max(t, 0.0), 1.0)


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1


@dataclass(frozen=True)
class MotionPlan:
    boxes: list[Box]  # uma caixa de recorte (na fonte) por quadro de saída
    out_w: int
    out_h: int

    @property
    def frames(self) -> int:
        return len(self.boxes)


def plan_motion(
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    motion: str,
    amount: float,
    frames: int,
    easing: Easing = smoothstep,
    focus: tuple[float, float] = (0.5, 0.5),
) -> MotionPlan:
    """Caixas de recorte por quadro. `amount` é o zoom máximo relativo (0.12 = 12%)."""
    if motion not in MOTIONS:
        raise ValueError(f"movimento desconhecido: {motion!r} (use {', '.join(MOTIONS)})")
    frames = max(int(frames), 1)
    aspect = out_w / out_h
    bx0, by0, bx1, by1 = cover_box(src_w, src_h, aspect, focus)
    base_w, base_h = bx1 - bx0, by1 - by0
    base_cx, base_cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    boxes: list[Box] = []
    for i in range(frames):
        t = i / (frames - 1) if frames > 1 else 0.0
        e = easing(t)
        if motion == "none" or amount <= 0:
            z, shift = 1.0, 0.0
        elif motion == "zoom-in":
            z, shift = 1 + amount * e, 0.0
        elif motion == "zoom-out":
            z, shift = 1 + amount * (1 - e), 0.0
        else:
            z = 1 + amount
            travel = base_w * (1 - 1 / z)  # espaço disponível para deslocar a janela
            direction = 1 if motion == "pan-left" else -1
            shift = direction * travel * (0.5 - e)  # começa de um lado, termina no outro
        w, h = base_w / z, base_h / z
        cx, cy = base_cx + shift, base_cy
        # mantém a janela dentro da fonte
        x0 = min(max(cx - w / 2, 0.0), src_w - w)
        y0 = min(max(cy - h / 2, 0.0), src_h - h)
        boxes.append(Box(x0, y0, x0 + w, y0 + h))
    return MotionPlan(boxes, out_w, out_h)


def render_frame(image: Image.Image, box: Box, out_w: int, out_h: int) -> bytes:
    """Um quadro RGB24 reamostrado da caixa fracionária (antialias LANCZOS)."""
    frame = image.resize((out_w, out_h), Image.Resampling.LANCZOS, box=box.as_tuple())
    return frame.tobytes()


def render_frames(image: Image.Image, plan: MotionPlan, workers: int = 4) -> Iterator[bytes]:
    """Quadros em ordem, renderizados em paralelo (o Pillow libera o GIL ao reamostrar)."""
    src = image.convert("RGB")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        yield from pool.map(
            lambda box: render_frame(src, box, plan.out_w, plan.out_h), plan.boxes, chunksize=4
        )


def source_size_for(out_w: int, out_h: int, amount: float, supersample: float = 2.0) -> tuple[int, int]:
    """Tamanho mínimo da fonte para que o recorte mais fechado ainda tenha `supersample`x a saída."""
    k = supersample * (1 + max(amount, 0))
    return int(round(out_w * k)), int(round(out_h * k))
