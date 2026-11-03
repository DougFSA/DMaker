"""Pipeline de renderização e serviços de projeto."""

# registra o renderizador de áudio (`audio/mp3`...) ao lado do de vídeo
from . import audio_render as _audio_render  # noqa: F401, I001
from .context import RenderContext, RenderOptions, RenderResult
from .output_kinds import create_renderer
from .projects import load_project, project_path, quick_project, save_project, scaffold_project, summarize
from .qa import contact_sheet, frame_at
from .renderer import RenderPipeline

__all__ = [
    "RenderContext",
    "RenderOptions",
    "RenderPipeline",
    "RenderResult",
    "contact_sheet",
    "create_renderer",
    "frame_at",
    "load_project",
    "project_path",
    "quick_project",
    "save_project",
    "scaffold_project",
    "summarize",
]
