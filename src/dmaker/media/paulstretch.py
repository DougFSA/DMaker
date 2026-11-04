"""O Paulstretch em numpy: estica o som por um fator grande sem mudar o tom, até virar uma textura contínua.

É o algoritmo público de Paul Nasca, escrito aqui do zero: o sinal é lido em janelas que andam devagar, cada janela tem
o módulo do espectro mantido e a fase sorteada, e as janelas processadas se somam com sobreposição de metade. Como a
fase é aleatória, janelas vizinhas não se somam em fase (somam potência), então uma janela de seno ao quadrado na
análise e na síntese mantém o nível constante. A semente é fixa: o mesmo som e os mesmos parâmetros dão sempre o mesmo
resultado, que por isso pode ficar em cache. Sem ffmpeg e sem disco: recebe amostras e devolve amostras.
"""

from __future__ import annotations

import numpy as np

# A semente da fase aleatória. Fixa de propósito: o resultado precisa ser reprodutível para ficar em cache por hash.
PAULSTRETCH_SEED = 20261104

# Menor janela (amostras): abaixo disto a FFT não separa as frequências e o resultado vira ruído sem timbre
MIN_WINDOW = 64
# Quantas amostras (janelas x canais x tamanho) cada lote processa de uma vez: o lote cabe em poucos MB, e o sinal
# esticado de 20 minutos nunca é recalculado por inteiro
BATCH_SAMPLES = 1 << 20


def window_size(time_resolution: float, sample_rate: int) -> int:
    """O tamanho da janela de análise em amostras: a resolução de tempo pedida, arredondada para a potência de dois
    acima (a FFT é mais rápida e a sobreposição de metade cai em número inteiro)."""
    wanted = max(round(time_resolution * sample_rate), MIN_WINDOW)
    return 1 << (wanted - 1).bit_length()


def stretched_length(length: int, stretch: float) -> int:
    """Quantas amostras tem a saída para `length` amostras de entrada."""
    return round(length * stretch)


def paulstretch(
    samples: np.ndarray,
    sample_rate: int,
    stretch: float,
    time_resolution: float,
    seed: int = PAULSTRETCH_SEED,
) -> np.ndarray:
    """O sinal `(amostras, canais)` esticado `stretch` vezes. A janela de análise dura `time_resolution` segundos (menor
    guarda mais do ritmo, maior deixa o som mais liso). Cada canal tem a própria fase sorteada, então a imagem
    estéreo se espalha em vez de colapsar. Processa em lotes de janelas e acumula a saída num só vetor de 32 bits."""
    total = len(samples)
    out_length = stretched_length(total, stretch)
    channels = samples.shape[1] if samples.ndim == 2 else 1
    if total == 0 or out_length == 0:
        return np.zeros((out_length, channels), dtype=np.float32)
    source = samples.reshape(total, channels)
    size = window_size(time_resolution, sample_rate)
    half = size // 2
    # O seno ao quadrado soma 1 com a janela deslocada de metade; o ganho repõe a energia que a janela de análise tira
    window = np.sin(np.pi * (np.arange(size) + 0.5) / size).astype(np.float32)
    gain = np.float32(1.0 / np.sqrt(np.mean(window.astype(np.float64) ** 2)))
    frames = (
        out_length - 1
    ) // half + 2  # cada trecho de `half` amostras da saída é coberto por duas janelas
    # blocos de `half` amostras; a janela k preenche o bloco k (primeira metade) e o k+1 (segunda), e o bloco 0 é descartado
    blocks = np.zeros((frames + 1, half, channels), dtype=np.float32)
    rng = np.random.default_rng(seed)
    batch = max(1, BATCH_SAMPLES // (size * channels))
    bins = size // 2 + 1
    for first in range(0, frames, batch):
        indices = np.arange(first, min(first + batch, frames))
        gathered = _gather(source, indices, half, size, stretch)  # (janelas, canais, tamanho)
        magnitude = np.abs(np.fft.rfft(gathered * window, axis=-1))
        # 32 bits bastam para uma fase sorteada, e metade do trabalho e da memória: o render de 20 minutos de saída fica viável
        phase = rng.random((len(indices), channels, bins), dtype=np.float32) * np.float32(2.0 * np.pi)
        phase[..., 0] = 0.0  # a componente contínua e a de Nyquist não têm fase
        phase[..., -1] = 0.0
        shaped = np.fft.irfft(magnitude * np.exp(1j * phase), n=size, axis=-1).astype(np.float32)
        shaped *= window * gain
        blocks[indices[0] : indices[-1] + 1] += shaped[..., :half].transpose(0, 2, 1)
        blocks[indices[0] + 1 : indices[-1] + 2] += shaped[..., half:].transpose(0, 2, 1)
    return blocks.reshape(-1, channels)[half : half + out_length]


def _gather(source: np.ndarray, frames: np.ndarray, half: int, size: int, stretch: float) -> np.ndarray:
    """As janelas de entrada de `frames`, de forma `(janelas, canais, tamanho)`. A janela k fica centrada no ponto da
    entrada que corresponde ao centro dela na saída (`k * half / stretch`); perto das pontas ela encosta no começo ou no
    fim do sinal em vez de ler zeros, para o nível não cair. Um sinal menor que a janela é completado com zeros."""
    total = len(source)
    centers = frames * (half / stretch)
    last_start = max(total - size, 0)
    starts = np.clip(np.round(centers - size / 2).astype(np.int64), 0, last_start)
    positions = starts[:, None] + np.arange(size)[None, :]
    inside = positions < total
    window = source[np.minimum(positions, total - 1)]  # (janelas, tamanho, canais)
    window = np.where(inside[..., None], window, 0.0)
    return window.transpose(0, 2, 1).astype(np.float32)
