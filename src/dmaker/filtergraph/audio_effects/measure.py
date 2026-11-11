"""Medida de um sinal para os efeitos que dependem dele (Normalizar, Amplificar sem clipar): o grafo da passada
de análise e a leitura do que o `astats` do ffmpeg imprime. Tudo puro; quem executa é o `FFmpegRunner`."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ...media.spectral import NoiseSpectrum

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
    """A medida de um sinal estéreo (ou mono): um `ChannelLevels` por canal e, para quem pede um perfil de ruído, o
    espectro dele (`noise`, que a passada de medida do processador preenche e a spec nunca guarda). Os efeitos de
    loudness leem `loudness` (LUFS integrado) ou `rms_db` (RMS da mistura dos canais), e só esses: a medida de pico dos
    outros efeitos continua a mesma linha de sempre. `mono_source` diz que o arquivo do item é mono (a mistura o leva
    para os dois lados, e a Normalização de loudness o trata como dual-mono)."""

    channels: tuple[ChannelLevels, ...] = ()
    noise: NoiseSpectrum | None = None
    loudness: float | None = None
    rms_db: float | None = None
    mono_source: bool = False

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


# ---------- loudness e RMS: só para os efeitos que pedem (`EffectBase.measure_kind`) ----------

_INTEGRATED = re.compile(r"^I:\s*(-?inf|-?[0-9.]+)\s*LUFS\s*$", re.IGNORECASE)
_RMS_LEVEL = re.compile(r"^RMS level dB:\s*(-?inf|-?[0-9.]+(?:e[-+]?\d+)?)\s*$", re.IGNORECASE)
_AUDIO_STREAM_LINE = re.compile(r"Stream #\d+:\d+[^:]*: Audio: [^\n]*?,\s*\d+ Hz,\s*([A-Za-z0-9. ()]+?),")


def level_measure_lines(
    kind: str, source: str, out: str, span_samples: tuple[int, int] | None = None
) -> list[str]:
    """A linha que mede `source` conforme o `kind` do efeito: `peak` é o `astats` de sempre (`measure_lines`); `lufs` é o
    `ebur128`, que imprime o resumo integrado no fim; `rms` é o `astats` lido no bloco Overall."""
    if kind == "peak":
        return measure_lines(source, out, span_samples)
    trim = (
        "" if span_samples is None else f"atrim=start_sample={span_samples[0]}:end_sample={span_samples[1]},"
    )
    if kind == "lufs":
        # `framelog=quiet`: só o resumo, sem uma linha de log a cada 100 ms
        return [f"{source}{trim}ebur128=framelog=quiet{out}"]
    if kind == "rms":
        return [f"{source}{trim}astats=metadata=0:reset=0{out}"]
    raise ValueError(f"tipo de medida desconhecido: {kind!r}")


def parse_level_measure(kind: str, stderr: str, stream: int = 0) -> Measure | None:
    """Lê o que `level_measure_lines` mandou o ffmpeg imprimir; `stream` é a faixa de áudio do arquivo que o item usa (a
    que diz se ele é mono). None quando o texto não traz a medida (simulação, ou um sinal sem som para o LUFS: o
    `ebur128` imprime `-inf` e o efeito não tem o que corrigir)."""
    if kind == "peak":
        return parse_astats(stderr)
    mono = _is_mono_source(stderr, stream)
    if kind == "lufs":
        for raw in stderr.splitlines():
            found = _INTEGRATED.match(_LINE_PREFIX.sub("", raw.strip()))
            if found:
                value = float(found.group(1))
                return Measure(loudness=value if math.isfinite(value) else None, mono_source=mono)
        return None
    if kind == "rms":
        rms = _overall_rms(stderr)
        return None if rms is None else Measure(rms_db=rms, mono_source=mono)
    raise ValueError(f"tipo de medida desconhecido: {kind!r}")


def _overall_rms(stderr: str) -> float | None:
    """O `RMS level dB` do bloco `Overall` do `astats` (a mistura de todos os canais)."""
    inside = False
    for raw in stderr.splitlines():
        line = _LINE_PREFIX.sub("", raw.strip())
        if line == "Overall":
            inside = True
        elif inside and (found := _RMS_LEVEL.match(line)):
            value = float(found.group(1))
            return value if math.isfinite(value) else None
    return None


def _is_mono_source(stderr: str, stream: int = 0) -> bool:
    """Se a faixa de áudio `stream` da primeira entrada do ffmpeg tem um canal só (`Stream #0:0: Audio: ..., 48000 Hz,
    mono, ...`). A listagem das entradas vem antes do `Stream mapping`, e só ela conta."""
    listing = stderr.split("Stream mapping:", 1)[0]
    found = list(_AUDIO_STREAM_LINE.finditer(listing))
    return 0 <= stream < len(found) and found[stream].group(1).strip().lower() == "mono"
