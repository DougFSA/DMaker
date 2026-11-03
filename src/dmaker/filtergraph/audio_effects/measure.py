"""Medida de um sinal para os efeitos que dependem dele (Normalizar, Amplificar sem clipar): o grafo da passada
de análise e a leitura do que o `astats` do ffmpeg imprime. Tudo puro; quem executa é o `FFmpegRunner`."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_LINE_PREFIX = re.compile(r"^\[[^\]]*\]\s*")
_CHANNEL = re.compile(r"^Channel:\s*(\d+)\s*$")
_NUMBER = re.compile(r"^([A-Za-z][A-Za-z ]*?):\s*(-?inf|nan|-?[0-9.]+(?:e[-+]?\d+)?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ChannelLevels:
    """O que se mediu de um canal: menor e maior amostra (valores de -1 a 1), deslocamento DC (média) e pico."""

    minimum: float
    maximum: float
    dc_offset: float
    peak_db: float

    def peak_after_dc(self, remove_dc: bool) -> float:
        """Pico linear do canal, depois de tirar o DC quando `remove_dc` (a onda é recentrada antes de medir)."""
        shift = self.dc_offset if remove_dc else 0.0
        return max(abs(self.maximum - shift), abs(self.minimum - shift))


@dataclass(frozen=True)
class Measure:
    """A medida de um sinal estéreo (ou mono): um `ChannelLevels` por canal."""

    channels: tuple[ChannelLevels, ...]

    @property
    def peak_db(self) -> float:
        """Maior pico entre os canais, em dBFS (`-inf` num sinal mudo)."""
        return max((channel.peak_db for channel in self.channels), default=-math.inf)


def measure_lines(source: str, out: str, span_samples: tuple[int, int] | None = None) -> list[str]:
    """A linha que mede `source` com o `astats`, só dentro de `span_samples` quando o efeito tem intervalo. O
    `reset=0` faz o filtro imprimir uma vez só, no fim, o resumo do sinal todo."""
    trim = (
        "" if span_samples is None else f"atrim=start_sample={span_samples[0]}:end_sample={span_samples[1]},"
    )
    return [f"{source}{trim}astats=metadata=0:reset=0{out}"]


def parse_astats(stderr: str) -> Measure | None:
    """Lê o resumo por canal que o `astats` imprime no fim. None quando o texto não traz nenhum canal (por
    exemplo no dry-run, em que nada foi executado)."""
    channels: list[ChannelLevels] = []
    current: dict[str, float] | None = None

    def flush() -> None:
        if current and {"Min level", "Max level", "DC offset", "Peak level dB"} <= current.keys():
            channels.append(
                ChannelLevels(
                    current["Min level"], current["Max level"], current["DC offset"], current["Peak level dB"]
                )
            )

    for raw in stderr.splitlines():
        line = _LINE_PREFIX.sub("", raw.strip())
        if _CHANNEL.match(line):
            flush()
            current = {}
        elif line == "Overall":
            flush()
            current = None
            break
        elif current is not None and (found := _NUMBER.match(line)):
            current[found.group(1)] = float(found.group(2))
    else:
        flush()
    return Measure(tuple(channels)) if channels else None
