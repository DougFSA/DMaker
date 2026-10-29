"""Prender uma composição em HTML a uma palavra da legenda: o início, o fim e a caixa vêm da palavra.

A composição com `anchor` (um grifo que circula "frio", por exemplo) não sabe de antemão onde nem quando a palavra
aparece: isso só se conhece depois que a legenda existe. Este resolvedor roda na hora de montar a camada de texto,
com as linhas finais da legenda, acha a palavra (`text/caption_layout.py`) e devolve a composição com `start`,
`end` e a caixa já concretos, como se o autor os tivesse escrito. O resto do pipeline não sabe de âncora.
"""

from __future__ import annotations

from ..domain.spec import HtmlOverlay
from ..text.caption_layout import find_caption_word
from ..text.captions import Cue
from ..text.overlays import Canvas
from .context import RenderContext


def anchor_html_overlay(
    ctx: RenderContext, overlay: HtmlOverlay, cues: list[Cue] | None, total: float, index: int
) -> HtmlOverlay | None:
    """A composição no tempo e no lugar da palavra, ou None (com aviso) se a palavra não aparece na legenda.
    Sem `anchor` devolve a própria composição."""
    anchor = overlay.anchor
    if anchor is None:
        return overlay
    captions = ctx.project.captions
    where = f"overlays[{index}]"
    if not (cues and captions and captions.enabled):
        ctx.warn(f"{where}: presa a uma palavra da legenda, mas não há legenda neste render; foi ignorada")
        return None
    canvas = Canvas(ctx.width, ctx.height, ctx.preset.safe, ctx.theme, total)
    word = find_caption_word(
        cues,
        anchor.word,
        captions.style,
        canvas,
        occurrence=anchor.occurrence,
        after=overlay.start,
        before=overlay.end,
    )
    if word is None:
        ordinal = f" ({anchor.occurrence}ª vez)" if anchor.occurrence > 1 else ""
        ctx.warn(f"{where}: a palavra {anchor.word!r}{ordinal} não aparece na legenda; foi ignorada")
        return None
    margin = anchor.margin * ctx.scale  # a folga é em px na base 1080
    left, right = max(word.left - margin, 0.0), min(word.right + margin, float(ctx.width))
    top, bottom = max(word.top - margin, 0.0), min(word.bottom + margin, float(ctx.height))
    end = word.line_end if anchor.hold == "line" else word.end
    return overlay.model_copy(
        update={
            "start": word.start,
            "end": end,
            "region": None,
            "x": (left + right) / 2 / ctx.width,
            "y": (top + bottom) / 2 / ctx.height,
            "width": (right - left) / ctx.width,
            "height": (bottom - top) / ctx.height,
        }
    )
