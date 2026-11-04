"""Construtores e respostas de frequência dos efeitos de equalização (as classes estão em `domain/audio_effects/eq.py`).

Um filtro, uma resposta, a mesma conta. Os filtros IIR (Graves e Agudos, prateleiras, passa-alta, passa-baixa, Notch e os
clássicos) são projetados em Python puro como seções de segunda ordem (`analysis/iir.py`): o construtor as entrega ao
`biquad` do ffmpeg, uma atrás da outra, e a resposta que a interface desenha sai das MESMAS seções. O EQ Gráfico e o EQ
por Curva são uma curva por pontos (`analysis/eq_curve.py`): o construtor a escreve no `gain_entry` do `firequalizer` e a
resposta desenhada é a mesma curva, sem rodar o ffmpeg.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ...analysis import eq_curve, iir
from ...domain.audio_effects import EffectBase
from ...domain.audio_effects.eq import (
    GRAPHIC_BANDS_HZ,
    BassTreble,
    ClassicFilter,
    FilterCurveEq,
    GraphicEq,
    Highpass,
    HighShelf,
    Lowpass,
    LowShelf,
    Notch,
)
from .registry import EffectRequest, register_builder, register_response

# A frequência e a inclinação das duas prateleiras do Graves e Agudos: os valores do Audacity (250 Hz e 4 kHz), com a
# inclinação aberta (0,4) que dá o timbre largo dele, em vez da prateleira firme dos efeitos de prateleira avulsos
BASS_HZ = 250.0
TREBLE_HZ = 4000.0
BASS_TREBLE_SLOPE = 0.4

# No EQ Gráfico "por bandas", cada banda mantém o ganho dela dentro de ±1/8 de oitava do centro (a banda de terço de
# oitava tem ±1/6) e a transição para a vizinha ocupa o 1/12 de oitava que sobra, entre os dois patamares
BAND_PLATEAU_OCTAVES = 1.0 / 8.0

# Abaixo disto o ganho da curva é zero para quem a escreve: o filtro seria a identidade, e um FIR de milhares de
# amostras à toa só atrasaria o som
FLAT_DB = 1e-6


@dataclass(frozen=True)
class FilterDesign:
    """O que um filtro IIR é: a série de seções de segunda ordem e um ganho fixo em dB aplicado junto (`volume`)."""

    sections: tuple[iir.Biquad, ...]
    gain_db: float = 0.0


Designer = Callable[[EffectBase, int], FilterDesign]
_DESIGNS: dict[str, Designer] = {}


def designs(*names: str) -> Callable[[Designer], Designer]:
    """Registra o projeto do filtro sob o `type` de um ou mais efeitos: os dois consumidores (o construtor do ffmpeg e a
    resposta de frequência) leem daqui, e é isso que os mantém iguais."""

    def decorator(function: Designer) -> Designer:
        for name in names:
            _DESIGNS[name] = function
        return function

    return decorator


def design_of(effect: EffectBase, rate: int) -> FilterDesign:
    """As seções do filtro IIR de um efeito, na taxa dos efeitos."""
    return _DESIGNS[effect.type](effect, rate)


@designs("bass_treble")
def _bass_treble(effect: EffectBase, rate: int) -> FilterDesign:
    assert isinstance(effect, BassTreble)
    sections = []
    if effect.bass_db != 0:
        sections.append(iir.low_shelf(BASS_HZ, effect.bass_db, BASS_TREBLE_SLOPE, rate))
    if effect.treble_db != 0:
        sections.append(iir.high_shelf(TREBLE_HZ, effect.treble_db, BASS_TREBLE_SLOPE, rate))
    return FilterDesign(tuple(sections), effect.volume_db)


@designs("low_shelf")
def _low_shelf(effect: EffectBase, rate: int) -> FilterDesign:
    assert isinstance(effect, LowShelf)
    return FilterDesign((iir.low_shelf(effect.frequency_hz, effect.gain_db, effect.slope, rate),))


@designs("high_shelf")
def _high_shelf(effect: EffectBase, rate: int) -> FilterDesign:
    assert isinstance(effect, HighShelf)
    return FilterDesign((iir.high_shelf(effect.frequency_hz, effect.gain_db, effect.slope, rate),))


@designs("highpass")
def _highpass(effect: EffectBase, rate: int) -> FilterDesign:
    assert isinstance(effect, Highpass)
    return FilterDesign(tuple(iir.slope_sections("highpass", effect.slope_db, effect.frequency_hz, rate)))


@designs("lowpass")
def _lowpass(effect: EffectBase, rate: int) -> FilterDesign:
    assert isinstance(effect, Lowpass)
    return FilterDesign(tuple(iir.slope_sections("lowpass", effect.slope_db, effect.frequency_hz, rate)))


@designs("notch")
def _notch(effect: EffectBase, rate: int) -> FilterDesign:
    assert isinstance(effect, Notch)
    return FilterDesign((iir.notch(effect.frequency_hz, effect.q, rate),))


@designs("classic_filter")
def _classic(effect: EffectBase, rate: int) -> FilterDesign:
    assert isinstance(effect, ClassicFilter)
    sections = iir.classic_sections(
        effect.family,
        effect.mode,
        effect.order,
        effect.frequency_hz,
        rate,
        effect.ripple_db,
        effect.stopband_db,
    )
    return FilterDesign(tuple(sections))


@register_builder(*_DESIGNS)
def build_biquads(request: EffectRequest) -> list[str]:
    design = design_of(request.effect, request.sample_rate)
    filters = [section.ffmpeg_filter() for section in design.sections]
    if design.gain_db != 0:
        filters.append(f"volume={design.gain_db:.6f}dB")
    return request.chain(*(filters or ["anull"]))


@register_response(*_DESIGNS)
def biquad_response(effect: EffectBase, hz: np.ndarray, rate: int) -> np.ndarray:
    design = design_of(effect, rate)
    return iir.response_db(list(design.sections), hz, rate, design.gain_db)


# ---------- EQ Gráfico e EQ por Curva ----------


@dataclass(frozen=True)
class Curve:
    """A curva de um equalizador por pontos: onde estão os pontos, o ganho neles, a escala e o desenho entre eles."""

    hz: tuple[float, ...]
    db: tuple[float, ...]
    scale: eq_curve.Scale
    method: eq_curve.Method

    def at(self, hz: np.ndarray) -> np.ndarray:
        return eq_curve.interpolate_db(self.hz, self.db, hz, self.scale, self.method)


def curve_of(effect: EffectBase) -> Curve:
    """A curva que um efeito de EQ por pontos descreve. É a que o gráfico mostra e a que o `firequalizer` recebe."""
    if isinstance(effect, GraphicEq):
        if effect.interpolation != "bands":
            return Curve(GRAPHIC_BANDS_HZ, tuple(effect.gains_db), "log", effect.interpolation)
        # cada banda vira um patamar (dois pontos de mesmo ganho) ligado ao da vizinha por um trecho suave
        factor = 2.0**BAND_PLATEAU_OCTAVES
        hz = [edge for center in GRAPHIC_BANDS_HZ for edge in (center / factor, center * factor)]
        db = [gain for gain in effect.gains_db for _ in range(2)]
        return Curve(tuple(hz), tuple(db), "log", "cosine")
    assert isinstance(effect, FilterCurveEq)
    return Curve(
        tuple(point.hz for point in effect.points),
        tuple(point.db for point in effect.points),
        effect.scale,
        effect.interpolation,
    )


def _filter_length(effect: EffectBase) -> int:
    assert isinstance(effect, GraphicEq | FilterCurveEq)
    return effect.length


@register_builder("graphic_eq", "filter_curve_eq")
def build_curve_eq(request: EffectRequest) -> list[str]:
    """O `firequalizer` com a curva amostrada. Ele é um FIR de fase linear e devolve o som atrasado em metade do
    filtro, com a mesma metade a mais no fim; o `atrim` tira as duas, e a saída tem o comprimento da entrada."""
    curve = curve_of(request.effect)
    hz, db = eq_curve.curve_for_filter(curve.hz, curve.db, curve.scale, curve.method)
    if float(np.max(np.abs(db))) < FLAT_DB:
        return request.chain("anull")
    half = (_filter_length(request.effect) - 1) // 2
    # o ffmpeg faz o filtro de 2*int(taxa*atraso)+1 amostras: o quarto de amostra de folga protege o int() de um
    # arredondamento para baixo
    delay = (half + 0.25) / request.sample_rate
    return request.chain(
        f"firequalizer=gain_entry='{eq_curve.gain_entry(hz, db)}':delay={delay:.9f}",
        f"atrim=start_sample={half}:end_sample={half + request.samples}",
        "asetpts=PTS-STARTPTS",
    )


@register_response("graphic_eq", "filter_curve_eq")
def curve_response(effect: EffectBase, hz: np.ndarray, rate: int) -> np.ndarray:
    return curve_of(effect).at(hz)
