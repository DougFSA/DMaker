"""Os geradores de sinal: Tom, Chirp, Ruído e Silêncio.

Os nomes e os padrões seguem os do Audacity (menu Gerar); o nível é em dBFS, como o resto do DMaker (o `amplitude` de 0 a 1
do Audacity é `10^(dB/20)`: 0,8 é -1,9 dB). O som sai de `filtergraph.generators.tones`: fontes do ffmpeg para Tom,
Chirp e Ruído, e zeros em numpy para o Silêncio.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from .base import GeneratorBase, param, register_generator

# O padrão de amplitude do Audacity (0,8 linear) em dB, arredondado: 20·log10(0,8) = -1,94
DEFAULT_AMPLITUDE_DB = -2.0
# Acima disto uma onda quadrada ou serrilhada já não cabe na taxa da mixagem (24 kHz, a metade dela): o limite prático
MAX_FREQUENCY_HZ = 20000.0

NOISE_NAMES = {"white": "branco", "pink": "rosa", "brown": "marrom"}
Waveform = Literal["sine", "square", "sawtooth", "square_bandlimited"]
# O que o catálogo mostra para cada onda: o nome do Audacity vai na dica
WAVEFORM_HINT = (
    "sine (senoidal), square (quadrada), sawtooth (dente de serra) ou square_bandlimited "
    "(quadrada sem aliasing, como o 'Square, no alias' do Audacity)."
)


@register_generator
class Tone(GeneratorBase):
    """Uma onda de frequência fixa."""

    type: Literal["tone"] = "tone"
    label: ClassVar[str] = "Tom"
    audacity_name: ClassVar[str] = "Tone"
    summary: ClassVar[str] = (
        "Uma onda senoidal, quadrada, dente de serra ou quadrada sem aliasing, numa frequência e num nível."
    )
    family: ClassVar[str] = "tons"

    waveform: Waveform = param("sine", label="Onda", hint=WAVEFORM_HINT)
    frequency_hz: float = param(
        440.0, label="Frequência", unit="Hz", hint="Altura do tom.", ge=1.0, le=MAX_FREQUENCY_HZ
    )
    amplitude_db: float = param(
        DEFAULT_AMPLITUDE_DB,
        label="Amplitude",
        unit="dBFS",
        hint="Pico do tom: 0 é o máximo possível, -6 é a metade da amplitude.",
        ge=-100.0,
        le=0.0,
    )

    def describe(self) -> str:
        return f"{self.label} {self.frequency_hz:g} Hz"


@register_generator
class Chirp(GeneratorBase):
    """Uma onda cuja frequência e amplitude vão de um valor a outro ao longo da duração do item."""

    type: Literal["chirp"] = "chirp"
    label: ClassVar[str] = "Chirp"
    audacity_name: ClassVar[str] = "Chirp"
    summary: ClassVar[str] = (
        "Uma varredura: a frequência e a amplitude vão de um valor inicial a um final, em linha reta ou em escala log."
    )
    family: ClassVar[str] = "tons"

    waveform: Waveform = param("sine", label="Onda", hint=WAVEFORM_HINT)
    start_hz: float = param(
        440.0,
        label="Frequência inicial",
        unit="Hz",
        hint="Onde a varredura começa.",
        ge=1.0,
        le=MAX_FREQUENCY_HZ,
    )
    end_hz: float = param(
        1320.0,
        label="Frequência final",
        unit="Hz",
        hint="Onde a varredura termina.",
        ge=1.0,
        le=MAX_FREQUENCY_HZ,
    )
    start_db: float = param(
        DEFAULT_AMPLITUDE_DB,
        label="Amplitude inicial",
        unit="dBFS",
        hint="Pico no começo.",
        ge=-100.0,
        le=0.0,
    )
    end_db: float = param(-20.0, label="Amplitude final", unit="dBFS", hint="Pico no fim.", ge=-100.0, le=0.0)
    interpolation: Literal["linear", "logarithmic"] = param(
        "linear",
        label="Interpolação",
        hint="linear: a frequência anda por igual em Hz; logarithmic: por igual em oitavas (a altura sobe sem pressa).",
    )

    def describe(self) -> str:
        return f"{self.label} {self.start_hz:g} a {self.end_hz:g} Hz"


@register_generator
class Noise(GeneratorBase):
    """Ruído branco, rosa ou marrom."""

    type: Literal["noise"] = "noise"
    label: ClassVar[str] = "Ruído"
    audacity_name: ClassVar[str] = "Noise"
    summary: ClassVar[str] = (
        "Ruído branco (igual em todas as frequências), rosa (-3 dB por oitava) ou marrom (uns -6 dB por oitava acima de 400 Hz)."
    )
    family: ClassVar[str] = "ruído"

    noise_type: Literal["white", "pink", "brown"] = param(
        "white", label="Tipo de ruído", hint="white (branco), pink (rosa) ou brown (marrom, Browniano)."
    )
    amplitude_db: float = param(
        DEFAULT_AMPLITUDE_DB,
        label="Amplitude",
        unit="dBFS",
        hint="Nível de referência do ruído: o branco tem o pico exatamente aqui, e o rosa e o marrom, que juntam a energia nos "
        "graves, ficam uns 1 a 2 dB abaixo.",
        ge=-100.0,
        le=0.0,
    )
    seed: int = param(
        0,
        label="Semente",
        hint="A mesma semente dá o mesmo ruído a cada render (e deixa o som guardado em cache).",
        ge=0,
        le=2**31 - 1,
    )

    def describe(self) -> str:
        return f"{self.label} {NOISE_NAMES[self.noise_type]}"


@register_generator
class Silence(GeneratorBase):
    """Silêncio: abre espaço numa trilha."""

    type: Literal["silence"] = "silence"
    label: ClassVar[str] = "Silêncio"
    audacity_name: ClassVar[str] = "Silence"
    summary: ClassVar[str] = "Um trecho de silêncio com a duração do item, para abrir espaço numa trilha."
    family: ClassVar[str] = "tons"
