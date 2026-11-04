"""Filtros que mudam com o tempo, feitos quadro a quadro no domínio da frequência: o Phaser, o Wahwah e o Vocoder.

Um filtro cuja resposta anda devagar (um LFO de 4 Hz, a envoltória de uma voz) é, em cada instante, um filtro fixo. O sinal
passa pela mesma janela da Redução de ruído (`media/spectral.py`: 2048 amostras, 75% de sobreposição, raiz de Hann na
análise e na síntese), cada quadro é multiplicado pela resposta daquele instante, e a soma das janelas devolve o sinal. É
exato para o que muda mais devagar que um quadro (43 ms), e é vetorial: não há laço por amostra, que num filtro com
realimentação e coeficiente móvel levaria minutos por minuto de som.

Funções puras sobre arrays; o sinal pode ser um arquivo mapeado e só um bloco de quadros por vez vai à memória.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from .spectral import (
    BLOCK_FRAMES,
    FFT_SIZE,
    HEAD,
    HOP,
    OVERLAP_GAIN,
    WINDOW,
    _block,
    _frame_count,
    _windowed,
)

# Recebe os instantes do centro de cada quadro do bloco (segundos) e os espectros `(quadros, bins)` de cada canal de cada
# sinal de entrada, na ordem; devolve os espectros de cada canal de saída
Processor = Callable[[np.ndarray, list[np.ndarray]], list[np.ndarray]]


def bin_omega() -> np.ndarray:
    """A frequência de cada bin da FFT em radianos por amostra (0 a pi)."""
    return 2.0 * np.pi * np.arange(FFT_SIZE // 2 + 1) / FFT_SIZE


def stft_process(signals: Sequence[np.ndarray], rate: int, process: Processor) -> np.ndarray:
    """Passa os sinais `(amostras, canais)` pelo `process`, quadro a quadro, e devolve o resultado `(amostras, saídas)` em
    ponto flutuante de 32 bits. Os sinais têm o mesmo comprimento; o resultado também."""
    length = len(signals[0])
    frames = _frame_count(length)
    output: np.ndarray | None = None
    for first in range(0, frames, BLOCK_FRAMES):
        count = min(BLOCK_FRAMES, frames - first)
        times = (np.arange(first, first + count) * HOP - HEAD + FFT_SIZE / 2) / rate
        spectra = []
        for signal in signals:
            block = _block(signal, first, count)
            spectra += [np.fft.rfft(_windowed(block, c, count), axis=1) for c in range(signal.shape[1])]
        produced = process(times, spectra)
        if output is None:
            output = np.zeros(((frames - 1) * HOP + FFT_SIZE, len(produced)), dtype=np.float32)
        for c, spectrum in enumerate(produced):
            frames_out = np.fft.irfft(spectrum, n=FFT_SIZE, axis=1) * WINDOW
            summed = np.zeros((count - 1) * HOP + FFT_SIZE)
            for k in range(count):
                summed[k * HOP : k * HOP + FFT_SIZE] += frames_out[k]
            begin = first * HOP
            output[begin : begin + len(summed), c] += summed.astype(np.float32)
    assert output is not None
    return output[HEAD : HEAD + length] / np.float32(OVERLAP_GAIN)


def apply_response(
    samples: np.ndarray, rate: int, response: Callable[[np.ndarray], np.ndarray]
) -> np.ndarray:
    """O sinal `(amostras, canais)` filtrado pela resposta `response(instantes) -> (quadros, bins)` complexa, a mesma em todos
    os canais. Mesmo tamanho e forma da entrada."""
    data = samples if samples.ndim == 2 else samples[:, None]

    def process(times: np.ndarray, spectra: list[np.ndarray]) -> list[np.ndarray]:
        gain = response(times)
        return [spectrum * gain for spectrum in spectra]

    result = stft_process([data], rate, process)
    return result[:, 0] if samples.ndim == 1 else result
