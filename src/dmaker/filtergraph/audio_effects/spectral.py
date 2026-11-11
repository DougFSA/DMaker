"""Construtores dos efeitos espectrais (as classes estão em `domain/audio_effects/spectral.py`).

O Apagar Espectral é uma conta em numpy (`media/spectral.delete_rectangle`: STFT, máscara suavizada e soma de
sobreposição). Os outros três são filtros do ffmpeg: a emenda de 10 ms nas bordas do intervalo é a de qualquer efeito com
`start`/`end` (`chain.apply_effect`), então aqui só se escolhe o filtro pela faixa."""

from __future__ import annotations

import math

import numpy as np

from ...domain.audio_effects.spectral import (
    SpectralDelete,
    SpectralMultiTool,
    SpectralParametricEq,
    SpectralShelves,
)
from ...media.spectral import delete_rectangle
from .registry import EffectRequest, SampleRequest, register_builder, register_sample_builder

# Abaixo disto a "frequência central" de uma faixa que começa em 0 Hz seria 0 (a média geométrica zera): 1 Hz mantém a conta
MIN_CENTER_HZ = 1.0
# Um passa-alta ou passa-baixa de dois polos cai 12 dB por oitava, pouco para dizer que "tirou" o que ficou fora da
# borda, e um rejeita-banda de dois polos derruba só uns 29 dB num tom a 7 Hz do centro (medido); duas seções em série
# dobram os dB de atenuação (24 dB por oitava e 58 dB no tom)
CASCADE_SECTIONS = 2


def _band(low: float, high: float) -> tuple[float, float]:
    """O centro (média geométrica, como a escala do espectrograma) e a largura em Hz de uma faixa."""
    return math.sqrt(max(low, MIN_CENTER_HZ) * high), high - low


@register_sample_builder("spectral_delete")
def build_spectral_delete(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, SpectralDelete) and effect.start is not None and effect.end is not None
    low, high = effect.edges()
    first = round(effect.start * request.sample_rate)
    last = round(effect.end * request.sample_rate)
    return delete_rectangle(request.samples, request.sample_rate, first, last, low, high)


@register_builder("spectral_multi_tool")
def build_spectral_multi_tool(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, SpectralMultiTool)
    if effect.low_hz is not None and effect.high_hz is not None:
        center, width = _band(effect.low_hz, effect.high_hz)
        return request.chain(*[f"bandreject=f={center:.6f}:t=h:w={width:.6f}"] * CASCADE_SECTIONS)
    if effect.low_hz is not None:
        return request.chain(*[f"highpass=f={effect.low_hz:.6f}"] * CASCADE_SECTIONS)
    assert effect.high_hz is not None
    return request.chain(*[f"lowpass=f={effect.high_hz:.6f}"] * CASCADE_SECTIONS)


@register_builder("spectral_eq")
def build_spectral_eq(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert (
        isinstance(effect, SpectralParametricEq) and effect.low_hz is not None and effect.high_hz is not None
    )
    center, width = _band(effect.low_hz, effect.high_hz)
    return request.chain(f"equalizer=f={center:.6f}:t=h:w={width:.6f}:g={effect.gain_db:.6f}")


@register_builder("spectral_shelves")
def build_spectral_shelves(request: EffectRequest) -> list[str]:
    """Só a borda de baixo: prateleira alta a partir dela. Só a de cima: prateleira baixa até ela. As duas: sobe o ganho
    na de baixo e o desfaz na de cima, e o ganho fica entre as duas (como o Audacity descreve)."""
    effect = request.effect
    assert isinstance(effect, SpectralShelves)
    gain = effect.gain_db
    filters: list[str] = []
    if effect.low_hz is not None:
        filters.append(f"highshelf=f={effect.low_hz:.6f}:g={gain:.6f}")
    if effect.high_hz is not None and effect.low_hz is not None:
        filters.append(f"highshelf=f={effect.high_hz:.6f}:g={-gain:.6f}")
    elif effect.high_hz is not None:
        filters.append(f"lowshelf=f={effect.high_hz:.6f}:g={gain:.6f}")
    return request.chain(*filters)
