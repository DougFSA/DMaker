"""Sobreposições de imagem (logo, marca d'água) no grafo de montagem."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.presets import SafeZone
from ..domain.spec import ImageOverlay
from .common import Inputs, even


@dataclass
class ResolvedImageOverlay:
    overlay: ImageOverlay
    path: Path
    start: float
    end: float


def overlay_position(position: str, W: int, H: int, margin: float, safe: SafeZone) -> tuple[str, str]:
    """Expressões x/y do filtro overlay, respeitando a zona segura do preset."""
    mt = margin + safe.top
    mb = margin + safe.bottom
    ml = margin + safe.left
    mr = margin + safe.right
    table = {
        "top-left": (f"{ml:.0f}", f"{mt:.0f}"),
        "top-right": (f"W-w-{mr:.0f}", f"{mt:.0f}"),
        "bottom-left": (f"{ml:.0f}", f"H-h-{mb:.0f}"),
        "bottom-right": (f"W-w-{mr:.0f}", f"H-h-{mb:.0f}"),
        "top": ("(W-w)/2", f"{mt:.0f}"),
        "bottom": ("(W-w)/2", f"H-h-{mb:.0f}"),
        "center": ("(W-w)/2", "(H-h)/2"),
    }
    return table[position]


def image_overlay_graph(
    lines: list[str],
    inputs: Inputs,
    cur_v: str,
    overlays: list[ResolvedImageOverlay],
    W: int,
    H: int,
    fps: float,
    total: float,
    scale: float,
    safe: SafeZone,
) -> str:
    """Encadeia um `overlay` por imagem sobre `cur_v` e devolve o rótulo final."""
    for k, item in enumerate(overlays):
        ov = item.overlay
        idx = inputs.add_looped_image(item.path, fps, total)
        w = even(W * ov.width)
        chain = [f"[{idx}:v]format=rgba", f"scale={w}:-2:flags=lanczos"]
        if ov.opacity < 1:
            chain.append(f"colorchannelmixer=aa={ov.opacity:.3f}")
        if ov.fade > 0:
            chain.append(f"fade=t=in:st={item.start:.3f}:d={ov.fade:.3f}:alpha=1")
            if item.end < total - 0.05:
                chain.append(
                    f"fade=t=out:st={max(item.end - ov.fade, item.start):.3f}:d={ov.fade:.3f}:alpha=1"
                )
        lines.append(",".join(chain) + f"[ov{k}]")
        x, y = overlay_position(ov.position, W, H, ov.margin * scale, safe if ov.safe_zone else SafeZone())
        lines.append(
            f"{cur_v}[ov{k}]overlay=x={x}:y={y}:enable='between(t,{item.start:.3f},{item.end:.3f})':format=auto[vo{k}]"
        )
        cur_v = f"[vo{k}]"
    return cur_v
