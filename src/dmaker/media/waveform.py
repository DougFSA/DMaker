"""Forma de onda (picos por janela) de uma faixa de áudio, para desenhar na linha do tempo da
interface sem decodificar o arquivo inteiro no navegador.

O cálculo é leve (8 kHz, mono) e o resultado (picos normalizados 0..1) fica em cache em
`config.WAVEFORM_DIR`, com o mesmo esquema de nome por hash usado pelos proxies de prévia
(`pipeline/proxies.py`): uma fonte trocada ou reeditada gera uma forma de onda nova.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import config
from .audiosync import extract_pcm, read_pcm
from .ffmpeg import FFmpegRunner
from .peak_levels import (
    BASE_BLOCK,
    BlockAccumulator,
    PeakLevel,
    block_extremes,
    build_levels,
    level_columns,
    pick_level,
    quantize,
)
from .sample_reader import SampleReader

WAVEFORM_VERSION = "w1"  # muda quando o cálculo dos picos muda (invalida o cache)
PEAKS_PER_SECOND = 50  # resolução visual: basta para o zoom máximo da linha do tempo
ANALYSIS_RATE = 8000  # Hz do áudio extraído; picos visuais não precisam de mais que isso


def peaks_from_samples(samples: np.ndarray, sample_rate: int, peaks_per_second: int) -> list[float]:
    """Pico absoluto de cada janela de ~1/`peaks_per_second` segundos, normalizado pelo maior pico do
    trecho (0..1). A última janela conta mesmo incompleta, senão a ponta do áudio some da forma de onda."""
    if len(samples) == 0 or sample_rate <= 0 or peaks_per_second <= 0:
        return []
    window = max(1, round(sample_rate / peaks_per_second))
    windows = int(np.ceil(len(samples) / window))
    raw_peaks = np.empty(windows, dtype=np.float64)
    for i in range(windows):
        chunk = samples[i * window : (i + 1) * window]
        raw_peaks[i] = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
    peak_max = float(raw_peaks.max())
    if peak_max <= 0:
        return [0.0] * windows
    return (raw_peaks / peak_max).tolist()


@dataclass
class Waveform:
    duration: float
    peaks_per_second: int
    peaks: list[float]

    def to_dict(self) -> dict:
        return {"duration": self.duration, "peaks_per_second": self.peaks_per_second, "peaks": self.peaks}

    @staticmethod
    def from_dict(data: dict) -> Waveform:
        return Waveform(
            duration=float(data["duration"]),
            peaks_per_second=int(data["peaks_per_second"]),
            peaks=[float(p) for p in data["peaks"]],
        )


def waveform_path(src: Path, stream: int = 0) -> Path:
    """Nome no cache: hash do caminho resolvido, data de modificação, tamanho, faixa de áudio e versão
    do cálculo, para que uma fonte trocada ou reeditada gere uma forma de onda nova em vez de reaproveitar
    uma velha (mesmo esquema de `pipeline/proxies.py`)."""
    resolved = src.resolve()
    st = resolved.stat()
    raw = f"{resolved.as_posix()}|{st.st_mtime_ns}|{st.st_size}|{stream}|{WAVEFORM_VERSION}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return config.WAVEFORM_DIR / f"{digest}.json"


class WaveformBuilder:
    """Gera (e põe em cache) os picos de uma fonte de áudio. `workdir` guarda o wav temporário usado
    para o cálculo; por padrão fica dentro do próprio cache de formas de onda."""

    def __init__(self, runner: FFmpegRunner, workdir: Path | None = None):
        self.runner = runner
        self._workdir = workdir

    def _workdir_path(self) -> Path:
        return self._workdir or (config.WAVEFORM_DIR / "tmp")

    def build(self, src: Path, stream: int = 0) -> Waveform:
        target = waveform_path(src, stream)
        target.parent.mkdir(parents=True, exist_ok=True)
        workdir = self._workdir_path()
        workdir.mkdir(parents=True, exist_ok=True)
        tmp_wav = workdir / f"{target.stem}.wav"
        try:
            extract_pcm(self.runner, src, tmp_wav, stream, rate=ANALYSIS_RATE)
            samples = read_pcm(tmp_wav)
        finally:
            tmp_wav.unlink(missing_ok=True)
        peaks = peaks_from_samples(samples, ANALYSIS_RATE, PEAKS_PER_SECOND)
        waveform = Waveform(
            duration=len(samples) / ANALYSIS_RATE, peaks_per_second=PEAKS_PER_SECOND, peaks=peaks
        )
        target.write_text(json.dumps(waveform.to_dict()), encoding="utf-8")
        return waveform

    def load_or_build(self, src: Path, stream: int = 0) -> Waveform:
        target = waveform_path(src, stream)
        if target.exists():
            try:
                return Waveform.from_dict(json.loads(target.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass  # cache corrompido: recalcula
        return self.build(src, stream)


# ---------- a pirâmide de picos do editor de onda ----------
#
# A forma de onda acima (8 kHz, mono, 50 picos por segundo) serve à linha do tempo. O editor de onda precisa de mais:
# os dois canais, no zoom que a pessoa quiser, até a amostra. Em vez de um desenho por zoom, guarda-se uma pirâmide
# de mínimos e máximos (`peak_levels`), que o desenho de qualquer janela consulta.

PYRAMID_VERSION = "p1"  # muda quando o cálculo da pirâmide muda (invalida o cache)
# Quanto áudio se lê por vez ao construir: o suficiente para o numpy trabalhar em lote, pouco o bastante para a
# memória não pesar (60 s de estéreo a 48 kHz em ponto flutuante são uns 23 MB).
PYRAMID_CHUNK_SECONDS = 60.0
# Pedaços reduzidos ao mesmo tempo: o suficiente para ocupar alguns núcleos sem tomar a máquina inteira (o editor
# roda ao lado de renders e de outros programas).
PYRAMID_WORKERS = 3


@dataclass
class PeakPyramid:
    """Os picos de um áudio em vários níveis, mais o que é preciso para ler uma janela dele: a taxa, os canais e
    quantos quadros o áudio tem (`frames`)."""

    rate: int
    channels: int
    frames: int
    levels: list[PeakLevel] = field(default_factory=list)
    complete: bool = True

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def window(self, start: float, end: float, columns: int) -> tuple[np.ndarray, np.ndarray] | None:
        """O mínimo e o máximo de `columns` colunas entre `start` e `end` (segundos), ou None quando as colunas são mais
        finas que o nível de base: então a janela deve ser lida em amostras (`sample_columns`)."""
        first, last = int(round(start * self.rate)), int(round(end * self.rate))
        if columns <= 0 or last <= first:
            return None
        level = pick_level(self.levels, (last - first) / columns)
        if level is None:
            return None
        return level_columns(level, first, last, columns)


def save_pyramid(path: Path, pyramid: PeakPyramid) -> None:
    """Grava só o nível de base: os mais grossos saem dele em milissegundos ao abrir, e o arquivo fica 25% menor."""
    base = pyramid.levels[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".tmp.npz")
    np.savez(
        staging,
        meta=np.array([pyramid.rate, pyramid.channels, pyramid.frames, base.block], dtype=np.int64),
        mins=base.mins,
        maxs=base.maxs,
    )
    staging.replace(path)


def load_pyramid(path: Path) -> PeakPyramid | None:
    """A pirâmide guardada, ou None quando o arquivo não existe ou está estragado (então se refaz)."""
    try:
        with np.load(path) as data:
            rate, channels, frames, block = (int(value) for value in data["meta"])
            base = PeakLevel(block, data["mins"], data["maxs"])
    except (OSError, KeyError, ValueError):
        return None
    return PeakPyramid(rate, channels, frames, build_levels(base))


def _chunk_blocks(reader: SampleReader, first: int, frames: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Lê `frames` quadros a partir de `first` e devolve o nível de base deles (já em inteiros de 8 bits)."""
    chunk = reader.read(first / reader.rate, frames / reader.rate)[:frames]
    low, high = block_extremes(chunk, BASE_BLOCK)
    return quantize(low), quantize(high), chunk.shape[0]


def build_pyramid(
    reader: SampleReader,
    duration: float,
    *,
    accumulator: BlockAccumulator | None = None,
    on_progress: Callable[[float], None] | None = None,
    chunk_seconds: float = PYRAMID_CHUNK_SECONDS,
    workers: int = PYRAMID_WORKERS,
    should_stop: Callable[[], bool] | None = None,
) -> PeakPyramid:
    """Lê o áudio em pedaços de `chunk_seconds` e monta a pirâmide, sem nunca ter o áudio inteiro na memória. Os pedaços
    terminam em fronteira de bloco, então vários são reduzidos ao mesmo tempo (o numpy solta o GIL ao reduzir, e cada
    decodificação do ffmpeg é um processo à parte) e chegam ao acumulador na ordem. Quem chama pode passar o `accumulator`
    para consultar a pirâmide parcial enquanto ela é feita; `on_progress` recebe os segundos já lidos."""
    accumulator = accumulator or BlockAccumulator(reader.channels)
    total = int(round(duration * reader.rate))
    step = max(1, round(chunk_seconds * reader.rate / BASE_BLOCK)) * BASE_BLOCK
    pending: deque[tuple[int, Future]] = deque()
    next_start = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        try:
            while next_start < total or pending:
                stopped = should_stop is not None and should_stop()
                while not stopped and next_start < total and len(pending) < max(1, workers) + 1:
                    frames = min(step, total - next_start)
                    pending.append((next_start, pool.submit(_chunk_blocks, reader, next_start, frames)))
                    next_start += frames
                if not pending:
                    break
                start, future = pending.popleft()
                low, high, frames = future.result()
                accumulator.append_blocks(low, high, frames)
                if on_progress is not None:
                    on_progress((start + frames) / reader.rate)
                if stopped:
                    break
        finally:
            for _, future in pending:
                future.cancel()
    base = accumulator.base(final=True)
    return PeakPyramid(reader.rate, reader.channels, accumulator.frames, build_levels(base))


__all__ = [
    "BASE_BLOCK",
    "PYRAMID_CHUNK_SECONDS",
    "PYRAMID_VERSION",
    "PeakPyramid",
    "Waveform",
    "WaveformBuilder",
    "build_pyramid",
    "load_pyramid",
    "peaks_from_samples",
    "save_pyramid",
    "waveform_path",
]
