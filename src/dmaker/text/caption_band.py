"""A faixa que a legenda queimada ocupa na altura do quadro, para quem precisa ficar fora dela (a persona sobreposta).

É a mesma conta do desenho: o centro sai de `style.y` ou de `default_caption_y`, a largura útil e a quebra são as de
`caption_layout` e a altura de cada linha é o tamanho da fonte, que é como `layout_cue` e o modo `rounded` a medem.
A altura cobre o pior caso que o estilo permite (`max_words` palavras e `max_chars` letras largas), porque a faixa
vale para o vídeo todo e as linhas de cada momento mudam. Pura: só mede texto pela régua injetada.
"""

from __future__ import annotations

from math import ceil

from ..domain.spec import CaptionStyle, Project
from ..media import fonts
from .caption_layout import max_text_width
from .overlays import Canvas, MeasureFn, default_caption_y, wrap_tokens

# contorno do modo `boxed`, em px na base 1080: é o `outline_w` que o estilo da caixa usa em `add_captions`
BOXED_OUTLINE_PX = 14
WIDEST_LETTER = "M"  # a letra mais larga: o pior caso de quebra

Band = tuple[float, float]  # topo e base, em px do quadro


def caption_band(style: CaptionStyle, canvas: Canvas, measure: MeasureFn = fonts.measure_rendered) -> Band:
    """(topo, base) do bloco de legenda em px do quadro, com o contorno que sai do texto e o máximo de linhas."""
    scale = canvas.scale
    ref = fonts.resolve(style.font or canvas.theme.font_family, style.weight)
    size = style.size * scale
    word = WIDEST_LETTER * ceil(style.max_chars / style.max_words)
    rows = wrap_tokens([word] * style.max_words, ref, size, max_text_width(style, canvas), 0, measure)
    center = style.y * canvas.height if style.y is not None else default_caption_y(canvas, size)
    halo = {"rounded": 0.0, "boxed": BOXED_OUTLINE_PX * scale}.get(style.mode, style.outline * scale)
    half = len(rows) * size / 2 + halo
    return center - half, center + half


def project_caption_band(
    project: Project,
    canvas: Canvas,
    *,
    no_captions: bool = False,
    measure: MeasureFn = fonts.measure_rendered,
) -> Band | None:
    """A faixa da legenda do projeto, ou None quando ele não queima legenda (a condição que o render usa)."""
    captions = project.captions
    if not captions or not captions.enabled or no_captions:
        return None
    return caption_band(captions.style, canvas, measure)
