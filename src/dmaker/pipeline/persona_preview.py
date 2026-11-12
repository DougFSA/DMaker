"""A prévia de uma persona falando: um vídeo curto de uma frase, no mesmo render do projeto (e no mesmo cache).

Não há um segundo caminho de desenho: a prévia é um projeto de um trecho `persona` de tela cheia, renderizado em baixa
resolução. O clipe da persona e a voz ficam em cache por conteúdo, então repetir a mesma frase não desenha nada de novo.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import config
from ..domain.spec import Project
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..persona.library import PersonaLibrary
from .context import RenderOptions, RenderResult

DEFAULT_PHRASE = "Olá! Eu sou a sua persona e este é o meu jeito de falar."
MAX_PHRASE_CHARS = 200  # uma frase só: a prévia existe para ver a boca e o jeito, não para narrar um vídeo
PREVIEW_PRESET = "instagram/reels"
PREVIEW_TAIL_SECONDS = 0.3


def preview_project_name(persona_id: str) -> str:
    return f"persona-previa-{persona_id}"


def preview_project(persona_id: str, phrase: str, base_dir: Path) -> Project:
    """O projeto de um trecho só, com a persona falando a frase (função pura: não toca o disco)."""
    text = phrase.strip() or DEFAULT_PHRASE
    if len(text) > MAX_PHRASE_CHARS:
        raise ValueError(f"A frase da prévia tem no máximo {MAX_PHRASE_CHARS} caracteres.")
    project = Project.model_validate(
        {
            "name": preview_project_name(persona_id),
            "output": {"preset": PREVIEW_PRESET},
            "timeline": [
                {
                    "type": "persona",
                    "persona": persona_id,
                    "speech": {"text": text},
                    "tail": PREVIEW_TAIL_SECONDS,
                }
            ],
            "audio": {"normalize": "off"},
        }
    )
    project.base_dir = base_dir
    return project


def render_persona_preview(
    persona_id: str,
    phrase: str = "",
    *,
    library: PersonaLibrary | None = None,
    runner: FFmpegRunner | None = None,
    log: Callable[[str], None] | None = None,
    **dependencies: Any,
) -> RenderResult:
    """Renderiza a prévia e devolve o resultado. Levanta o erro do motor (modelo 3D que falta, por exemplo) com a
    mensagem em português."""
    from . import RenderPipeline
    from .persona_render import PersonaStage

    library = library or PersonaLibrary()
    library.get(persona_id)  # persona que não existe: a mensagem lista as que existem
    base_dir = config.JOBS_DIR / preview_project_name(persona_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    project = preview_project(persona_id, phrase, base_dir)
    options = RenderOptions(preview=True, quiet=True, no_captions=True, out=base_dir / "previa.mp4")
    pipeline = RenderPipeline(
        project,
        options,
        runner=runner or SubprocessRunner(quiet=True),
        log=log,
        personas=PersonaStage(library),
        **dependencies,
    )
    return pipeline.run()
