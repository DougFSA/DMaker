"""Os efeitos de equalização e filtros, a família "EQ and Filters" do Audacity: Graves e Agudos, EQ Gráfico, EQ por Curva,
passa-alta, passa-baixa, Notch, prateleiras de grave e de agudo e os filtros clássicos (Butterworth e Chebyshev).

Todos têm resposta de frequência calculada por conta pura (`has_response`), que a interface desenha sem rodar o ffmpeg.
Os filtros de poucos polos viram seções de segunda ordem (`analysis/iir.py`) aplicadas pelo `biquad` do ffmpeg; o EQ
Gráfico e o EQ por Curva viram uma curva por pontos no `firequalizer` (`analysis/eq_curve.py`). Os nomes, as faixas e os
padrões seguem os do Audacity, e o comportamento é reproduzido por filtros do ffmpeg, não copiado do código dele.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import EPSILON, EffectBase, param, register_effect

# Os filtros aceitam de 1 Hz a 20 kHz, o fim do espectro audível (que também é o teto dos pontos da curva)
MIN_HZ = 1.0
MAX_HZ = 20000.0
# O EQ por Curva escreve os pontos no `firequalizer`, que só aceita 100 entradas: com os pontos cabem ao menos 50 amostras
MAX_CURVE_POINTS = 40
# Tamanho do filtro (FIR) do EQ Gráfico e do EQ por Curva, em amostras: os limites e o padrão são os do Audacity
MIN_FILTER_LENGTH = 21
MAX_FILTER_LENGTH = 8191
# As 31 bandas de terço de oitava do EQ Gráfico (série ISO, de 20 Hz a 20 kHz)
GRAPHIC_BANDS_HZ: tuple[float, ...] = (
    20.0, 25.0, 31.5, 40.0, 50.0, 63.0, 80.0, 100.0, 125.0, 160.0, 200.0, 250.0, 315.0, 400.0, 500.0, 630.0,
    800.0, 1000.0, 1250.0, 1600.0, 2000.0, 2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 8000.0, 10000.0, 12500.0,
    16000.0, 20000.0,
)  # fmt: skip
GRAPHIC_BAND_COUNT = len(GRAPHIC_BANDS_HZ)
GRAPHIC_GAIN_LIMIT_DB = 20.0
CURVE_GAIN_LIMIT_DB = 40.0


def _format_hz(hz: float) -> str:
    return f"{hz / 1000:g}k" if hz >= 1000 else f"{hz:g}"


class CurvePoint(BaseModel):
    """Um ponto da curva do EQ por Curva: a frequência (Hz) e o ganho nela (dB)."""

    model_config = ConfigDict(extra="forbid")

    hz: float = Field(ge=20.0, le=MAX_HZ)
    db: float = Field(ge=-CURVE_GAIN_LIMIT_DB, le=CURVE_GAIN_LIMIT_DB)


class EqEffect(EffectBase):
    """O que os efeitos do EQ têm em comum: a resposta de frequência conhecida. Não é registrado."""

    has_response: ClassVar[bool] = True


# ---------- Graves e Agudos, prateleiras ----------


@register_effect
class BassTreble(EqEffect):
    """Sobe ou desce os graves (prateleira em 250 Hz) e os agudos (prateleira em 4 kHz) e acerta o volume depois."""

    type: Literal["bass_treble"] = "bass_treble"
    label: ClassVar[str] = "Graves e agudos"
    audacity_name: ClassVar[str] = "Bass and Treble"
    summary: ClassVar[str] = (
        "Sobe ou desce os graves (abaixo de 250 Hz) e os agudos (acima de 4 kHz) e ajusta o volume no fim."
    )

    bass_db: float = param(0.0, label="Graves", unit="dB", hint="Ganho abaixo de 250 Hz.", ge=-30.0, le=30.0)
    treble_db: float = param(0.0, label="Agudos", unit="dB", hint="Ganho acima de 4 kHz.", ge=-30.0, le=30.0)
    volume_db: float = param(
        0.0, label="Volume", unit="dB", hint="Ganho aplicado depois dos dois ajustes.", ge=-30.0, le=30.0
    )


@register_effect
class LowShelf(EqEffect):
    """Prateleira de graves: muda em `gain_db` tudo abaixo da frequência."""

    type: Literal["low_shelf"] = "low_shelf"
    label: ClassVar[str] = "Prateleira de graves"
    audacity_name: ClassVar[str] = "Low Shelf"
    summary: ClassVar[str] = "Sobe ou desce, em dB, tudo abaixo de uma frequência, com transição suave."

    frequency_hz: float = param(
        200.0, label="Frequência", unit="Hz", hint="Onde a prateleira muda.", ge=MIN_HZ, le=MAX_HZ
    )
    gain_db: float = param(
        6.0, label="Ganho", unit="dB", hint="Positivo realça, negativo corta.", ge=-40.0, le=40.0
    )
    slope: float = param(
        1.0,
        label="Inclinação",
        hint="1 é a transição mais firme sem ondulação; valores menores abrem a transição.",
        ge=0.1,
        le=1.0,
    )


@register_effect
class HighShelf(EqEffect):
    """Prateleira de agudos: muda em `gain_db` tudo acima da frequência."""

    type: Literal["high_shelf"] = "high_shelf"
    label: ClassVar[str] = "Prateleira de agudos"
    audacity_name: ClassVar[str] = "High Shelf"
    summary: ClassVar[str] = "Sobe ou desce, em dB, tudo acima de uma frequência, com transição suave."

    frequency_hz: float = param(
        4000.0, label="Frequência", unit="Hz", hint="Onde a prateleira muda.", ge=MIN_HZ, le=MAX_HZ
    )
    gain_db: float = param(
        6.0, label="Ganho", unit="dB", hint="Positivo realça, negativo corta.", ge=-40.0, le=40.0
    )
    slope: float = param(
        1.0,
        label="Inclinação",
        hint="1 é a transição mais firme sem ondulação; valores menores abrem a transição.",
        ge=0.1,
        le=1.0,
    )


# ---------- passa-alta, passa-baixa, notch ----------


class _SlopedFilter(EqEffect):
    """O que o passa-alta e o passa-baixa têm em comum: a frequência de corte e a inclinação em dB por oitava."""

    slope_db: Literal[6, 12, 18, 24, 30, 36, 42, 48] = param(
        6,
        label="Inclinação",
        unit="dB/oitava",
        hint="Quão rápido o som cai depois do corte: 6 é suave, 48 é quase um muro.",
    )

    @field_validator("slope_db", mode="before")
    @classmethod
    def _number(cls, value: object) -> object:
        """A interface manda a escolha como texto ("24"); a spec guarda o número."""
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
        return value


@register_effect
class Highpass(_SlopedFilter):
    """Deixa passar o que está acima da frequência de corte e derruba os graves abaixo dela."""

    type: Literal["highpass"] = "highpass"
    label: ClassVar[str] = "Passa-alta"
    audacity_name: ClassVar[str] = "High-Pass Filter"
    summary: ClassVar[str] = "Corta os graves abaixo da frequência (ronco, vento, estouro de microfone)."

    frequency_hz: float = param(
        100.0, label="Frequência de corte", unit="Hz", hint="Abaixo dela o som cai.", ge=MIN_HZ, le=MAX_HZ
    )


@register_effect
class Lowpass(_SlopedFilter):
    """Deixa passar o que está abaixo da frequência de corte e derruba os agudos acima dela."""

    type: Literal["lowpass"] = "lowpass"
    label: ClassVar[str] = "Passa-baixa"
    audacity_name: ClassVar[str] = "Low-Pass Filter"
    summary: ClassVar[str] = "Corta os agudos acima da frequência (chiado, voz abafada de propósito)."

    frequency_hz: float = param(
        1000.0, label="Frequência de corte", unit="Hz", hint="Acima dela o som cai.", ge=MIN_HZ, le=MAX_HZ
    )


@register_effect
class Notch(EqEffect):
    """Rejeita uma frequência só, num corte estreito, sem mexer no som em volta."""

    type: Literal["notch"] = "notch"
    label: ClassVar[str] = "Notch"
    audacity_name: ClassVar[str] = "Notch Filter"
    summary: ClassVar[str] = (
        "Tira uma frequência (o zumbido de 60 Hz da rede) e deixa a voz em volta intacta."
    )

    frequency_hz: float = param(
        60.0,
        label="Frequência",
        unit="Hz",
        hint="O que sai: 60 Hz (50 Hz em alguns países).",
        ge=MIN_HZ,
        le=MAX_HZ,
    )
    q: float = param(
        1.0,
        label="Q",
        hint="Estreiteza do corte: 1 é largo, 10 a 30 só pega o zumbido.",
        ge=0.1,
        le=100.0,
    )


# ---------- filtros clássicos ----------


@register_effect
class ClassicFilter(EqEffect):
    """Passa-baixa ou passa-alta de ordem escolhida, Butterworth (sem ondulação), Chebyshev I (ondulação na banda
    passante) ou Chebyshev II (ondulação na banda de rejeição), como o "Classic Filters" do Audacity."""

    type: Literal["classic_filter"] = "classic_filter"
    label: ClassVar[str] = "Filtros clássicos"
    audacity_name: ClassVar[str] = "Classic Filters"
    summary: ClassVar[str] = (
        "Passa-baixa ou passa-alta Butterworth, Chebyshev I ou Chebyshev II, com a ordem e a ondulação à escolha."
    )

    family: Literal["butterworth", "chebyshev1", "chebyshev2"] = param(
        "butterworth",
        label="Família",
        hint="butterworth: sem ondulação; chebyshev1: corte mais firme, com ondulação na banda passante; "
        "chebyshev2: ondulação só na banda de rejeição.",
    )
    mode: Literal["lowpass", "highpass"] = param(
        "lowpass", label="Tipo", hint="lowpass deixa passar os graves; highpass, os agudos."
    )
    order: int = param(
        1,
        label="Ordem",
        hint="Número de polos: cada um acrescenta 6 dB por oitava de inclinação.",
        ge=1,
        le=10,
    )
    frequency_hz: float = param(
        1000.0,
        label="Frequência de corte",
        unit="Hz",
        hint="Butterworth: queda de 3 dB; chebyshev1: fim da banda passante; chebyshev2: começo da rejeição.",
        ge=MIN_HZ,
        le=MAX_HZ,
    )
    ripple_db: float = param(
        1.0,
        label="Ondulação da banda passante",
        unit="dB",
        hint="Só vale no chebyshev1.",
        ge=0.01,
        le=20.0,
    )
    stopband_db: float = param(
        30.0,
        label="Rejeição mínima",
        unit="dB",
        hint="Só vale no chebyshev2: quanto a banda de rejeição cai, no mínimo.",
        ge=1.0,
        le=120.0,
    )


# ---------- EQ Gráfico e EQ por Curva ----------


@register_effect
class GraphicEq(EqEffect):
    """Um controle de ganho (-20 a +20 dB) para cada uma das 31 bandas de terço de oitava, de 20 Hz a 20 kHz."""

    type: Literal["graphic_eq"] = "graphic_eq"
    label: ClassVar[str] = "EQ gráfico"
    audacity_name: ClassVar[str] = "Graphic EQ"
    summary: ClassVar[str] = "31 bandas de terço de oitava, de 20 Hz a 20 kHz, cada uma de -20 a +20 dB."

    gains_db: list[Annotated[float, Field(ge=-GRAPHIC_GAIN_LIMIT_DB, le=GRAPHIC_GAIN_LIMIT_DB)]] = param(
        [0.0] * GRAPHIC_BAND_COUNT,
        label="Ganho por banda",
        unit="dB",
        hint="Os 31 ganhos, da banda de 20 Hz à de 20 kHz.",
        kind="band_gains",
        low=-GRAPHIC_GAIN_LIMIT_DB,
        high=GRAPHIC_GAIN_LIMIT_DB,
        options=[_format_hz(hz) for hz in GRAPHIC_BANDS_HZ],
        min_length=GRAPHIC_BAND_COUNT,
        max_length=GRAPHIC_BAND_COUNT,
    )
    interpolation: Literal["bands", "cubic", "cosine", "linear"] = param(
        "bands",
        label="Desenho da curva",
        hint="bands: cada banda mantém o ganho dela; cubic, cosine e linear: uma curva liga os controles.",
    )
    length: int = param(
        MAX_FILTER_LENGTH,
        label="Tamanho do filtro",
        unit="amostras",
        hint="Mais longo separa melhor os graves; mais curto responde mais rápido.",
        ge=MIN_FILTER_LENGTH,
        le=MAX_FILTER_LENGTH,
    )


@register_effect
class FilterCurveEq(EqEffect):
    """Uma curva livre de ganho por frequência, desenhada por pontos (Hz, dB)."""

    type: Literal["filter_curve_eq"] = "filter_curve_eq"
    label: ClassVar[str] = "EQ por curva"
    audacity_name: ClassVar[str] = "Filter Curve EQ"
    summary: ClassVar[str] = (
        "Curva livre de ganho por frequência, por pontos, em escala linear ou logarítmica."
    )

    points: list[CurvePoint] = param(
        [CurvePoint(hz=20.0, db=0.0), CurvePoint(hz=MAX_HZ, db=0.0)],
        label="Pontos da curva",
        unit="Hz / dB",
        hint="Cada ponto é uma frequência e o ganho nela; fora do primeiro e do último o ganho se mantém.",
        kind="freq_points",
        low=-CURVE_GAIN_LIMIT_DB,
        high=CURVE_GAIN_LIMIT_DB,
        min_length=1,
        max_length=MAX_CURVE_POINTS,
    )
    scale: Literal["log", "linear"] = param(
        "log", label="Escala", hint="log: a curva é traçada por oitavas; linear: por Hz."
    )
    interpolation: Literal["cubic", "cosine", "linear"] = param(
        "cubic", label="Interpolação", hint="Como a curva liga um ponto ao seguinte."
    )
    length: int = param(
        MAX_FILTER_LENGTH,
        label="Tamanho do filtro",
        unit="amostras",
        hint="Mais longo separa melhor os graves; mais curto responde mais rápido.",
        ge=MIN_FILTER_LENGTH,
        le=MAX_FILTER_LENGTH,
    )

    @model_validator(mode="after")
    def _ordered_points(self) -> FilterCurveEq:
        ordered = sorted(self.points, key=lambda point: point.hz)
        for before, after in zip(ordered, ordered[1:], strict=False):
            if after.hz - before.hz <= EPSILON:
                raise ValueError(
                    f"efeito filter_curve_eq: dois pontos na mesma frequência ({after.hz:g} Hz); use frequências diferentes"
                )
        self.points = ordered
        return self
