"""Os instrumentos sintetizados: Pluck (corda dedilhada) e Risset Drum (tambor).

Os nomes e os padrões seguem os do Audacity; o som é de síntese própria em numpy (`filtergraph.generators.instruments`),
que só reproduz o comportamento descrito no manual dele.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Literal

from .base import GeneratorBase, param, register_generator
from .tones import DEFAULT_AMPLITUDE_DB


@register_generator
class Pluck(GeneratorBase):
    """Uma nota de corda dedilhada, por nota MIDI."""

    type: Literal["pluck"] = "pluck"
    label: ClassVar[str] = "Pluck"
    audacity_name: ClassVar[str] = "Pluck"
    summary: ClassVar[str] = (
        "Uma nota de corda dedilhada: a altura é uma nota MIDI e o fim pode ser gradual ou seco."
    )
    family: ClassVar[str] = "instrumentos"

    midi_note: int = param(
        60, label="Nota MIDI", hint="60 é o dó central; 69 é o lá de 440 Hz.", ge=0, le=127
    )
    fade: Literal["gradual", "abrupt"] = param(
        "gradual",
        label="Fade",
        hint="gradual: a nota morre sozinha, até o fim do item; abrupt: corta seco no fim do item.",
    )
    amplitude_db: float = param(
        DEFAULT_AMPLITUDE_DB, label="Amplitude", unit="dBFS", hint="Pico da nota.", ge=-100.0, le=0.0
    )

    def natural_duration(self, resolve: Callable[[str], Path] | None = None) -> float:
        return 2.0  # uma corda dedilhada soa uns dois segundos


@register_generator
class RissetDrum(GeneratorBase):
    """Um tambor de Risset: parciais inarmônicos que decaem, misturados a uma faixa de ruído."""

    type: Literal["risset_drum"] = "risset_drum"
    label: ClassVar[str] = "Tambor de Risset"
    audacity_name: ClassVar[str] = "Risset Drum"
    summary: ClassVar[str] = (
        "Um tambor sintético de Jean-Claude Risset: uma frequência que decai, com uma faixa de ruído em volta de um centro."
    )
    family: ClassVar[str] = "instrumentos"

    frequency_hz: float = param(
        100.0, label="Frequência", unit="Hz", hint="Altura do tambor.", ge=1.0, le=5000.0
    )
    decay_s: float = param(
        2.0, label="Decaimento", unit="s", hint="Em quanto tempo o tambor perde 60 dB.", ge=0.05, le=30.0
    )
    noise_center_hz: float = param(
        500.0,
        label="Centro do ruído",
        unit="Hz",
        hint="Frequência central da faixa de ruído.",
        ge=1.0,
        le=20000.0,
    )
    noise_width_hz: float = param(
        1.0,
        label="Largura do ruído",
        unit="Hz",
        hint="Largura da faixa de ruído em volta do centro.",
        ge=1.0,
        le=20000.0,
    )
    noise_percent: float = param(
        80.0,
        label="Ruído na mistura",
        unit="%",
        hint="Quanto da mistura é a faixa de ruído.",
        ge=0.0,
        le=100.0,
    )
    amplitude_db: float = param(
        DEFAULT_AMPLITUDE_DB, label="Amplitude", unit="dBFS", hint="Pico do tambor.", ge=-100.0, le=0.0
    )

    def natural_duration(self, resolve: Callable[[str], Path] | None = None) -> float:
        return round(self.decay_s, 3)
