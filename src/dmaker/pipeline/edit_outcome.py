"""O que uma operação de edição devolve e o que a edição aplicada entrega a quem a pediu.

Ficam num módulo à parte para as operações (`restoration_ops`, `audio_edit_ops`) poderem devolver um `EditOutcome` sem
importar o despacho (`pipeline.edits`), que importa todas elas."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.spec import Project
from ..domain.time_map import TimeMap


@dataclass(frozen=True)
class EditOutcome:
    """O que uma operação devolve quando sabe o tempo que mexeu: o projeto novo e o mapa de tempo dos intervalos
    removidos e inseridos (em tempo ANTIGO). Devolver só o `Project` quer dizer "não declaro nada". `notes` são
    linhas para quem pediu a edição, sobre o que ela fez (quantos silêncios saíram), e não avisos de problema."""

    project: Project
    time_map: TimeMap | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EditReport:
    """A edição aplicada: o projeto novo (com os marcadores já no lugar), os avisos para a pessoa (marcador apagado
    por estar num trecho cortado), o mapa de tempo que foi usado e as notas da operação."""

    project: Project
    warnings: list[str] = field(default_factory=list)
    time_map: TimeMap = field(default_factory=TimeMap.identity)
    notes: list[str] = field(default_factory=list)
