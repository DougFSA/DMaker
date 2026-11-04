"""Leitura de amostras de um arquivo de áudio para quem faz conta em numpy (perfil de ruído, Truncar Silêncio).

A decodificação é do ffmpeg, pelo `FFmpegRunner` injetado: o arquivo vira PCM de ponto flutuante cru numa pasta
temporária e o numpy o lê de lá. Um protocolo pequeno (`SampleReader`) deixa os testes trocarem o ffmpeg por amostras
sintéticas, e a simulação do render (o `RecordingRunner` não grava nada) devolve um sinal vazio em vez de falhar.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..media.ffmpeg import FFmpegCommand, FFmpegRunner

PCM_FORMAT = ["-f", "f32le"]  # ponto flutuante de 32 bits, sem cabeçalho: o numpy lê direto, sem perda


@dataclass(frozen=True)
class AudioSlice:
    """Um trecho de um arquivo: `duration` segundos a partir de `start`, na faixa de áudio `stream`."""

    path: Path
    start: float
    duration: float
    stream: int = 0


class SampleReader(Protocol):
    def read(self, audio: AudioSlice, *, rate: int, channels: int) -> np.ndarray:
        """O trecho como amostras `(n, canais)` em ponto flutuante, reamostrado para `rate` e com `channels` canais."""


class FFmpegSampleReader:
    """Lê o trecho decodificando com o ffmpeg do runner injetado."""

    def __init__(self, runner: FFmpegRunner) -> None:
        self.runner = runner

    def read(self, audio: AudioSlice, *, rate: int, channels: int) -> np.ndarray:
        scratch = Path(tempfile.mkdtemp(prefix="dmaker-pcm-"))
        try:
            raw = scratch / "trecho.f32"
            self.runner.run(
                FFmpegCommand(
                    [
                        *["-ss", f"{max(audio.start, 0.0):.6f}", "-t", f"{audio.duration:.6f}"],
                        *["-i", str(audio.path), "-map", f"0:a:{audio.stream}", "-vn"],
                        *["-ac", str(channels), "-ar", str(rate), *PCM_FORMAT, str(raw)],
                    ],
                    label="ler o áudio",
                    total=audio.duration,
                )
            )
            if not raw.exists():  # na simulação (RecordingRunner) nada é gravado
                return np.zeros((0, channels), dtype=np.float32)
            return np.fromfile(raw, dtype="<f4").reshape(-1, channels)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
