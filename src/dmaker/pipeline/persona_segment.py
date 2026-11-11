"""O trecho de tela cheia da persona: o clipe dela sobre o fundo escolhido, com a fala como áudio.

O preparador se registra em `DEFAULT_PREPARERS` (ao fim de `segments.py`), como os dos outros tipos de trecho. O clipe
(a parte cara, desenhada no navegador) fica em cache por conteúdo no `PersonaStage`; o mezanino só o junta ao fundo.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.spec import PersonaBackground, PersonaSegment, Segment
from ..domain.timeline import persona_segment_duration
from ..filtergraph.persona import Backdrop, persona_mezzanine
from ..media.matting import hex_to_rgb, tone_of
from .cache_key import cache_key
from .context import RenderContext
from .persona_render import PersonaStage
from .segments import (
    DEFAULT_PREPARERS,
    MEZZ_VERSION,
    PreparedSegment,
    _label,
    _look_part,
    _needs_render,
    segment_look,
)
from .sources import Source

DEFAULT_BACKGROUND_COLOR = "#D9E4F2"  # um azul claro e neutro: a persona aparece bem sobre ele


def persona_stage(ctx: RenderContext) -> PersonaStage:
    """O serviço de personas do render; quem monta o contexto sem ele (o quadro de um instante) ganha o padrão."""
    if ctx.personas is None:
        ctx.personas = PersonaStage()
    return ctx.personas


def backdrop_of(background: PersonaBackground, ctx: RenderContext) -> Backdrop:
    """O fundo da spec como o filtro o lê: o caminho do arquivo resolvido ou a cor (chave da marca ou #RRGGBB)."""
    if background.image:
        return Backdrop("image", str(ctx.project.resolve(background.image)))
    if background.clip:
        return Backdrop("clip", str(ctx.project.resolve(background.clip)), background.clip_start)
    return Backdrop.color(ctx.theme.color(background.color, DEFAULT_BACKGROUND_COLOR))


def _backdrop_identity(backdrop: Backdrop) -> tuple:
    """Quem entra na chave do mezanino: a cor, ou o arquivo e a data dele (trocar a imagem renderiza de novo)."""
    if backdrop.kind == "color":
        return (backdrop.kind, backdrop.value)
    try:
        stat = Path(backdrop.value).stat()
        return (backdrop.kind, backdrop.value, stat.st_size, stat.st_mtime_ns, backdrop.start)
    except OSError:
        return (backdrop.kind, backdrop.value, None, backdrop.start)


class PersonaPreparer:
    """Persona falando em tela cheia: fundo + clipe do motor + fala."""

    def prepare(self, index: int, segment: Segment, source: Source, ctx: RenderContext) -> PreparedSegment:
        assert isinstance(segment, PersonaSegment)
        stage = persona_stage(ctx)
        persona = stage.library.get(segment.persona)
        line = stage.line_for(ctx, persona, segment.speech)
        duration = persona_segment_duration(segment, source.info)
        size = (ctx.width, ctx.height)
        clip, alpha = stage.clip_for(ctx, persona, line, segment.expression, segment.marks, duration, size)
        backdrop = backdrop_of(segment.background, ctx) if alpha else None
        look = segment_look(index, segment, ctx)
        speech_file = line.path
        stat = speech_file.stat() if speech_file is not None and speech_file.exists() else None
        key = cache_key(
            MEZZ_VERSION,
            "persona",
            segment.model_dump(mode="json"),
            _look_part(look),
            clip.name,  # o nome carrega a chave do clipe (persona, boca, marcas, tamanho, versão do motor)
            str(speech_file) if speech_file else None,
            (stat.st_size, stat.st_mtime_ns) if stat else None,
            _backdrop_identity(backdrop) if backdrop else None,
            round(duration, 6),
            ctx.width,
            ctx.height,
            ctx.fps,
        )
        out = ctx.cache_dir / f"{key}.mov"
        command = persona_mezzanine(
            clip,
            speech_file,
            backdrop,
            duration,
            size,
            ctx.fps,
            out,
            color=segment.color,
            look=look,
            fade_in=segment.fade_in,
            fade_out=segment.fade_out,
            label=_label(index, ctx),
        )
        tone = None
        if backdrop is not None and backdrop.kind == "color":
            tone = tone_of(hex_to_rgb(backdrop.value))
        return PreparedSegment(
            index, segment, duration, out, tone, command if _needs_render(out, ctx) else None
        )


DEFAULT_PREPARERS[PersonaSegment] = PersonaPreparer()
