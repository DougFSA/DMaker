"""Reenquadramento de vídeo (clipes) para o tamanho de saída."""

from __future__ import annotations

from ..domain.spec import Reframe
from ..visuals.geometry import fit_rect
from .common import even


def resolve_reframe_mode(mode: str, sw: int, sh: int, W: int, H: int, has_brand: bool = False) -> str:
    """auto: proporção parecida corta; muito diferente usa fundo da marca (se houver tema) ou desfocado."""
    if mode != "auto":
        return mode
    if not sw or not sh:
        return "crop"
    sa, ta = sw / sh, W / H
    ratio = max(sa / ta, ta / sa)
    if ratio <= 1.34:
        return "crop"
    return "brand" if has_brand else "blur"


def reframe_graph(
    src: str,
    out: str,
    sw: int,
    sh: int,
    W: int,
    H: int,
    reframe: Reframe,
    has_brand: bool = False,
    backdrop: str | None = None,
) -> str:
    """Grafo que leva `src` (rótulo de entrada) até `out` no tamanho WxH.

    No modo brand, `backdrop` é o rótulo da entrada com o fundo gerado (já em WxH); sem ele cai no desfoque.
    """
    mode = resolve_reframe_mode(reframe.mode, sw, sh, W, H, has_brand)
    if mode == "brand" and not backdrop:
        mode = "blur"
    fx, fy = reframe.focus
    z = reframe.zoom
    if mode == "stretch":
        return f"{src}scale={W}:{H}:flags=lanczos{out}"
    if mode == "brand":
        x, y, fw, fh = fit_rect(sw, sh, W, H, reframe.margin)
        return f"{src}scale={fw}:{fh}:flags=lanczos[rf_fg];{backdrop}[rf_fg]overlay={x}:{y}:format=auto{out}"
    if mode == "crop":
        zw, zh = even(W * z), even(H * z)
        return (
            f"{src}scale={zw}:{zh}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{H}:(iw-ow)*{fx:.4f}:(ih-oh)*{fy:.4f}{out}"
        )
    if mode == "pad":
        return (
            f"{src}scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={reframe.pad_color}{out}"
        )
    # blur: fundo desfocado preenchendo o quadro, fonte inteira por cima
    bw, bh = even(W / 4), even(H / 4)
    sigma = max(reframe.blur / 4, 1)
    return (
        f"{src}split=2[rf_bg][rf_fg];"
        f"[rf_bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
        f"gblur=sigma={sigma:.2f},eq=brightness=-0.06:saturation=0.85,scale={W}:{H}:flags=bicubic[rf_bgb];"
        f"[rf_fg]scale={even(W * z)}:{even(H * z)}:force_original_aspect_ratio=decrease:force_divisible_by=2"
        f":flags=lanczos[rf_fgs];"
        f"[rf_bgb][rf_fgs]overlay=(W-w)/2:(H-h)/2:format=auto{out}"
    )
