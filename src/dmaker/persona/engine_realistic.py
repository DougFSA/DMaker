"""O motor da persona realista: uma foto e a fala dela viram um vídeo da pessoa falando (ditto-talkinghead).

Diferente do 2D e do 3D, o rosto não é desenhado a partir de visemas: o ditto escuta o áudio da fala e anima a
própria foto, então o pedido leva o arquivo de áudio (`PersonaRender.audio`) e a boca da linha do tempo não é usada.
O clipe sai opaco (a foto traz o fundo dela). A foto é enquadrada aqui, no formato do vídeo, antes de ir ao ditto;
quem desenha, e roda num subprocesso, é a implementação injetada de `TalkingHead` (`media/talking_head.py`).

A foto é um arquivo na pasta da persona. Expressões e gestos não existem neste tipo: o ditto só anima a fala.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .. import config
from ..filtergraph.persona import realistic_clip_command
from ..media.ditto_models import MODEL_ID, REVISION, paths_in
from ..media.ffmpeg import FFmpegError, FFmpegRunner
from ..media.talking_head import (
    DEFAULT_SEED,
    DEFAULT_STEPS,
    TALKING_HEAD_FPS,
    DittoTalkingHead,
    TalkingHead,
    TalkingHeadError,
    TalkingHeadRequest,
    estimate_seconds,
    format_duration,
)
from .engine import PersonaEngine, PersonaEngineError, PersonaRender, register_engine
from .html_clip import FrameStream
from .portrait import FaceFinder, PhotoError, PreparedPhoto, blaze_face_finder, prepare_photo

ENGINE_VERSION = "pr1"  # muda quando o jeito de enquadrar a foto ou de montar o clipe muda
EXPRESSIONS = ("neutral",)
GESTURES: tuple[str, ...] = ()
EXTRA_NAME = "persona-realista"  # o extra do pip (`pip install -e .[persona-realista]`)
# Os módulos que o subprocesso importa: se um falta, o render falharia só depois do preparo.
REQUIRED_MODULES = ("cv2", "openvino", "onnxruntime", "torch", "scipy", "librosa")
_PHOTO_NAME = re.compile(r"^\w[\w .-]*\.(jpe?g|png)$", re.IGNORECASE)
MIN_STEPS, MAX_STEPS = 5, 50
STILL_NOTICE = (
    "Este quadro é a foto enquadrada, parada: a boca da persona realista só se mexe no render do vídeo."
)


class AppearanceRealistic(BaseModel):
    """A aparência da persona realista: o arquivo da foto (na pasta da persona) e os passos da difusão."""

    model_config = ConfigDict(extra="forbid")

    photo: str
    steps: int = DEFAULT_STEPS

    @field_validator("photo")
    @classmethod
    def _photo_name(cls, value: str) -> str:
        if not _PHOTO_NAME.match(value) or ".." in value:
            raise ValueError(
                f"{value!r} não é uma foto; use o nome de um arquivo .jpg ou .png que está na pasta da persona"
            )
        return value

    @field_validator("steps")
    @classmethod
    def _steps_range(cls, value: int) -> int:
        if not MIN_STEPS <= value <= MAX_STEPS:
            raise ValueError(f"steps deve ficar entre {MIN_STEPS} e {MAX_STEPS} (o padrão é {DEFAULT_STEPS})")
        return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def missing_packages() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def install_hint() -> str:
    return f"Instale os pacotes da persona realista com `pip install -e .[{EXTRA_NAME}]`."


def download_hint() -> str:
    return (
        "Os modelos da persona realista (2,3 GB, Apache-2.0) ainda não foram baixados. "
        f"Baixe com `dmaker models download {MODEL_ID}` e tente de novo."
    )


def doctor_line(head: TalkingHead | None = None, models_dir: Path | None = None) -> str:
    """A linha do `dmaker doctor` sobre o motor realista: pacotes, modelos e se há GPU integrada."""
    missing = missing_packages()
    if missing:
        return (
            f"persona realista (opcional): faltam os pacotes {', '.join(missing)} "
            f"(pip install -e .[{EXTRA_NAME}])"
        )
    absent = paths_in(models_dir or config.MODELS_DIR).missing_files()
    if absent:
        return f"persona realista (opcional): modelos não baixados (dmaker models download {MODEL_ID})"
    gpu = (head or DittoTalkingHead()).has_gpu()
    where = "com GPU integrada (OpenVINO)" if gpu else "sem GPU integrada: só CPU, bem mais lento"
    return f"persona realista (opcional): pronta, {where}"


class RealisticEngine:
    kind = "realistic"
    version = ENGINE_VERSION
    produces_alpha = False
    reports_progress = True  # `render` aceita `on_log` (veja o protocolo em engine.py)
    expressions = EXPRESSIONS
    gestures = GESTURES

    def __init__(
        self,
        head: TalkingHead | None = None,
        face_finder: FaceFinder | None = None,
        models_dir: Path | None = None,
    ) -> None:
        self._head = head
        self._face_finder = face_finder
        self._models_dir = models_dir

    @property
    def head(self) -> TalkingHead:
        if self._head is None:
            self._head = DittoTalkingHead(self._models_dir)
        return self._head

    @property
    def models_dir(self) -> Path:
        return self._models_dir or config.MODELS_DIR

    def _finder(self) -> FaceFinder:
        if self._face_finder is None:
            self._face_finder = blaze_face_finder(paths_in(self.models_dir).face_detector)
        return self._face_finder

    # ---------- o contrato do motor ----------

    def normalize_appearance(self, appearance: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return AppearanceRealistic.model_validate(dict(appearance)).model_dump()
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            raise PersonaEngineError(f"Aparência realista inválida: {problems}") from exc

    def photo_file(self, request: PersonaRender) -> Path:
        """A foto da persona, na pasta dela; levanta o que falta."""
        name = self.normalize_appearance(request.persona.appearance)["photo"]
        folder = request.persona.folder
        path = folder / name if folder is not None else None
        if path is None or not path.is_file():
            raise PersonaEngineError(
                f"A foto {name!r} da persona {request.persona.name!r} não está na pasta dela; "
                "recrie a persona com `dmaker persona create ... --kind realistic --photo <arquivo>`."
            )
        return path

    def _steps(self, request: PersonaRender) -> int:
        return self.normalize_appearance(request.persona.appearance)["steps"]

    @staticmethod
    def _seed(request: PersonaRender) -> int:
        return DEFAULT_SEED if request.seed is None else request.seed

    def cache_parts(self, request: PersonaRender) -> tuple[Any, ...]:
        """O conteúdo que decide o vídeo: a foto e o áudio (por hash, o mesmo conteúdo dá o mesmo clipe), a revisão
        dos modelos, os passos da difusão e a semente."""
        audio = _sha256(request.audio) if request.audio is not None and request.audio.is_file() else None
        return (
            _sha256(self.photo_file(request)),
            audio,
            REVISION,
            self._steps(request),
            self._seed(request),
        )

    def unavailable_reason(self) -> str | None:
        missing = missing_packages()
        if missing:
            return f"Faltam pacotes para a persona realista ({', '.join(missing)}). {install_hint()}"
        if paths_in(self.models_dir).missing_files():
            return download_hint()
        return None

    def forecast(self, request: PersonaRender) -> str:
        """O que o log do render diz antes de começar o clipe: quanto deve levar (estimativa medida), e onde."""
        gpu = self.head.has_gpu()
        where = "na GPU integrada" if gpu else "na CPU (sem GPU integrada, bem mais lento)"
        return f"estimativa de {format_duration(estimate_seconds(request.duration, gpu))} {where}"

    # ---------- o desenho ----------

    def _prepare(self, request: PersonaRender, on_warning: Callable[[str], None]) -> PreparedPhoto:
        try:
            prepared = prepare_photo(self.photo_file(request), request.size, request.framing, self._finder())
        except PhotoError as exc:
            raise PersonaEngineError(str(exc)) from exc
        for warning in prepared.warnings:
            on_warning(warning)
        return prepared

    def render(
        self,
        request: PersonaRender,
        out: Path,
        runner: FFmpegRunner,
        on_warning: Callable[[str], None],
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        import cv2

        reason = self.unavailable_reason()
        if reason:
            raise PersonaEngineError(reason)
        if request.audio is None or not request.audio.is_file():
            raise PersonaEngineError(
                f"A persona realista {request.persona.name!r} precisa do áudio da fala para se mexer, e ele não "
                "existe neste render (a simulação, `--dry-run`, não gera o clipe)."
            )
        log = on_log or (lambda _: None)
        prepared = self._prepare(request, on_warning)
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name(f"{out.stem}.part{out.suffix}")
        with tempfile.TemporaryDirectory(prefix="photo_", dir=out.parent) as folder:
            photo = Path(folder) / "foto.png"
            cv2.imwrite(str(photo), cv2.cvtColor(prepared.image, cv2.COLOR_RGB2BGR))
            ask = TalkingHeadRequest(
                photo=photo,
                audio=request.audio,
                duration=request.duration,
                size=request.size,
                seed=self._seed(request),
                steps=self._steps(request),
            )
            stream = FrameStream(self.head.frames(ask, log, on_warning))
            command = realistic_clip_command(
                stream,
                request.size,
                TALKING_HEAD_FPS,
                request.fps,
                request.duration,
                partial,
                label=f"persona {request.persona.id}",
            )
            try:
                try:
                    runner.run(command)
                except FFmpegError:
                    if stream.error is not None:
                        raise self._failure(stream.error) from stream.error
                    raise
                if stream.error is not None:
                    raise self._failure(stream.error) from stream.error
                partial.replace(out)
            finally:
                partial.unlink(missing_ok=True)

    @staticmethod
    def _failure(error: Exception) -> PersonaEngineError:
        if isinstance(error, TalkingHeadError):
            return PersonaEngineError(f"A persona realista falhou: {error}")
        return PersonaEngineError(f"A persona realista parou no meio do desenho: {error}")

    def still(self, request: PersonaRender, at: float, on_warning: Callable[[str], None]) -> bytes:
        import cv2

        prepared = self._prepare(request, on_warning)
        on_warning(STILL_NOTICE)
        ok, png = cv2.imencode(".png", cv2.cvtColor(np.ascontiguousarray(prepared.image), cv2.COLOR_RGB2BGR))
        if not ok:
            raise PersonaEngineError("Não consegui gerar o quadro da persona realista.")
        return png.tobytes()


_ENGINE: PersonaEngine = register_engine(RealisticEngine())
