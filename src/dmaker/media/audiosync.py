"""Sincronização de fontes pelo áudio (câmeras e gravadores que captaram o mesmo evento).

Duas etapas de correlação cruzada: uma grosseira sobre o envelope (100 Hz) do áudio inteiro, que
encontra o deslocamento aproximado mesmo em horas de gravação, e uma fina em 8 kHz numa janela
ao redor desse ponto, que refina para ~1 ms. O resultado é o instante, no relógio da fonte
principal, em que a outra fonte começa.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .ffmpeg import FFmpegCommand, FFmpegRunner

RATE = 8000  # Hz do áudio extraído para a correlação
ENVELOPE_HZ = 100  # resolução da etapa grosseira
FINE_WINDOW_S = 2.0  # busca fina ao redor do resultado grosseiro
FINE_EXCERPT_S = 90.0  # trecho usado na etapa fina (basta para refinar)


@dataclass(frozen=True)
class SyncResult:
    offset: float  # segundos: other_time = master_time - offset
    confidence: float  # razão pico/ruído da correlação; abaixo de ~4 desconfie

    @property
    def reliable(self) -> bool:
        return self.confidence >= 4.0


def extract_pcm(runner: FFmpegRunner, src: Path, dst: Path, stream: int = 0) -> Path:
    """Mono 8 kHz PCM 16 bits, o suficiente para correlacionar e leve para arquivos longos."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-i",
        str(src),
        "-map",
        f"0:a:{stream}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(RATE),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    runner.run(FFmpegCommand(args, label=f"áudio para sincronizar ({src.name})"))
    return dst


def read_pcm(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _envelope(signal: np.ndarray, rate: int, hz: int) -> np.ndarray:
    block = max(rate // hz, 1)
    n = len(signal) // block
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    env = np.abs(signal[: n * block]).reshape(n, block).mean(axis=1)
    return env - env.mean()


def _xcorr_lag(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """Lag (amostras) que melhor alinha `b` a `a` e a confiança (pico / desvio da correlação)."""
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    fa = np.fft.rfft(a, size)
    fb = np.fft.rfft(b, size)
    full = np.fft.irfft(fa * np.conj(fb), size)
    # correlação circular: lags positivos (b começa depois) em 0..len(a)-1; lags negativos no fim do vetor
    negative = full[size - (len(b) - 1) :] if len(b) > 1 else full[:0]
    corr = np.concatenate([negative, full[: len(a)]])
    peak = int(np.argmax(corr))
    lag = peak - (len(b) - 1)
    noise = float(np.std(corr)) or 1e-9
    return lag, float(corr[peak]) / noise


def estimate_offset(master: np.ndarray, other: np.ndarray, rate: int = RATE) -> SyncResult:
    """Deslocamento de `other` em relação a `master` (segundos, positivo = other começa depois)."""
    env_m = _envelope(master, rate, ENVELOPE_HZ)
    env_o = _envelope(other, rate, ENVELOPE_HZ)
    coarse_lag, confidence = _xcorr_lag(env_m, env_o)
    coarse = coarse_lag * (rate // ENVELOPE_HZ) / rate

    # etapa fina: janela em 8 kHz ao redor do alinhamento grosseiro, num trecho comum
    overlap_start = max(0.0, coarse)  # em segundos no relógio do master
    excerpt = int(min(FINE_EXCERPT_S, len(master) / rate - overlap_start, len(other) / rate) * rate)
    if excerpt > rate:  # pelo menos 1 s em comum
        m0 = int(overlap_start * rate)
        o0 = int((overlap_start - coarse) * rate)
        window = int(FINE_WINDOW_S * rate)
        seg_m = master[max(m0 - window, 0) : m0 + excerpt + window]
        seg_o = other[max(o0, 0) : o0 + excerpt]
        if len(seg_m) > len(seg_o) > rate:
            fine_lag, fine_conf = _xcorr_lag(seg_m - seg_m.mean(), seg_o - seg_o.mean())
            fine = (max(m0 - window, 0) + fine_lag - max(o0, 0)) / rate
            if abs(fine - coarse) <= FINE_WINDOW_S:
                return SyncResult(round(fine, 4), round(max(confidence, fine_conf), 2))
    return SyncResult(round(coarse, 4), round(confidence, 2))


def sync_offset(
    runner: FFmpegRunner,
    master: Path,
    other: Path,
    workdir: Path,
    master_stream: int = 0,
    other_stream: int = 0,
) -> SyncResult:
    """Extrai o áudio das duas fontes e estima o deslocamento."""
    m = extract_pcm(runner, master, workdir / f"{master.stem}.sync.wav", master_stream)
    o = extract_pcm(runner, other, workdir / f"{other.stem}.sync.wav", other_stream)
    return estimate_offset(read_pcm(m), read_pcm(o))
