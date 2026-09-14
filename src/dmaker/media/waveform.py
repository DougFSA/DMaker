"""Forma de onda (picos por janela) de uma faixa de áudio, para desenhar na linha do tempo da
interface sem decodificar o arquivo inteiro no navegador.

O cálculo é leve (8 kHz, mono) e o resultado (picos normalizados 0..1) fica em cache em
`config.WAVEFORM_DIR`, com o mesmo esquema de nome por hash usado pelos proxies de prévia
(`pipeline/proxies.py`): uma fonte trocada ou reeditada gera uma forma de onda nova.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config
from .audiosync import extract_pcm, read_pcm
from .ffmpeg import FFmpegRunner

WAVEFORM_VERSION = "w1"  # muda quando o cálculo dos picos muda (invalida o cache)
PEAKS_PER_SECOND = 50  # resolução visual: basta para o zoom máximo da linha do tempo
ANALYSIS_RATE = 8000  # Hz do áudio extraído; picos visuais não precisam de mais que isso


def peaks_from_samples(samples: np.ndarray, sample_rate: int, peaks_per_second: int) -> list[float]:
    """Pico absoluto de cada janela de ~1/`peaks_per_second` segundos, normalizado pelo maior pico do
    trecho (0..1). A última janela conta mesmo incompleta, senão a ponta do áudio some da forma de onda."""
    if len(samples) == 0 or sample_rate <= 0 or peaks_per_second <= 0:
        return []
    window = max(1, round(sample_rate / peaks_per_second))
    windows = int(np.ceil(len(samples) / window))
    raw_peaks = np.empty(windows, dtype=np.float64)
    for i in range(windows):
        chunk = samples[i * window : (i + 1) * window]
        raw_peaks[i] = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
    peak_max = float(raw_peaks.max())
    if peak_max <= 0:
        return [0.0] * windows
    return (raw_peaks / peak_max).tolist()


@dataclass
class Waveform:
    duration: float
    peaks_per_second: int
    peaks: list[float]

    def to_dict(self) -> dict:
        return {"duration": self.duration, "peaks_per_second": self.peaks_per_second, "peaks": self.peaks}

    @staticmethod
    def from_dict(data: dict) -> Waveform:
        return Waveform(
            duration=float(data["duration"]),
            peaks_per_second=int(data["peaks_per_second"]),
            peaks=[float(p) for p in data["peaks"]],
        )


def waveform_path(src: Path, stream: int = 0) -> Path:
    """Nome no cache: hash do caminho resolvido, data de modificação, tamanho, faixa de áudio e versão
    do cálculo, para que uma fonte trocada ou reeditada gere uma forma de onda nova em vez de reaproveitar
    uma velha (mesmo esquema de `pipeline/proxies.py`)."""
    resolved = src.resolve()
    st = resolved.stat()
    raw = f"{resolved.as_posix()}|{st.st_mtime_ns}|{st.st_size}|{stream}|{WAVEFORM_VERSION}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return config.WAVEFORM_DIR / f"{digest}.json"


class WaveformBuilder:
    """Gera (e põe em cache) os picos de uma fonte de áudio. `workdir` guarda o wav temporário usado
    para o cálculo; por padrão fica dentro do próprio cache de formas de onda."""

    def __init__(self, runner: FFmpegRunner, workdir: Path | None = None):
        self.runner = runner
        self._workdir = workdir

    def _workdir_path(self) -> Path:
        return self._workdir or (config.WAVEFORM_DIR / "tmp")

    def build(self, src: Path, stream: int = 0) -> Waveform:
        target = waveform_path(src, stream)
        target.parent.mkdir(parents=True, exist_ok=True)
        workdir = self._workdir_path()
        workdir.mkdir(parents=True, exist_ok=True)
        tmp_wav = workdir / f"{target.stem}.wav"
        try:
            extract_pcm(self.runner, src, tmp_wav, stream, rate=ANALYSIS_RATE)
            samples = read_pcm(tmp_wav)
        finally:
            tmp_wav.unlink(missing_ok=True)
        peaks = peaks_from_samples(samples, ANALYSIS_RATE, PEAKS_PER_SECOND)
        waveform = Waveform(
            duration=len(samples) / ANALYSIS_RATE, peaks_per_second=PEAKS_PER_SECOND, peaks=peaks
        )
        target.write_text(json.dumps(waveform.to_dict()), encoding="utf-8")
        return waveform

    def load_or_build(self, src: Path, stream: int = 0) -> Waveform:
        target = waveform_path(src, stream)
        if target.exists():
            try:
                return Waveform.from_dict(json.loads(target.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass  # cache corrompido: recalcula
        return self.build(src, stream)
