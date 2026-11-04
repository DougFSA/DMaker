"""O espectrograma de um item como o painel Áudio o mostra: uma imagem PNG em tons de cinza de um trecho do som, com cache.

A imagem sai do som "como se ouve" (o leitor do `AudioPanelService`: o arquivo já com os efeitos, se o item os tem) e da
FFT de `analysis.spectrogram`. Duas coisas mantêm o custo baixo numa hora de áudio:

- cada coluna lê só uns poucos quadros de dentro do trecho dela (`MAX_FRAMES_PER_COLUMN`), e os quadros são lidos em pedaços
  de 20 s ou, se são raros, um a um, nunca o áudio todo de uma vez;
- o trecho pedido é encaixado numa grade de colunas (`snap_grid`), então um passo de zoom ou de rolagem pequeno cai na
  mesma imagem já guardada em `cache/spectrogram`, que tem a chave do som mais os parâmetros e o trecho da grade.

O PNG é em tons de cinza de 0 a 255, já com ganho e alcance. A cor é escolhida por quem mostra a imagem.
"""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .. import config
from ..analysis.spectrogram import SpectrogramParams, spectrogram_gray
from ..media.sample_reader import SampleReader, random_access
from .audio_panel import HeardPlan

SPECTROGRAM_VERSION = "sg1"  # muda quando a conta da imagem muda (invalida o cache)
GRID_COLUMNS = 64  # o trecho começa e termina em múltiplos disto, na grade de colunas
MAX_COLUMNS = 4096
CHUNK_SECONDS = 20.0  # quanto áudio se lê de uma vez quando os quadros são muitos
# 2 milhões de amostras por lote de FFT (uns 16 MB por canal em 64 bits): o lote encolhe quando o quadro cresce
BATCH_SAMPLES = 1 << 21
# Quadros que ocupam menos que 1/4 do trecho lido ficam mais baratos lidos um a um (num WAV a leitura por posição é barata)
SPARSE_FRACTION = 4


@dataclass(frozen=True)
class SpectrogramRequest:
    """O pedido: o trecho de tempo e as colunas desejadas, mais os parâmetros da imagem."""

    start: float
    end: float
    columns: int
    params: SpectrogramParams


@dataclass(frozen=True)
class SpectrogramImage:
    """A imagem pronta e o que a tela precisa para pô-la no eixo: o trecho que ela cobre de verdade (encaixado na grade),
    o tamanho e a faixa de frequência."""

    png: bytes
    start: float
    end: float
    columns: int
    rows: int
    min_hz: float
    max_hz: float
    cached: bool


def snap_grid(start: float, end: float, columns: int, duration: float) -> tuple[float, int, int]:
    """A grade que cobre `[start, end)` com cerca de `columns` colunas: (segundos por coluna, primeira coluna, quantas).
    O tempo por coluna é arredondado para um quarto de oitava e o começo e o fim para múltiplos de `GRID_COLUMNS`, de modo
    que pedidos vizinhos caiam na mesma imagem. O fim nunca passa do áudio."""
    columns = max(1, min(columns, MAX_COLUMNS))
    seconds = max((end - start) / columns, 1e-6)
    step = 2.0 ** (round(math.log2(seconds) * 4.0) / 4.0)
    first = math.floor(start / step / GRID_COLUMNS) * GRID_COLUMNS
    last = math.ceil(end / step / GRID_COLUMNS) * GRID_COLUMNS
    last = max(min(last, math.ceil(duration / step)), first + 1)
    return step, int(first), int(last - first)


class ReaderFrameSource:
    """Os quadros de FFT lidos de um `SampleReader`, sem trazer o áudio todo: em pedaços de `CHUNK_SECONDS` quando os
    quadros são muitos, e um a um quando são raros e o leitor acessa por posição (um WAV)."""

    def __init__(self, reader: SampleReader, gain: float = 1.0) -> None:
        self.reader = reader
        self.rate = reader.rate
        self.gain = np.float32(gain)
        self.random_access = random_access(reader)

    def _read(self, start: int, count: int) -> np.ndarray:
        """`count` amostras a partir de `start`, com silêncio onde passam das pontas do áudio."""
        lead = max(-start, 0)
        data = self.reader.read(max(start, 0) / self.rate, max(count - lead, 0) / self.rate)
        data = data[: max(count - lead, 0)]
        if data.shape[0] < count - lead:
            data = np.concatenate([data, np.zeros((count - lead - data.shape[0], data.shape[1]), np.float32)])
        if lead:
            data = np.concatenate([np.zeros((lead, data.shape[1]), np.float32), data])
        return data * self.gain if self.gain != 1.0 else data

    def batches(self, starts: np.ndarray, size: int) -> Iterator[tuple[int, np.ndarray]]:
        chunk = max(int(CHUNK_SECONDS * self.rate), 2 * size)
        per_batch = max(1, BATCH_SAMPLES // size)
        index = np.arange(size)
        at = 0
        while at < len(starts):
            first = int(starts[at])
            stop = max(int(np.searchsorted(starts, first + chunk - size, side="right")), at + 1)
            group = starts[at:stop]
            span = int(group[-1]) + size - first
            sparse = self.random_access and len(group) * size * SPARSE_FRACTION < span
            block = None if sparse else self._read(first, span)
            for piece in range(0, len(group), per_batch):
                part = group[piece : piece + per_batch]
                if block is None and hasattr(self.reader, "frames"):
                    frames = self.reader.frames(part, size)
                    if self.gain != 1.0:
                        frames = frames * self.gain
                elif block is None:
                    frames = np.stack([self._read(int(s), size) for s in part])
                else:
                    frames = block[(part - first)[:, None] + index[None, :]]
                yield at + piece, frames
            at = stop


def cache_path(
    plan: HeardPlan, gain: float, params: SpectrogramParams, step: float, first: int, count: int
) -> Path:
    """Onde a imagem fica: a chave dela é a do som que se ouve mais tudo que muda a imagem."""
    raw = repr(
        (SPECTROGRAM_VERSION, plan.key, round(gain, 6), sorted(asdict(params).items()), step, first, count)
    )
    return config.SPECTROGRAM_DIR / f"{hashlib.sha1(raw.encode('utf-8')).hexdigest()}.png"


def encode_png(gray: np.ndarray) -> bytes:
    """O PNG em tons de cinza; compressão leve, porque a imagem é pequena e o cache é local."""
    buffer = io.BytesIO()
    Image.fromarray(gray, mode="L").save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


def render_spectrogram(
    plan: HeardPlan, reader: SampleReader, request: SpectrogramRequest
) -> SpectrogramImage:
    """A imagem do pedido: do cache, se esse trecho da grade já foi calculado, senão calculada e guardada."""
    rate = reader.rate
    params = request.params.checked(rate)
    if request.end <= request.start or request.start >= plan.duration:
        raise ValueError(
            f"o trecho de {request.start:g} a {request.end:g} s não cabe no áudio (que dura {plan.duration:g} s)"
        )
    step, first, count = snap_grid(request.start, request.end, request.columns, plan.duration)
    path = cache_path(plan, plan.item.gain, params, step, first, count)
    meta = {
        "start": first * step,
        "end": (first + count) * step,
        "columns": count,
        "rows": params.rows,
        "min_hz": params.min_hz,
        "max_hz": params.max_hz,
    }
    if path.exists():
        return SpectrogramImage(path.read_bytes(), cached=True, **meta)
    source = ReaderFrameSource(reader, plan.item.gain)
    gray = spectrogram_gray(source, rate, first * step * rate, step * rate, count, params)
    png = encode_png(gray)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(png)
    temporary.replace(path)  # nunca deixa uma imagem pela metade no cache
    return SpectrogramImage(png, cached=False, **meta)
