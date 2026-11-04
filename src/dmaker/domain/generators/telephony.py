"""DTMF: os tons do teclado do telefone (toque de discagem), com a tabela de frequências pura."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import field_validator

from .base import GeneratorBase, param, register_generator

# A tabela do padrão DTMF (ITU-T Q.23): cada tecla soa uma frequência grave (a linha) e uma aguda (a coluna) juntas
DTMF_ROWS = (697.0, 770.0, 852.0, 941.0)
DTMF_COLUMNS = (1209.0, 1336.0, 1477.0, 1633.0)
DTMF_KEYS = ("123A", "456B", "789C", "*0#D")
DTMF_FREQUENCIES: dict[str, tuple[float, float]] = {
    key: (DTMF_ROWS[row], DTMF_COLUMNS[column])
    for row, keys in enumerate(DTMF_KEYS)
    for column, key in enumerate(keys)
}

# O tempo que cada tecla ocupa (tom mais silêncio) quando ninguém fixa a duração do item: o de uma discagem rápida
SLOT_SECONDS = 0.25


def dtmf_pair(key: str) -> tuple[float, float]:
    """As duas frequências (grave, aguda) de uma tecla; erro em português para o que o teclado não tem."""
    try:
        return DTMF_FREQUENCIES[key.upper()]
    except KeyError:
        raise ValueError(f"tecla DTMF desconhecida: {key!r}. Use 0-9, *, # e A-D") from None


@register_generator
class Dtmf(GeneratorBase):
    """A sequência de teclas do telefone, cada uma um par de tons seguido de um silêncio."""

    type: Literal["dtmf"] = "dtmf"
    label: ClassVar[str] = "Tons DTMF"
    audacity_name: ClassVar[str] = "DTMF Tones"
    summary: ClassVar[str] = (
        "O som das teclas de um telefone: cada dígito (0-9, *, #, A-D) é um par de tons, e a duração do item "
        "se divide por igual entre as teclas."
    )
    family: ClassVar[str] = "telefonia"
    has_natural_duration: ClassVar[bool] = True

    sequence: str = param(
        "123",
        label="Sequência",
        kind="text",
        hint="As teclas a tocar: dígitos 0-9, * e # e as letras A a D do teclado completo.",
        min_length=1,
        max_length=200,
    )
    amplitude_db: float = param(
        -2.0,
        label="Amplitude",
        unit="dBFS",
        hint="Pico do par de tons somado.",
        ge=-100.0,
        le=0.0,
    )
    tone_percent: float = param(
        55.0,
        label="Proporção de tom",
        unit="%",
        hint="Quanto de cada tecla é tom; o resto é silêncio entre as teclas.",
        gt=0.0,
        le=100.0,
    )

    def describe(self) -> str:
        return f"{self.label} {self.sequence}"

    @field_validator("sequence")
    @classmethod
    def _keys(cls, value: str) -> str:
        """As teclas em maiúsculas, recusando o que o teclado não tem: o erro diz qual tecla."""
        keys = value.upper()
        for key in keys:
            dtmf_pair(key)
        return keys

    def natural_duration(self, resolve: Callable[[str], Path] | None = None) -> float:
        return len(self.sequence) * SLOT_SECONDS
