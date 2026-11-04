"""Importar Amostras: um texto com um valor por linha vira áudio (dados de laboratório, sinais de teste)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Literal

from .base import GeneratorBase, param, register_generator


@register_generator
class SampleData(GeneratorBase):
    """O áudio escrito amostra por amostra num arquivo de texto."""

    type: Literal["sample_data"] = "sample_data"
    label: ClassVar[str] = "Importar amostras"
    audacity_name: ClassVar[str] = "Sample Data Import"
    summary: ClassVar[str] = (
        "Lê um arquivo de texto com um valor por linha (de -1 a 1) e o toca como áudio, na taxa que você disser."
    )
    family: ClassVar[str] = "dados"
    has_natural_duration: ClassVar[bool] = True

    src: str = param(
        "dados.txt",
        label="Arquivo de texto",
        kind="text",
        hint="Um valor por linha, relativo à pasta do projeto. Linhas vazias e as que começam com # são ignoradas.",
        min_length=1,
    )
    sample_rate: int = param(
        44100,
        label="Taxa das amostras",
        unit="Hz",
        hint="Quantas linhas do arquivo valem um segundo de áudio.",
        ge=100,
        le=192000,
    )
    normalize: bool = param(
        False,
        label="Normalizar",
        hint="Ajusta os valores para o maior caber em 1. Desligado, um valor fora de -1 a 1 é recusado.",
    )

    def files(self) -> list[str]:
        return [self.src]

    def natural_duration(self, resolve: Callable[[str], Path] | None = None) -> float:
        """O tempo que as linhas do arquivo ocupam na taxa dada; sem o arquivo à mão, um segundo."""
        if resolve is None:
            return super().natural_duration()
        from ...filtergraph.generators.samples import read_sample_values

        values = read_sample_values(resolve(self.src))
        return max(round(len(values) / self.sample_rate, 6), 0.001)
