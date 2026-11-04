"""O Vocoder de canais: a voz (moduladora) desenha o espectro de um som de fundo (a portadora).

O espectro é dividido em `bandas` faixas em escala log. Em cada quadro (a análise e a síntese STFT são as de
`media/stft_filter.py`), o ganho de cada faixa é a razão entre o nível da voz e o da portadora naquela faixa, interpolado
entre as faixas vizinhas para os bins não darem degrau. Assim a portadora sai com a envoltória espectral da fala: o ritmo e as
vogais da voz com o timbre da onda (a dente de serra, o clássico som de robô).

Para as consoantes (que a portadora harmônica não tem) a portadora recebe ruído branco e, se pedido, agulhas de radar, um trem de
pulsos de uma amostra que enche o espectro todo. O original pode voltar misturado. Função pura sobre arrays, com semente fixa
no ruído: o mesmo pedido dá o mesmo som.
"""

from __future__ import annotations

import numpy as np

from .spectral import FFT_SIZE
from .stft_filter import stft_process

# A faixa vai de 80 Hz (abaixo disso a voz tem pouco a dizer) até onde houver bins; acima do último centro a última faixa vale
BAND_LOW_HZ = 80.0
BAND_HIGH_HZ = 12000.0
# A razão máxima entre o nível da voz e o da portadora numa faixa (40 dB): onde a portadora quase não tem energia o ganho
# explodiria e traria só ruído de arredondamento
MAX_GAIN = 100.0
# O ruído e as agulhas são medidos contra a potência da portadora, para o controle valer igual com qualquer onda
NOISE_SEED = 7
POWER_FLOOR = 1e-18


def band_weights(rate: int, bands: int, distance: float) -> np.ndarray:
    """A matriz `(bandas, bins)` dos pesos das faixas: cada faixa é um triângulo em escala log de frequência. `distance`
    (1 a 120; 20 é o padrão) é a largura do triângulo em relação ao espaço entre as faixas: 20 deixa cada bin em duas faixas
    vizinhas, menos separa, mais borra."""
    hz = np.arange(FFT_SIZE // 2 + 1) * rate / FFT_SIZE
    high = min(BAND_HIGH_HZ, rate / 2.0)
    # o bin 0 e os abaixo de BAND_LOW_HZ ficam na primeira faixa: a posição é limitada ao centro das pontas
    position = np.log(np.maximum(hz, BAND_LOW_HZ) / BAND_LOW_HZ) / np.log(high / BAND_LOW_HZ) * bands
    position = np.clip(position, 0.5, bands - 0.5)
    half = max(distance / 20.0, 0.05)
    centers = np.arange(bands) + 0.5
    weights = np.maximum(0.0, 1.0 - np.abs(position[None, :] - centers[:, None]) / half)
    covered = weights.sum(axis=0)
    # um bin que a largura estreita deixou entre duas faixas, sem peso, vai para a mais próxima
    nearest = np.argmin(np.abs(position[None, :] - centers[:, None]), axis=0)
    weights[nearest[covered == 0], np.nonzero(covered == 0)[0]] = 1.0
    return weights


def _augmented_carrier(
    carrier: np.ndarray, rate: int, noise: float, radar: float, radar_hz: float
) -> np.ndarray:
    """A portadora com o ruído branco e as agulhas de radar somados, cada um com `noise` e `radar` (frações) da potência da
    portadora. O pulso de uma amostra a cada `rate / radar_hz` amostras tem a mesma potência dela quando a altura é a raiz do
    período vezes a RMS."""
    power = float(np.mean(carrier.astype(np.float64) ** 2))
    result = np.array(carrier, dtype=np.float64, copy=True)
    if power <= POWER_FLOOR:
        return result
    rms = np.sqrt(power)
    if noise > 0:
        result += noise * rms * np.random.default_rng(NOISE_SEED).standard_normal(result.shape)
    if radar > 0:
        period = max(round(rate / radar_hz), 1)
        result[::period] += radar * rms * np.sqrt(period)
    return result


def vocode(
    modulator: np.ndarray,
    carrier: np.ndarray,
    rate: int,
    bands: int,
    distance: float,
    original: float,
    noise: float,
    radar: float,
    radar_hz: float,
) -> np.ndarray:
    """A voz `modulator` vocodificada sobre a `carrier`, ambas `(amostras, canais)` do mesmo comprimento. `original`, `noise`
    e `radar` são frações (0 a 1) do original misturado e do ruído e das agulhas somados à portadora. Sai estéreo."""
    mono = modulator.astype(np.float64).mean(axis=1, keepdims=True)
    wide = carrier if carrier.shape[1] == 2 else np.repeat(carrier, 2, axis=1)
    source = _augmented_carrier(wide, rate, noise, radar, radar_hz)
    weights = band_weights(rate, bands, distance)
    normal = weights / np.maximum(weights.sum(axis=1, keepdims=True), POWER_FLOOR)
    spread = weights / np.maximum(weights.sum(axis=0, keepdims=True), POWER_FLOOR)

    def process(_: np.ndarray, spectra: list[np.ndarray]) -> list[np.ndarray]:
        voice, left, right = spectra
        voice_power = normal @ (np.abs(voice) ** 2).T  # (bandas, quadros)
        results = []
        for channel in (left, right):
            carrier_power = normal @ (np.abs(channel) ** 2).T
            gain = np.minimum(np.sqrt(voice_power / (carrier_power + POWER_FLOOR)), MAX_GAIN)
            results.append(channel * (spread.T @ gain).T)
        return results

    shaped = stft_process([mono, source], rate, process).astype(np.float64)
    if original > 0:
        shaped += original * mono
    return shaped.astype(np.float32)
