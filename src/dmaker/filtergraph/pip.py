"""Picture-in-picture no grafo de montagem: vídeo secundário recortado por máscara, com moldura,
posicionado e animado sobre a linha do tempo; o áudio dele volta como rótulo para a mixagem."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.presets import SafeZone
from ..domain.spec import VideoOverlay
from .common import AUDIO_FMT_MIX, Inputs

SLIDE_SECONDS = 0.45


@dataclass
class ResolvedVideoOverlay:
    overlay: VideoOverlay
    path: Path
    in_point: float  # tempo no arquivo mostrado em `start`
    start: float
    end: float
    width: int  # tamanho do PiP no quadro
    height: int
    mask: Path
    frame: Path | None
    pad: int
    audio_stream: int = 0
    has_audio: bool = True

    @property
    def duration(self) -> float:
        return self.end - self.start


def pip_position(pip: ResolvedVideoOverlay, W: int, H: int, scale: float, safe: SafeZone) -> tuple[int, int]:
    """Canto superior esquerdo do PiP, respeitando a zona segura do preset."""
    ov = pip.overlay
    if ov.x is not None and ov.y is not None:
        return int(round(ov.x * W - pip.width / 2)), int(round(ov.y * H - pip.height / 2))
    m = ov.margin * scale
    xs = {
        "left": int(round(safe.left + m)),
        "right": int(round(W - safe.right - m - pip.width)),
        "center": (W - pip.width) // 2,
    }
    ys = {
        "top": int(round(safe.top + m)),
        "bottom": int(round(H - safe.bottom - m - pip.height)),
        "center": (H - pip.height) // 2,
    }
    vertical, _, horizontal = ov.position.partition("-")
    if ov.position == "center":
        return xs["center"], ys["center"]
    if not horizontal:  # "top" / "bottom"
        return xs["center"], ys[vertical]
    return xs[horizontal], ys[vertical]


def _slide_expr(axis_value: int, size: int, edge_far: int, start: float, position: str, axis: str) -> str:
    """Expressão que traz o PiP de fora da tela até a posição final nos primeiros SLIDE_SECONDS."""
    progress = f"min(1,(t-{start:.3f})/{SLIDE_SECONDS})"
    ease = f"(1-pow(1-{progress},2))"  # desacelera ao chegar
    if axis == "x":
        comes_from_right = "right" in position
        comes_from_left = "left" in position
        if not (comes_from_right or comes_from_left):
            return str(axis_value)
        off = (edge_far - axis_value) if comes_from_right else (axis_value + size)
        sign = "+" if comes_from_right else "-"
        return f"{axis_value}{sign}{off}*(1-{ease})"
    comes_from_top = position.startswith("top")
    comes_from_bottom = position.startswith("bottom")
    if "-" in position or not (comes_from_top or comes_from_bottom):
        return str(axis_value)
    off = (axis_value + size) if comes_from_top else (edge_far - axis_value)
    sign = "-" if comes_from_top else "+"
    return f"{axis_value}{sign}{off}*(1-{ease})"


def video_overlay_graph(
    lines: list[str],
    inputs: Inputs,
    cur_v: str,
    pips: list[ResolvedVideoOverlay],
    W: int,
    H: int,
    fps: float,
    total: float,
    scale: float,
    safe: SafeZone,
) -> tuple[str, list[str]]:
    """Compõe cada PiP sobre `cur_v`. Devolve (rótulo do vídeo, rótulos de áudio dos PiPs para mixar)."""
    audio_labels: list[str] = []
    for k, pip in enumerate(pips):
        ov = pip.overlay
        dur = pip.duration
        idx = inputs.add(pip.path, "-ss", f"{max(pip.in_point, 0):.3f}", "-t", f"{dur:.3f}")
        mask_idx = inputs.add_looped_image(pip.mask, fps, dur)
        w, h = pip.width, pip.height
        lines.append(
            f"[{idx}:v]setpts=PTS-STARTPTS,fps={fps:g},scale={w}:{h}:force_original_aspect_ratio=increase"
            f":flags=lanczos,crop={w}:{h},format=rgba[pipv{k}]"
        )
        lines.append(f"[{mask_idx}:v]format=gray,scale={w}:{h}[pipm{k}]")
        post = [f"[pipv{k}][pipm{k}]alphamerge"]
        if ov.opacity < 1:
            post.append(f"colorchannelmixer=aa={ov.opacity:.3f}")
        if ov.animation == "fade" and ov.fade > 0:
            post.append(f"fade=t=in:st=0:d={ov.fade:.3f}:alpha=1")
            if pip.end < total - 0.05:
                post.append(f"fade=t=out:st={max(dur - ov.fade, 0):.3f}:d={ov.fade:.3f}:alpha=1")
        if pip.start > 0:  # quadros transparentes até o PiP entrar, para os tempos coincidirem
            post.append(f"tpad=start_duration={pip.start:.3f}:start_mode=add:color=black@0.0")
        lines.append(",".join(post) + f"[pipf{k}]")

        x, y = pip_position(pip, W, H, scale, safe)
        enable = f"enable='between(t,{pip.start:.3f},{pip.end:.3f})'"
        if ov.animation == "slide":
            x_expr = _slide_expr(x, w, W, pip.start, ov.position, "x")
            y_expr = _slide_expr(y, h, H, pip.start, ov.position, "y")
            eval_mode = ":eval=frame"
        else:
            x_expr, y_expr, eval_mode = str(x), str(y), ""

        if pip.frame is not None:
            frame_idx = inputs.add_looped_image(pip.frame, fps, total)
            frame_chain = [f"[{frame_idx}:v]format=rgba"]
            if ov.animation == "fade" and ov.fade > 0:
                frame_chain.append(f"fade=t=in:st={pip.start:.3f}:d={ov.fade:.3f}:alpha=1")
                if pip.end < total - 0.05:
                    frame_chain.append(
                        f"fade=t=out:st={max(pip.end - ov.fade, pip.start):.3f}:d={ov.fade:.3f}:alpha=1"
                    )
            lines.append(",".join(frame_chain) + f"[pipfr{k}]")
            fx = f"'({x_expr})-{pip.pad}'" if eval_mode else str(x - pip.pad)
            fy = f"'({y_expr})-{pip.pad}'" if eval_mode else str(y - pip.pad)
            lines.append(f"{cur_v}[pipfr{k}]overlay=x={fx}:y={fy}:format=auto:{enable}{eval_mode}[pipb{k}]")
            cur_v = f"[pipb{k}]"

        # aspas: as expressões têm vírgulas (min, pow), que o parser de opções trataria como separador
        lines.append(
            f"{cur_v}[pipf{k}]overlay=x='{x_expr}':y='{y_expr}':format=auto:eof_action=pass:{enable}{eval_mode}[pv{k}]"
        )
        cur_v = f"[pv{k}]"

        if pip.has_audio and ov.volume > 0:
            chain = [
                f"[{idx}:a:{pip.audio_stream}]asetpts=PTS-STARTPTS",
                f"adelay={int(round(pip.start * 1000))}:all=1",
                f"volume={ov.volume:.3f}",
                AUDIO_FMT_MIX,
            ]
            lines.append(",".join(chain) + f"[pipaud{k}]")
            audio_labels.append(f"[pipaud{k}]")
    return cur_v, audio_labels
