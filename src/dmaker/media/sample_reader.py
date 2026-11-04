"""Ler um trecho de um áudio como amostras, sem carregar o arquivo inteiro: o que a onda do editor precisa para as
janelas que desenha, toca e processa.

Há duas formas, escolhidas por `open_reader`: o WAV PCM é lido direto do disco por posição (sem ffmpeg, é o caso do
arquivo já processado pelos efeitos e dos WAV de gravação), e qualquer outro formato passa pelo `FFmpegRunner` injetado,
que decodifica só a janela pedida para um WAV temporário. Quem lê não sabe qual das duas está por trás.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from .decode import decode_to_wav
from .ffmpeg import FFmpegRunner
from .probe import MediaInfo
from .wavio import _decode_pcm, _wav_layout, read_wav_float

# A onda mostra no máximo dois canais, um em cima do outro, como o Audacity. Um arquivo com mais canais mostra os dois primeiros.
MAX_CHANNELS = 2
# Quanto a decodificação pode vir mais curta que o pedido sem desconfiarmos da busca (o fim de um MP3 acaba no meio de
# um quadro de 1152 amostras) e quanto se volta no arquivo quando desconfiamos.
SHORT_READ_FRAMES = 2304
SEEK_BACKOFF_SECONDS = 2.0


class SampleReader(Protocol):
    """Um áudio do qual se lê qualquer janela. `read` devolve exatamente `round(duration * rate)` quadros (o que passa do
    fim do áudio completa com zeros), para as janelas lidas em sequência nunca perderem nem ganharem uma amostra."""

    rate: int
    channels: int

    def read(self, start: float, duration: float) -> np.ndarray: ...


def _exact(samples: np.ndarray, frames: int, channels: int) -> np.ndarray:
    """As amostras com `frames` quadros e `channels` canais: corta o excesso e completa com silêncio o que falta."""
    samples = samples[:, :channels]
    if samples.shape[0] >= frames:
        return samples[:frames]
    padded = np.zeros((frames, channels), dtype=np.float32)
    padded[: samples.shape[0]] = samples
    return padded


def wav_format(path: Path) -> tuple[int, int] | None:
    """A taxa e os canais de um WAV que `read_wav_float` lê direto por posição (PCM ou ponto flutuante); None quando o
    arquivo é de outro formato."""
    try:
        with open(path, "rb") as handle:
            _, channels, rate, _, _, _ = _wav_layout(handle)
    except (OSError, ValueError):
        return None
    return rate, channels


@dataclass
class WavReader:
    """Lê a janela direto de um WAV, a partir de `base` segundos dentro do arquivo."""

    path: Path
    rate: int
    channels: int
    base: float = 0.0

    def read(self, start: float, duration: float) -> np.ndarray:
        frames = int(round(duration * self.rate))
        if frames <= 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        samples, _ = read_wav_float(self.path, max(self.base + start, 0.0), duration)
        return _exact(samples, frames, self.channels)

    def frames(self, starts: np.ndarray, size: int) -> np.ndarray:
        """Os quadros de `size` amostras que começam em cada `starts` (amostras do áudio, a partir de `base`), com o arquivo
        aberto uma vez só: milhares de quadros espalhados (o espectrograma de uma hora) gastam o tempo em abrir e
        reinterpretar o cabeçalho, e não em ler. O que passa das pontas do arquivo completa com silêncio."""
        result = np.zeros((len(starts), size, self.channels), dtype=np.float32)
        with open(self.path, "rb") as handle:
            tag, channels, rate, bits, position, byte_size = _wav_layout(handle)
            block = channels * (bits // 8)
            total = byte_size // block
            shift = int(round(self.base * rate))
            for index, start in enumerate(starts):
                first = int(start) + shift
                low, high = max(first, 0), min(first + size, total)
                if high <= low:
                    continue
                handle.seek(position + low * block)
                data = _decode_pcm(handle.read((high - low) * block), tag, bits, self.path).reshape(
                    -1, channels
                )
                result[index, low - first : low - first + len(data)] = data[:, : self.channels]
        return result


@dataclass
class DecodingReader:
    """Decodifica só a janela pedida com o ffmpeg (formato comprimido, vídeo, faixa de áudio que não é a primeira)."""

    runner: FFmpegRunner
    path: Path
    rate: int
    channels: int
    stream: int = 0
    base: float = 0.0

    def _decode(self, start: float, duration: float) -> np.ndarray:
        """O trecho decodificado pelo ffmpeg, com a taxa do leitor e os canais do arquivo (o corte em dois é de quem lê)."""
        with tempfile.TemporaryDirectory(prefix="dmaker-onda-") as folder:
            wav = decode_to_wav(
                self.runner,
                self.path,
                Path(folder) / "janela.wav",
                start=start,
                duration=duration,
                stream=self.stream,
                sample_rate=self.rate,
                channels=self.channels if self.channels < 2 else None,
            )
            decoded, _ = read_wav_float(wav)
        return decoded

    def read(self, start: float, duration: float) -> np.ndarray:
        frames = int(round(duration * self.rate))
        if frames <= 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        # `-ss` negativo não existe: antes do começo do arquivo o que falta é silêncio
        first = self.base + start
        lead = int(round(max(-first, 0.0) * self.rate))
        window_start = max(first, 0.0)
        wanted = max(duration - lead / self.rate, 0.0)
        if wanted <= 0:
            return np.zeros((frames, self.channels), dtype=np.float32)
        decoded = self._decode(window_start, wanted)
        if decoded.shape[0] < int(round(wanted * self.rate)) - SHORT_READ_FRAMES and window_start > 0:
            # alguns formatos (FLAC sem tabela de busca) devolvem pouco ou nada ao buscar perto do fim; decodificar
            # de um pouco antes dá o mesmo trecho. No fim de verdade o resultado continua curto e completa com silêncio.
            run_in = min(window_start, SEEK_BACKOFF_SECONDS)
            earlier = self._decode(window_start - run_in, wanted + run_in)
            decoded = earlier[int(round(run_in * self.rate)) :]
        decoded = _exact(decoded, frames - lead, self.channels)
        if lead:
            decoded = np.concatenate([np.zeros((lead, self.channels), dtype=np.float32), decoded])
        return decoded


# O ffmpeg leva um som mono para estéreo (`aformat=channel_layouts=stereo`, o que a cadeia de efeitos e a mixagem fazem)
# copiando-o nos dois canais com ganho de raiz de 1/2, os 3 dB que mantêm a potência. Há teste que mede isso no ffmpeg.
MONO_TO_STEREO_GAIN = 0.7071067811865476


@dataclass
class StereoReader:
    """Mostra um áudio mono nos dois canais como a mixagem o faz: assim o som sem efeito e o já processado (que a cadeia
    sempre deixa em estéreo) têm o mesmo nível e a mesma forma, e o antes e o depois de um efeito se comparam de verdade."""

    inner: SampleReader
    channels: int = 2

    @property
    def rate(self) -> int:
        return self.inner.rate

    def read(self, start: float, duration: float) -> np.ndarray:
        mono = self.inner.read(start, duration)
        return np.repeat(mono[:, :1], 2, axis=1) * np.float32(MONO_TO_STEREO_GAIN)

    def frames(self, starts: np.ndarray, size: int) -> np.ndarray:
        """Como `WavReader.frames`, com o mono nos dois canais a -3 dB."""
        mono = self.inner.frames(starts, size)  # type: ignore[attr-defined]
        return np.repeat(mono[:, :, :1], 2, axis=2) * np.float32(MONO_TO_STEREO_GAIN)


def open_reader(
    runner: FFmpegRunner,
    path: Path,
    *,
    prober: Callable[[Path], MediaInfo],
    stream: int = 0,
    base: float = 0.0,
) -> SampleReader:
    """O leitor do arquivo: direto quando é um WAV na primeira faixa (a taxa e os canais saem do cabeçalho, sem
    consultar o ffprobe), e pelo ffmpeg nos outros casos."""
    layout = wav_format(path) if stream == 0 else None
    if layout is not None:
        rate, channels = layout
        reader: SampleReader = WavReader(path, rate, max(1, min(channels, MAX_CHANNELS)), base)
    else:
        info = prober(path)
        rate, channels = info.sample_rate or 48000, info.channels or 2
        reader = DecodingReader(runner, path, rate, max(1, min(channels, MAX_CHANNELS)), stream, base)
    return StereoReader(reader) if reader.channels == 1 else reader


def random_access(reader: SampleReader) -> bool:
    """Se ler uma janela pequena é barato (um WAV lido por posição). Um arquivo comprimido sobe um ffmpeg a cada leitura, e
    aí vale ler pedaços grandes de uma vez."""
    if isinstance(reader, StereoReader):
        return random_access(reader.inner)
    return isinstance(reader, WavReader)
