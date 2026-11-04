"""Tom, Chirp, Ruído e Silêncio.

Tom, Chirp e Ruído saem de fontes do ffmpeg (`aevalsrc` e `anoisesrc`): as expressões são montadas aqui como texto, sem
executar nada. A única onda que o ffmpeg não gera é a quadrada sem aliasing, feita em numpy (PolyBLEP); o Silêncio são zeros.
"""

from __future__ import annotations

import math

import numpy as np

from ...domain.generators.tones import Chirp, Noise, Silence, Tone
from .registry import FilterSource, GeneratorRequest, register_generator_builder


def db_to_linear(db: float) -> float:
    """Pico em dBFS como fração da escala cheia: 0 dB é 1, -6 dB é 0,501."""
    return 10.0 ** (db / 20.0)


def _number(value: float) -> str:
    """Um número como texto de expressão do ffmpeg: sem notação que o analisador dele não leia."""
    return f"{value:.12g}"


def wave_expression(waveform: str, cycles: str, amplitude: str) -> str:
    """A expressão do `aevalsrc` de uma onda: `cycles` é a fase em ciclos (`F*t`) e `amplitude` o fator de pico. A seno e a
    quadrada são as de livro; a serrilhada sobe de -1 a 1 a cada ciclo, como a do Audacity."""
    if waveform == "sine":
        return f"{amplitude}*sin(2*PI*({cycles}))"
    if waveform == "square":
        return f"{amplitude}*if(lt(mod({cycles},1),0.5),1,-1)"
    if waveform == "sawtooth":
        return f"{amplitude}*(2*mod({cycles},1)-1)"
    raise ValueError(f"onda {waveform!r} não tem expressão do ffmpeg")


def source_graph(expression: str, request: GeneratorRequest) -> FilterSource:
    """A fonte `aevalsrc` mono com a expressão: aspas simples protegem as vírgulas do grafo de filtros."""
    return FilterSource(
        f"aevalsrc=exprs='{expression}':sample_rate={request.sample_rate}:duration={_number(request.duration)}"
    )


def sweep_cycles(chirp: Chirp, duration: float) -> str:
    """A fase da varredura em ciclos como expressão de `t`. Linear: a frequência anda por igual em Hz, e a fase é a integral
    `f0·t + (f1-f0)·t²/(2T)`. Logarítmica: anda por igual em oitavas, `f(t) = f0·r^(t/T)`, e a fase é `f0·T/ln r·(r^(t/T) - 1)`."""
    f0, f1 = chirp.start_hz, chirp.end_hz
    if chirp.interpolation == "logarithmic" and not math.isclose(f0, f1):
        ratio = f1 / f0
        return f"{_number(f0 * duration / math.log(ratio))}*(pow({_number(ratio)},t/{_number(duration)})-1)"
    return f"{_number(f0)}*t+{_number((f1 - f0) / (2 * duration))}*t*t"


def sweep_amplitude(chirp: Chirp, duration: float) -> str:
    """O pico ao longo do tempo: a reta em dB do valor inicial ao final (a escala em que o ouvido a sente reta)."""
    slope = (chirp.end_db - chirp.start_db) / duration
    return f"pow(10,({_number(chirp.start_db)}+{_number(slope)}*t)/20)"


def blep(position: np.ndarray, step: np.ndarray | float) -> np.ndarray:
    """A correção PolyBLEP de um salto: suaviza as amostras vizinhas à descontinuidade (`position` é a fase em ciclos, de 0
    a 1, e `step` o avanço de fase por amostra). Vale 0 longe do salto."""
    step = np.maximum(step, 1e-12)
    rising = position < step
    falling = position > 1.0 - step
    low = position / step
    high = (position - 1.0) / step
    result = np.zeros_like(position)
    result = np.where(rising, low + low - low * low - 1.0, result)
    return np.where(falling, high * high + high + high + 1.0, result)


def bandlimited_square(cycles: np.ndarray, step: np.ndarray | float) -> np.ndarray:
    """Onda quadrada de -1 a 1 sem aliasing: a quadrada ingênua com a correção PolyBLEP nas duas bordas de cada ciclo. Troca o
    degrau (que espalha energia acima da metade da taxa e a dobra de volta) por uma borda de duas amostras."""
    phase = np.mod(cycles, 1.0)
    naive = np.where(phase < 0.5, 1.0, -1.0)
    return naive + blep(phase, step) - blep(np.mod(phase + 0.5, 1.0), step)


@register_generator_builder("tone")
def build_tone(request: GeneratorRequest) -> FilterSource | np.ndarray:
    tone = request.generator
    assert isinstance(tone, Tone)
    amplitude = db_to_linear(tone.amplitude_db)
    if tone.waveform == "square_bandlimited":
        cycles = tone.frequency_hz * np.arange(request.frames) / request.sample_rate
        return amplitude * bandlimited_square(cycles, tone.frequency_hz / request.sample_rate)
    expression = wave_expression(tone.waveform, f"{_number(tone.frequency_hz)}*t", _number(amplitude))
    return source_graph(expression, request)


@register_generator_builder("chirp")
def build_chirp(request: GeneratorRequest) -> FilterSource | np.ndarray:
    chirp = request.generator
    assert isinstance(chirp, Chirp)
    if chirp.waveform == "square_bandlimited":
        return _bandlimited_sweep(chirp, request)
    expression = wave_expression(
        chirp.waveform, sweep_cycles(chirp, request.duration), sweep_amplitude(chirp, request.duration)
    )
    return source_graph(expression, request)


def _bandlimited_sweep(chirp: Chirp, request: GeneratorRequest) -> np.ndarray:
    """A varredura quadrada sem aliasing: a mesma fase da expressão acima, calculada em numpy, e a amplitude em dB."""
    t = np.arange(request.frames) / request.sample_rate
    duration, f0, f1 = request.duration, chirp.start_hz, chirp.end_hz
    if chirp.interpolation == "logarithmic" and not math.isclose(f0, f1):
        ratio = f1 / f0
        cycles = f0 * duration / math.log(ratio) * (np.power(ratio, t / duration) - 1.0)
        frequency = f0 * np.power(ratio, t / duration)
    else:
        cycles = f0 * t + (f1 - f0) / (2 * duration) * t * t
        frequency = f0 + (f1 - f0) * t / duration
    amplitude = np.power(10.0, (chirp.start_db + (chirp.end_db - chirp.start_db) * t / duration) / 20.0)
    return amplitude * bandlimited_square(cycles, frequency / request.sample_rate)


@register_generator_builder("noise")
def build_noise(request: GeneratorRequest) -> FilterSource | np.ndarray:
    noise = request.generator
    assert isinstance(noise, Noise)
    return FilterSource(
        f"anoisesrc=color={noise.noise_type}:amplitude={_number(db_to_linear(noise.amplitude_db))}"
        f":seed={noise.seed}:sample_rate={request.sample_rate}:duration={_number(request.duration)}"
    )


@register_generator_builder("silence")
def build_silence(request: GeneratorRequest) -> FilterSource | np.ndarray:
    assert isinstance(request.generator, Silence)
    return np.zeros(request.frames, dtype=np.float32)
