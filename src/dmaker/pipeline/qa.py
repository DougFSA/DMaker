"""Ferramentas de conferência visual: grade de quadros e quadros em instantes específicos."""

from __future__ import annotations

from pathlib import Path

from ..media import ffmpeg
from ..media.probe import probe


def contact_sheet(video: Path, out: Path, cols: int = 3, rows: int = 3, width: int = 360) -> Path:
    """Grade de quadros igualmente espaçados: um único PNG para revisar o vídeo inteiro."""
    info = probe(video)
    step = max(info.duration / (cols * rows), 0.1)
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(
        [
            "-i",
            str(video),
            "-vf",
            f"fps=1/{step:.4f},scale={width}:-2,tile={cols}x{rows}:padding=4:margin=4",
            "-frames:v",
            "1",
            str(out),
        ],
        quiet=True,
    )
    return out


def frame_at(video: Path, t: float, out: Path, width: int | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-ss", f"{t:.3f}", "-i", str(video)]
    if width:
        args += ["-vf", f"scale={width}:-2"]
    args += ["-frames:v", "1", "-q:v", "2", str(out)]
    ffmpeg.run(args, quiet=True)
    return out
