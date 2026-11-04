"""A Faixa de Ritmo: um metrônomo com compasso e destaque no primeiro tempo."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Literal

from .base import GeneratorBase, param, register_generator
from .tones import DEFAULT_AMPLITUDE_DB


@register_generator
class RhythmTrack(GeneratorBase):
    """Uma batida por tempo, no andamento e no compasso pedidos; o primeiro tempo de cada compasso pode soar diferente."""

    type: Literal["rhythm_track"] = "rhythm_track"
    label: ClassVar[str] = "Faixa de ritmo"
    audacity_name: ClassVar[str] = "Rhythm Track"
    summary: ClassVar[str] = (
        "Um metrônomo: uma batida por tempo no andamento pedido, com o primeiro tempo do compasso destacado."
    )
    family: ClassVar[str] = "ritmo"
    has_natural_duration: ClassVar[bool] = True

    tempo_bpm: float = param(
        120.0, label="Andamento", unit="BPM", hint="Batidas por minuto.", ge=30.0, le=300.0
    )
    beats_per_measure: int = param(
        4, label="Tempos por compasso", hint="De quantos em quantos tempos o destaque se repete.", ge=1, le=20
    )
    beats: int = param(
        16,
        label="Número de batidas",
        hint="Quantas batidas tocar; depois delas, silêncio até o fim do item.",
        ge=1,
        le=4000,
    )
    beat_sound: Literal["metronome", "ping", "cowbell", "noise_click", "drip"] = param(
        "metronome",
        label="Tipo de batida",
        hint="metronome (clique de madeira), ping (tom puro), cowbell (sino de vaca), noise_click (clique de "
        "ruído) ou drip (gota).",
    )
    accent_first: bool = param(
        True,
        label="Destacar o primeiro tempo",
        hint="O primeiro tempo de cada compasso soa mais agudo e mais forte.",
    )
    amplitude_db: float = param(
        DEFAULT_AMPLITUDE_DB,
        label="Amplitude",
        unit="dBFS",
        hint="Pico da batida destacada.",
        ge=-100.0,
        le=0.0,
    )

    def describe(self) -> str:
        return f"{self.label} {self.tempo_bpm:g} BPM"

    def natural_duration(self, resolve: Callable[[str], Path] | None = None) -> float:
        return round(self.beats * 60.0 / self.tempo_bpm, 6)
