"""Folha de contato dos looks: a mesma cena sintética sem acabamento e com cada look, lado a lado, num JPEG em cache.

Serve ao guia, à CLI (`dmaker looks sheet`) e à galeria da interface: quem escolhe um look vê o que ele faz sem
montar um projeto. O acabamento é o do render de verdade (`filtergraph.finish.post_video_lines`), aplicado a uma cena
de teste que traz o que cada efeito precisa para aparecer: tons de pele, cores primárias, uma rampa de cinzas, uma
luz forte (brilho) e linhas finas sobre faixa clara (aberração). O ffmpeg entra por `FFmpegRunner`; o grafo é puro.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config
from ..domain.looks import Look, available_looks, resolve_look
from ..domain.spec import ColorAdjust
from ..filtergraph.common import ffq
from ..filtergraph.finish import post_video_lines
from ..media import fonts
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner

# O acabamento é calculado em meia resolução do Full HD: o grão e a aberração acompanham a largura do quadro, então
# a prévia mostra a mesma proporção do render, e o custo fica em uma fração de segundo por look.
SCENE_SIZE = (540, 960)
SCENE_FPS = 15.0
SCENE_SECONDS = 2.0  # uma passagem inteira do vazamento de luz
SHEET_FRAME = 15  # o meio da passagem, onde o vazamento está mais forte
TILE_WIDTH = 300
LABEL_HEIGHT = 30
# Mude quando a receita da folha (cena, quadro escolhido, escala, rótulo) mudar: entra na chave do cache. A receita
# do próprio acabamento já entra pelo texto do grafo, então ajustar um look invalida a folha dele.
SHEET_VERSION = 1


@dataclass(frozen=True)
class SheetGraph:
    source: str  # fonte lavfi da cena
    lines: list[str]  # grafo completo, até o rótulo `out`
    out: str


def scene_source(size: tuple[int, int] = SCENE_SIZE) -> str:
    """Cena de teste: céu em degradê, retratos de cor e uma rampa de cinzas."""
    width, height = size

    def box(x: float, y: float, box_width: float, box_height: float, color: str) -> str:
        """Retângulo cheio; posição e tamanho em fração do quadro, para a cena valer em qualquer resolução."""
        return f"drawbox=x=iw*{x}:y=ih*{y}:w=iw*{box_width}:h=ih*{box_height}:color={color}:t=fill"

    def line(x: float, thin: int) -> str:
        return f"drawbox=x=iw*{x}:y=ih*0.69:w={thin}:h=ih*0.05:color=black:t=fill"

    boxes = [
        box(0.10, 0.28, 0.36, 0.24, "0xd8a07c"),  # pele clara
        box(0.54, 0.28, 0.36, 0.24, "0x8d5a3b"),  # pele escura
        box(0.10, 0.56, 0.18, 0.09, "0xc0392b"),  # vermelho
        box(0.32, 0.56, 0.18, 0.09, "0x2e9e5a"),  # verde
        box(0.54, 0.56, 0.18, 0.09, "0x2d6cdf"),  # azul
        box(0.76, 0.56, 0.14, 0.09, "0xf1c40f"),  # amarelo
        box(0.10, 0.69, 0.80, 0.05, "0xffffff"),  # faixa clara com linhas finas (aberração)
        line(0.14, 2),
        line(0.50, 3),
        line(0.84, 2),
        box(0.74, 0.08, 0.10, 0.05, "0xffffff"),  # luz forte (brilho)
    ]
    grays = ("0x0a0a0a", "0x404040", "0x808080", "0xbfbfbf", "0xf5f5f5")
    ramp = [box(round(0.10 + 0.16 * i, 2), 0.80, 0.16, 0.12, color) for i, color in enumerate(grays)]
    sky = (
        f"gradients=size={width}x{height}:rate={SCENE_FPS:g}:duration={SCENE_SECONDS:g}:nb_colors=4"
        f":c0=0x4f86d6:c1=0xf0c27b:c2=0xc9794b:c3=0x2e3a55:x0=0:y0=0:x1=0:y1={height}:speed=0.0001:seed=5"
    )
    return ",".join([sky, *boxes, *ramp, "format=yuv420p"])


def _label(text: str, font: Path | None) -> str:
    """Rótulo do quadro: o nome embaixo, sobre uma tarja escura, quando há fonte para desenhá-lo."""
    bar = f"drawbox=x=0:y=ih-{LABEL_HEIGHT}:w=iw:h={LABEL_HEIGHT}:color=black@0.6:t=fill"
    if font is None:
        return bar
    return (
        f"{bar},drawtext=fontfile={ffq(font)}:text={ffq(text)}:fontsize=18:fontcolor=white"
        f":x=(w-text_w)/2:y=h-{LABEL_HEIGHT}+(({LABEL_HEIGHT}-text_h)/2)"
    )


def sheet_graph(looks: Sequence[Look], font: Path | None = None) -> SheetGraph:
    """Grafo da folha: a cena sem acabamento e uma cópia com cada look, em fila."""
    if not looks:
        raise ValueError("a folha precisa de ao menos um look")
    count = len(looks) + 1
    lines = [f"[0:v]split={count}" + "".join(f"[s{i}]" for i in range(count))]
    tiles = [f"[s0]select='eq(n,{SHEET_FRAME})',scale={TILE_WIDTH}:-2,{_label('original', font)}[t0]"]
    for index, look in enumerate(looks, start=1):
        lines += post_video_lines(
            f"[s{index}]",
            f"[g{index}]",
            ColorAdjust(),
            look.color,
            0.0,
            0.0,
            SCENE_SECONDS,
            SCENE_SIZE,
            SCENE_FPS,
            tag=f"lk{index}",
        )
        tiles.append(
            f"[g{index}]select='eq(n,{SHEET_FRAME})',scale={TILE_WIDTH}:-2,{_label(look.name, font)}[t{index}]"
        )
    lines += tiles
    lines.append("".join(f"[t{i}]" for i in range(count)) + f"hstack=inputs={count}[sheet]")
    return SheetGraph(scene_source(), lines, "[sheet]")


def sheet_command(graph: SheetGraph, out: Path) -> FFmpegCommand:
    args = ["-f", "lavfi", "-i", graph.source, "-filter_complex", ";".join(graph.lines)]
    args += ["-map", graph.out, "-frames:v", "1", "-q:v", "3", str(out)]
    return FFmpegCommand(args, label="prévia dos looks")


def sheet_key(graph: SheetGraph) -> str:
    """Identidade da folha: muda quando muda o grafo, a cena ou a receita da folha."""
    text = "\n".join([str(SHEET_VERSION), graph.source, *graph.lines])
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


class LookPreview:
    """Gera (uma vez) e guarda em cache a folha de cada look e a de todos lado a lado."""

    def __init__(self, runner: FFmpegRunner, cache_dir: Path | None = None, font: Path | None = None) -> None:
        self.runner = runner
        self._cache_dir = cache_dir
        self._font = font

    @property
    def cache_dir(self) -> Path:
        # lido na hora do uso: os testes (e quem trocar DMAKER_DATA_DIR) redirecionam config.CACHE_DIR
        return self._cache_dir or config.CACHE_DIR / "looks"

    def _font_file(self) -> Path | None:
        if self._font is not None:
            return self._font
        candidate = fonts.fontsdir() / "Poppins-SemiBold.ttf"
        return candidate if candidate.exists() else None

    def _render(self, name: str, looks: Sequence[Look]) -> Path:
        graph = sheet_graph(looks, self._font_file())
        out = self.cache_dir / f"{name}-{sheet_key(graph)}.jpg"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            self.runner.run(sheet_command(graph, out))
        return out

    def sheet(self, name: str, brand_looks: Mapping[str, Mapping[str, Any]] | None = None) -> Path:
        """Folha de um look: a cena original e a cena com ele."""
        look = resolve_look(name, brand_looks)
        return self._render(look.name, [look])

    def overview(self, brand_looks: Mapping[str, Mapping[str, Any]] | None = None) -> Path:
        """Folha com a cena original e todos os looks (os padrões e os da marca) lado a lado."""
        return self._render("todos", list(available_looks(brand_looks).values()))
