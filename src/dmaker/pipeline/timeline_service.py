"""A vista de linha do tempo de um projeto, calculada do disco: o serviço que a interface e o MCP chamam.

Separado de `timeline_view.py` (que só monta a vista a partir de um layout já calculado, sem tocar disco)
porque aqui se olha para os arquivos: o editor precisa abrir o projeto mesmo quando uma fonte foi movida ou
apagada, e então o trecho dela aparece marcado como "fonte não encontrada" em vez de a vista falhar.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.spec import Project
from ..media.probe import probe
from .context import Prober
from .layout import project_layout
from .missing import MissingMedia
from .sync import OffsetFinder
from .timeline_view import TimelineView, build_timeline_view


def project_timeline_view(
    project: Project,
    narration_durations: Sequence[float | None] = (),
    prober: Prober = probe,
    offset_finder: OffsetFinder | None = None,
) -> TimelineView:
    """Vista multitrilha do projeto, com os itens de arquivo ausente marcados (`TrackItem.missing`)."""
    missing = MissingMedia.scan(project)
    layout = project_layout(project, prober, offset_finder, missing)
    return build_timeline_view(project, layout, narration_durations=narration_durations, missing=missing)
