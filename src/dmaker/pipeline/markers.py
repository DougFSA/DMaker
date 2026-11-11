"""Serviços dos marcadores usados pela CLI e pelo servidor MCP: importar e exportar o `.txt` do Audacity e gerar
marcadores regulares. A lógica é pura (`domain/audacity_labels.py`, `domain/markers.py`); aqui só se lê e se grava."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .. import config
from ..domain.audacity_labels import format_labels, parse_labels
from ..domain.markers import MarkerError, regular_markers
from ..domain.spec import Marker, Project
from ..media.probe import probe
from .context import Prober
from .edit_history import EditHistory
from .layout import project_layout, to_presentation
from .projects import load_project, project_path, save_project

NewlineChoice = Literal["auto", "lf", "crlf"]
NEWLINES = {"lf": "\n", "crlf": "\r\n"}


@dataclass(frozen=True)
class MarkersResult:
    """O que importar ou gerar fez: o projeto salvo, quantos marcadores entraram e os avisos para a pessoa."""

    project: Project
    added: int
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarkersExport:
    path: Path
    count: int


def default_export_path(project_name: str) -> Path:
    """Onde `export_labels` grava sem `out`: o nome do projeto na pasta de saída. O gate do agente usa esta mesma
    conta para perguntar antes de sobrescrever um arquivo que já existe."""
    return config.OUTPUT_DIR / f"{project_name}-marcadores.txt"


def newline_text(choice: NewlineChoice) -> str:
    """A quebra de linha do arquivo: `auto` é a do sistema (o Audacity grava assim), as outras fixam uma."""
    if choice == "auto":
        return os.linesep
    if choice not in NEWLINES:
        raise MarkerError(f"quebra de linha desconhecida: {choice!r} (use auto, lf ou crlf)")
    return NEWLINES[choice]


def read_labels_file(file: Path) -> str:
    if not file.exists():
        raise FileNotFoundError(f"Arquivo de marcadores não encontrado: {file}")
    try:
        return file.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MarkerError(
            f"{file.name} não está em UTF-8 (o Audacity grava assim); salve-o em UTF-8"
        ) from exc


def _record(before: Project, after: Project, name_or_path: str | Path, label: str) -> None:
    """Guarda o estado de antes no histórico de edições (`undo_edit` desfaz a importação ou os marcadores regulares)."""
    spec_path = project_path(name_or_path)
    EditHistory(before.base_dir or spec_path.parent, spec_path=spec_path).record(before, after, label)


def import_labels(
    name_or_path: str | Path, file: Path, group: str = "", replace: bool = False
) -> MarkersResult:
    """Lê o `.txt` do Audacity e põe os marcadores no projeto, no `group` dado. Com `replace`, os que o grupo já
    tinha saem antes (importar o mesmo arquivo de novo não duplica); sem ele, os novos vão para o fim."""
    project = load_project(name_or_path)
    parsed = parse_labels(read_labels_file(file), group.strip())
    kept = [marker for marker in project.markers if not (replace and marker.group == group.strip())]
    updated = project.model_copy(update={"markers": [*kept, *parsed.markers]})
    _record(project, updated, name_or_path, f"Importar marcadores de {file.name}")
    save_project(updated, project_path(name_or_path).parent)
    return MarkersResult(updated, len(parsed.markers), parsed.warnings)


def export_labels(
    name_or_path: str | Path,
    out: Path | None = None,
    group: str | None = None,
    newline: NewlineChoice = "auto",
) -> MarkersExport:
    """Grava os marcadores do projeto (de um grupo, ou todos) no formato do Audacity. Sem `out`, o arquivo vai para
    `output/<projeto>-marcadores.txt`."""
    project = load_project(name_or_path)
    chosen = [marker for marker in project.markers if group is None or marker.group == group.strip()]
    if not chosen:
        which = "o projeto" if group is None else f"o grupo {group!r}"
        raise MarkerError(f"{which} não tem marcadores para exportar")
    target = out or default_export_path(project.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    # em bytes: o texto já traz a quebra de linha escolhida, e o modo texto do Windows trocaria o \n por \r\n
    target.write_bytes(format_labels(chosen, newline_text(newline)).encode("utf-8"))
    return MarkersExport(target, len(chosen))


def project_total(project: Project, prober: Prober = probe) -> float:
    """A duração final do projeto, a mesma que a vista da linha do tempo mostra."""
    return to_presentation(project, project_layout(project, prober)).total


def add_regular_markers(
    name_or_path: str | Path,
    interval: float | None = None,
    parts: int | None = None,
    start: float = 0.0,
    end: float | None = None,
    prefix: str = "",
    first_number: int = 1,
    digits: int = 1,
    group: str = "",
    color: str | None = None,
    kind: Literal["region", "instant"] = "region",
    replace: bool = False,
    prober: Prober = probe,
) -> MarkersResult:
    """Gera marcadores a cada `interval` segundos ou em `parts` partes iguais e os põe no projeto. Com `replace`,
    os marcadores que o grupo já tinha saem antes."""
    project = load_project(name_or_path)
    created: list[Marker] = regular_markers(
        project_total(project, prober),
        interval=interval,
        parts=parts,
        start=start,
        end=end,
        prefix=prefix,
        first_number=first_number,
        digits=digits,
        group=group.strip(),
        color=color,
        kind=kind,
    )
    kept = [marker for marker in project.markers if not (replace and marker.group == group.strip())]
    updated = project.model_copy(update={"markers": [*kept, *created]})
    _record(project, updated, name_or_path, "Marcadores regulares")
    save_project(updated, project_path(name_or_path).parent)
    return MarkersResult(updated, len(created))
