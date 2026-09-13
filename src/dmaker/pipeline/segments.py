"""Preparação dos trechos: cada tipo de trecho tem seu preparador (estratégia), que decide como
gerar o mezanino e calcula a chave de cache. Um tipo novo entra registrando outro preparador.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from ..domain.presets import SafeZone
from ..domain.spec import CardSegment, ClipSegment, ImageSegment, Segment
from ..domain.timeline import segment_duration
from ..filtergraph.mezzanine import clip_mezzanine, frames_mezzanine, still_mezzanine
from ..filtergraph.reframe import resolve_reframe_mode
from ..media.ffmpeg import FFmpegCommand
from ..visuals.cards import render_backdrop, render_card, save_card
from ..visuals.geometry import fit_rect
from ..visuals.motion import plan_motion, render_frames, source_size_for
from ..visuals.reframe_image import reframe_image
from .context import RenderContext
from .sources import Source

MEZZ_VERSION = "m4"  # muda quando a receita do mezanino muda (invalida o cache)


def cache_key(*parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class PreparedSegment:
    index: int
    segment: Segment
    duration: float
    mezzanine: Path
    tone: str | None  # light/dark quando o fundo vem do tema; None para vídeo/foto real
    command: FFmpegCommand | None  # None quando o mezanino já está em cache


class SegmentPreparer(Protocol):
    def prepare(
        self, index: int, segment: Segment, source: Source, ctx: RenderContext
    ) -> PreparedSegment: ...


def _theme_signature(ctx: RenderContext) -> tuple:
    return (ctx.theme.key, ctx.theme.colors, ctx.theme.style.get("card_variant"), ctx.preset.safe.__dict__)


def _needs_render(out: Path, ctx: RenderContext) -> bool:
    return ctx.options.dry_run or ctx.options.force or not out.exists()


def _label(index: int, ctx: RenderContext) -> str:
    return f"trecho {index + 1}/{len(ctx.project.timeline)}"


def _default_variant(ctx: RenderContext) -> str:
    return ctx.theme.style.get("card_variant", "light")


class ClipPreparer:
    """Vídeo: corte, velocidade, enquadramento e cor ficam no FFmpeg."""

    def prepare(self, index: int, segment: Segment, source: Source, ctx: RenderContext) -> PreparedSegment:
        assert isinstance(segment, ClipSegment) and source.path is not None and source.info is not None
        info = source.info
        W, H = ctx.width, ctx.height
        mode = resolve_reframe_mode(segment.reframe.mode, info.width, info.height, W, H, ctx.has_brand)
        theme_part = _theme_signature(ctx) if mode == "brand" else None
        key = cache_key(
            MEZZ_VERSION,
            segment.model_dump(mode="json"),
            str(source.path),
            source.stat_key(),
            W,
            H,
            ctx.fps,
            mode,
            theme_part,
        )
        out = ctx.cache_dir / f"{key}.mov"
        duration = segment_duration(segment, info)
        backdrop = None
        tone = None
        if mode == "brand":
            tone = segment.reframe.variant or _default_variant(ctx)
            backdrop = ctx.cache_dir / f"{key}_bg.png"
            if _needs_render(backdrop, ctx) and not ctx.options.dry_run:
                rect = fit_rect(info.width, info.height, W, H, segment.reframe.margin)
                save_card(render_backdrop(ctx.theme, W, H, segment.reframe.variant, index, rect), backdrop)
        command = clip_mezzanine(
            segment,
            info,
            source.path,
            duration,
            W,
            H,
            ctx.fps,
            out,
            backdrop=backdrop,
            has_brand=ctx.has_brand,
            label=_label(index, ctx),
        )
        return PreparedSegment(
            index, segment, duration, out, tone, command if _needs_render(out, ctx) else None
        )


class ImagePreparer:
    """Foto/print: reenquadramento no Pillow e movimento sub-pixel gerado quadro a quadro."""

    def prepare(self, index: int, segment: Segment, source: Source, ctx: RenderContext) -> PreparedSegment:
        assert isinstance(segment, ImageSegment) and source.path is not None and source.info is not None
        info = source.info
        W, H = ctx.width, ctx.height
        mode = resolve_reframe_mode(segment.reframe.mode, info.width, info.height, W, H, ctx.has_brand)
        theme_part = _theme_signature(ctx) if mode == "brand" else None
        key = cache_key(
            MEZZ_VERSION,
            segment.model_dump(mode="json"),
            str(source.path),
            source.stat_key(),
            W,
            H,
            ctx.fps,
            mode,
            theme_part,
        )
        out = ctx.cache_dir / f"{key}.mov"
        tone = (segment.reframe.variant or _default_variant(ctx)) if mode == "brand" else None
        duration = segment.duration
        path = source.path
        theme = ctx.theme if mode == "brand" else None

        if segment.motion == "none" or segment.motion_amount <= 0:
            png = ctx.cache_dir / f"{key}_still.png"
            if _needs_render(png, ctx) and not ctx.options.dry_run:
                still = reframe_image(Image.open(path), W, H, segment.reframe, mode, theme, index)
                save_card(still, png)
            command = still_mezzanine(
                png,
                segment.color,
                segment.fade_in,
                segment.fade_out,
                duration,
                ctx.fps,
                out,
                _label(index, ctx),
            )
        else:
            src_w, src_h = source_size_for(W, H, segment.motion_amount)
            plan = plan_motion(
                src_w, src_h, W, H, segment.motion, segment.motion_amount, round(duration * ctx.fps)
            )

            def frames() -> Iterator[bytes]:
                big = reframe_image(Image.open(path), src_w, src_h, segment.reframe, mode, theme, index)
                yield from render_frames(big, plan)

            command = frames_mezzanine(
                frames(),
                W,
                H,
                segment.color,
                segment.fade_in,
                segment.fade_out,
                duration,
                ctx.fps,
                out,
                _label(index, ctx),
            )
        return PreparedSegment(
            index, segment, duration, out, tone, command if _needs_render(out, ctx) else None
        )


class CardPreparer:
    """Cartão gerado no visual do tema, parado ou com zoom suave."""

    def prepare(self, index: int, segment: Segment, source: Source, ctx: RenderContext) -> PreparedSegment:
        assert isinstance(segment, CardSegment)
        W, H = ctx.width, ctx.height
        key = cache_key(MEZZ_VERSION, segment.model_dump(mode="json"), W, H, ctx.fps, _theme_signature(ctx))
        out = ctx.cache_dir / f"{key}.mov"
        tone = segment.variant or _default_variant(ctx)
        duration = segment.duration
        theme, safe = ctx.theme, ctx.preset.safe

        def draw(width: int, height: int, supersample: int) -> Image.Image:
            k = width / W
            scaled_safe = SafeZone(
                *(int(round(v * k)) for v in (safe.top, safe.bottom, safe.left, safe.right))
            )
            return render_card(
                theme,
                width,
                height,
                segment.title,
                segment.subtitle,
                segment.variant,
                segment.logo,
                segment.background,
                scaled_safe,
                seed=index,
                supersample=supersample,
            )

        if segment.motion == "none" or segment.motion_amount <= 0:
            png = ctx.cache_dir / f"{key}_card.png"
            if _needs_render(png, ctx) and not ctx.options.dry_run:
                save_card(draw(W, H, 2), png)
            command = still_mezzanine(
                png,
                segment.color,
                segment.fade_in,
                segment.fade_out,
                duration,
                ctx.fps,
                out,
                _label(index, ctx),
            )
        else:
            src_w, src_h = source_size_for(W, H, segment.motion_amount)
            plan = plan_motion(
                src_w, src_h, W, H, segment.motion, segment.motion_amount, round(duration * ctx.fps)
            )

            def frames() -> Iterator[bytes]:
                yield from render_frames(draw(src_w, src_h, 1), plan)

            command = frames_mezzanine(
                frames(),
                W,
                H,
                segment.color,
                segment.fade_in,
                segment.fade_out,
                duration,
                ctx.fps,
                out,
                _label(index, ctx),
            )
        return PreparedSegment(
            index, segment, duration, out, tone, command if _needs_render(out, ctx) else None
        )


DEFAULT_PREPARERS: dict[type, SegmentPreparer] = {
    ClipSegment: ClipPreparer(),
    ImageSegment: ImagePreparer(),
    CardSegment: CardPreparer(),
}


class MezzanineBuilder:
    """Prepara e gera (quando não está em cache) o mezanino de cada trecho."""

    def __init__(self, preparers: dict[type, SegmentPreparer] | None = None):
        self.preparers = preparers or DEFAULT_PREPARERS

    def prepare(self, ctx: RenderContext, sources: list[Source]) -> list[PreparedSegment]:
        prepared: list[PreparedSegment] = []
        for i, (segment, source) in enumerate(zip(ctx.project.timeline, sources, strict=True)):
            preparer = self.preparers.get(type(segment))
            if preparer is None:
                raise TypeError(f"timeline[{i}]: nenhum preparador para {type(segment).__name__}")
            prepared.append(preparer.prepare(i, segment, source, ctx))
        return prepared

    def build(self, ctx: RenderContext, prepared: list[PreparedSegment]) -> None:
        for item in prepared:
            if item.command is not None:
                ctx.runner.run(item.command)
