"""Sinais de teste e medidas dos efeitos criativos (eco, reverb, modulação): tudo gerado aqui, com semente fixa.

A "fala" é um sinal parecido com fala (voz com harmônicos de uma fonte glótica, formantes, sílabas e chiado de consoante), e não
uma gravação: serve para medir o pico dos efeitos e das predefinições a -1 dBFS, que é o que o card pede, sem baixar nem rodar
um modelo de voz. A fala sintetizada de verdade (Kokoro) entra só na conferência manual e no teste do Vocoder com o Whisper.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from dmaker.media.wavio import write_wav_float

RATE = 48000


def speech_like(seconds: float = 6.0, peak_db: float = -1.0, seed: int = 5) -> np.ndarray:
    """Um sinal `(amostras, 2)` com cara de fala: a voz (harmônicos de um tom que passeia entre 100 e 140 Hz, realçados em volta
    de três formantes) em sílabas de cerca de 200 ms com pausas curtas, e chiado de consoante entre elas. Pico em `peak_db`."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    # o tom de uma voz de verdade nunca se repete: uma deriva lenta aleatória (4 pontos por segundo, interpolados) tira o
    # alinhamento dos picos entre o som e as repetições do eco
    knots = rng.standard_normal(int(seconds * 4) + 2)
    drift = np.interp(t, np.arange(len(knots)) / 4.0, knots)
    f0 = 120.0 + 20.0 * np.sin(2 * np.pi * 0.7 * t) + 6.0 * np.sin(2 * np.pi * 2.3 * t) + 12.0 * drift
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    voice = np.zeros(n)
    for harmonic in range(1, 40):
        hz = harmonic * 120.0
        gain = sum(
            np.exp(-0.5 * ((hz - center) / width) ** 2)
            for center, width in ((700, 200), (1200, 300), (2600, 500))
        )
        voice += (0.02 + gain) / harmonic**0.6 * np.sin(harmonic * phase)
    envelope = np.zeros(n)
    noise_envelope = np.zeros(n)
    cursor = 0.15
    while cursor < seconds - 0.4:
        length = rng.uniform(0.14, 0.26)
        start, stop = int(cursor * RATE), int((cursor + length) * RATE)
        bump = np.sin(np.pi * np.linspace(0, 1, stop - start)) ** 2
        envelope[start:stop] = bump * rng.uniform(0.6, 1.0)
        gap = rng.uniform(0.04, 0.12)
        fr_start, fr_stop = stop, min(int((cursor + length + gap) * RATE), n)
        noise_envelope[fr_start:fr_stop] = 0.15 * np.sin(np.pi * np.linspace(0, 1, fr_stop - fr_start)) ** 2
        cursor += length + gap
    hiss = np.diff(rng.standard_normal(n + 1))  # ruído branco derivado: sobe os agudos (um "s")
    signal = voice * envelope / np.abs(voice).max() + hiss * noise_envelope
    signal *= 10.0 ** (peak_db / 20.0) / np.abs(signal).max()
    return np.stack([signal, signal], axis=1).astype(np.float32)


def write_speech_like(path: Path, seconds: float = 6.0) -> Path:
    return write_wav_float(path, speech_like(seconds), RATE)


def click(seconds: float, at: float = 0.5, amplitude: float = 0.8) -> np.ndarray:
    """Silêncio estéreo com um clique de uma amostra em `at`."""
    samples = np.zeros((round(seconds * RATE), 2), dtype=np.float32)
    samples[round(at * RATE)] = amplitude
    return samples


def peak_db(samples: np.ndarray) -> float:
    return float(20 * np.log10(max(float(np.abs(samples).max()), 1e-12)))


def schroeder_rt60(samples: np.ndarray, start: int, rate: int = RATE) -> float:
    """O RT60 de uma resposta a um clique, pela integração de Schroeder: a energia que ainda falta soar, ao contrário, em dB;
    a reta entre -5 e -25 dB é extrapolada até -60 dB."""
    energy = np.cumsum((samples[start:, 0].astype(np.float64) ** 2)[::-1])[::-1]
    decay = 10 * np.log10(np.maximum(energy / energy[0], 1e-30))
    seconds = np.arange(len(decay)) / rate
    window = (decay <= -5) & (decay >= -25)
    slope = np.polyfit(seconds[window], decay[window], 1)[0]
    return float(-60.0 / slope)


def burst(seconds: float, start: float = 0.3, length: float = 0.2, amplitude: float = 0.5) -> np.ndarray:
    """Silêncio estéreo com um trecho de ruído branco de semente fixa: tem energia para o reverb deixar uma cauda que se vê."""
    samples = np.zeros((round(seconds * RATE), 2), dtype=np.float32)
    first, last = round(start * RATE), round((start + length) * RATE)
    noise = np.random.default_rng(9).uniform(-amplitude, amplitude, last - first)
    samples[first:last] = noise[:, None]
    return samples


def envelope_peaks(samples: np.ndarray, block: int = 480) -> np.ndarray:
    """A envoltória por blocos (10 ms por padrão): o maior valor absoluto de cada bloco do canal esquerdo."""
    mono = np.abs(samples[:, 0])
    return np.array([mono[i : i + block].max() for i in range(0, len(mono) - block, block)])


def dominant_frequency(series: np.ndarray, step_seconds: float) -> float:
    """A frequência dominante (sem o nível médio) de uma série amostrada a cada `step_seconds`."""
    spectrum = np.abs(np.fft.rfft(series - series.mean()))
    return float(np.fft.rfftfreq(len(series), step_seconds)[int(np.argmax(spectrum))])
