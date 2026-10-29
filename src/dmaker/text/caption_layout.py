"""Onde cada palavra da legenda cai na tela e em que instante: a âncora de um grifo, de uma seta, de um círculo.

A legenda é desenhada pelo libass (`overlays.add_captions`) e o DMaker não recebe de volta onde ele pôs cada
palavra. Aqui a conta é refeita com a mesma fonte, o mesmo tamanho e a mesma quebra de linha, e o resultado é a
caixa da tinta da palavra em pixels do quadro, mais o tempo em que ela é dita. Tudo é puro: recebe as linhas da
legenda e o estilo, devolve números, não toca disco nem ffmpeg.

A quebra é a do modo `rounded` (feita pelo DMaker, `wrap_tokens`, exata). Nos outros modos o libass quebra
sozinho; para uma legenda de uma linha, que é o caso de `max_words`/`max_chars` curtos, a conta é a mesma. Uma
linha que o libass quebraria de outro jeito sai com a palavra no lugar errado: o teste de render real (karaokê e
`rounded`) prende o caso comum.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..domain.spec import CaptionStyle
from ..media import fonts
from .captions import Cue, Word, fold
from .overlays import Canvas, default_caption_y, highlight_windows, wrap_tokens

PUNCTUATION = ".,;:!?\"'()[]…«»“”"


@dataclass(frozen=True)
class CaptionWord:
    """Uma palavra da legenda: o texto como aparece, o tempo e a caixa da tinta, em px do quadro final.

    `start`/`end` são a janela em que ela é a palavra da vez (o destaque do karaokê) e `line_end` é quando a linha
    inteira sai da tela."""

    text: str
    start: float
    end: float
    line_end: float
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


def _word_key(text: str) -> str:
    """A palavra sem acento, sem caixa e sem pontuação, para achar "Frio," pedindo "frio"."""
    return fold(text.strip().strip(PUNCTUATION))


def _timed_words(cue: Cue) -> list[Word]:
    """As palavras da linha com tempo. Uma legenda sem tempo por palavra (SRT) reparte a duração pelo tamanho
    de cada uma, como `flatten_words`."""
    words = [word for word in cue.words if word.text.strip()]
    if words:
        return words
    tokens = cue.text.split()
    total = sum(len(token) for token in tokens)
    spoken: list[Word] = []
    cursor = cue.start
    for token in tokens:
        share = cue.duration * (len(token) / total) if total else cue.duration / max(len(tokens), 1)
        spoken.append(Word(cursor, min(cursor + share, cue.end), token))
        cursor += share
    return spoken


def _max_text_width(style: CaptionStyle, canvas: Canvas) -> float:
    """A largura que a linha pode ter: a do quadro menos as margens da legenda (e, no `rounded`, a folga da caixa)."""
    scale = canvas.scale
    margin_l = int(canvas.safe.left + 40 * scale)
    margin_r = int(canvas.safe.right + 40 * scale)
    width = canvas.width - margin_l - margin_r
    if style.mode == "rounded":
        width -= 2 * canvas.theme.rounded_box_padding * scale
    return width


def layout_cue(cue: Cue, style: CaptionStyle, canvas: Canvas) -> list[CaptionWord]:
    """Todas as palavras de uma linha da legenda, com tempo e caixa de tinta."""
    theme, scale = canvas.theme, canvas.scale
    ref = fonts.resolve(style.font or theme.font_family, style.weight)
    size = style.size * scale
    spoken = _timed_words(cue)
    if not spoken:
        return []
    tokens = [word.text.strip().upper() if style.uppercase else word.text.strip() for word in spoken]
    rows = wrap_tokens(tokens, ref, size, _max_text_width(style, canvas), 0, fonts.measure_rendered)
    windows = {
        active: (start, end) for start, end, active in highlight_windows(cue, spoken) if active is not None
    }
    center_y = style.y * canvas.height if style.y is not None else default_caption_y(canvas, size)
    block_top = center_y - len(rows) * size / 2
    baseline_in_row = fonts.baseline_offset(ref, size)
    placed: list[CaptionWord] = []
    index = 0
    for row_number, row in enumerate(rows):
        row_left = canvas.width / 2 - fonts.measure_rendered(" ".join(row), ref, size)[0] / 2
        baseline = block_top + row_number * size + baseline_in_row
        for position, token in enumerate(row):
            before = fonts.measure_rendered(" ".join(row[:position]) + " ", ref, size)[0] if position else 0.0
            ink_left, ink_top, ink_right, ink_bottom = fonts.ink_box(token, ref, size)
            start, end = windows.get(index, (spoken[index].start, spoken[index].end))
            placed.append(
                CaptionWord(
                    token,
                    start,
                    end,
                    cue.end,
                    row_left + before + ink_left,
                    baseline + ink_top,
                    row_left + before + ink_right,
                    baseline + ink_bottom,
                )
            )
            index += 1
    return placed


def find_caption_word(
    cues: Sequence[Cue],
    target: str,
    style: CaptionStyle,
    canvas: Canvas,
    *,
    occurrence: int = 1,
    after: float = 0.0,
    before: float | None = None,
) -> CaptionWord | None:
    """A `occurrence`-ésima vez que `target` é dita entre `after` e `before` (segundos), ou None se não aparece.
    A comparação ignora acento, caixa e pontuação."""
    wanted = _word_key(target)
    seen = 0
    for cue in sorted(cues, key=lambda item: item.start):
        if cue.end <= cue.start or cue.end <= after:
            continue
        for word in layout_cue(cue, style, canvas):
            if _word_key(word.text) != wanted or word.start < after - 1e-6:
                continue
            if before is not None and word.start >= before:
                return None
            seen += 1
            if seen == occurrence:
                return word
    return None
