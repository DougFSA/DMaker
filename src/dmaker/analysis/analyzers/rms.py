"""Medir RMS (Measure RMS): o nível médio e o pico de cada canal, em dBFS, do trecho inteiro ou em janelas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

import numpy as np

from ..registry import AnalysisResult, AnalyzerBase, param, register_analyzer
from ..signal import Signal, frame_levels_db, peak_db, rms_db


@dataclass(kw_only=True)
class ChannelLevel:
    """O nível de um canal: RMS e pico em dBFS e o deslocamento DC (a média das amostras, de -1 a 1)."""

    channel: int
    rms_db: float
    peak_db: float
    dc_offset: float


@dataclass(kw_only=True)
class RmsResult(AnalysisResult):
    overall_rms_db: float
    overall_peak_db: float
    channels: list[ChannelLevel]
    # o RMS de cada janela, na ordem do tempo (vazio quando o pedido mede o trecho inteiro de uma vez)
    window_seconds: float = 0.0
    windows: list[dict[str, float]] = field(default_factory=list)

    def table(self, separator: str = ",") -> str | None:
        if not self.windows:
            return None
        rows = ["tempo_s", "rms_db"]
        lines = [separator.join(rows)]
        lines += [f"{item['start']:.6f}{separator}{item['rms_db']:.3f}" for item in self.windows]
        return "\n".join(lines) + "\n"


@register_analyzer
class MeasureRms(AnalyzerBase):
    """Mede o RMS e o pico do trecho por canal. Com `window`, devolve também o RMS de cada janela consecutiva."""

    type: Literal["rms"] = "rms"
    label: ClassVar[str] = "Medir RMS"
    audacity_name: ClassVar[str] = "Measure RMS"
    summary: ClassVar[str] = (
        "Mede o nível médio (RMS) e o pico de cada canal, em dB, do trecho ou em janelas."
    )
    exports: ClassVar[tuple[str, ...]] = ("csv",)

    window: float = param(
        0.0,
        label="Janela",
        unit="s",
        hint="Mede o RMS de cada janela deste tamanho, em sequência. Zero mede o trecho inteiro de uma vez.",
        ge=0.0,
        le=600.0,
    )

    def analyze(self, signal: Signal) -> RmsResult:
        samples = signal.samples
        if samples.shape[0] == 0:
            raise ValueError("não há amostras para medir: o trecho está vazio")
        channels = [
            ChannelLevel(
                channel=index + 1,
                rms_db=round(rms_db(samples[:, index]), 3),
                peak_db=round(peak_db(samples[:, index]), 3),
                dc_offset=round(float(np.mean(samples[:, index], dtype=np.float64)), 6),
            )
            for index in range(signal.channels)
        ]
        overall_rms, overall_peak = round(rms_db(samples), 3), round(peak_db(samples), 3)
        windows: list[dict[str, float]] = []
        if self.window > 0:
            levels = frame_levels_db(samples, signal.sample_rate, self.window)
            windows = [
                {"start": round(position * self.window, 6), "rms_db": round(float(level), 3)}
                for position, level in enumerate(levels)
            ]
        where = ", ".join(f"canal {item.channel}: {item.rms_db:.1f} dB" for item in channels)
        return RmsResult(
            analyzer=self.type,
            summary=f"RMS {overall_rms:.1f} dBFS, pico {overall_peak:.1f} dBFS ({where}).",
            overall_rms_db=overall_rms,
            overall_peak_db=overall_peak,
            channels=channels,
            window_seconds=self.window,
            windows=windows,
        )
