"""Camada de texto (ASS): títulos, CTA, barra de progresso, legendas e guias, com o tom do fundo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.brand import Theme
from ..domain.spec import ImageOverlay, ProgressBar, Project, TextOverlay
from ..domain.timeline import tone_for
from ..filtergraph.overlays import ResolvedImageOverlay
from ..text.ass import AssDoc
from ..text.captions import Cue
from ..text.overlays import Canvas, add_captions, add_guides, add_progress_bar, add_text_overlay
from .context import RenderContext


@dataclass
class TextLayer:
    doc: AssDoc
    image_overlays: list[ResolvedImageOverlay] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return bool(self.doc.events)


def resolve_overlay_image(project: Project, theme: Theme, src: str) -> Path:
    """`logo`, `logo:<tipo>` (do tema) ou caminho de imagem."""
    if src == "logo" or src.startswith("logo:"):
        kind = src.split(":", 1)[1] if ":" in src else "horizontal"
        path = theme.logo(kind)
        if not path:
            raise FileNotFoundError(
                f"O tema {theme.name!r} não tem logo {kind!r}. Use brand=medlycare ou informe um caminho de imagem."
            )
        return path
    path = project.resolve(src)
    if not path.exists():
        raise FileNotFoundError(f"Imagem de sobreposição não encontrada: {src}")
    return path


def build_text_layer(
    ctx: RenderContext,
    total: float,
    spans: list[tuple[float, float]],
    tones: list[str | None],
    cues: list[Cue] | None,
    guides: bool,
) -> TextLayer:
    project = ctx.project
    canvas = Canvas(ctx.width, ctx.height, ctx.preset.safe, ctx.theme, total)
    layer = TextLayer(AssDoc(ctx.width, ctx.height, project.name))
    text_index = 0
    for overlay in project.overlays:
        if isinstance(overlay, TextOverlay):
            end = min(overlay.end if overlay.end is not None else total, total)
            tone = tone_for(overlay.start, end, spans, tones)
            add_text_overlay(layer.doc, canvas, overlay, text_index, tone=tone)
            text_index += 1
        elif isinstance(overlay, ProgressBar):
            add_progress_bar(layer.doc, canvas, overlay)
        elif isinstance(overlay, ImageOverlay):
            path = resolve_overlay_image(project, ctx.theme, overlay.src)
            end = min(overlay.end if overlay.end is not None else total, total)
            if end > overlay.start:
                layer.image_overlays.append(ResolvedImageOverlay(overlay, path, overlay.start, end))
    if cues and project.captions:
        add_captions(
            layer.doc, canvas, cues, project.captions.style, tone_fn=lambda a, b: tone_for(a, b, spans, tones)
        )
    if guides:
        add_guides(layer.doc, canvas)
    return layer
