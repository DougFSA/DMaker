"""DTMF em numpy: cada tecla é a soma de dois senos (a linha e a coluna dela) seguida de um silêncio."""

from __future__ import annotations

import numpy as np

from ...domain.generators.telephony import Dtmf, dtmf_pair
from .registry import FilterSource, GeneratorRequest, register_generator_builder
from .tones import db_to_linear

# A rampa que abre e fecha cada tom: sem ela o corte seco estala, e 2 ms não mexem na detecção do dígito (um tom DTMF
# precisa de 40 ms para ser reconhecido, e o menor aqui, com 20 teclas em 1 s, tem 27 ms de tom)
EDGE_SECONDS = 0.002


def key_tone(key: str, frames: int, sample_rate: int) -> np.ndarray:
    """O tom de uma tecla: os dois senos somados, cada um com metade da amplitude (o pico da soma não passa de 1), e a
    rampa de 2 ms nas pontas."""
    low, high = dtmf_pair(key)
    t = np.arange(frames) / sample_rate
    tone = 0.5 * (np.sin(2 * np.pi * low * t) + np.sin(2 * np.pi * high * t))
    ramp = min(int(EDGE_SECONDS * sample_rate), frames // 2)
    if ramp > 0:
        edge = np.linspace(0.0, 1.0, ramp, endpoint=False)
        tone[:ramp] *= edge
        tone[-ramp:] *= edge[::-1]
    return tone


@register_generator_builder("dtmf")
def build_dtmf(request: GeneratorRequest) -> FilterSource | np.ndarray:
    dtmf = request.generator
    assert isinstance(dtmf, Dtmf)
    keys = dtmf.sequence
    out = np.zeros(request.frames, dtype=np.float64)
    slot = request.frames / len(keys)  # a duração do item se divide por igual entre as teclas
    amplitude = db_to_linear(dtmf.amplitude_db)
    for position, key in enumerate(keys):
        begin = round(position * slot)
        length = round(slot * dtmf.tone_percent / 100.0)
        length = min(length, request.frames - begin)
        if length > 0:
            out[begin : begin + length] = amplitude * key_tone(key, length, request.sample_rate)
    return out
