"""O motor da persona ilustrada 2D: um personagem em SVG desenhado quadro a quadro no Chromium da composição HTML.

A página (`assets/html/persona/2d/index.html`) recebe a persona, a boca e as marcas como dados e desenha cada
instante a partir de `dmakerSeek(t)`. O motor só monta esses dados (função pura) e entrega os quadros ao ffmpeg
pelo mesmo caminho das composições em HTML: não há um segundo jeito de capturar quadros.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .. import config
from ..media.ffmpeg import FFmpegRunner
from ..media.html_render import HtmlComposition, HtmlRenderer, PlaywrightHtmlRenderer
from .engine import PersonaEngine, PersonaEngineError, PersonaRender, register_engine
from .html_clip import page_digest, render_html_clip
from .marks import expression_track, gesture_track
from .mouth import mouth_timeline

ENGINE_VERSION = "p1"  # muda quando o desenho da página ou o jeito de montar os dados muda
EXPRESSIONS = ("neutral", "happy", "sad", "surprised")
GESTURES = ("nod", "shake", "tilt", "wave")
HAIR_STYLES = ("short", "long", "bun")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class Appearance2D(BaseModel):
    """A aparência da persona ilustrada: cores em `#RRGGBB` e um entre os estilos de cabelo."""

    model_config = ConfigDict(extra="forbid")

    skin: str = "#E8B796"
    hair_color: str = "#3B2A20"
    hair_style: Literal["short", "long", "bun"] = "short"
    eye_color: str = "#4A7BA7"
    outfit_color: str = "#2F6FDE"

    @field_validator("skin", "hair_color", "eye_color", "outfit_color")
    @classmethod
    def _hex_color(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError(f"{value!r} não é uma cor; use o formato #RRGGBB (ex.: #E8B796)")
        return value.upper()


def page_data(request: PersonaRender, appearance: Mapping[str, Any]) -> dict[str, Any]:
    """Os dados que a página lê em `dmaker.data` (função pura: o mesmo pedido dá sempre os mesmos dados)."""
    return {
        "appearance": dict(appearance),
        "mouth": [[round(a, 4), round(b, 4), shape] for a, b, shape in mouth_timeline(request.visemes)],
        "expressions": [
            [round(at, 4), name] for at, name in expression_track(request.expression, request.marks)
        ],
        "gestures": [[round(at, 4), name] for at, name in gesture_track(request.marks)],
    }


class Engine2D:
    kind = "2d"
    version = ENGINE_VERSION
    produces_alpha = True
    expressions = EXPRESSIONS
    gestures = GESTURES

    def __init__(self, renderer: HtmlRenderer | None = None, page_dir: Path | None = None) -> None:
        self._renderer = renderer
        self._page_dir = page_dir

    @property
    def page_dir(self) -> Path:
        return self._page_dir or config.PERSONA_PAGES_DIR / "2d"

    def _html(self) -> HtmlRenderer:
        if self._renderer is None:
            self._renderer = PlaywrightHtmlRenderer()
        return self._renderer

    def normalize_appearance(self, appearance: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return Appearance2D.model_validate(dict(appearance)).model_dump()
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            raise PersonaEngineError(f"Aparência 2D inválida: {problems}") from exc

    def cache_parts(self, request: PersonaRender) -> tuple[Any, ...]:
        """O conteúdo da página entra na chave: mexer no desenho invalida os clipes sem precisar mudar a versão."""
        return (page_digest(self.page_dir),)

    def unavailable_reason(self) -> str | None:
        return self._html().unavailable_reason()

    def render(
        self, request: PersonaRender, out: Path, runner: FFmpegRunner, on_warning: Callable[[str], None]
    ) -> None:
        appearance = self.normalize_appearance(request.persona.appearance)
        composition = HtmlComposition(
            source=self.page_dir,
            size=request.size,
            scale=1.0,
            fps=request.fps,
            duration=request.duration,
            data=page_data(request, appearance),
        )
        render_html_clip(self._html(), composition, request, out, runner, on_warning)


_ENGINE: PersonaEngine = register_engine(Engine2D())
