"""Espectro de Frequência (Plot Spectrum): o gráfico de nível por frequência de um trecho.

Os quatro algoritmos do Audacity: o espectro (FFT com janela, média dos quadros), a autocorrelação, a autocorrelação
aprimorada e o cepstro. Os três últimos servem para achar o tom de um som (a frequência fundamental) e saem na mesma
forma do primeiro, uma lista de frequência e nível em dB. A conta é do módulo `analysis/fft.py`, que o espectrograma
reaproveita; aqui entram só os algoritmos e o resultado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import field_validator

from ..fft import (
    DEFAULT_FFT_SIZE,
    DEFAULT_WINDOW,
    FRAME_BATCH,
    SPECTRUM_FLOOR_DB,
    WindowName,
    amplitude_spectrum_db,
    averaged_power,
    bin_frequencies,
    frame_count,
    is_fft_size,
    peak_frequency,
    refine_peak,
    window_coefficients,
    windowed_frames,
)
from ..notes import note_for
from ..registry import AnalysisResult, AnalyzerBase, param, register_analyzer
from ..signal import Signal

Algorithm = Literal["spectrum", "autocorrelation", "enhanced_autocorrelation", "cepstrum"]
ALGORITHMS = ("spectrum", "autocorrelation", "enhanced_autocorrelation", "cepstrum")
Axis = Literal["linear", "log"]

# a correlação normalizada vai de -1 a 1; abaixo deste valor o dB é piso, não sinal
_CORRELATION_FLOOR = 1e-4
_TOP_PEAKS = 5
# o tom mais agudo que a autocorrelação e o cepstro procuram: acima disso é timbre, não a fundamental de uma voz
MAX_PITCH_HZ = 2000
# abaixo disto não é som audível (e o piso de baixa frequência do espectro não é um pico de verdade)
MIN_PEAK_HZ = 20.0
# o número de pontos da curva que o resultado em JSON leva (o CSV leva todos)
DEFAULT_CURVE_POINTS = 512


@dataclass(kw_only=True)
class SpectrumPeak:
    frequency: float
    level_db: float
    note: str | None = None


@dataclass(kw_only=True)
class SpectrumResult(AnalysisResult):
    algorithm: str
    window: str
    size: int
    sample_rate: int
    axis: str
    bin_hz: float
    peak_hz: float
    peak_bin: int
    peak_db: float
    peak_note: str | None
    peaks: list[SpectrumPeak]
    frequencies: list[float] = field(repr=False)
    levels_db: list[float] = field(repr=False)

    def to_dict(self, detail: str = "compact", limit: int | None = None) -> dict[str, Any]:
        """O resultado sem as listas completas: a curva vai reduzida a `limit` pontos (512 por padrão; o pico de cada
        grupo, para nenhum pico sumir), e o arquivo CSV leva todos. `detail="full"` entrega a curva inteira."""
        data = {
            key: value
            for key, value in self.__dict__.items()
            if key not in ("frequencies", "levels_db", "peaks")
        }
        data["peaks"] = [peak.__dict__ for peak in self.peaks]
        frequencies, levels = decimate_curve(
            self.frequencies, self.levels_db, None if detail == "full" else limit or DEFAULT_CURVE_POINTS
        )
        data["curve"] = {
            "frequencies": frequencies,
            "levels_db": levels,
            "points_total": len(self.frequencies),
        }
        return data

    def table(self, separator: str = ",") -> str:
        """Uma frequência e um nível em dB por linha, como o "Export" do Audacity."""
        lines = [f"frequencia_hz{separator}nivel_db"]
        lines += [
            f"{frequency:.4f}{separator}{level:.3f}"
            for frequency, level in zip(self.frequencies, self.levels_db, strict=True)
        ]
        return "\n".join(lines) + "\n"


def decimate_curve(
    frequencies: list[float], levels: list[float], points: int | None
) -> tuple[list[float], list[float]]:
    """Reduz a curva a `points` pontos guardando, em cada grupo de divisões vizinhas, a mais alta: o gráfico fica
    leve e um pico estreito não desaparece. Sem `points` (ou com menos divisões que isso) devolve a curva inteira."""
    count = len(frequencies)
    if points is None or points <= 0 or count <= points:
        return [round(f, 4) for f in frequencies], [round(v, 3) for v in levels]
    edges = np.linspace(0, count, points + 1).astype(int)
    values = np.asarray(levels)
    picked = [
        int(low + np.argmax(values[low:high])) if high > low else min(low, count - 1)
        for low, high in zip(edges[:-1], edges[1:], strict=True)
    ]
    return [round(frequencies[i], 4) for i in picked], [round(levels[i], 3) for i in picked]


# ---------- os algoritmos ----------


def spectrum_curve(
    samples: np.ndarray, sample_rate: int, size: int, window_name: str
) -> tuple[np.ndarray, np.ndarray]:
    """Frequência e nível (dBFS de amplitude) de cada divisão da FFT, na média dos quadros do trecho."""
    window = window_coefficients(window_name, size)
    levels = amplitude_spectrum_db(averaged_power(samples, size, window), window)
    return bin_frequencies(size, sample_rate), levels


def autocorrelation(samples: np.ndarray, size: int, window_name: str) -> np.ndarray:
    """A autocorrelação normalizada (1,0 no atraso zero) dos quadros janelados, na média. A FFT leva o dobro do
    quadro em zeros para a correlação não dar a volta (a circular misturaria o fim com o começo)."""
    window = window_coefficients(window_name, size)
    total = frame_count(len(samples), size)
    accumulated = np.zeros(size, dtype=np.float64)
    for first in range(0, total, FRAME_BATCH):
        frames = windowed_frames(samples, size, window, None, first, FRAME_BATCH)
        spectra = np.abs(np.fft.rfft(frames, n=2 * size, axis=1)) ** 2
        accumulated += np.fft.irfft(spectra, n=2 * size, axis=1)[:, :size].sum(axis=0)
    if accumulated[0] <= 0:
        return np.zeros(size, dtype=np.float64)
    return accumulated / accumulated[0]


def enhanced_autocorrelation(correlation: np.ndarray) -> np.ndarray:
    """Tira da autocorrelação os picos dos múltiplos do atraso (o dobro e o triplo), que fazem um tom parecer uma
    oitava mais grave do que é: só o atraso da fundamental sobra."""
    base = np.maximum(correlation, 0.0)
    lags = np.arange(len(base), dtype=np.float64)
    enhanced = base.copy()
    for factor in (2.0, 3.0):
        stretched = np.interp(lags / factor, lags, base)
        enhanced = np.maximum(enhanced - stretched, 0.0)
    return enhanced


def cepstrum(samples: np.ndarray, size: int, window_name: str) -> np.ndarray:
    """O cepstro real: a transformada inversa do logaritmo do espectro (na média dos quadros). Um som com tom, que
    tem harmônicos regulares, mostra um pico no atraso do período dele."""
    window = window_coefficients(window_name, size)
    total = frame_count(len(samples), size)
    log_power = np.zeros(size // 2 + 1, dtype=np.float64)
    for first in range(0, total, FRAME_BATCH):
        frames = windowed_frames(samples, size, window, None, first, FRAME_BATCH)
        log_power += np.log(np.abs(np.fft.rfft(frames, axis=1)) ** 2 + 1e-18).sum(axis=0)
    return np.abs(np.fft.irfft(log_power / total, n=size))[: size // 2]


def lag_peak(values: np.ndarray, skip_first_lobe: bool, min_lag: int = 2) -> float | None:
    """O atraso, em amostras, do pico que marca o período do tom, refinado entre amostras. Na autocorrelação o
    pico do atraso zero é só o som consigo mesmo, então a busca começa depois de a curva cruzar o zero. `min_lag`
    descarta os atrasos curtos demais para ser um tom (o envelope do espectro enche o começo do cepstro)."""
    count = len(values)
    low = max(min_lag, 2)
    if skip_first_lobe:
        below = np.flatnonzero(values[1:] <= 0.0)
        low = max(low, int(below[0]) + 1 if below.size else count)
    if low >= count - 1:
        return None
    lag = low + int(np.argmax(values[low : count - 1]))
    if values[lag] <= 0.0:
        return None
    if 0 < lag < count - 1:
        left, centre, right = (float(values[lag + shift]) for shift in (-1, 0, 1))
        curvature = left - 2.0 * centre + right
        if curvature < 0:
            return lag + 0.5 * (left - right) / curvature
    return float(lag)


def lags_as_curve(values: np.ndarray, sample_rate: int, to_db_floor: float) -> tuple[np.ndarray, np.ndarray]:
    """Põe uma curva de atraso (autocorrelação, cepstro) no mesmo formato do espectro: a frequência de cada atraso
    (taxa / atraso, em ordem crescente) e o nível em dB, em que o maior valor da curva fica em 0 dB."""
    lags = np.arange(1, len(values))
    peak = float(np.max(np.abs(values[1:]))) if len(values) > 1 else 0.0
    scale = peak if peak > 0 else 1.0
    levels = 20.0 * np.log10(np.maximum(np.abs(values[1:]) / scale, _CORRELATION_FLOOR))
    levels = np.maximum(levels, to_db_floor)
    frequencies = sample_rate / lags
    return frequencies[::-1], levels[::-1]


@register_analyzer
class FrequencySpectrum(AnalyzerBase):
    """O nível por frequência do trecho, pelo espectro, pela autocorrelação ou pelo cepstro."""

    type: Literal["spectrum"] = "spectrum"
    label: ClassVar[str] = "Espectro de Frequência"
    audacity_name: ClassVar[str] = "Plot Spectrum"
    summary: ClassVar[str] = (
        "Mostra o nível de cada frequência do trecho (espectro, autocorrelação ou cepstro), com o pico, a nota "
        "mais próxima e os dados em CSV ou PNG."
    )
    exports: ClassVar[tuple[str, ...]] = ("csv", "png")

    algorithm: Algorithm = param(
        "spectrum",
        label="Algoritmo",
        hint="Espectro (FFT), autocorrelação, autocorrelação aprimorada ou cepstro. Os três últimos acham o tom.",
    )
    window: WindowName = param(
        DEFAULT_WINDOW,
        label="Janela",
        hint="O formato da janela da FFT: Hann, Hamming, Blackman, Blackman-Harris, Welch, Bartlett, "
        "retangular ou gaussiana.",
    )
    size: int = param(
        DEFAULT_FFT_SIZE,
        label="Tamanho da FFT",
        unit="amostras",
        hint="Potência de dois de 128 a 65536. Maior separa melhor as frequências e mostra menos o tempo.",
        ge=128,
        le=65536,
    )
    axis: Axis = param(
        "log",
        label="Eixo de frequência",
        hint="Logarítmico (como o ouvido escuta) ou linear. Vale para o gráfico em PNG e na interface.",
    )

    @field_validator("size")
    @classmethod
    def _power_of_two(cls, value: int) -> int:
        if not is_fft_size(value):
            raise ValueError(f"{value} não é uma potência de dois de 128 a 65536")
        return value

    def analyze(self, signal: Signal) -> SpectrumResult:
        if signal.frames == 0:
            raise ValueError("não há amostras para analisar: o trecho está vazio")
        mono, rate = signal.mono(), signal.sample_rate
        if self.algorithm == "spectrum":
            frequencies, levels = spectrum_curve(mono, rate, self.size, self.window)
            peak_bin, peak_hz = peak_frequency(levels, frequencies)
            peak_db = refine_peak(levels, frequencies, peak_bin)[
                1
            ]  # o nível do tom, não o da divisão mais perto
        else:
            frequencies, levels, peak_hz, peak_bin = self._pitch_curve(mono, rate)
            peak_db = float(levels[peak_bin]) if len(levels) else SPECTRUM_FLOOR_DB
        note = note_for(peak_hz)
        peaks = _top_peaks(frequencies, levels, self.algorithm == "spectrum")
        what = {
            "spectrum": "do espectro",
            "autocorrelation": "da autocorrelação",
            "enhanced_autocorrelation": "da autocorrelação aprimorada",
            "cepstrum": "do cepstro",
        }[self.algorithm]
        return SpectrumResult(
            analyzer=self.type,
            summary=(
                f"Pico {what} em {peak_hz:.1f} Hz ({peak_db:.1f} dB"
                + (f", perto de {note.name}" if note else "")
                + ")."
            ),
            algorithm=self.algorithm,
            window=self.window,
            size=self.size,
            sample_rate=rate,
            axis=self.axis,
            bin_hz=round(rate / self.size, 6),
            peak_hz=round(peak_hz, 3),
            peak_bin=int(peak_bin),
            peak_db=round(peak_db, 3),
            peak_note=note.label() if note else None,
            peaks=peaks,
            frequencies=[float(f) for f in frequencies],
            levels_db=[float(v) for v in levels],
        )

    def _pitch_curve(self, mono: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray, float, int]:
        """A curva e o pico de um dos algoritmos de atraso (autocorrelação, aprimorada ou cepstro)."""
        if self.algorithm == "cepstrum":
            values, skip_lobe = cepstrum(mono, self.size, self.window), False
        else:
            values = autocorrelation(mono, self.size, self.window)
            values = (
                enhanced_autocorrelation(values) if self.algorithm == "enhanced_autocorrelation" else values
            )
            skip_lobe = self.algorithm == "autocorrelation"
        frequencies, levels = lags_as_curve(values, rate, SPECTRUM_FLOOR_DB)
        lag = lag_peak(values, skip_lobe, int(rate // MAX_PITCH_HZ))
        if lag is None:
            return frequencies, levels, 0.0, 0
        peak_hz = rate / lag
        return frequencies, levels, peak_hz, int(np.argmin(np.abs(frequencies - peak_hz)))


def _top_peaks(frequencies: np.ndarray, levels: np.ndarray, refine: bool) -> list[SpectrumPeak]:
    """Os `_TOP_PEAKS` maiores picos locais da curva acima de `MIN_PEAK_HZ`, do mais alto ao mais baixo, cada um com a
    nota mais próxima. Na curva do espectro (`refine`) a frequência de cada um é refinada entre divisões, como a do pico
    principal; nas de atraso (autocorrelação, cepstro) as divisões não são uniformes e valem como vêm."""
    if len(levels) < 3:
        return []
    inner = levels[1:-1]
    local = np.flatnonzero((inner > levels[:-2]) & (inner >= levels[2:])) + 1
    local = local[frequencies[local] >= MIN_PEAK_HZ]
    order = local[np.argsort(levels[local])[::-1]][:_TOP_PEAKS]
    peaks = []
    for index in order:
        frequency, level = (
            refine_peak(levels, frequencies, int(index))
            if refine
            else (float(frequencies[index]), float(levels[index]))
        )
        note = note_for(frequency)
        peaks.append(
            SpectrumPeak(
                frequency=round(frequency, 3), level_db=round(level, 3), note=note.label() if note else None
            )
        )
    return peaks


__all__ = ["ALGORITHMS", "FrequencySpectrum", "SpectrumPeak", "SpectrumResult"]
