"""Pluck e Tambor de Risset em numpy: síntese aditiva, sem laço por amostra e sem sorteio fora de semente fixa.

Cada função devolve as amostras (o pico já no nível pedido) e é pura: o mesmo gerador dá sempre os mesmos números, o que
deixa o som em cache e os testes numéricos.
"""

from __future__ import annotations

import math

import numpy as np

from ...domain.generators.instruments import Pluck, RissetDrum
from .registry import FilterSource, GeneratorRequest, register_generator_builder
from .tones import db_to_linear

# Quanto um som decai nos "60 dB" do decaimento: a definição de tempo de reverberação (RT60), de 1 a 0,001 da amplitude
RT60_NEPERS = math.log(1000.0)
# Os harmônicos de uma corda param antes da metade da taxa: acima disso dobrariam de volta (aliasing)
MAX_HARMONIC_HZ_FRACTION = 0.45
# Quanto cada harmônico da corda decai mais depressa que o anterior: a corda real perde o agudo primeiro, e é isso que
# faz o som parecer dedilhado e não um órgão
PLUCK_BRIGHTNESS_LOSS = 0.5
# A corda solta (fade abrupto) decai assim, em segundos para -60 dB do fundamental, sem ajuda do fim do item
PLUCK_NATURAL_RT60 = 3.0
PLUCK_ATTACK_SECONDS = 0.002
# As razões dos modos de uma membrana circular (os zeros da função de Bessel): são elas que dão ao tambor de Risset o
# timbre sem altura definida, ao contrário dos harmônicos de uma corda
MEMBRANE_RATIOS = (1.0, 1.593, 2.136, 2.296, 2.653, 2.918)
MEMBRANE_LEVELS = (1.0, 0.6, 0.45, 0.35, 0.25, 0.2)
# O tambor começa agudo e cai ao tom: a pele esticada relaxa depois da batida
DRUM_PITCH_DROP = 0.4
DRUM_PITCH_DROP_SECONDS = 0.03
NOISE_SEED = 20240  # fixa: o ruído do tambor é o mesmo a cada render


def midi_to_hz(note: int) -> float:
    """A frequência de uma nota MIDI (afinação de concerto: o lá 69 é 440 Hz)."""
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def scaled_to_peak(samples: np.ndarray, peak_db: float) -> np.ndarray:
    """O sinal levado a um pico em dBFS; sinal mudo fica mudo."""
    top = float(np.max(np.abs(samples))) if samples.size else 0.0
    return samples if top == 0.0 else samples * (db_to_linear(peak_db) / top)


def pluck_samples(pluck: Pluck, frames: int, sample_rate: int) -> np.ndarray:
    """A corda dedilhada: a soma dos harmônicos da nota (amplitude 1/k), cada um decaindo mais depressa que o anterior.
    `gradual` ajusta o decaimento para a nota chegar a -60 dB no fim do item; `abrupt` deixa a corda soar como soaria e
    corta no fim do item."""
    frequency = midi_to_hz(pluck.midi_note)
    t = np.arange(frames) / sample_rate
    duration = max(frames / sample_rate, 1e-3)
    rt60 = duration if pluck.fade == "gradual" else PLUCK_NATURAL_RT60
    out = np.zeros(frames, dtype=np.float64)
    harmonic = 1
    while harmonic * frequency < MAX_HARMONIC_HZ_FRACTION * sample_rate:
        loss = 1.0 + PLUCK_BRIGHTNESS_LOSS * (harmonic - 1)
        decay = np.exp(-RT60_NEPERS * loss * t / rt60)
        out += np.sin(2 * np.pi * harmonic * frequency * t) * decay / harmonic
        harmonic += 1
    attack = min(int(PLUCK_ATTACK_SECONDS * sample_rate), frames)
    if attack:
        out[:attack] *= np.linspace(0.0, 1.0, attack, endpoint=False)
    return scaled_to_peak(out, pluck.amplitude_db)


def band_noise(frames: int, sample_rate: int, center_hz: float, width_hz: float) -> np.ndarray:
    """Ruído de semente fixa limitado a uma faixa (`center_hz` ± `width_hz`/2), recortando o espectro de um ruído branco. Com
    uma faixa mais estreita que o intervalo entre dois pontos do espectro, fica o ponto mais próximo do centro."""
    white = np.random.default_rng(NOISE_SEED).standard_normal(frames)
    spectrum = np.fft.rfft(white)
    frequencies = np.fft.rfftfreq(frames, 1.0 / sample_rate)
    keep = np.abs(frequencies - center_hz) <= width_hz / 2.0
    if not keep.any():
        keep[int(np.argmin(np.abs(frequencies - center_hz)))] = True
    spectrum[~keep] = 0.0
    return np.fft.irfft(spectrum, n=frames)


def risset_drum_samples(drum: RissetDrum, frames: int, sample_rate: int) -> np.ndarray:
    """O tambor: os modos de uma membrana, cada um com o seu decaimento (os agudos somem antes) e uma queda de tom no
    começo, misturados à faixa de ruído que decai no tempo do tambor. Cada metade é levada a pico 1 antes da mistura, para
    `noise_percent` ser a proporção de verdade e não depender de quanto cada uma rende."""
    t = np.arange(frames) / sample_rate
    envelope = np.exp(-RT60_NEPERS * t / drum.decay_s)
    tonal = np.zeros(frames, dtype=np.float64)
    for index, (ratio, level) in enumerate(zip(MEMBRANE_RATIOS, MEMBRANE_LEVELS, strict=True)):
        mode_hz = drum.frequency_hz * ratio
        if mode_hz >= MAX_HARMONIC_HZ_FRACTION * sample_rate:
            break
        # a frequência é `modo·(1 + queda·e^(-t/τ))`; a fase é a integral dela, e com a queda exponencial a conta fechada é esta
        settle = 1.0 - np.exp(-t / DRUM_PITCH_DROP_SECONDS)
        phase = mode_hz * (t + DRUM_PITCH_DROP * DRUM_PITCH_DROP_SECONDS * settle)
        decay = np.exp(-RT60_NEPERS * (1.0 + 0.5 * index) * t / drum.decay_s)
        tonal += level * np.sin(2 * np.pi * phase) * decay
    noise = band_noise(frames, sample_rate, drum.noise_center_hz, drum.noise_width_hz) * envelope
    mix = drum.noise_percent / 100.0
    tonal_part = scaled_to_peak(tonal, 0.0)
    noise_part = scaled_to_peak(noise, 0.0)
    return scaled_to_peak((1.0 - mix) * tonal_part + mix * noise_part, drum.amplitude_db)


@register_generator_builder("pluck")
def build_pluck(request: GeneratorRequest) -> FilterSource | np.ndarray:
    assert isinstance(request.generator, Pluck)
    return pluck_samples(request.generator, request.frames, request.sample_rate)


@register_generator_builder("risset_drum")
def build_risset_drum(request: GeneratorRequest) -> FilterSource | np.ndarray:
    assert isinstance(request.generator, RissetDrum)
    return risset_drum_samples(request.generator, request.frames, request.sample_rate)
