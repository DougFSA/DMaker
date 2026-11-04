"""Achar Clipping (Find Clipping): os trechos em que o som bate no teto, canal por canal, com início e fim.

Um trecho começa quando `start_threshold` amostras seguidas estão no teto e acaba quando `stop_threshold` amostras
seguidas ficam abaixo dele (os padrões do Audacity, 3 e 3), então uma amostra solta no teto não conta e dois
estouros colados viram um só.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Literal

import numpy as np

from ..registry import AnalysisResult, AnalyzerBase, MarkerProposal, param, register_analyzer
from ..signal import Signal, db_to_linear

# Um arquivo de 16 bits tem como maior valor 32767/32768, uma divisão de escala abaixo de 1,0: sem esta folga, o
# estouro de um WAV de 16 bits não contaria como "no teto". Vale uma divisão e meia, abaixo do degrau seguinte.
CEILING_TOLERANCE = 1.5 / 32768.0
MIN_REGION_SECONDS = 0.005


@dataclass(kw_only=True)
class ClipRegion:
    """Um trecho no teto: o canal (de 1), o início e o fim em segundos desde o começo do sinal e as amostras que
    ele tem no teto (as do trecho todo, contando as poucas abaixo dele que não o interromperam)."""

    channel: int
    start: float
    end: float
    samples: int


@dataclass(kw_only=True)
class ClippingResult(AnalysisResult):
    ceiling_db: float
    start_threshold: int
    stop_threshold: int
    regions: list[ClipRegion]
    clipped_samples: int
    clipped_percent: float

    def merged(self) -> list[tuple[float, float]]:
        """Os trechos estourados de todos os canais, juntos: o que dois canais estouram ao mesmo tempo é um trecho só."""
        return merge_regions(self.regions)

    def markers(self) -> list[MarkerProposal]:
        """Um marcador por trecho estourado: região se ele dura pelo menos 5 ms, instante se é só um punhado de amostras
        (uma região de fração de milissegundo não se vê na linha do tempo)."""
        return [
            MarkerProposal(start, end if end - start >= MIN_REGION_SECONDS else None, f"Clipping {number}")
            for number, (start, end) in enumerate(self.merged(), 1)
        ]


def merge_regions(regions: list[ClipRegion]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for region in sorted(regions, key=lambda item: item.start):
        if merged and region.start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], region.end)
        else:
            merged.append([region.start, region.end])
    return [(start, end) for start, end in merged]


def clipped_regions(mask: np.ndarray, start_threshold: int, stop_threshold: int) -> list[tuple[int, int]]:
    """Os trechos [primeira, última] (índices de amostra, os dois dentro) de um canal, dada a máscara das amostras
    no teto. Uma sequência curta demais para começar um trecho só vale se ela cai perto (a menos de
    `stop_threshold` amostras) do fim de um que já começou."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    starts, ends = edges[0::2], edges[1::2]  # cada sequência no teto é [início, fim)
    regions: list[list[int]] = []
    current: list[int] | None = None
    for first, stop in zip(starts.tolist(), ends.tolist(), strict=True):
        if current is not None and first - current[1] < stop_threshold:
            current[1] = stop
            continue
        if current is not None:
            regions.append(current)
            current = None
        if stop - first >= start_threshold:
            current = [first, stop]
    if current is not None:
        regions.append(current)
    return [(first, stop - 1) for first, stop in regions]


@register_analyzer
class FindClipping(AnalyzerBase):
    """Acha cada trecho com amostras seguidas no teto, por canal, com o instante em que começa e termina."""

    type: Literal["clipping"] = "clipping"
    label: ClassVar[str] = "Achar Clipping"
    audacity_name: ClassVar[str] = "Find Clipping"
    summary: ClassVar[str] = "Acha os trechos em que o som estoura o teto, canal por canal, com início e fim."
    marker_group: ClassVar[str] = "clipping"
    marker_color: ClassVar[str | None] = "#e03131"

    start_threshold: int = param(
        3,
        label="Amostras para começar",
        unit="amostras",
        hint="Quantas amostras seguidas no teto abrem um trecho estourado (padrão do Audacity: 3).",
        ge=1,
        le=1000,
    )
    stop_threshold: int = param(
        3,
        label="Amostras para parar",
        unit="amostras",
        hint="Quantas amostras seguidas abaixo do teto fecham o trecho (padrão do Audacity: 3).",
        ge=1,
        le=1000,
    )
    ceiling_db: float = param(
        0.0,
        label="Teto",
        unit="dBFS",
        hint="O nível a partir do qual a amostra conta como estourada. 0 dBFS é o teto digital.",
        ge=-60.0,
        le=0.0,
    )

    def analyze(self, signal: Signal) -> ClippingResult:
        if signal.frames == 0:
            raise ValueError("não há amostras para conferir: o trecho está vazio")
        limit = db_to_linear(self.ceiling_db) - CEILING_TOLERANCE
        regions: list[ClipRegion] = []
        clipped = 0
        for index in range(signal.channels):
            mask = np.abs(signal.samples[:, index]) >= limit
            clipped += int(mask.sum())
            for first, last in clipped_regions(mask, self.start_threshold, self.stop_threshold):
                regions.append(
                    ClipRegion(
                        channel=index + 1,
                        start=round(first / signal.sample_rate, 6),
                        end=round((last + 1) / signal.sample_rate, 6),
                        samples=int(mask[first : last + 1].sum()),
                    )
                )
        regions.sort(key=lambda item: (item.start, item.channel))
        percent = 100.0 * clipped / signal.samples.size
        merged = merge_regions(regions)
        if merged:
            where = f"o primeiro em {merged[0][0]:.3f} s"
            channels = f" ({len(regions)} por canal)" if len(regions) != len(merged) else ""
            summary = f"{len(merged)} trecho(s) estourado(s){channels}; {where}."
        else:
            summary = "Nenhum trecho estourou o teto."
        return ClippingResult(
            analyzer=self.type,
            summary=summary,
            ceiling_db=self.ceiling_db,
            start_threshold=self.start_threshold,
            stop_threshold=self.stop_threshold,
            regions=regions,
            clipped_samples=clipped,
            clipped_percent=0.0 if math.isnan(percent) else round(percent, 4),
        )
