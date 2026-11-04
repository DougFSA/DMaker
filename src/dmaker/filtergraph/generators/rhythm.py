"""A Faixa de Ritmo em numpy: o instante de cada batida sai da conta do andamento, e cada tipo de batida é um estouro curto."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ...domain.generators.rhythm import RhythmTrack
from .instruments import scaled_to_peak
from .registry import FilterSource, GeneratorRequest, register_generator_builder
from .tones import db_to_linear

# Um tempo fraco soa 6 dB abaixo do destacado: a diferença que o ouvido lê como "este é o um" sem esconder os outros
WEAK_BEAT_DB = -6.0
# O destaque também é mais agudo, em razão: uma quinta acima (3/2) separa o um dos outros sem soar desafinado
ACCENT_PITCH_RATIO = 1.5


def beat_positions(tempo_bpm: float, beats: int, sample_rate: int) -> list[int]:
    """A amostra em que cada batida começa: `n · 60/andamento` segundos, arredondado à amostra. Contado do começo e não
    somando intervalos, para o erro não crescer com o número de batidas."""
    return [round(index * 60.0 / tempo_bpm * sample_rate) for index in range(beats)]


def _decaying_sine(frequency: float, seconds: float, sample_rate: int, rt60: float) -> np.ndarray:
    t = np.arange(round(seconds * sample_rate)) / sample_rate
    return np.sin(2 * np.pi * frequency * t) * np.exp(-6.9078 * t / rt60)


def _metronome(pitch: float, sample_rate: int) -> np.ndarray:
    """O clique de madeira: um seno de 1 kHz que morre em 40 ms."""
    return _decaying_sine(1000.0 * pitch, 0.05, sample_rate, 0.04)


def _ping(pitch: float, sample_rate: int) -> np.ndarray:
    """Um tom limpo que decai em 150 ms."""
    return _decaying_sine(880.0 * pitch, 0.2, sample_rate, 0.15)


def _cowbell(pitch: float, sample_rate: int) -> np.ndarray:
    """Dois parciais inarmônicos (a razão 1,48 é a do sino de vaca clássico) com decaimento curto."""
    return _decaying_sine(540.0 * pitch, 0.2, sample_rate, 0.12) + _decaying_sine(
        540.0 * 1.48 * pitch, 0.2, sample_rate, 0.12
    )


def _noise_click(pitch: float, sample_rate: int) -> np.ndarray:
    """Um estouro de ruído de 10 ms; o destaque é mais agudo por um filtro de uma polo, que deixa passar o agudo."""
    generator = np.random.default_rng(7)
    burst = generator.standard_normal(round(0.012 * sample_rate))
    burst *= np.exp(-6.9078 * np.arange(burst.size) / sample_rate / 0.01)
    if pitch > 1.0:
        burst = np.diff(burst, prepend=0.0)
    return burst


def _drip(pitch: float, sample_rate: int) -> np.ndarray:
    """A gota: um seno que sobe de tom rápido e morre em 80 ms."""
    t = np.arange(round(0.12 * sample_rate)) / sample_rate
    start, end = 600.0 * pitch, 1800.0 * pitch
    glide = 0.04  # a subida de tom dura 40 ms
    phase = start * t + (end - start) * (t - glide * (1.0 - np.exp(-t / glide)))
    return np.sin(2 * np.pi * phase) * np.exp(-6.9078 * t / 0.08)


BEAT_SOUNDS: dict[str, Callable[[float, int], np.ndarray]] = {
    "metronome": _metronome,
    "ping": _ping,
    "cowbell": _cowbell,
    "noise_click": _noise_click,
    "drip": _drip,
}


@register_generator_builder("rhythm_track")
def build_rhythm_track(request: GeneratorRequest) -> FilterSource | np.ndarray:
    track = request.generator
    assert isinstance(track, RhythmTrack)
    make = BEAT_SOUNDS[track.beat_sound]
    peak = db_to_linear(track.amplitude_db)
    accent = scaled_to_peak(make(ACCENT_PITCH_RATIO if track.accent_first else 1.0, request.sample_rate), 0.0)
    regular = scaled_to_peak(make(1.0, request.sample_rate), 0.0) * db_to_linear(WEAK_BEAT_DB)
    out = np.zeros(request.frames, dtype=np.float64)
    for index, begin in enumerate(beat_positions(track.tempo_bpm, track.beats, request.sample_rate)):
        if begin >= request.frames:
            break
        strong = track.accent_first and index % track.beats_per_measure == 0
        burst = accent if strong else regular
        if not track.accent_first:
            burst = scaled_to_peak(burst, 0.0)  # sem destaque todas as batidas têm o mesmo nível
        length = min(burst.size, request.frames - begin)
        out[begin : begin + length] += burst[:length]
    return peak * out
