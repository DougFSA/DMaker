"""Exportar Amostras (Sample Data Export): os valores das primeiras amostras do trecho, em texto ou CSV.

Serve para conferir à mão o que está num trecho curto (o começo de um estalo, o degrau de uma emenda). O limite de
quantidade existe porque um trecho de minutos tem milhões de amostras, que nenhum humano nem modelo lê.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

import numpy as np

from ..registry import AnalysisResult, AnalyzerBase, param, register_analyzer
from ..signal import Signal, linear_to_db

MAX_SAMPLES = 1_000_000


@dataclass(kw_only=True)
class SamplesResult(AnalysisResult):
    unit: str
    sample_rate: int
    channels: int
    start_sample: int
    count: int
    total_samples: int
    truncated: bool
    # uma linha por amostra: os valores de cada canal, na unidade pedida
    values: list[list[float]]

    def to_dict(self, detail: str = "compact", limit: int | None = None) -> dict:
        """O resultado com no máximo `limit` linhas de valores (200 por padrão); o arquivo e `detail="full"` levam todas."""
        data = {key: value for key, value in self.__dict__.items() if key != "values"}
        shown = self.values if detail == "full" else self.values[: limit or 200]
        data["values"] = shown
        data["values_shown"] = len(shown)
        return data

    def table(self, separator: str = ",") -> str:
        """Uma amostra por linha: o número dela, o instante e o valor de cada canal."""
        header = ["amostra", "tempo_s", *(f"canal_{n + 1}" for n in range(self.channels))]
        lines = [separator.join(header)]
        for offset, row in enumerate(self.values):
            index = self.start_sample + offset
            cells = [str(index), f"{index / self.sample_rate:.6f}", *(f"{value:.6f}" for value in row)]
            lines.append(separator.join(cells))
        return "\n".join(lines) + "\n"


@register_analyzer
class SampleDataExport(AnalyzerBase):
    """Lista o valor das primeiras amostras do trecho, por canal, em escala linear ou em dB."""

    type: Literal["samples"] = "samples"
    label: ClassVar[str] = "Exportar Amostras"
    audacity_name: ClassVar[str] = "Sample Data Export"
    summary: ClassVar[str] = (
        "Lista o valor das primeiras amostras do trecho, por canal, em escala linear ou em dB."
    )
    exports: ClassVar[tuple[str, ...]] = ("csv", "txt")

    limit: int = param(
        100,
        label="Limite de amostras",
        unit="amostras",
        hint="Quantas amostras listar, a partir do começo do trecho (padrão do Audacity: 100).",
        ge=1,
        le=MAX_SAMPLES,
    )
    unit: Literal["linear", "db"] = param(
        "linear", label="Escala", hint="linear (de -1 a 1) ou db (dBFS do módulo da amostra)."
    )

    def analyze(self, signal: Signal) -> SamplesResult:
        if signal.frames == 0:
            raise ValueError("não há amostras para listar: o trecho está vazio")
        chosen = signal.samples[: self.limit]
        values = np.asarray(linear_to_db(chosen) if self.unit == "db" else chosen, dtype=np.float64)
        return SamplesResult(
            analyzer=self.type,
            summary=f"{len(chosen)} amostra(s) de {signal.frames}, em escala {'dB' if self.unit == 'db' else 'linear'}.",
            unit=self.unit,
            sample_rate=signal.sample_rate,
            channels=signal.channels,
            start_sample=0,
            count=len(chosen),
            total_samples=signal.frames,
            truncated=signal.frames > len(chosen),
            values=[[round(float(v), 6) for v in row] for row in values],
        )
