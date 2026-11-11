"""Exportar o áudio de um projeto: a porta de entrada que a CLI, o MCP e a interface compartilham.

Junta o pedido (formato, modo, trechos, loudness, opções de codificação) num `ExportRequest` e numa
`AudioRenderPipeline`, e devolve o resultado como dado simples. Não decide nada de áudio: isso é do render
(`audio_render.py`) e da exportação (`audio_export.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import config
from ..domain.audio_export import EXPORT_MODES, ExportRequest
from ..domain.audio_presets import EncodingChoices, get_audio_preset, is_audio_preset
from ..domain.loudness import parse_loudness_target
from ..domain.spec import Project
from .audio_export import AudioExporter, ExportResult, destinations
from .audio_render import AudioRenderPipeline, encoding_for
from .context import RenderOptions
from .projects import load_project


def export_request(
    mode: str = "mix",
    *,
    group: str | None = None,
    pauses: bool = False,
    numbered: bool = False,
    start: float | str | None = None,
    end: float | str | None = None,
    tracks: list[str] | None = None,
) -> ExportRequest:
    """O pedido de exportação, com o modo conferido (erro claro em português para um modo que não existe)."""
    if mode not in EXPORT_MODES:
        raise ValueError(f"modo de exportação desconhecido: {mode!r} (use {', '.join(EXPORT_MODES)})")
    return ExportRequest(mode, group, pauses, numbered, start, end, tuple(tracks or ()))  # type: ignore[arg-type]


def project_with_loudness(project: Project, loudness: str | float | None) -> Project:
    """O projeto com o alvo de loudness do pedido (`podcast`, `-16`...) no lugar de `audio.target_lufs`."""
    if loudness is None:
        return project
    target = parse_loudness_target(loudness)
    changed = project.model_copy(update={"audio": project.audio.model_copy(update={"target_lufs": target})})
    changed.base_dir = project.base_dir
    return changed


def audio_preset_name(project: Project, preset: str | None) -> str:
    """O preset de áudio do pedido, ou o da spec quando ela já é de áudio; senão, erro dizendo o que falta."""
    chosen = preset or project.output.preset
    if not is_audio_preset(chosen):
        raise ValueError(
            "informe o formato do arquivo (preset: audio/mp3, audio/wav, audio/flac, audio/ogg, audio/opus, "
            f"audio/m4a ou audio/aiff): o preset do projeto ({project.output.preset}) é de vídeo"
        )
    return get_audio_preset(chosen).id


def build_pipeline(
    project: Project,
    preset: str | None,
    *,
    loudness: str | float | None = None,
    choices: EncodingChoices | None = None,
    options: RenderOptions | None = None,
    **dependencies: Any,
) -> AudioRenderPipeline:
    """A `AudioRenderPipeline` do pedido: o preset de áudio e o alvo de loudness do pedido já aplicados."""
    chosen = audio_preset_name(project, preset)
    options = options or RenderOptions(quiet=True)
    options.preset = chosen
    return AudioRenderPipeline(
        project_with_loudness(project, loudness), options, overrides=choices, **dependencies
    )


def export_audio_project(
    name_or_path: str | Path,
    request: ExportRequest,
    *,
    preset: str | None = None,
    out: Path | str | None = None,
    out_dir: Path | str | None = None,
    loudness: str | float | None = None,
    choices: EncodingChoices | None = None,
    options: RenderOptions | None = None,
    **dependencies: Any,
) -> ExportResult:
    """Carrega o projeto e exporta o áudio dele como o pedido manda."""
    project = load_project(name_or_path)
    pipeline = build_pipeline(
        project, preset, loudness=loudness, choices=choices, options=options, **dependencies
    )
    return AudioExporter(pipeline).run(request, out=out, out_dir=out_dir)


def planned_outputs(
    name_or_path: str | Path,
    request: ExportRequest,
    *,
    preset: str | None = None,
    out: Path | str | None = None,
    out_dir: Path | str | None = None,
    output_dir: Path | None = None,
    loader: Callable[[str | Path], Project] = load_project,
) -> list[Path]:
    """Os arquivos que o pedido gravaria, sem renderizar nada: é o que o agente confere antes de sobrescrever."""
    project = loader(name_or_path)
    audio = get_audio_preset(audio_preset_name(project, preset))
    planned, _ = destinations(
        project, request, audio, out=out, out_dir=out_dir, output_dir=output_dir or config.OUTPUT_DIR
    )
    return [path for _, path in planned]


def result_dict(result: ExportResult) -> dict:
    """O resultado como dado simples (MCP, interface): os arquivos com tempo, trilha e tamanho, e os avisos."""
    return {
        "mode": result.mode,
        "preset": result.preset.id,
        "folder": str(result.folder) if result.folder else None,
        "files": [
            {
                "path": str(item.path),
                "name": item.name,
                "kind": item.kind,
                "start_s": round(item.start, 3),
                "duration_s": round(item.duration, 3),
                "track": item.track,
                "size_mb": round(item.path.stat().st_size / 1e6, 3) if item.path.exists() else 0,
            }
            for item in result.files
        ],
        "warnings": result.warnings,
    }


__all__ = [
    "audio_preset_name",
    "build_pipeline",
    "encoding_for",
    "export_audio_project",
    "export_request",
    "planned_outputs",
    "project_with_loudness",
    "result_dict",
]
