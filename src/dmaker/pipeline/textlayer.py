"""Camada de texto (ASS): títulos, CTA, barra de progresso, legendas e guias, com o tom do fundo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.audiogram import audiogram_size, bars_layout, resolve_follow
from ..domain.brand import Theme
from ..domain.regions import resolve_region
from ..domain.spec import (
    AudiogramOverlay,
    ImageOverlay,
    ProgressBar,
    Project,
    TextOverlay,
    VideoOverlay,
    parse_aspect,
)
from ..domain.timeline import tone_for
from ..filtergraph.audiogram import ResolvedAudiogram
from ..filtergraph.common import even
from ..filtergraph.overlays import ResolvedImageOverlay
from ..filtergraph.pip import ResolvedVideoOverlay
from ..text.ass import AssDoc
from ..text.captions import Cue
from ..text.overlays import Canvas, add_captions, add_guides, add_progress_bar, add_text_overlay
from ..visuals.audiogram import style_assets
from ..visuals.pip import pip_mask, render_pip_assets
from .context import RenderContext

# `even` trunca: 480 / (480/226) pode dar 225.99999999999997 e virar 224, 2 px a menos que a região pedida
FRAME_SLACK_PX = 1e-6
PIP_SHORT_TOLERANCE = 0.5  # s: o vídeo do PiP pode terminar um pouco antes do pedido sem merecer aviso


@dataclass
class TextLayer:
    doc: AssDoc
    image_overlays: list[ResolvedImageOverlay] = field(default_factory=list)
    video_overlays: list[ResolvedVideoOverlay] = field(default_factory=list)
    audiograms: list[ResolvedAudiogram] = field(default_factory=list)

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
    available = info.duration - in_point
    if info.duration and available + PIP_SHORT_TOLERANCE < end - overlay.start:
        ctx.warn(
            f"o vídeo de sobreposição {overlay.src or overlay.source!r} tem {available:.1f}s a partir do ponto "
            f"de entrada, menos que os {end - overlay.start:.1f}s pedidos: o quadro some antes do fim"
        )

    width = even(ctx.width * overlay.width)
    if overlay.shape == "circle":
        aspect = 1.0
    elif overlay.aspect:
        aspect = parse_aspect(overlay.aspect)
    else:
        aspect = info.aspect or 16 / 9
    height = even(width / aspect + FRAME_SLACK_PX)
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


def resolve_image_overlay(
    ctx: RenderContext, overlay: ImageOverlay, path: Path, total: float, index: int
) -> ResolvedImageOverlay | None:
    """A imagem no tempo certo e, no recorte circular, com a máscara (a mesma do PiP) no diretório do job."""
    end = min(overlay.end if overlay.end is not None else total, total)
    if end <= overlay.start:
        return None
    mask_path = None
    if overlay.shape == "circle":
        side = even(ctx.width * overlay.width)
        mask_path = ctx.job_dir / f"image{index}_mask.png"
        pip_mask(side, side, "circle", radius=0, softness=0).save(mask_path)
    return ResolvedImageOverlay(overlay, path, overlay.start, end, mask_path)


def resolve_audiogram(
    ctx: RenderContext, overlay: AudiogramOverlay, total: float, index: int, has_voice: bool
) -> ResolvedAudiogram | None:
    """Tamanho em px, cor, áudio que segue e as imagens estáticas do estilo (salvas no diretório do job)."""
    end = min(overlay.end if overlay.end is not None else total, total)
    if end <= overlay.start:
        return None
    width, height = audiogram_size(overlay, ctx.width, ctx.height)
    if overlay.style == "bars":
        width = bars_layout(width, height).width  # um número inteiro de colunas por barra
    assets: dict[str, Path] = {}
    for name, image in style_assets(overlay.style, width, height, overlay.inner_radius).items():
        assets[name] = ctx.job_dir / f"audiogram{index}_{name}.png"
        image.save(assets[name])
    accent = ctx.theme.color("accent", "#FFFFFF")  # sem `color`, a cor de destaque da marca
    return ResolvedAudiogram(
        overlay,
        width,
        height,
        ctx.theme.color(overlay.color, accent),
        overlay.start,
        end,
        resolve_follow(overlay.follow, has_voice),
        assets,
    )


def build_text_layer(
    ctx: RenderContext,
    total: float,
    spans: list[tuple[float, float]],
    tones: list[str | None],
    cues: list[Cue] | None,
    guides: bool,
    has_voice: bool = False,
) -> TextLayer:
    """`has_voice` diz se o projeto tem voz (decide o áudio que um audiograma `auto` segue)."""
    project = ctx.project
    canvas = Canvas(ctx.width, ctx.height, ctx.preset.safe, ctx.theme, total)
    layer = TextLayer(AssDoc(ctx.width, ctx.height, project.name))
    text_index = 0
    for overlay in project.overlays:
        if isinstance(overlay, TextOverlay):
            overlay = resolve_region(overlay, project.regions, ctx.width, ctx.height)
            end = min(overlay.end if overlay.end is not None else total, total)
            tone = tone_for(overlay.start, end, spans, tones)
            add_text_overlay(layer.doc, canvas, overlay, text_index, tone=tone)
            text_index += 1
        elif isinstance(overlay, ProgressBar):
            add_progress_bar(layer.doc, canvas, overlay)
        elif isinstance(overlay, ImageOverlay):
            path = resolve_overlay_image(project, ctx.theme, overlay.src)
            if overlay.region:  # a imagem cabe na região: precisa da proporção do arquivo (o círculo é 1:1)
                aspect = 1.0 if overlay.shape == "circle" else ctx.prober(path).aspect
                overlay = resolve_region(overlay, project.regions, ctx.width, ctx.height, aspect)
            image = resolve_image_overlay(ctx, overlay, path, total, len(layer.image_overlays))
            if image is not None:
                layer.image_overlays.append(image)
        elif isinstance(overlay, VideoOverlay):
            overlay = resolve_region(overlay, project.regions, ctx.width, ctx.height)
            pip = resolve_video_overlay(ctx, overlay, total, len(layer.video_overlays))
            if pip is not None:
                layer.video_overlays.append(pip)
        elif isinstance(overlay, AudiogramOverlay):
            overlay = resolve_region(overlay, project.regions, ctx.width, ctx.height)
            audiogram = resolve_audiogram(ctx, overlay, total, len(layer.audiograms), has_voice)
            if audiogram is not None:
                layer.audiograms.append(audiogram)
    if cues and project.captions:
        style = project.captions.style
        tone_fn = (lambda a, b: tone_for(a, b, spans, tones)) if style.follow_background else None
        add_captions(layer.doc, canvas, cues, style, tone_fn=tone_fn)
    if guides:
        add_guides(layer.doc, canvas)
    return layer
