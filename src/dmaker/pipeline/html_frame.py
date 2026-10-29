"""Conferir uma composição em HTML antes do render: um quadro dela em PNG, e inserir a composição no projeto.

É o serviço por trás de `dmaker html frame` e das ferramentas MCP `render_html_frame` e `add_html_overlay`: quem
escreve a composição vê o quadro do instante que quiser (inclusive o do meio, sem renderizar os de antes) e só
então manda renderizar o vídeo."""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.brand import load_theme, normalize_hex
from ..domain.edits import add_overlay
from ..domain.spec import Project
from ..media.html_render import HtmlComposition, HtmlRenderer, PlaywrightHtmlRenderer
from ..media.html_site import entry_file
from .html_layer import brand_page_fields

DEFAULT_SIZE = (1080, 1920)
SIZE_RE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")


@dataclass
class HtmlFrame:
    """O quadro gravado e o que a página tentou e foi negado ou deu erro."""

    path: Path
    size: tuple[int, int]
    warnings: list[str] = field(default_factory=list)


def parse_size(text: str) -> tuple[int, int]:
    """`1080x1920` -> (1080, 1920). Levanta ValueError com a mensagem de uso."""
    match = SIZE_RE.match(text)
    if not match:
        raise ValueError(f"tamanho inválido: {text!r} (use LARGURAxALTURA, como 1080x1920)")
    width, height = int(match.group(1)), int(match.group(2))
    if not (16 <= width <= 8192 and 16 <= height <= 8192):
        raise ValueError(f"tamanho fora do limite: {width}x{height} (de 16 a 8192 px por lado)")
    return width, height


def _over_background(png: bytes, color: str) -> bytes:
    """O quadro transparente sobre uma cor lisa, para quem o olha (um visualizador de imagem mostra o transparente
    como preto ou branco e esconde o texto da cor oposta)."""
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        frame = image.convert("RGBA")
    base = Image.new("RGBA", frame.size, normalize_hex(color))
    base.alpha_composite(frame)
    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def render_html_frame(
    source: Path,
    out: Path,
    *,
    at: float = 0.0,
    size: tuple[int, int] = DEFAULT_SIZE,
    duration: float = 5.0,
    fps: float = 30.0,
    scale: float = 1.0,
    data: dict[str, Any] | None = None,
    brand: str | None = None,
    background: str | None = None,
    renderer: HtmlRenderer | None = None,
    files: Mapping[str, Path] | None = None,
) -> HtmlFrame:
    """Renderiza o quadro de `source` no instante `at` e o grava em `out` (PNG, com alfa; com `background`, sobre
    essa cor). A página é desenhada com `size` px (base 1080) e `scale` pixels de saída por px; a marca (`brand`)
    chega a ela por variáveis CSS, como no render do vídeo; `files` são os arquivos de fora da pasta que a página lê
    (ver `HtmlOverlay.files`)."""
    if at < 0 or duration <= 0 or fps <= 0 or scale <= 0:
        raise ValueError(
            "o instante, a duração, o fps e a escala precisam ser positivos (o instante pode ser 0)"
        )
    entry_file(source)
    theme = load_theme(brand)
    composition = HtmlComposition(
        source=source,
        size=size,
        scale=scale,
        fps=fps,
        duration=duration,
        data=data or {},
        files=files or {},
        **brand_page_fields(theme),
    )
    warnings: list[str] = []
    png = (renderer or PlaywrightHtmlRenderer()).still(composition, at, warnings.append)
    if background:
        png = _over_background(png, background)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    return HtmlFrame(out, composition.output_size, warnings)


def default_frame_path(output_dir: Path, source: Path, at: float) -> Path:
    """Onde o quadro cai quando ninguém escolhe: `output/html/<nome>_<instante>s.png`."""
    name = (source.stem if source.is_file() else source.name) or "composicao"
    return output_dir / "html" / f"{name}_{at:06.2f}s.png"


def insert_html_overlay(project: Project, overlay: dict[str, Any]) -> Project:
    """O projeto com a composição acrescentada às sobreposições (validada pela spec: região que não existe,
    `x` sem `y` e `end` antes de `start` falham aqui, com a mensagem do campo)."""
    return add_overlay(project, {"type": "html", **overlay})
