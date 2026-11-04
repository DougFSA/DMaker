"""Marcar Sons (Label Sounds): marca os trechos com som, ou os silêncios, acima ou abaixo de um limiar.

O som é o quadro de 10 ms cujo RMS passa do limiar. Dois sons separados por um silêncio mais curto que
`min_silence` viram um só (uma pausa entre palavras não parte a frase), e um som mais curto que `min_sound` é
ignorado (um estalo não é fala). O marcador cai no começo do som (antes), no fim (depois) ou cobre o trecho todo
(região).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

import numpy as np

from ..registry import AnalysisResult, AnalyzerBase, MarkerProposal, param, register_analyzer
from ..signal import Signal, frame_levels_db

FRAME_SECONDS = 0.01  # 10 ms: curto para achar o começo do som com precisão, longo para um RMS estável


@dataclass(kw_only=True)
class SoundRegion:
    start: float
    end: float


@dataclass(kw_only=True)
class SoundsResult(AnalysisResult):
    mode: str
    position: str
    threshold_db: float
    label: str
    regions: list[SoundRegion]
    total_seconds: float

    def markers(self) -> list[MarkerProposal]:
        proposals = []
        for number, region in enumerate(self.regions, 1):
            text = f"{self.label} {number}".strip()
            if self.position == "region":
                proposals.append(MarkerProposal(region.start, region.end, text))
            elif self.position == "start":
                proposals.append(MarkerProposal(region.start, None, text))
            else:
                proposals.append(MarkerProposal(region.end, None, text))
        return proposals


def active_runs(active: np.ndarray) -> list[tuple[int, int]]:
    """Os trechos [início, fim) de quadros seguidos com `active` verdadeiro."""
    padded = np.concatenate(([False], active, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist(), strict=True))


def sound_regions(
    levels_db: np.ndarray, threshold_db: float, min_sound: int, min_silence: int
) -> list[tuple[int, int]]:
    """Os sons, em quadros [início, fim): quadros acima do limiar, com as pausas curtas (menores que `min_silence`
    quadros) preenchidas e depois os sons curtos (menores que `min_sound` quadros) descartados."""
    merged: list[list[int]] = []
    for first, stop in active_runs(levels_db > threshold_db):
        if merged and first - merged[-1][1] < min_silence:
            merged[-1][1] = stop
        else:
            merged.append([first, stop])
    return [(first, stop) for first, stop in merged if stop - first >= max(min_sound, 1)]


@register_analyzer
class LabelSounds(AnalyzerBase):
    """Marca os sons (ou os silêncios) do trecho, com duração mínima e a posição do marcador."""

    type: Literal["sounds"] = "sounds"
    label: ClassVar[str] = "Marcar Sons"
    audacity_name: ClassVar[str] = "Label Sounds"
    summary: ClassVar[str] = (
        "Marca os trechos com som, ou os silêncios, acima ou abaixo de um limiar, com duração mínima e o "
        "marcador no começo, no fim ou cobrindo o trecho."
    )
    marks_by_default: ClassVar[bool] = True
    marker_group: ClassVar[str] = "sons"
    marker_color: ClassVar[str | None] = "#2f9e44"

    mode: Literal["sounds", "silences"] = param(
        "sounds", label="O que marcar", hint="Os trechos com som ou os silêncios entre eles."
    )
    threshold_db: float = param(
        -30.0,
        label="Limiar",
        unit="dB",
        hint="O RMS abaixo disto conta como silêncio (padrão do Audacity: -30 dB).",
        ge=-100.0,
        le=0.0,
    )
    min_silence: float = param(
        1.0,
        label="Silêncio mínimo entre sons",
        unit="s",
        hint="Uma pausa mais curta que isto não separa dois sons: eles viram um só.",
        ge=0.0,
        le=600.0,
    )
    min_sound: float = param(
        0.5,
        label="Duração mínima do som",
        unit="s",
        hint="Um som mais curto que isto é ignorado.",
        ge=0.0,
        le=600.0,
    )
    position: Literal["region", "start", "end"] = param(
        "region",
        label="Posição do marcador",
        hint="region cobre o trecho, start marca o começo (antes) e end marca o fim (depois).",
    )
    text: str = param(
        "", label="Texto", hint="O texto de cada marcador, seguido do número. Vazio usa Som ou Silêncio."
    )

    def analyze(self, signal: Signal) -> SoundsResult:
        if signal.frames == 0:
            raise ValueError("não há amostras para marcar: o trecho está vazio")
        levels = frame_levels_db(signal.samples, signal.sample_rate, FRAME_SECONDS)
        if levels.size == 0:
            raise ValueError("o trecho é mais curto que 10 ms: não há o que marcar")
        sounds = sound_regions(
            levels,
            self.threshold_db,
            round(self.min_sound / FRAME_SECONDS),
            round(self.min_silence / FRAME_SECONDS),
        )
        if self.mode == "sounds":
            chosen = sounds
        else:
            chosen = _silences(sounds, len(levels), round(self.min_silence / FRAME_SECONDS))
        regions = [
            SoundRegion(start=round(a * FRAME_SECONDS, 6), end=round(b * FRAME_SECONDS, 6)) for a, b in chosen
        ]
        noun = "som(ns)" if self.mode == "sounds" else "silêncio(s)"
        label = self.text.strip() or ("Som" if self.mode == "sounds" else "Silêncio")
        return SoundsResult(
            analyzer=self.type,
            summary=(
                f"{len(regions)} {noun} acima de {self.threshold_db:g} dB"
                if self.mode == "sounds"
                else f"{len(regions)} {noun} abaixo de {self.threshold_db:g} dB"
            )
            + (f", o primeiro em {regions[0].start:.2f} s." if regions else "."),
            mode=self.mode,
            position=self.position,
            threshold_db=self.threshold_db,
            label=label,
            regions=regions,
            total_seconds=round(float(signal.duration), 6),
        )


def _silences(sounds: list[tuple[int, int]], frames: int, min_length: int) -> list[tuple[int, int]]:
    """Os silêncios: o que sobra do trecho fora dos sons, com pelo menos `min_length` quadros."""
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for first, stop in sounds:
        if first > cursor:
            gaps.append((cursor, first))
        cursor = stop
    if cursor < frames:
        gaps.append((cursor, frames))
    return [(a, b) for a, b in gaps if b - a >= max(min_length, 1)]
