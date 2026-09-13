"""Camada de texto (ASS): títulos, CTA, barra de progresso, legendas e guias, com o tom do fundo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.brand import Theme
from ..domain.spec import ImageOverlay, ProgressBar, Project, TextOverlay, VideoOverlay, parse_aspect
from ..domain.timeline import tone_for
from ..filtergraph.common import even
from ..filtergraph.overlays import ResolvedImageOverlay
from ..filtergraph.pip import ResolvedVideoOverlay
from ..text.ass import AssDoc
from ..text.captions import Cue
from ..text.overlays import Canvas, add_captions, add_guides, add_progress_bar, add_text_overlay
from ..visuals.pip import render_pip_assets
from .context import RenderContext


@dataclass
class TextLayer:
    doc: AssDoc
    image_overlays: list[ResolvedImageOverlay] = field(default_factory=list)
    video_overlays: list[ResolvedVideoOverlay] = field(default_factory=list)

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


def resolve_video_overlay(
    ctx: RenderContext, overlay: VideoOverlay, total: float, index: int
) -> ResolvedVideoOverlay | None:
    """Localiza o vídeo do PiP (arquivo ou fonte da sessão), calcula o tamanho no quadro e gera
    a máscara e a moldura no diretório do job."""
    if overlay.source:
        source = ctx.session[overlay.source]
        path, info = source.path, source.info
        in_point = source.in_point(overlay.offset)  # `offset` é tempo da sessão
        audio_stream = source.audio_stream
    else:
        path = ctx.project.resolve(overlay.src or "")
        if not path.exists():
            raise FileNotFoundError(f"vídeo do PiP não encontrado: {overlay.src}")
        info = ctx.prober(path)
        in_point, audio_stream = overlay.offset, 0
    assert path is not None and info is not None
    if not info.has_video:
        raise ValueError(f"o PiP {overlay.src or overlay.source!r} não tem vídeo")
    end = min(overlay.end if overlay.end is not None else total, total)
    if end <= overlay.start:
        return None

    width = even(ctx.width * overlay.width)
    if overlay.shape == "circle":
        aspect = 1.0
    elif overlay.aspect:
        aspect = parse_aspect(overlay.aspect)
    else:
        aspect = info.aspect or 16 / 9
    height = even(width / aspect)
    assets = render_pip_assets(
        width,
        height,
        overlay.shape,
        radius=int(round(width * overlay.radius)),
        softness=int(round(overlay.softness * ctx.scale)),
        border=int(round(overlay.border * ctx.scale)),
        border_color=ctx.theme.color(overlay.border_color, "#FFFFFF"),
        shadow=overlay.shadow,
    )
    mask_path = ctx.job_dir / f"pip{index}_mask.png"
    assets.mask.save(mask_path)
    frame_path = None
    if assets.frame is not None:
        frame_path = ctx.job_dir / f"pip{index}_frame.png"
        assets.frame.save(frame_path)
    return ResolvedVideoOverlay(
        overlay,
        path,
        in_point,
        overlay.start,
        end,
        width,
        height,
        mask_path,
        frame_path,
        assets.pad,
        audio_stream,
        info.has_audio,
    )


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
        elif isinstance(overlay, VideoOverlay):
            pip = resolve_video_overlay(ctx, overlay, total, len(layer.video_overlays))
            if pip is not None:
                layer.video_overlays.append(pip)
    if cues and project.captions:
        add_captions(
            layer.doc, canvas, cues, project.captions.style, tone_fn=lambda a, b: tone_for(a, b, spans, tones)
        )
    if guides:
        add_guides(layer.doc, canvas)
    return layer
