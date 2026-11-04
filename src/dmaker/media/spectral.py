"""Redução de ruído por subtração espectral: o perfil do ruído, a janela e a porta que atenua só o que é ruído.

Funções puras sobre amostras (numpy), sem ffmpeg nem disco. O `afftdn` do ffmpeg foi medido primeiro (ver
`filtergraph/audio_effects/restoration.py`) e não serviu: o perfil por bandas é ignorado e, no modo de ruído
branco, ele fica abaixo da redução pedida. Aqui a redução em dB é a que o usuário pede, e o perfil é o espectro
médio de um trecho que só tem ruído, bin a bin, como no fluxo "pegar o perfil, aplicar" do Audacity.

O sinal passa por uma janela de 2048 amostras (43 ms a 48 kHz) com 75% de sobreposição. Em cada quadro, cada bin
cuja potência não passa do ruído do perfil (mais uma margem, a "sensibilidade") é atenuado por `reduction_db`; o
que passa fica como está. O ganho sobe de uma vez e desce devagar (o `RELEASE_SECONDS`), para o fim de uma palavra
não ser engolido, e é suavizado entre bins vizinhos (a "suavização de frequência"), que é o que tira o chiado
metálico de bins soltos que escapam da porta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

FFT_SIZE = 2048
HOP = FFT_SIZE // 4  # 75% de sobreposição: a janela ao quadrado (Hann) soma a mesma constante em toda amostra
OVERLAP_GAIN = 2.0  # soma das quatro janelas Hann sobrepostas; dividir por ela devolve o sinal sem alteração
MIN_PROFILE_SECONDS = 0.1  # um perfil mais curto que isso tem poucos quadros para uma média que se sustente
BLOCK_FRAMES = 1024  # quadros processados por vez: a memória não cresce com o tamanho do item
# a porta fecha em 60 ms depois de a fala acabar: o bastante para o fim de uma palavra não ser cortado e curto
# o bastante para o ruído entre duas frases voltar a ser atenuado
RELEASE_SECONDS = 0.06
# a transição entre "ruído" e "sinal" não é um degrau: o ganho vai de -reduction a 0 dB ao longo de 6 dB de potência
KNEE_DB = 6.0
# a decisão ruído/sinal olha a média de 3 bins vizinhos: um bin só de ruído branco varia ±5,6 dB de um quadro para
# outro, e a média de 3 reduz isso o bastante para a margem da sensibilidade valer
DECISION_BINS = 3
FLOOR_POWER = 1e-20

WINDOW = np.sin(
    np.pi * np.arange(FFT_SIZE) / FFT_SIZE
)  # raiz da janela Hann: a mesma na análise e na síntese


@dataclass(frozen=True)
class NoiseSpectrum:
    """O ruído de um trecho: a potência média de cada bin da FFT, um vetor por canal."""

    power: np.ndarray  # forma (canais, bins), potência média por bin da janela de FFT_SIZE
    sample_rate: int
    frames: int  # quantos quadros entraram na média (diz o quanto confiar nela)

    @property
    def bins(self) -> int:
        return int(self.power.shape[1])

    @property
    def channels(self) -> int:
        return int(self.power.shape[0])


# ---------- janela e quadros ----------


HEAD = FFT_SIZE - HOP  # zeros antes do sinal: a primeira amostra precisa dos quatro quadros que a cobrem


def _frame_count(length: int) -> int:
    """Quantos quadros cobrem `length` amostras com o zero de `HEAD` na frente."""
    return (HEAD + length - 1) // HOP + 1


def _block(samples: np.ndarray, first: int, count: int) -> np.ndarray:
    """As amostras `(n, canais)`, em ponto flutuante de 64 bits, que os `count` quadros a partir do quadro `first`
    cobrem (com zeros onde passam das pontas do sinal). Só este pedaço sai da memória do sinal: ele pode ser um
    arquivo mapeado."""
    begin = first * HOP - HEAD
    size = (count - 1) * HOP + FFT_SIZE
    block = np.zeros((size, samples.shape[1]), dtype=np.float64)
    low, high = max(begin, 0), min(begin + size, len(samples))
    if high > low:
        block[low - begin : high - begin] = samples[low:high]
    return block


def _windowed(block: np.ndarray, channel: int, count: int) -> np.ndarray:
    """Os `count` quadros de um canal do bloco, já multiplicados pela janela."""
    view = np.lib.stride_tricks.sliding_window_view(block[:, channel], FFT_SIZE)[::HOP][:count]
    return view * WINDOW


# ---------- o perfil ----------


def noise_spectrum(samples: np.ndarray, sample_rate: int) -> NoiseSpectrum:
    """O perfil de um trecho que só tem ruído: a potência média de cada bin, por canal. `samples` tem a forma
    `(amostras, canais)` (ou `(amostras,)`, mono). Falha, com o motivo, num trecho curto demais para uma média."""
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    if len(data) < max(FFT_SIZE, int(MIN_PROFILE_SECONDS * sample_rate)):
        raise ValueError(
            f"o trecho de ruído tem {len(data) / sample_rate:.3f} s; use pelo menos "
            f"{max(FFT_SIZE / sample_rate, MIN_PROFILE_SECONDS):.2f} s só de ruído para medir o perfil"
        )
    spectra = []
    count = 0
    for channel in data.T:
        # sem o zero das pontas: o perfil são quadros inteiros do ruído, não a subida do zero para ele
        frames = (len(channel) - FFT_SIZE) // HOP + 1
        view = np.lib.stride_tricks.sliding_window_view(channel, FFT_SIZE)[::HOP][:frames]
        power = np.abs(np.fft.rfft(view * WINDOW, axis=1)) ** 2
        spectra.append(power.mean(axis=0))
        count = frames
    return NoiseSpectrum(np.asarray(spectra), sample_rate, count)


QUIET_FRAME_SECONDS = 0.01  # a energia é medida em quadros de 10 ms
# uma pausa só de ruído tem que ficar pelo menos 10 dB abaixo da média da gravação: a fala de uma conversa tem pausas
# 20 dB ou mais abaixo, e abaixo desta margem o "ruído" mais quieto ainda é fala ou um tom contínuo
AUTO_PROFILE_MARGIN_DB = 10.0


def _frame_energy(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """A energia média (potência) de cada quadro de 10 ms, com os canais misturados. Lida em pedaços de 30 s: o sinal pode
    ser um arquivo mapeado de uma hora."""
    size = max(1, int(sample_rate * QUIET_FRAME_SECONDS))
    count = len(samples) // size
    chunk = 3000 * size
    energy = np.empty(count)
    for begin in range(0, count * size, chunk):
        block = np.asarray(samples[begin : min(begin + chunk, count * size)], dtype=np.float64)
        if block.ndim > 1:
            block = block.mean(axis=1)
        energy[begin // size : begin // size + len(block) // size] = (
            np.square(block).reshape(-1, size).mean(axis=1)
        )
    return energy


def quietest_window(samples: np.ndarray, sample_rate: int, seconds: float) -> tuple[float, float]:
    """O início e o fim (segundos) da janela de `seconds` com menos energia. A energia é somada numa janela deslizante de
    quadros de 10 ms; sem janela inteira, o trecho todo."""
    window = _quietest(samples, sample_rate, seconds)
    return window[:2]


def quiet_pause_window(
    samples: np.ndarray, sample_rate: int, seconds: float, margin_db: float = AUTO_PROFILE_MARGIN_DB
) -> tuple[float, float] | None:
    """A janela mais quieta como perfil automático, ou None quando ela não é uma pausa de verdade: se não fica `margin_db`
    abaixo da potência média da gravação, não há trecho só de ruído (uma fala sem pausas, um tom contínuo), e usar o
    mais quieto como "ruído" apagaria o som querido."""
    first, last, quiet, mean = _quietest(samples, sample_rate, seconds)
    if mean <= 0:
        return None  # silêncio digital em tudo: não há som a limpar
    if quiet <= 0:
        return first, last  # uma janela de silêncio digital: a pausa mais limpa que existe
    return (first, last) if 10.0 * np.log10(quiet / mean) <= -margin_db else None


def _quietest(samples: np.ndarray, sample_rate: int, seconds: float) -> tuple[float, float, float, float]:
    """Início, fim, potência média da janela mais quieta e potência média da gravação inteira."""
    duration = len(samples) / sample_rate
    energy = _frame_energy(samples, sample_rate)
    mean = float(energy.mean()) if energy.size else 0.0
    if duration <= seconds or energy.size == 0:
        return 0.0, duration, mean, mean
    span = max(1, round(seconds / QUIET_FRAME_SECONDS))
    means = np.convolve(energy, np.ones(span), mode="valid") / span
    first = int(np.argmin(means))
    start = first * QUIET_FRAME_SECONDS
    return start, min(start + seconds, duration), float(means[first]), mean


# ---------- a porta ----------


def _smooth_bins(values: np.ndarray, width: int) -> np.ndarray:
    """Média móvel de `width` bins ao longo do último eixo, com as pontas repetidas (sem encolher o espectro)."""
    if width <= 1:
        return values
    half = width // 2
    padded = np.pad(values, [(0, 0)] * (values.ndim - 1) + [(half, half)], mode="edge")
    sums = np.cumsum(padded, axis=-1, dtype=np.float64)
    sums = np.concatenate([np.zeros_like(sums[..., :1]), sums], axis=-1)
    return (sums[..., width:] - sums[..., :-width]) / width


def reduce_noise(
    samples: np.ndarray,
    profile: NoiseSpectrum,
    reduction_db: float = 12.0,
    sensitivity: float = 6.0,
    smoothing_bands: int = 3,
) -> np.ndarray:
    """O sinal `(amostras, canais)` com o ruído do `profile` atenuado em `reduction_db` dB.

    `sensitivity` (dB) é a margem acima do ruído do perfil a partir da qual um bin passa a contar como sinal: com
    mais sensibilidade, mais bins são tratados como ruído (e mais som querido pode ir junto). `smoothing_bands`
    alarga a média de ganho entre bins vizinhos (`2 * bandas + 1` bins). Os canais abrem juntos (o ganho de cada
    bin é o maior dos canais), para a imagem estéreo da fala não se mexer. Mesmo tamanho e forma da entrada."""
    data = samples
    squeeze = data.ndim == 1
    if squeeze:
        data = data[:, None]
    if reduction_db <= 0 or len(data) == 0:
        return np.asarray(samples)
    if profile.channels not in (1, data.shape[1]):
        raise ValueError("o perfil de ruído e o sinal têm números de canais diferentes")

    floor = 10.0 ** (-reduction_db / 20.0)
    margin = 10.0 ** (sensitivity / 10.0)
    noise = _smooth_bins(profile.power, DECISION_BINS) * margin + FLOOR_POWER
    if profile.channels == 1:
        noise = np.repeat(noise, data.shape[1], axis=0)
    release = math.exp(-HOP / (RELEASE_SECONDS * profile.sample_rate))
    width = 2 * int(smoothing_bands) + 1

    frames = _frame_count(len(data))
    # o resultado soma as contribuições de quatro quadros por amostra; em 32 bits o erro de cada soma (1e-7) some
    # perto do piso de ruído de qualquer gravação
    output = np.zeros(((frames - 1) * HOP + FFT_SIZE, data.shape[1]), dtype=np.float32)
    held = np.ones(profile.bins) * floor
    for first in range(0, frames, BLOCK_FRAMES):
        count = min(BLOCK_FRAMES, frames - first)
        block = _block(data, first, count)
        spectra = [
            np.fft.rfft(_windowed(block, c, count), axis=1) for c in range(data.shape[1])
        ]  # um espectro por canal
        gains = np.max(
            [_gate(spectrum, noise[c], floor) for c, spectrum in enumerate(spectra)], axis=0
        )  # os canais abrem juntos
        gains, held = _release(gains, held, release)
        gains = np.clip(_smooth_bins(gains, width), floor, 1.0)
        for c, spectrum in enumerate(spectra):
            frames_out = np.fft.irfft(spectrum * gains, n=FFT_SIZE, axis=1) * WINDOW
            summed = np.zeros((count - 1) * HOP + FFT_SIZE)
            for k in range(count):
                summed[k * HOP : k * HOP + FFT_SIZE] += frames_out[k]
            begin = first * HOP
            output[begin : begin + len(summed), c] += summed.astype(np.float32)
    result = output[HEAD : HEAD + len(data)] / np.float32(OVERLAP_GAIN)
    return result[:, 0] if squeeze else result


def _gate(spectrum: np.ndarray, noise: np.ndarray, floor: float) -> np.ndarray:
    """O ganho de cada bin de cada quadro: `floor` quando a potência não passa do ruído, 1 quando passa do ruído mais
    o joelho, e a rampa em dB entre os dois."""
    power = _smooth_bins(np.abs(spectrum) ** 2, DECISION_BINS)
    over_db = 10.0 * np.log10((power + FLOOR_POWER) / noise)
    opened = np.clip(over_db / KNEE_DB, 0.0, 1.0)
    return floor ** (1.0 - opened)


def _release(gains: np.ndarray, held: np.ndarray, release: float) -> tuple[np.ndarray, np.ndarray]:
    """O ganho sobe na hora e desce devagar: cada quadro vale o maior entre o ganho dele e o do quadro anterior
    amortecido por `release`. `held` é o ganho com que o bloco anterior terminou."""
    result = np.empty_like(gains)
    for k in range(len(gains)):
        held = np.maximum(gains[k], held * release)
        result[k] = held
    return result, held


# ---------- a medida por banda (o que o MCP mostra) ----------

# bandas de um terço de oitava, de 100 Hz a 16 kHz (a série ISO): o que quem mexe com áudio reconhece. Abaixo de 100 Hz
# a janela de 2048 amostras (23 Hz por bin) não tem um bin por banda, e a medida seria um buraco
THIRD_OCTAVES_HZ = (
    100.0, 125.0, 160.0, 200.0, 250.0, 315.0, 400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0, 2000.0,
    2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 8000.0, 10000.0, 12500.0, 16000.0,
)  # fmt: skip


def band_levels(spectrum: NoiseSpectrum) -> list[tuple[float, float]]:
    """O nível do ruído em cada banda de um terço de oitava, em dBFS (RMS da banda), somando os canais pela média.
    Bandas acima da metade da taxa de amostragem ficam de fora."""
    nyquist = spectrum.sample_rate / 2
    power = spectrum.power.mean(axis=0)
    freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / spectrum.sample_rate)
    # a potência por bin de uma janela de FFT_SIZE que soma Hann ao quadrado: dividir por (N * soma de w^2) devolve
    # a potência média do sinal em dBFS^2 (uma senoide de amplitude 1 vale -3 dBFS)
    scale = FFT_SIZE * float(np.sum(WINDOW**2))
    levels: list[tuple[float, float]] = []
    for center in THIRD_OCTAVES_HZ:
        low, high = center / 2 ** (1 / 6), center * 2 ** (1 / 6)
        if center > nyquist:
            continue
        selected = (freqs >= low) & (freqs < min(high, nyquist + 1))
        if not selected.any():
            continue
        total = float(power[selected].sum()) * 2 / scale  # x2: o rfft só guarda metade do espectro
        levels.append((center, 10.0 * math.log10(max(total, FLOOR_POWER))))
    return levels
