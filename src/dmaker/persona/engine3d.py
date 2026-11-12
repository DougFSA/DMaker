"""O motor da persona 3D: um personagem em glTF animado pelo TalkingHead e desenhado no Chromium da composição HTML.

A página (`assets/html/persona/3d/index.html`) leva o TalkingHead no modo `avatarOnly` ao instante pedido, em passos
fixos de 1/fps, e liga cada visema da linha do tempo em Python (a mesma do motor 2D) ao blendshape do avatar. O motor
só monta os dados (função pura), confere o avatar e entrega os quadros ao ffmpeg pelo caminho comum dos motores HTML.

O personagem padrão (`mpfb`, CC0) é um modelo baixável em `cache/models` e não vai no git; uma persona pode trazer
o próprio `.glb` na pasta dela, desde que tenha o esqueleto do Mixamo e os visemas Oculus.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .. import config
from ..media.ffmpeg import FFmpegRunner
from ..media.html_render import HtmlComposition, HtmlRenderer, PlaywrightHtmlRenderer
from .engine import PersonaEngine, PersonaEngineError, PersonaRender, register_engine
from .glb import avatar_problems
from .html_clip import page_digest, render_html_clip
from .marks import expression_track, gesture_track

ENGINE_VERSION = "p3d3"  # muda quando o desenho da página ou o jeito de montar os dados muda
EXPRESSIONS = ("neutral", "happy", "sad", "surprised")
# Os gestos de mão do TalkingHead que não dependem de arquivo Mixamo, mais o aceno e a negação com a cabeça.
# `wave` e `tilt` também existem no motor 2D: assim a spec de uma persona 2D vale ao trocá-la por uma 3D.
GESTURES = ("nod", "shake", "tilt", "wave", "handup", "index", "ok", "thumbup", "thumbdown", "side", "shrug")
# O desenho por software (SwiftShader) custa por pixel: acima deste lado maior o quadro é desenhado num tamanho menor
# (a página mantém o mesmo enquadramento) e ampliado pelo ffmpeg, para a tela cheia não levar dezenas de minutos.
MAX_DRAWN_SIDE = 960
BUILTIN_MODEL = "mpfb"
BUILTIN_MODEL_ID = "persona3d-mpfb"  # o id no registro de modelos (`dmaker models`)
BUILTIN_MODEL_FILE = "persona3d/mpfb.glb"  # dentro de `cache/models`
MODEL_URL_NAME = "avatar.glb"  # o nome com que a página enxerga o arquivo (`/_dmaker/files/<nome>`)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_FILE_NAME = re.compile(r"^\w[\w .-]*\.glb$", re.IGNORECASE)


class Appearance3D(BaseModel):
    """A aparência da persona 3D: o personagem pronto (`mpfb`) ou o nome de um `.glb` na pasta da persona."""

    model_config = ConfigDict(extra="forbid")

    model: str = BUILTIN_MODEL
    # A roupa do personagem pronto é lisa nesta cor (a textura dele traz um logotipo de terceiro). Vale para o
    # modelo pronto; um `.glb` próprio traz a roupa dele.
    outfit_color: str = "#3A4A5E"

    @field_validator("outfit_color")
    @classmethod
    def _hex_color(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError(f"{value!r} não é uma cor; use o formato #RRGGBB (ex.: #3A4A5E)")
        return value.upper()

    @field_validator("model")
    @classmethod
    def _model_name(cls, value: str) -> str:
        if value == BUILTIN_MODEL:
            return value
        if not _FILE_NAME.match(value) or ".." in value:
            raise ValueError(
                f"{value!r} não é um modelo; use `{BUILTIN_MODEL}` (o personagem pronto) ou o nome de um arquivo "
                ".glb que está na pasta da persona (ex.: meu-personagem.glb)"
            )
        return value


def builtin_model_path() -> Path:
    return config.MODELS_DIR / BUILTIN_MODEL_FILE


def download_hint() -> str:
    return (
        "O personagem da persona 3D ainda não foi baixado (36,8 MB, licença CC0). "
        f"Baixe com `dmaker models download {BUILTIN_MODEL_ID}` e tente de novo."
    )


def doctor_line() -> str:
    """A linha do `dmaker doctor` sobre o personagem 3D: opcional, baixado ou não, e o comando que baixa."""
    if builtin_model_path().is_file():
        return "personagem da persona 3D (opcional): baixado"
    return (
        "personagem da persona 3D (opcional): não baixado; só é preciso para personas 3D "
        f"(dmaker models download {BUILTIN_MODEL_ID})"
    )


def draw_scale(size: tuple[int, int]) -> float:
    """A escala em que a página é desenhada: 1 até `MAX_DRAWN_SIDE` no lado maior, menos que isso acima dele."""
    return min(1.0, MAX_DRAWN_SIDE / max(size))


def view_for(framing: str) -> str:
    """O enquadramento da página: meio corpo na tela cheia, cabeça e ombros na sobreposição do canto."""
    return "corner" if framing == "corner" else "full"


def page_data(request: PersonaRender, outfit_color: str = "#3A4A5E") -> dict[str, Any]:
    """Os dados que a página lê em `dmaker.data` (função pura: o mesmo pedido dá sempre os mesmos dados)."""
    return {
        "model": f"/_dmaker/files/{MODEL_URL_NAME}",
        "view": view_for(request.framing),
        "outfit": outfit_color,
        "fps": request.fps,
        "visemes": [[round(span.start, 4), round(span.end, 4), span.viseme] for span in request.visemes],
        "expressions": [
            [round(at, 4), name] for at, name in expression_track(request.expression, request.marks)
        ],
        "gestures": [[round(at, 4), name] for at, name in gesture_track(request.marks)],
    }


class Engine3D:
    kind = "3d"
    version = ENGINE_VERSION
    produces_alpha = True
    expressions = EXPRESSIONS
    gestures = GESTURES

    def __init__(self, renderer: HtmlRenderer | None = None, page_dir: Path | None = None) -> None:
        self._renderer = renderer
        self._page_dir = page_dir

    @property
    def page_dir(self) -> Path:
        return self._page_dir or config.PERSONA_PAGES_DIR / "3d"

    def _html(self) -> HtmlRenderer:
        if self._renderer is None:
            self._renderer = PlaywrightHtmlRenderer()
        return self._renderer

    def normalize_appearance(self, appearance: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return Appearance3D.model_validate(dict(appearance)).model_dump()
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            raise PersonaEngineError(f"Aparência 3D inválida: {problems}") from exc

    def model_file(self, request: PersonaRender) -> Path:
        """O `.glb` da persona (o pronto em `cache/models` ou o da pasta dela), conferido; levanta o que falta."""
        model = self.normalize_appearance(request.persona.appearance)["model"]
        if model == BUILTIN_MODEL:
            path = builtin_model_path()
            if not path.is_file():
                raise PersonaEngineError(download_hint())
        else:
            folder = request.persona.folder
            path = (folder / model) if folder is not None else None
            if path is None or not path.is_file():
                raise PersonaEngineError(
                    f"O modelo {model!r} da persona {request.persona.name!r} não está na pasta dela; "
                    "coloque o arquivo .glb ao lado do persona.json."
                )
        problems = avatar_problems(path)
        if problems:
            raise PersonaEngineError(" ".join(problems))
        return path

    def cache_parts(self, request: PersonaRender) -> tuple[Any, ...]:
        """O conteúdo da página e o modelo entram na chave. O `.glb` próprio já entra pela impressão da persona;
        o pronto (que mora fora da pasta dela) entra pelo tamanho, que o download confere por hash."""
        path = builtin_model_path()
        model = self.normalize_appearance(request.persona.appearance)["model"]
        shipped = path.stat().st_size if model == BUILTIN_MODEL and path.is_file() else None
        return (page_digest(self.page_dir), model, shipped)

    def unavailable_reason(self) -> str | None:
        return self._html().unavailable_reason() or (
            None if builtin_model_path().is_file() else download_hint()
        )

    def _composition(self, request: PersonaRender) -> HtmlComposition:
        model = self.model_file(request)
        return HtmlComposition(
            source=self.page_dir,
            size=request.size,
            scale=draw_scale(request.size),
            fps=request.fps,
            duration=request.duration,
            data=page_data(request, self.normalize_appearance(request.persona.appearance)["outfit_color"]),
            files={MODEL_URL_NAME: model},
        )

    def render(
        self, request: PersonaRender, out: Path, runner: FFmpegRunner, on_warning: Callable[[str], None]
    ) -> None:
        render_html_clip(self._html(), self._composition(request), request, out, runner, on_warning)

    def still(self, request: PersonaRender, at: float, on_warning: Callable[[str], None]) -> bytes:
        return self._html().still(self._composition(request), at, on_warning)


_ENGINE: PersonaEngine = register_engine(Engine3D())
