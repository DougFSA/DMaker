"""FFT e janelas em numpy: a base comum do espectro de frequência e, no próximo card, do espectrograma.

É o módulo que o espectrograma (DMK-63) reaproveita: `window_coefficients` dá a janela pelo nome do Audacity,
`windowed_frames` parte o sinal em quadros já janelados (com a sobreposição que o espectrograma quiser) e
`amplitude_spectrum_db` põe cada quadro em dBFS. Cada função é pura, sem disco e sem ffmpeg.

A escala é a da amplitude: um seno de amplitude A que cai no centro de uma divisão mostra 20·log10(A) dBFS nela,
qualquer que seja a janela e o tamanho. Para isso o espectro é dividido pelo ganho coerente da janela (a soma dos
coeficientes), que é o que mantém o pico na altura certa quando a janela atenua as pontas do quadro.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Literal

import numpy as np

# As janelas do "Plot Spectrum" do Audacity, com o nome da spec (minúsculo, sem acento).
WindowName = Literal[
    "rectangular",
    "bartlett",
    "hamming",
    "hann",
    "blackman",
    "blackman_harris",
    "welch",
    "gaussian_2_5",
    "gaussian_3_5",
    "gaussian_4_5",
]
WINDOW_NAMES: tuple[str, ...] = (
    "rectangular",
    "bartlett",
    "hamming",
    "hann",
    "blackman",
    "blackman_harris",
    "welch",
    "gaussian_2_5",
    "gaussian_3_5",
    "gaussian_4_5",
)
DEFAULT_WINDOW: WindowName = "hann"

# Os tamanhos de FFT que o Audacity oferece (potências de dois de 128 a 65536) e o padrão dele.
MIN_FFT_SIZE = 128
MAX_FFT_SIZE = 65536
DEFAULT_FFT_SIZE = 2048

# Abaixo disto uma divisão do espectro conta como silêncio (-240 dB): evita o logaritmo de zero.
_POWER_FLOOR = 1e-24
SPECTRUM_FLOOR_DB = -240.0


def is_fft_size(size: int) -> bool:
    """Se `size` é uma potência de dois dentro dos limites de `MIN_FFT_SIZE` a `MAX_FFT_SIZE`."""
    return MIN_FFT_SIZE <= size <= MAX_FFT_SIZE and size & (size - 1) == 0


def _check_size(size: int) -> None:
    if not is_fft_size(size):
        raise ValueError(
            f"tamanho de FFT inválido: {size} (use uma potência de dois de {MIN_FFT_SIZE} a {MAX_FFT_SIZE})"
        )


@lru_cache(maxsize=32)
def _window(name: str, size: int) -> np.ndarray:
    """A janela periódica (a forma certa para a FFT: o fim do quadro é o começo do próximo)."""
    n = np.arange(size, dtype=np.float64)
    phase = 2.0 * math.pi * n / size
    if name == "rectangular":
        coefficients = np.ones(size)
    elif name == "bartlett":
        coefficients = 1.0 - np.abs(2.0 * n / size - 1.0)
    elif name == "hamming":
        coefficients = 0.54 - 0.46 * np.cos(phase)
    elif name == "hann":
        coefficients = 0.5 - 0.5 * np.cos(phase)
    elif name == "blackman":
        coefficients = 0.42 - 0.5 * np.cos(phase) + 0.08 * np.cos(2.0 * phase)
    elif name == "blackman_harris":
        coefficients = (
            0.35875 - 0.48829 * np.cos(phase) + 0.14128 * np.cos(2.0 * phase) - 0.01168 * np.cos(3.0 * phase)
        )
    elif name == "welch":
        coefficients = 1.0 - np.square((n - size / 2.0) / (size / 2.0))
    elif name.startswith("gaussian_"):
        # a = 2,5, 3,5 ou 4,5: quanto maior, mais estreita a janela e mais alto o lóbulo lateral que some
        a = float(name.removeprefix("gaussian_").replace("_", "."))
        coefficients = np.exp(-0.5 * np.square(a * (n - size / 2.0) / (size / 2.0)))
    else:
        raise ValueError(f"janela desconhecida: {name!r}. Use uma de: {', '.join(WINDOW_NAMES)}")
    coefficients.setflags(write=False)
    return coefficients


def window_coefficients(name: str, size: int) -> np.ndarray:
    """Os `size` coeficientes da janela `name` (somente leitura)."""
    if size < 2:
        raise ValueError("a janela precisa de pelo menos 2 amostras")
    return _window(name, size)


def coherent_gain(window: np.ndarray) -> float:
    """A soma dos coeficientes: por quanto a janela atenua um tom que cai no centro de uma divisão."""
    return float(window.sum())


def frame_count(total: int, size: int, hop: int | None = None) -> int:
    """Quantos quadros de `size` amostras (a cada `hop`) cobrem um sinal de `total` amostras: um sinal curto demais
    ainda dá um quadro, para o espectro de um trecho curto sair em vez de falhar."""
    step = max(hop or size // 2, 1)
    return 1 if total <= size else 1 + math.ceil((total - size) / step)


def windowed_frames(
    samples: np.ndarray,
    size: int,
    window: np.ndarray,
    hop: int | None = None,
    first: int = 0,
    count: int | None = None,
) -> np.ndarray:
    """Parte o sinal mono em quadros de `size` amostras (a cada `hop`, meio quadro por padrão) e aplica a janela.

    `first` e `count` escolhem uma faixa de quadros, para um sinal longo ser processado aos poucos sem montar a
    matriz inteira na memória. O que sobra no fim entra num último quadro completado com zeros. Devolve
    (quadros, size)."""
    step = max(hop or size // 2, 1)
    available = frame_count(len(samples), size, step)
    wanted = available - first if count is None else min(count, available - first)
    if wanted <= 0:
        return np.zeros((0, size), dtype=np.float64)
    begin = first * step
    chunk = np.zeros((wanted - 1) * step + size, dtype=np.float64)
    piece = samples[begin : begin + len(chunk)]
    chunk[: len(piece)] = piece
    index = np.arange(size)[None, :] + step * np.arange(wanted)[:, None]
    return chunk[index] * window


def power_spectra(frames: np.ndarray) -> np.ndarray:
    """O quadrado do módulo da FFT de cada quadro (só as divisões de 0 ao Nyquist)."""
    return np.abs(np.fft.rfft(frames, axis=1)) ** 2


def amplitude_spectrum_db(power: np.ndarray, window: np.ndarray) -> np.ndarray:
    """A potência (já média dos quadros, se for o caso) em dBFS de amplitude. O DC e o Nyquist não têm par
    espelhado, então não levam o fator 2 que as outras divisões levam."""
    amplitude = np.sqrt(np.maximum(power, _POWER_FLOOR)) / coherent_gain(window)
    amplitude = amplitude * 2.0
    amplitude[..., 0] *= 0.5
    amplitude[..., -1] *= 0.5
    return np.maximum(20.0 * np.log10(np.maximum(amplitude, 1e-12)), SPECTRUM_FLOOR_DB)


def bin_frequencies(size: int, sample_rate: int) -> np.ndarray:
    """A frequência, em Hz, de cada divisão do espectro de um quadro de `size` amostras."""
    return np.fft.rfftfreq(size, d=1.0 / sample_rate)


def refine_peak(levels_db: np.ndarray, frequencies: np.ndarray, index: int) -> tuple[float, float]:
    """A frequência e o nível do pico da divisão `index`, refinados pela parábola que passa pelos três pontos em volta
    (acerta o tom entre duas divisões a uma fração delas). Sem vizinhos dos dois lados, ou sem curvatura para baixo,
    devolve a própria divisão."""
    if 0 < index < len(levels_db) - 1:
        left, centre, right = (float(levels_db[index + shift]) for shift in (-1, 0, 1))
        curvature = left - 2.0 * centre + right
        if curvature < 0:
            shift = 0.5 * (left - right) / curvature
            level = centre - 0.25 * (left - right) * shift
            return float(frequencies[index] + shift * (frequencies[1] - frequencies[0])), level
    return float(frequencies[index]), float(levels_db[index])


def peak_frequency(levels_db: np.ndarray, frequencies: np.ndarray) -> tuple[int, float]:
    """A divisão mais alta e a frequência do pico, refinada entre divisões. Devolve (divisão, Hz)."""
    index = int(np.argmax(levels_db))
    return index, refine_peak(levels_db, frequencies, index)[0]


# Quantos quadros entram na matriz de cada vez: o bastante para a FFT em lote render, pouco para a memória não crescer
# com a duração do áudio (2048 amostras × 128 quadros × 8 bytes = 2 MB).
FRAME_BATCH = 128


def averaged_power(samples: np.ndarray, size: int, window: np.ndarray, hop: int | None = None) -> np.ndarray:
    """A potência média, divisão a divisão, de todos os quadros janelados do sinal mono (o espectro que o Audacity
    desenha para uma seleção). Os quadros são processados em lotes de `FRAME_BATCH`."""
    total = frame_count(len(samples), size, hop)
    power = np.zeros(size // 2 + 1, dtype=np.float64)
    for first in range(0, total, FRAME_BATCH):
        power += power_spectra(windowed_frames(samples, size, window, hop, first, FRAME_BATCH)).sum(axis=0)
    return power / total
