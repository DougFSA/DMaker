"""Sincronização de fontes pelo áudio (câmeras e gravadores que captaram o mesmo evento).

Duas formas de buscar o deslocamento: cega (`estimate_offset`), com uma etapa grosseira sobre o
envelope (100 Hz) do áudio inteiro, que encontra o alinhamento aproximado mesmo em horas de
gravação, seguida de uma fina em 8 kHz que refina para ~1 ms; e guiada (`estimate_offset_near`),
que já sabe a vizinhança esperada e por isso correlaciona direto em 8 kHz, sem a etapa grosseira —
o envelope de 100 Hz existe para tornar viável um arquivo inteiro de horas, mas amassa demais um
recorte de minutos, a ponto de a rajada de áudio certa perder para uma coincidência de ruído em
outro ponto do recorte. O resultado é o instante, no relógio da fonte principal, em que a outra
fonte começa.
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
MIN_GUIDED_OVERLAP_S = 8.0  # abaixo disso não há sinal suficiente para correlacionar com confiança
MAX_GUIDED_OVERLAP_S = 600.0  # teto do trecho correlacionado na busca guiada, para a FFT ficar rápida


@dataclass(frozen=True)
class SyncResult:
    offset: float  # segundos: other_time = master_time - offset
    confidence: float  # razão pico/ruído da correlação; abaixo de ~4 desconfie

    @property
    def reliable(self) -> bool:
        return self.confidence >= 4.0


def extract_pcm(runner: FFmpegRunner, src: Path, dst: Path, stream: int = 0, rate: int = RATE) -> Path:
    """Mono PCM 16 bits em `rate` Hz, leve o bastante para correlacionar ou calcular picos mesmo em
    arquivos longos. `rate` por padrão é o da sincronização (8 kHz); a forma de onda (`waveform.py`)
    usa o mesmo valor por coincidência de necessidade, não por acoplamento entre os dois módulos."""
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
        str(rate),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    runner.run(FFmpegCommand(args, label=f"áudio para análise ({src.name})"))
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


def estimate_offset_near(
    master: np.ndarray, other: np.ndarray, expected: float, tolerance: float, rate: int = RATE
) -> SyncResult:
    """Correlaciona só a região onde `other` deveria cair se o deslocamento for `expected ± tolerance`,
    para achar um alinhamento confiável entre dois arquivos longos com pouca sobreposição em comum
    (a correlação cega dilui o sinal real no ruído do resto do arquivo)."""
    master_duration = len(master) / rate
    other_duration = len(other) / rate
    overlap_start = max(0.0, expected)
    overlap_end = min(master_duration, expected + other_duration)
    if overlap_end - overlap_start < MIN_GUIDED_OVERLAP_S:
        return SyncResult(round(expected, 4), 0.0)

    m_lo = max(0.0, expected - tolerance)
    m_hi = min(master_duration, expected + other_duration + tolerance)
    if m_hi - m_lo > MAX_GUIDED_OVERLAP_S:
        center = (overlap_start + overlap_end) / 2
        half = MAX_GUIDED_OVERLAP_S / 2
        m_lo = max(0.0, center - half)
        m_hi = min(master_duration, center + half)

    o_lo = max(0.0, m_lo - expected)
    o_hi = min(other_duration, m_hi - expected)
    seg_m = master[int(round(m_lo * rate)) : int(round(m_hi * rate))]
    seg_o = other[int(round(o_lo * rate)) : int(round(o_hi * rate))]
    if len(seg_m) < rate or len(seg_o) < rate:  # menos de 1s em algum lado: nada para correlacionar
        return SyncResult(round(expected, 4), 0.0)

    # correlação direta em `rate` (sem o envelope grosseiro): o recorte já é pequeno o bastante
    # (no máximo `MAX_GUIDED_OVERLAP_S`) para a FFT ficar rápida mesmo na resolução plena
    lag, confidence = _xcorr_lag(seg_m - seg_m.mean(), seg_o - seg_o.mean())
    absolute = lag / rate + m_lo - o_lo  # compensa o corte: os dois trechos começam depois de 0
    return SyncResult(round(absolute, 4), round(confidence, 2))


def sync_offset_near(
    runner: FFmpegRunner,
    master: Path,
    other: Path,
    workdir: Path,
    expected: float,
    tolerance: float,
    master_stream: int = 0,
    other_stream: int = 0,
) -> SyncResult:
    """Como `sync_offset`, mas guiado por um deslocamento esperado; reaproveita o PCM já extraído."""
    m = extract_pcm(runner, master, workdir / f"{master.stem}.sync.wav", master_stream)
    o = extract_pcm(runner, other, workdir / f"{other.stem}.sync.wav", other_stream)
    return estimate_offset_near(read_pcm(m), read_pcm(o), expected, tolerance)
