"""Blocos básicos de filtros do FFmpeg compartilhados pelos grafos."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.spec import ColorAdjust

AUDIO_FMT_MEZZ = "aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo"
AUDIO_FMT_MIX = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def ffq(path: str | Path) -> str:
    """Caminho como valor de opção de filtro: barras normais, dois-pontos escapado, entre aspas simples."""
    s = str(path).replace("\\", "/").replace("'", r"\'").replace(":", r"\:")
    return f"'{s}'"


def even(v: float) -> int:
    return max(2, int(v) // 2 * 2)


def atempo_chain(speed: float) -> str:
    """atempo aceita 0.5..2 por estágio; velocidades fora disso viram uma cadeia."""
    factors: list[float] = []
    s = speed
    while s > 2.0:
        factors.append(2.0)
        s /= 2.0
    while s < 0.5:
        factors.append(0.5)
        s /= 0.5
    factors.append(s)
    return ",".join(f"atempo={f:.5g}" for f in factors)


def color_chain(color: ColorAdjust) -> list[str]:
    steps: list[str] = []
    if color.brightness != 0 or color.contrast != 1 or color.saturation != 1 or color.gamma != 1:
        steps.append(
            f"eq=brightness={color.brightness:.3f}:contrast={color.contrast:.3f}"
            f":saturation={color.saturation:.3f}:gamma={color.gamma:.3f}"
        )
    if color.denoise:
        steps.append("hqdn3d=3:2:4:3")
    if color.sharpen:
        steps.append(f"unsharp=5:5:{color.sharpen:.2f}:5:5:0")
    if color.vignette:
        steps.append("vignette=angle=PI/5")
    if color.lut:
        steps.append(f"lut3d=file={ffq(color.lut)}")
    if color.extra:
        steps.append(color.extra)
    return steps


def fade_chains(fade_in: float, fade_out: float, duration: float) -> tuple[list[str], list[str]]:
    """(filtros de vídeo, filtros de áudio) para fade de entrada e saída."""
    video: list[str] = []
    audio: list[str] = []
    if fade_in:
        video.append(f"fade=t=in:st=0:d={fade_in:.3f}")
        audio.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out:
        st = max(duration - fade_out, 0)
        video.append(f"fade=t=out:st={st:.3f}:d={fade_out:.3f}")
        audio.append(f"afade=t=out:st={st:.3f}:d={fade_out:.3f}")
    return video, audio


@dataclass
class Inputs:
    """Lista de entradas `-i` com os índices que os rótulos do grafo usam."""

    args: list[str] = field(default_factory=list)
    count: int = 0

    def add(self, path: str | Path, *pre: str) -> int:
        idx = self.count
        self.args += [*pre, "-i", str(path)]
        self.count += 1
        return idx

    def add_silence(self, duration: float) -> int:
        return self.add("anullsrc=r=48000:cl=stereo", "-f", "lavfi", "-t", f"{duration:.3f}")

    def add_looped_image(self, path: Path, fps: float, duration: float) -> int:
        return self.add(path, "-loop", "1", "-framerate", f"{fps:g}", "-t", f"{duration:.3f}")
