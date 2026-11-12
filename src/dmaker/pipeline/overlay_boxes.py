"""A caixa de cada sobreposição no quadro: a conta única da interface (arrastar e redimensionar), do QA da zona
segura e do aviso de quem sai dela.

Cada tipo de sobreposição tem um calculador registrado em `CALCULATORS` (tipo novo entra por ali, sem `if/elif`).
Eles não repetem fórmula: texto, imagem, PiP e HTML chamam as mesmas funções que o render usa para desenhar
(`layout_text_overlay`, `image_overlay_origin`, `pip_origin`, `html_box`...), de modo que a caixa, o aviso e o
vídeo final dão a mesma conta. Tudo em pixels do preset; `BoxLayout.to_dict` entrega as frações que a API devolve.
A régua de texto e a sonda de mídia entram por parâmetro, e nada aqui executa ffmpeg nem toca o disco além do que
o `Prober` injetado olhar.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from ..domain.audiogram import audiogram_size, bars_layout
from ..domain.brand import Theme
from ..domain.infographics import resolve_infographic
from ..domain.presets import Preset, SafeZone
from ..domain.regions import html_box, resolve_region
from ..domain.spec import (
    AudiogramOverlay,
    HtmlOverlay,
    ImageOverlay,
    PersonaOverlay,
    ProgressBar,
    Project,
    TextOverlay,
    VideoOverlay,
    parse_aspect,
)
from ..filtergraph.audiogram import audiogram_expressions
from ..filtergraph.common import even
from ..filtergraph.expressions import evaluate
from ..filtergraph.overlays import image_overlay_origin, image_overlay_size
from ..filtergraph.pip import pip_origin, pip_size
from ..media.ffmpeg import FFmpegError
from ..text.overlays import Canvas, MeasureFn, TextLayout, layout_text_overlay
from .context import Prober
from .textlayer import resolve_overlay_image

# 1 px de folga: a conta do desenho tem arredondamentos (o ffmpeg trunca para par, o libass desenha em 1/64 de
# px), e uma caixa que encosta exatamente na borda da zona segura não é uma invasão.
SAFE_ZONE_SLACK_PX = 1.0
SIDES = ("top", "bottom", "left", "right")
_FRACTION_DIGITS = 6

Rect = tuple[float, float, float, float]  # esquerda, topo, largura, altura, em px do preset


@dataclass(frozen=True)
class OverlayBox:
    """A área que uma sobreposição desenha, em px do preset, mais o que a interface precisa para mexer nela.

    `rect` e `anchor` são None quando o lugar não se sabe antes do render (HTML presa a uma palavra da legenda)
    ou não dá para calcular (a imagem sumiu do disco, a região não existe): então `movable` é falso e
    `locked_reason` diz por quê. `text` guarda a medida do texto, para o QA conferir a palavra mais larga que a
    área sem medir de novo; ele não vai para a API."""

    index: int
    kind: str
    start: float
    end: float | None
    rect: Rect | None
    anchor: tuple[float, float] | None
    placement: str
    region: str | None
    resize: str
    wrap: tuple[float, float] | None  # (esquerda, largura) da área da quebra, só no texto
    movable: bool
    locked_reason: str | None
    outside_safe_zone: tuple[str, ...]
    text: TextLayout | None = None


@dataclass(frozen=True)
class BoxLayout:
    """As caixas de um projeto e o quadro em que elas valem."""

    width: int
    height: int
    safe: SafeZone
    boxes: list[OverlayBox]

    def to_dict(self) -> dict:
        """O corpo de `POST /api/projects/{name}/boxes`: tudo em fração do quadro nativo do preset."""
        return {
            "width": self.width,
            "height": self.height,
            "safe_zone": {
                "top": _fraction(self.safe.top, self.height),
                "bottom": _fraction(self.safe.bottom, self.height),
                "left": _fraction(self.safe.left, self.width),
                "right": _fraction(self.safe.right, self.width),
            },
            "boxes": [_box_dict(box, self.width, self.height) for box in self.boxes],
        }


def _fraction(value: float, total: float) -> float:
    return round(value / total, _FRACTION_DIGITS)


def _box_dict(box: OverlayBox, width: int, height: int) -> dict:
    left = top = box_width = box_height = anchor = wrap = None
    if box.rect is not None:
        left, top = _fraction(box.rect[0], width), _fraction(box.rect[1], height)
        box_width, box_height = _fraction(box.rect[2], width), _fraction(box.rect[3], height)
    if box.anchor is not None:
        anchor = {"x": _fraction(box.anchor[0], width), "y": _fraction(box.anchor[1], height)}
    if box.wrap is not None:
        wrap = {"left": _fraction(box.wrap[0], width), "width": _fraction(box.wrap[1], width)}
    return {
        "index": box.index,
        "kind": box.kind,
        "start": box.start,
        "end": box.end,
        "left": left,
        "top": top,
        "width": box_width,
        "height": box_height,
        "anchor": anchor,
        "placement": box.placement,
        "region": box.region,
        "resize": box.resize,
        "wrap": wrap,
        "movable": box.movable,
        "locked_reason": box.locked_reason,
        "outside_safe_zone": list(box.outside_safe_zone),
    }


def sides_outside_safe_zone(
    rect: Rect, width: int, height: int, safe: SafeZone, slack: float = SAFE_ZONE_SLACK_PX
) -> tuple[str, ...]:
    """Os lados (`top`, `bottom`, `left`, `right`) em que a caixa invade a zona segura, com `slack` px de folga."""
    left, top, box_width, box_height = rect
    sides = []
    if top < safe.top - slack:
        sides.append("top")
    if top + box_height > height - safe.bottom + slack:
        sides.append("bottom")
    if left < safe.left - slack:
        sides.append("left")
    if left + box_width > width - safe.right + slack:
        sides.append("right")
    return tuple(sides)


@dataclass(frozen=True)
class BoxContext:
    """O que todo calculador precisa: o projeto, o preset (quadro nativo e zona segura), a marca e as sondas."""

    project: Project
    preset: Preset
    theme: Theme
    prober: Prober
    measure: MeasureFn | None = None

    @property
    def width(self) -> int:
        return self.preset.width

    @property
    def height(self) -> int:
        return self.preset.height

    @property
    def safe(self) -> SafeZone:
        return self.preset.safe

    @property
    def scale(self) -> float:
        """Fator para medidas definidas na base 1080 (lado menor), o mesmo de `RenderContext.scale`."""
        return self.preset.short_side / 1080


Calculator = Callable[[BoxContext, int, Any], OverlayBox]


def _placement(overlay: Any) -> str:
    """Como o lugar da sobreposição é dado na spec: `region`, `anchor` (palavra da legenda), `xy` (centro
    explícito) ou `position` (posição nomeada, inclusive a do papel quando o texto não diz nenhuma)."""
    if getattr(overlay, "region", None):
        return "region"
    if getattr(overlay, "anchor", None) is not None:
        return "anchor"
    if getattr(overlay, "x", None) is not None and getattr(overlay, "y", None) is not None:
        return "xy"
    return "position"


def _center(context: BoxContext, placed: Any, rect: Rect) -> tuple[float, float]:
    """O centro que a spec dá (`x`/`y`, em px exatos: o render arredonda o canto, a spec não), ou o centro da
    área quando o lugar vem de uma posição nomeada."""
    if getattr(placed, "x", None) is not None and getattr(placed, "y", None) is not None:
        return placed.x * context.width, placed.y * context.height
    left, top, width, height = rect
    return left + width / 2, top + height / 2


def _box(
    context: BoxContext,
    index: int,
    overlay: Any,
    kind: str,
    rect: Rect,
    *,
    resize: str,
    placement: str | None = None,
    wrap: tuple[float, float] | None = None,
    anchor: tuple[float, float] | None = None,
    text: TextLayout | None = None,
    skip_safe_zone: bool = False,
) -> OverlayBox:
    """Uma caixa que se move. A âncora padrão é o centro da área (`x`/`y` das sobreposições de imagem, PiP e HTML)."""
    left, top, width, height = rect
    outside = (
        () if skip_safe_zone else sides_outside_safe_zone(rect, context.width, context.height, context.safe)
    )
    return OverlayBox(
        index=index,
        kind=kind,
        start=overlay.start,
        end=overlay.end,
        rect=rect,
        anchor=anchor or (left + width / 2, top + height / 2),
        placement=placement or _placement(overlay),
        region=getattr(overlay, "region", None),
        resize=resize,
        wrap=wrap,
        movable=True,
        locked_reason=None,
        outside_safe_zone=outside,
        text=text,
    )


def _locked(
    index: int,
    overlay: Any,
    kind: str,
    reason: str,
    rect: Rect | None = None,
    placement: str | None = None,
) -> OverlayBox:
    """Uma caixa que não se move (ou que não tem lugar conhecido): a interface mostra `reason` no lugar das alças."""
    return OverlayBox(
        index=index,
        kind=kind,
        start=getattr(overlay, "start", 0.0),
        end=getattr(overlay, "end", None),
        rect=rect,
        anchor=None if rect is None else (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2),
        placement=placement or _placement(overlay),
        region=getattr(overlay, "region", None),
        resize="none",
        wrap=None,
        movable=False,
        locked_reason=reason,
        outside_safe_zone=(),
    )


# ---------- texto ----------


def _text_box(context: BoxContext, index: int, overlay: TextOverlay) -> OverlayBox:
    """O bloco medido pela régua do libass, com o padding quando há caixa de fundo. A âncora é a do `x`/`y` da
    spec: o centro do texto centralizado, a borda do texto alinhado à esquerda ou à direita."""
    placed = resolve_region(overlay, context.project.regions, context.width, context.height)
    canvas = Canvas(context.width, context.height, context.safe, context.theme, total=0.0)
    layout = layout_text_overlay(canvas, placed, measure=context.measure)
    # a área da quebra é o que a largura permitida (`style.max_width`) deixa ao bloco já com o padding
    wrap_width = layout.wrap_width + 2 * layout.padding
    if layout.align == "left":
        wrap_left = layout.anchor_x - layout.padding
    elif layout.align == "right":
        wrap_left = layout.anchor_x + layout.padding - wrap_width
    else:
        wrap_left = layout.anchor_x - wrap_width / 2
    placement = (
        "region" if overlay.region else "xy" if overlay.x is not None or overlay.y is not None else "position"
    )
    return _box(
        context,
        index,
        overlay,
        "text",
        layout.area(),
        resize="text_width",
        placement=placement,
        wrap=(wrap_left, wrap_width),
        anchor=(layout.anchor_x, layout.anchor_y),
        text=layout,
    )


# ---------- imagem ----------


def _image_box(context: BoxContext, index: int, overlay: ImageOverlay) -> OverlayBox:
    """O retângulo da imagem como o grafo a escala e a posiciona, sem a sombra (a imagem não tem)."""
    path = resolve_overlay_image(context.project, context.theme, overlay.src)
    aspect = 1.0 if overlay.shape == "circle" else (context.prober(path).aspect or 1.0)
    placed = resolve_region(overlay, context.project.regions, context.width, context.height, aspect)
    size = image_overlay_size(placed, context.width, aspect)
    left, top = image_overlay_origin(placed, size, context.width, context.height, context.scale, context.safe)
    rect = (left, top, float(size[0]), float(size[1]))
    return _box(
        context, index, overlay, "image", rect, resize="keep_aspect", anchor=_center(context, placed, rect)
    )


# ---------- picture-in-picture ----------


def _video_path(project: Project, overlay: VideoOverlay):
    """O arquivo que dá a proporção do PiP: o `src`, ou o primeiro arquivo da fonte nomeada."""
    if overlay.source:
        return project.resolve(
            project.sources[overlay.source].files[0]
        )  # a spec já garante que a fonte existe
    return project.resolve(overlay.src or "")


def _video_box(context: BoxContext, index: int, overlay: VideoOverlay) -> OverlayBox:
    """O retângulo do vídeo do PiP, sem a borda nem a sombra (a moldura fica por fora dele)."""
    path = _video_path(context.project, overlay)
    if not path.exists():
        raise FileNotFoundError(f"Vídeo do PiP não encontrado: {overlay.src or overlay.source}")
    placed = resolve_region(overlay, context.project.regions, context.width, context.height)
    size = pip_size(placed, context.width, context.prober(path).aspect)
    left, top = pip_origin(placed, *size, context.width, context.height, context.scale, context.safe)
    rect = (float(left), float(top), float(size[0]), float(size[1]))
    return _box(
        context, index, overlay, "video", rect, resize="keep_aspect", anchor=_center(context, placed, rect)
    )


# ---------- composição em HTML ----------


def _html_box(context: BoxContext, index: int, overlay: HtmlOverlay) -> OverlayBox:
    """O `html_box` da composição. A presa a uma palavra da legenda só tem lugar depois da legenda existir: fica
    sem área, travada. A página inteira não confere a zona segura: o que ela desenha dentro é decisão dela."""
    resolved = resolve_infographic(overlay, context.project)  # o modelo pronto tem a área que o esquema dá
    if resolved.anchor is not None:
        reason = f'Presa à palavra "{resolved.anchor.word}" da legenda: o lugar e o tempo vêm da palavra.'
        return _locked(index, resolved, "html", reason, placement="anchor")
    placed = resolve_region(resolved, context.project.regions, context.width, context.height)
    left, top, width, height = html_box(placed, context.width, context.height)
    is_full_page = width >= context.width - 1 and height >= context.height - 1
    if resolved.region:  # `resolve_region` devolve a composição já sem o nome da região
        placement = "region"
    elif placed.x is None and placed.width >= 1 and placed.height >= 1:
        placement = "full"
    else:
        placement = "xy"
    rect = (float(left), float(top), float(width), float(height))
    return _box(
        context,
        index,
        overlay,
        "html",
        rect,
        resize="free",
        placement=placement,
        anchor=_center(context, placed, rect),
        skip_safe_zone=is_full_page,
    )


# ---------- o que não se move ----------


def _progress_bar_box(context: BoxContext, index: int, overlay: ProgressBar) -> OverlayBox:
    """A faixa da barra de progresso na borda de cima ou de baixo: aparece, mas fica presa à borda."""
    height = overlay.height * context.scale
    top = 0.0 if overlay.position == "top" else context.height - height
    return _locked(
        index,
        overlay,
        "progress-bar",
        "A barra de progresso fica presa à borda do quadro.",
        rect=(0.0, top, float(context.width), height),
        placement="position",
    )


def _audiogram_box(context: BoxContext, index: int, overlay: AudiogramOverlay) -> OverlayBox:
    """A área do audiograma como o grafo a desenha. Mover o audiograma fica para outro chamado."""
    placed = resolve_region(overlay, context.project.regions, context.width, context.height)
    width, height = audiogram_size(placed, context.width, context.height)
    if placed.style == "bars":
        width = bars_layout(width, height).width  # um número inteiro de colunas por barra
    x, y = audiogram_expressions(placed, context.width, context.height, context.scale, context.safe)
    names = {"W": context.width, "H": context.height, "w": width, "h": height}
    rect = (evaluate(x, names), evaluate(y, names), float(width), float(height))
    return _locked(index, overlay, "audiogram", "O audiograma ainda não se move no quadro.", rect=rect)


# ---------- persona ----------


def _persona_box(context: BoxContext, index: int, overlay: PersonaOverlay) -> OverlayBox:
    """O quadro da persona no canto, do tamanho e no lugar em que a montagem o põe (as mesmas contas do render)."""
    width = even(context.width * overlay.width)
    aspect = 1.0 if overlay.shape == "circle" and overlay.background else parse_aspect(overlay.aspect)
    height = even(width / aspect)
    left, top = pip_origin(overlay, width, height, context.width, context.height, context.scale, context.safe)
    rect = (float(left), float(top), float(width), float(height))
    return _locked(index, overlay, "persona", "A persona ainda não se move no quadro.", rect=rect)


# Como cada tipo de sobreposição vira caixa. Um tipo novo entra aqui, com o seu calculador.
CALCULATORS: dict[type, tuple[str, Calculator]] = {
    TextOverlay: ("text", _text_box),
    ImageOverlay: ("image", _image_box),
    VideoOverlay: ("video", _video_box),
    HtmlOverlay: ("html", _html_box),
    ProgressBar: ("progress-bar", _progress_bar_box),
    AudiogramOverlay: ("audiogram", _audiogram_box),
    PersonaOverlay: ("persona", _persona_box),
}

# O que um calculador levanta quando a sobreposição não tem lugar calculável: a caixa fica sem área e diz o motivo.
# `ValueError` cobre o modelo de infográfico que não existe ou não confere com o esquema (`InfographicError`,
# `SchemaError`) e a região que o projeto não declara (`RegionError`).
_UNRESOLVED = (FileNotFoundError, FFmpegError, ValueError)


def _reason(error: Exception) -> str:
    text = str(error).strip()
    return text[:1].upper() + text[1:] if text else "Não foi possível calcular a área."


def overlay_boxes(
    project: Project,
    preset: Preset,
    theme: Theme,
    prober: Prober,
    *,
    measure: MeasureFn | None = None,
    kinds: Collection[str] | None = None,
) -> BoxLayout:
    """A caixa de cada sobreposição de `project.overlays`, na ordem delas (`OverlayBox.index` é o índice na lista).

    A geometria base não depende do tempo nem do tom do fundo (a cor muda, o tamanho não), então não há
    layout de trechos aqui. `kinds` limita o cálculo aos tipos pedidos (o QA só quer texto, ou só HTML); os
    outros ficam de fora da lista, e `index` continua apontando para a lista da spec."""
    context = BoxContext(project, preset, theme, prober, measure)
    boxes: list[OverlayBox] = []
    for index, overlay in enumerate(project.overlays):
        kind, calculator = CALCULATORS[type(overlay)]
        if kinds is not None and kind not in kinds:
            continue
        try:
            boxes.append(calculator(context, index, overlay))
        except _UNRESOLVED as exc:
            boxes.append(_locked(index, overlay, kind, _reason(exc)))
    return BoxLayout(preset.width, preset.height, preset.safe, boxes)
