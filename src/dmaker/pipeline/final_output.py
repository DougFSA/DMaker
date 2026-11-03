"""A última saída final (não prévia) já renderizada de um projeto, para o QA e as análises lerem o arquivo pronto."""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..domain.outputs import output_extension, resolve_output
from ..domain.spec import Project


def latest_final_output(project: Project) -> Path | None:
    """O arquivo mais recente que o render final do preset da spec gravou em `output/`, se houver."""
    if not config.OUTPUT_DIR.exists():
        return None
    preset = resolve_output(project.output.preset)
    files = sorted(
        config.OUTPUT_DIR.glob(f"{project.name}__{preset.id.replace('/', '-')}{output_extension(preset)}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None
