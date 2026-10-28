"""Folha de contato de uma transição: os quadros da troca entre dois clipes sintéticos, num PNG em cache.

Serve ao guia, à CLI (`dmaker transitions sheet`) e à galeria da interface: quem escolhe uma transição vê o
que ela faz sem montar um projeto. O ffmpeg entra por `FFmpegRunner`; o grafo é função pura.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..domain.curves import CURVES
from ..domain.spec import Transition
from ..domain.timeline import effective_transition
from ..domain.transitions import all_transition_names
from ..filtergraph.timeline import timeline_graph
from ..filtergraph.transitions.registry import first_frame_at, frame_count
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner

# Quadro pequeno em 9:16: a folha é para ver o movimento, não a resolução, e a prévia sai em um segundo.
PREVIEW_SIZE = (360, 640)
PREVIEW_FPS = 30.0
CLIP_SECONDS = 1.2
TRANSITION_SECONDS = 0.6  # cabe na metade de cada clipe: a duração efetiva da transição é esta mesma
SHEET_FRAMES = 8
THUMB_WIDTH = 150
# Mude quando a receita da folha (clipes, quadros escolhidos, escala) mudar: entra na chave do cache. A receita
# das próprias transições já entra pelo texto do grafo, então ajustar uma transição invalida a folha dela.
SHEET_VERSION = 1


@dataclass(frozen=True)
class SheetGraph:
    inputs: list[str]  # fontes lavfi (vídeo e áudio mudo) dos dois clipes
    lines: list[str]  # grafo completo, até o rótulo `out`
    out: str


def _clip_source(video: str) -> str:
    """Entrada lavfi com vídeo `out0` e áudio mudo `out1`: o grafo da linha do tempo sempre monta os dois."""
    return f"{video}[out0];anullsrc=r=48000:cl=stereo:d={CLIP_SECONDS:g}[out1]"


def preview_sources(size: tuple[int, int] = PREVIEW_SIZE) -> list[str]:
    """Dois clipes bem diferentes: um padrão de teste colorido (A) e um gradiente com formas (B), para o olho
    separar quem sai de quem entra e o movimento de cada um se ler."""
    width, height = size
    rate = f"{PREVIEW_FPS:g}"
    seconds = f"{CLIP_SECONDS:g}"
    clip_a = f"testsrc2=size={width}x{height}:rate={rate}:duration={seconds},format=yuv420p"
    clip_b = (
        f"gradients=size={width}x{height}:rate={rate}:duration={seconds}:nb_colors=4"
        ":c0=0xff5e3a:c1=0x2d6cdf:c2=0x16c79a:c3=0xffd23f:speed=0.02,"
        "drawbox=x=iw*0.13:y=ih*0.16:w=iw*0.28:h=iw*0.28:color=white:t=fill,"
        "drawbox=x=iw*0.55:y=ih*0.47:w=iw*0.3:h=iw*0.3:color=black:t=fill,"
        "drawbox=x=iw*0.18:y=ih*0.73:w=iw*0.64:h=iw*0.11:color=yellow:t=fill,format=yuv420p"
    )
    return [_clip_source(clip_a), _clip_source(clip_b)]


def sheet_indices(first_window_frame: int, window_frames: int, count: int = SHEET_FRAMES) -> list[int]:
    """Números dos quadros da folha: igualmente espaçados do quadro anterior à troca ao primeiro depois dela,
    para a folha mostrar de onde a imagem parte, o caminho e onde ela chega."""
    first, last = max(0, first_window_frame - 1), first_window_frame + window_frames
    step = (last - first) / (count - 1)
    return sorted({round(first + step * i) for i in range(count)})


def sheet_graph(name: str, curve: str = "linear", size: tuple[int, int] = PREVIEW_SIZE) -> SheetGraph:
    """Grafo da folha: dois clipes ligados pela transição, os quadros escolhidos e a grade."""
    if name not in all_transition_names():
        raise KeyError(f"Transição desconhecida: {name}")
    if curve not in CURVES:
        raise ValueError(f"Curva desconhecida: {curve!r}. Use {', '.join(CURVES)}.")
    transition = Transition(type=name, duration=TRANSITION_SECONDS, curve=curve)
    timeline = timeline_graph(
        2, [CLIP_SECONDS, CLIP_SECONDS], [None, transition], PREVIEW_FPS, want_video=True, size=size
    )
    duration = effective_transition(transition, CLIP_SECONDS, CLIP_SECONDS)
    first = first_frame_at(CLIP_SECONDS - duration, PREVIEW_FPS)
    frames = "+".join(f"eq(n,{n})" for n in sheet_indices(first, frame_count(duration, PREVIEW_FPS)))
    lines = list(timeline.lines)
    lines.append(f"{timeline.audio}anullsink")
    lines.append(
        f"{timeline.video}select='{frames}',scale={THUMB_WIDTH}:-2,"
        f"tile={SHEET_FRAMES}x1:padding=3:margin=3:color=0x202124[sheet]"
    )
    return SheetGraph(preview_sources(size), lines, "[sheet]")


def sheet_command(graph: SheetGraph, out: Path) -> FFmpegCommand:
    args: list[str] = []
    for source in graph.inputs:
        args += ["-f", "lavfi", "-i", source]
    args += ["-filter_complex", ";".join(graph.lines), "-map", graph.out, "-frames:v", "1", str(out)]
    return FFmpegCommand(args, label="prévia da transição")


def sheet_key(graph: SheetGraph) -> str:
    """Identidade da folha: muda quando muda o grafo, os clipes ou a receita da folha."""
    text = "\n".join([str(SHEET_VERSION), *graph.inputs, *graph.lines])
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


class TransitionPreview:
    """Gera (uma vez) e guarda em cache a folha de contato de cada transição e curva."""

    def __init__(self, runner: FFmpegRunner, cache_dir: Path | None = None) -> None:
        self.runner = runner
        self._cache_dir = cache_dir

    @property
    def cache_dir(self) -> Path:
        # lido na hora do uso: os testes (e quem trocar DMAKER_DATA_DIR) redirecionam config.CACHE_DIR
        return self._cache_dir or config.CACHE_DIR / "transitions"

    def sheet(self, name: str, curve: str = "linear") -> Path:
        graph = sheet_graph(name, curve)
        out = self.cache_dir / f"{name}-{curve}-{sheet_key(graph)}.png"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            self.runner.run(sheet_command(graph, out))
        return out
