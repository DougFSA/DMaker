"""Síntese dos efeitos sonoros da biblioteca: funções puras (numpy, semente fixa, sem disco).

Os sons são sintetizados aqui, e não baixados, para a biblioteca ser obra própria do DMaker (sem licença de
terceiros), reproduzível e sem depender da internet. Cada som é um gerador registrado por nome; o
acabamento comum (bordas sem estalo e pico em -3 dBFS) é aplicado em `synthesize`, não em cada gerador.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 48_000  # a taxa da mixagem do DMaker: o som entra sem reamostrar
# Pico padronizado de todo som da biblioteca: com o mesmo pico, o `volume` da spec significa o mesmo em todos.
# -3 dBFS deixa folga contra o clipe de conversão para 16 bits e contra a soma com outros sons.
PEAK_DBFS = -3.0
FADE_IN_SECONDS = 0.001  # 1 ms: o menor que ainda zera a primeira amostra sem comer o ataque
# 21 ms a 48 kHz: janela longa o bastante para resolver 100 Hz e curta para seguir uma varredura
STFT_FRAME = 1024
STFT_HOP = STFT_FRAME // 4  # 75% de sobreposição: com janela de Hann a reconstrução é exata


@dataclass(frozen=True)
class Sound:
    """Som pronto: amostras mono em float (-1..1) e a taxa."""

    samples: np.ndarray
    sample_rate: int = SAMPLE_RATE

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate

    @property
    def peak_dbfs(self) -> float:
        peak = float(np.max(np.abs(self.samples))) if len(self.samples) else 0.0
        return 20.0 * np.log10(peak) if peak > 0 else float("-inf")


@dataclass(frozen=True)
class SoundDef:
    """Receita de um som: o nome que a spec usa, o que ele é, a duração e o gerador."""

    name: str
    description: str
    duration: float  # segundos
    seed: int  # fixa o ruído: o mesmo som sai idêntico a cada geração
    generate: Callable[[np.random.Generator], np.ndarray]  # amostras mono em float, sem o acabamento
    fade_out: float = 0.01  # s: a cauda que leva o som a zero sem estalo no fim


_REGISTRY: dict[str, SoundDef] = {}


def sound(name: str, description: str, duration: float, seed: int, fade_out: float = 0.01):
    """Registra um gerador na biblioteca (extensão por registro: som novo é uma função nova, sem `if`)."""

    def register(generate: Callable[[np.random.Generator], np.ndarray]):
        if name in _REGISTRY:
            raise ValueError(f"som duplicado na biblioteca: {name!r}")
        _REGISTRY[name] = SoundDef(name, description, duration, seed, generate, fade_out)
        return generate

    return register


def library_names() -> tuple[str, ...]:
    """Nomes da biblioteca, na ordem em que foram registrados."""
    return tuple(_REGISTRY)


def sound_def(name: str) -> SoundDef:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"som {name!r} não existe na biblioteca (disponíveis: {', '.join(_REGISTRY)})"
        ) from None


def synthesize(name: str) -> Sound:
    """Gera o som `name` do zero: mesma semente, mesmas amostras. Já sai com bordas suaves e pico de -3 dBFS."""
    definition = sound_def(name)
    rng = np.random.default_rng(definition.seed)
    count = int(round(definition.duration * SAMPLE_RATE))
    samples = np.asarray(definition.generate(rng), dtype=np.float64)
    if len(samples) != count:
        raise ValueError(f"{name}: o gerador devolveu {len(samples)} amostras, esperava {count}")
    samples = samples * _edge_window(count, FADE_IN_SECONDS, definition.fade_out)
    return Sound(normalize_peak(samples, PEAK_DBFS))


def normalize_peak(samples: np.ndarray, peak_dbfs: float) -> np.ndarray:
    """Escala as amostras para que o maior valor absoluto fique em `peak_dbfs`; silêncio fica como está."""
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak <= 0:
        return samples
    return samples * (10.0 ** (peak_dbfs / 20.0) / peak)


def _edge_window(count: int, fade_in: float, fade_out: float) -> np.ndarray:
    """Janela que sobe do zero no começo e volta a zero no fim (meio cosseno), para nunca haver estalo."""
    window = np.ones(count)
    for length, ascending in (
        (int(round(fade_in * SAMPLE_RATE)), True),
        (int(round(fade_out * SAMPLE_RATE)), False),
    ):
        length = min(length, count // 2)
        if length < 1:
            continue
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(length) / length)  # 0 -> quase 1
        if ascending:
            window[:length] *= ramp
        else:
            window[count - length :] *= ramp[::-1]
    window[-1] = 0.0  # a última amostra é zero mesmo com fade de 1 amostra
    return window


# ---------- blocos de síntese ----------


def _seconds(duration: float) -> np.ndarray:
    return np.arange(int(round(duration * SAMPLE_RATE))) / SAMPLE_RATE


def _white_noise(rng: np.random.Generator, count: int) -> np.ndarray:
    """Ruído branco uniforme em -1..1 (o uniforme, e não o normal: o fluxo do PCG64 é estável entre versões)."""
    return 2.0 * rng.random(count) - 1.0


def _geometric_sweep(start_hz: float, end_hz: float, count: int, curve: float = 1.0) -> np.ndarray:
    """Frequência que vai de `start_hz` a `end_hz` em escala geométrica (o ouvido sente oitavas, não hertz).
    `curve` > 1 demora no início e acelera no fim."""
    progress = np.linspace(0.0, 1.0, count) ** curve
    return start_hz * (end_hz / start_hz) ** progress


def _bandpass_sweep(
    noise: np.ndarray, center_hz: np.ndarray, width_octaves: float, sample_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """Filtra `noise` por uma banda gaussiana (em oitavas) cujo centro segue `center_hz` amostra a amostra.

    É o que dá o "fiu" do whoosh: ruído branco passado por uma banda que varre o espectro. Feito por STFT
    com sobreposição e janela de Hann, porque um filtro IIR de coeficientes variáveis precisaria de um laço
    por amostra, e aqui o ganho por quadro é uma conta vetorial.
    """
    count = len(noise)
    padded = np.pad(noise, (STFT_FRAME, 2 * STFT_FRAME))  # folga para todo quadro ter vizinhos dos dois lados
    window = np.hanning(STFT_FRAME)
    starts = np.arange(0, len(padded) - STFT_FRAME, STFT_HOP)
    frames = np.stack([padded[s : s + STFT_FRAME] * window for s in starts])
    spectrum = np.fft.rfft(frames, axis=1)
    frequencies = np.fft.rfftfreq(STFT_FRAME, 1.0 / sample_rate)
    middle = np.clip(starts + STFT_FRAME // 2 - STFT_FRAME, 0, count - 1)  # amostra do meio de cada quadro
    centers = center_hz[middle][:, None]
    octaves = np.log2(np.maximum(frequencies, 1.0)[None, :] / centers)
    gain = np.exp(-0.5 * (octaves / width_octaves) ** 2)
    gain[:, 0] = 0.0  # sem componente contínua
    filtered = np.fft.irfft(spectrum * gain, n=STFT_FRAME, axis=1) * window
    out = np.zeros(len(padded))
    weight = np.zeros(len(padded))
    for index, start in enumerate(starts):
        out[start : start + STFT_FRAME] += filtered[index]
        weight[start : start + STFT_FRAME] += window**2
    out /= np.maximum(weight, 1e-9)
    return out[STFT_FRAME : STFT_FRAME + count]


def _swell(count: int, peak_at: float, power: float = 1.0) -> np.ndarray:
    """Sobe e desce em sino, com o máximo em `peak_at` (0..1 da duração): o contorno de volume de um whoosh."""
    progress = np.linspace(0.0, 1.0, count)
    warped = progress ** (np.log(0.5) / np.log(peak_at))  # leva o máximo para o meio do seno
    return np.sin(np.pi * warped) ** (2.0 * power)


def _decay(t: np.ndarray, tau: float, attack: float = 0.001) -> np.ndarray:
    """Subida linear curta (sem estalo) seguida de queda exponencial de constante `tau`."""
    rise = np.minimum(t / attack, 1.0) if attack > 0 else 1.0
    return rise * np.exp(-t / tau)


def _tone(frequency_hz: np.ndarray) -> np.ndarray:
    """Seno cuja frequência instantânea é `frequency_hz` (a fase é a integral, sem salto)."""
    return np.sin(2.0 * np.pi * np.cumsum(frequency_hz) / SAMPLE_RATE)


# ---------- a biblioteca ----------


@sound("whoosh", "passagem de ar que sobe e some, para entrada de elemento ou troca de cena", 0.75, seed=11)
def _whoosh(rng: np.random.Generator) -> np.ndarray:
    count = int(round(0.75 * SAMPLE_RATE))
    noise = _white_noise(rng, count)
    band = _bandpass_sweep(noise, _geometric_sweep(260.0, 3400.0, count), width_octaves=1.1)
    return band * _swell(count, peak_at=0.42)


@sound("whip", "chicote curto e agudo, para entradas rápidas", 0.3, seed=12, fade_out=0.015)
def _whip(rng: np.random.Generator) -> np.ndarray:
    count = int(round(0.3 * SAMPLE_RATE))
    noise = _white_noise(rng, count)
    band = _bandpass_sweep(noise, _geometric_sweep(800.0, 7600.0, count), width_octaves=0.9)
    return band * _swell(count, peak_at=0.3, power=1.5)


@sound("pop", "estalo de bolha, para texto ou ícone que aparece", 0.16, seed=13, fade_out=0.02)
def _pop(rng: np.random.Generator) -> np.ndarray:
    t = _seconds(0.16)
    pitch = 380.0 + 820.0 * np.exp(-t / 0.014)  # cai de ~1200 Hz para 380 Hz em poucos milissegundos
    body = _tone(pitch) * _decay(t, tau=0.028, attack=0.0008)
    overtone = _tone(pitch * 2.0) * _decay(t, tau=0.012, attack=0.0008) * 0.25
    hiss = _bandpass_sweep(_white_noise(rng, len(t)), np.full(len(t), 3200.0), 1.2) * _decay(t, 0.004, 0.0003)
    return body + overtone + 0.35 * hiss / max(float(np.max(np.abs(hiss))), 1e-9)


@sound("click", "clique de mouse (aperta e solta), para toque e seleção", 0.08, seed=14, fade_out=0.015)
def _click(rng: np.random.Generator) -> np.ndarray:
    t = _seconds(0.08)
    noise = _white_noise(rng, len(t))
    press = _bandpass_sweep(noise, np.full(len(t), 3600.0), 1.0) * _decay(t, 0.0045, 0.0002)
    t_release = np.clip(t - 0.045, 0.0, None)  # o "solta" vem 45 ms depois, mais fraco e mais grave
    release = _bandpass_sweep(noise[::-1].copy(), np.full(len(t), 2400.0), 1.0) * _decay(
        t_release, 0.003, 0.0002
    )
    press_peak = max(float(np.max(np.abs(press))), 1e-9)
    return press / press_peak + 0.35 * release / max(float(np.max(np.abs(release))), 1e-9)


@sound("riser", "subida de tensão que cresce até o fim, para pôr logo antes de uma revelação", 1.6, seed=15)
def _riser(rng: np.random.Generator) -> np.ndarray:
    count = int(round(1.6 * SAMPLE_RATE))
    t = np.arange(count) / SAMPLE_RATE
    progress = t / 1.6
    noise = _bandpass_sweep(_white_noise(rng, count), _geometric_sweep(180.0, 6500.0, count, curve=1.4), 0.8)
    tone = _tone(_geometric_sweep(220.0, 1760.0, count, curve=1.4))
    return (noise * 1.0 + tone * 0.6) * progress**2.2


@sound("impact", "pancada grave com cauda, para o momento de maior peso", 1.4, seed=16, fade_out=0.05)
def _impact(rng: np.random.Generator) -> np.ndarray:
    t = _seconds(1.4)
    pitch = 38.0 + 82.0 * np.exp(-t / 0.06)  # o tom cai de 120 Hz para 38 Hz: o "thud"
    body = _tone(pitch) * _decay(t, tau=0.30, attack=0.003)
    noise = _white_noise(rng, len(t))
    rumble = _bandpass_sweep(noise, np.full(len(t), 70.0), 1.2) * _decay(t, 0.38, 0.002)
    crack = _bandpass_sweep(noise[::-1].copy(), np.full(len(t), 1800.0), 1.5) * _decay(t, 0.012, 0.0005)
    rumble /= max(float(np.max(np.abs(rumble))), 1e-9)
    crack /= max(float(np.max(np.abs(crack))), 1e-9)
    return body + 0.5 * rumble + 0.3 * crack


@sound("ding", "sino curto e limpo, para destacar um resultado", 1.3, seed=17, fade_out=0.08)
def _ding(rng: np.random.Generator) -> np.ndarray:
    t = _seconds(1.3)
    out = np.zeros(len(t))
    # parciais de sino (não harmônicos): cada um decai mais rápido que o anterior, e é isso que soa a metal
    for ratio, level, tau in ((1.0, 1.0, 0.45), (2.7, 0.45, 0.28), (5.2, 0.25, 0.16), (8.1, 0.12, 0.09)):
        out += level * np.sin(2.0 * np.pi * 1318.5 * ratio * t) * _decay(t, tau, attack=0.0015)
    return out
