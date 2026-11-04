"""Achar Batidas (Beat Finder): marca as batidas do trecho, que servem de base para cortar o vídeo no ritmo.

A batida é um pico da envoltória do som (a energia suavizada) que passa de uma fração do pico mais alto, e duas
batidas ficam sempre a pelo menos `min_distance` uma da outra: entre dois picos colados vale o mais forte. O
resultado traz também o andamento (batidas por minuto) e onde cai o primeiro tempo, que o card de andamento usa: o
andamento sai da autocorrelação dos ataques (`analysis/tempo.py`), porque a mediana dos intervalos entre os picos achados
só vê os tempos fortes de um compasso e erra por um múltiplo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

import numpy as np

from ..registry import AnalysisResult, AnalyzerBase, MarkerProposal, param, register_analyzer
from ..signal import Signal
from ..tempo import estimate_tempo

# A envoltória é calculada de 5 em 5 ms: o bastante para a batida cair a poucos milissegundos do instante real
# (a tolerância de corte de vídeo é de um quadro, 33 ms) sem pesar numa música de minutos.
HOP_SECONDS = 0.005


@dataclass(kw_only=True)
class BeatsResult(AnalysisResult):
    beats: list[float]
    bpm: float | None
    intervals: list[float]
    beat_offset: float | None  # onde cai o primeiro tempo (segundos desde o começo do trecho)
    bpm_confidence: float | None  # 0 a 1: quanto da energia dos ataques se repete nesse andamento
    bpm_alternatives: list[float]  # a metade e o dobro, quando a música é ouvida em outro tempo
    threshold_percent: float
    min_distance: float
    label: str

    def markers(self) -> list[MarkerProposal]:
        return [
            MarkerProposal(time, None, f"{self.label} {number}") for number, time in enumerate(self.beats, 1)
        ]


def envelope(samples: np.ndarray, sample_rate: int, smoothing: float) -> tuple[np.ndarray, int]:
    """A envoltória do sinal mono: o módulo das amostras, em blocos de `HOP_SECONDS`, suavizado por uma janela de
    Hann de `smoothing` segundos centrada em cada bloco (centrada para o pico cair no meio do estalo, e não depois).
    Devolve a envoltória e o tamanho do bloco em amostras."""
    hop = max(int(round(sample_rate * HOP_SECONDS)), 1)
    count = len(samples) // hop
    if count == 0:
        return np.zeros(0, dtype=np.float64), hop
    blocks = np.abs(np.asarray(samples[: count * hop], dtype=np.float64)).reshape(count, hop).mean(axis=1)
    # largura ímpar e janela de Hann: a média fica exatamente centrada no bloco e tem um máximo só (com uma média
    # simples, o clique vira um patamar e o pico sairia na ponta dele, até 2 blocos antes do clique)
    width = max(int(round(smoothing / HOP_SECONDS)), 1) | 1
    if width > 1:
        kernel = np.hanning(width + 2)[1:-1]
        blocks = np.convolve(blocks, kernel / kernel.sum(), mode="same")
    return blocks, hop


def pick_beats(levels: np.ndarray, threshold: float, min_gap: int) -> list[int]:
    """Os índices dos picos locais de `levels` acima de `threshold`, com pelo menos `min_gap` índices entre dois:
    ao disputar a vaga, vence o mais alto."""
    if levels.size < 3:
        return []
    inner = levels[1:-1]
    peaks = np.flatnonzero((inner > levels[:-2]) & (inner >= levels[2:]) & (inner >= threshold)) + 1
    chosen: list[int] = []
    for index in peaks[np.argsort(levels[peaks])[::-1]].tolist():
        if all(abs(index - other) >= min_gap for other in chosen):
            chosen.append(index)
    return sorted(chosen)


@register_analyzer
class BeatFinder(AnalyzerBase):
    """Acha as batidas do trecho por um limiar sobre a envoltória e uma distância mínima entre elas."""

    type: Literal["beats"] = "beats"
    label: ClassVar[str] = "Achar Batidas"
    audacity_name: ClassVar[str] = "Beat Finder"
    summary: ClassVar[str] = (
        "Marca as batidas da música (os picos de energia acima de um limiar, com distância mínima entre eles), "
        "como base para cortar o vídeo no ritmo."
    )
    marks_by_default: ClassVar[bool] = True
    marker_group: ClassVar[str] = "batidas"
    marker_color: ClassVar[str | None] = "#e8590c"

    threshold_percent: float = param(
        65.0,
        label="Limiar",
        unit="%",
        hint="O pico só conta como batida se passar desta porcentagem do pico mais alto do trecho (padrão do "
        "Audacity: 65).",
        ge=1.0,
        le=100.0,
    )
    min_distance: float = param(
        0.25,
        label="Distância mínima entre batidas",
        unit="s",
        hint="Duas batidas nunca ficam mais perto que isto (0,25 s admite até 240 batidas por minuto).",
        ge=0.05,
        le=10.0,
    )
    smoothing: float = param(
        0.02,
        label="Suavização",
        unit="s",
        hint="Quanto a envoltória é suavizada antes de procurar os picos: mais alto ignora ruído, mais baixo "
        "separa batidas coladas.",
        ge=0.005,
        le=0.5,
    )
    text: str = param(
        "", label="Texto", hint="O texto de cada marcador, seguido do número. Vazio usa Batida."
    )

    def analyze(self, signal: Signal) -> BeatsResult:
        if signal.frames == 0:
            raise ValueError("não há amostras para analisar: o trecho está vazio")
        levels, hop = envelope(signal.mono(), signal.sample_rate, self.smoothing)
        if levels.size == 0:
            raise ValueError("o trecho é curto demais para achar batidas")
        top = float(levels.max())
        indices = (
            pick_beats(
                levels, top * self.threshold_percent / 100.0, max(round(self.min_distance / HOP_SECONDS), 1)
            )
            if top > 0
            else []
        )
        # o bloco `i` cobre [i·hop, (i+1)·hop): o centro dele é o instante do pico
        beats = [round((index + 0.5) * hop / signal.sample_rate, 6) for index in indices]
        intervals = [round(b - a, 6) for a, b in zip(beats, beats[1:], strict=False)]
        estimate = estimate_tempo(signal.mono(), signal.sample_rate)
        if estimate is not None:
            bpm = estimate.bpm
        else:
            bpm = round(60.0 / float(np.median(intervals)), 2) if intervals else None
        if beats:
            summary = f"{len(beats)} batida(s); a primeira em {beats[0]:.3f} s" + (
                f", cerca de {bpm:g} batidas por minuto." if bpm else "."
            )
        else:
            summary = "Nenhuma batida passou do limiar."
        return BeatsResult(
            analyzer=self.type,
            summary=summary,
            beats=beats,
            bpm=bpm,
            intervals=intervals,
            beat_offset=None if estimate is None else estimate.beat_offset,
            bpm_confidence=None if estimate is None else estimate.confidence,
            bpm_alternatives=[] if estimate is None else list(estimate.alternatives),
            threshold_percent=self.threshold_percent,
            min_distance=self.min_distance,
            label=self.text.strip() or "Batida",
        )
