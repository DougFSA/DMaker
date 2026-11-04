"""O nível de um item como ele soa, para o painel do item: RMS, pico e LUFS integrado.

O RMS e o pico saem do analisador `rms` (DMK-60) sobre o som que o render usaria, já com os efeitos do item; o LUFS integrado
é do `ebur128` do ffmpeg, lido do mesmo som (a conta do BS.1770 pede filtros em cascata que o ffmpeg já faz). Só lê: não
grava nada no projeto.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from ..domain.spec import Project
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from .audio_analysis import AnalysisRequest, AudioAnalysisService

_INTEGRATED = re.compile(r"^\s*I:\s*(-?inf|-?[0-9.]+)\s*LUFS", re.IGNORECASE | re.MULTILINE)


def integrated_lufs(runner: FFmpegRunner, samples: np.ndarray, rate: int) -> float | None:
    """O loudness integrado (LUFS) das amostras `(n, canais)`, ou None num trecho mudo (o `ebur128` não tem o que medir)."""
    if samples.shape[0] == 0:
        return None
    with tempfile.TemporaryDirectory(prefix="dmaker-lufs-") as scratch:
        raw = Path(scratch) / "trecho.f32"
        np.asarray(samples, dtype="<f4").tofile(raw)
        args = ["-f", "f32le", "-ar", str(rate), "-ac", str(samples.shape[1]), "-i", str(raw)]
        args += ["-af", "ebur128=framelog=quiet", "-f", "null", "-"]
        report = runner.capture(args, label="loudness do item")
    found = _INTEGRATED.findall(report)
    if not found:
        return None
    value = float(found[-1])
    return value if np.isfinite(value) and value > -70.0 else None


def measure_item_level(
    project: Project,
    target: str,
    start: float | str | None = None,
    end: float | str | None = None,
    runner: FFmpegRunner | None = None,
) -> dict[str, Any]:
    """RMS e pico (dBFS) e LUFS integrado do item `target` (ou do trecho `start`..`end` dele), como ele soa."""
    runner = runner or SubprocessRunner(quiet=True)
    service = AudioAnalysisService(runner)
    request = AnalysisRequest("rms", target=target, start=start, end=end)
    loaded = service.load(project, request)
    outcome = service.analyze_loaded(project, request, loaded)
    result = outcome.result
    lufs = integrated_lufs(runner, loaded.signal.samples, loaded.signal.sample_rate)
    return {
        "target": target,
        "rms_db": result.overall_rms_db,
        "peak_db": result.overall_peak_db,
        "lufs": None if lufs is None else round(lufs, 1),
        "interval_s": [round(outcome.interval[0], 6), round(outcome.interval[1], 6)],
    }
