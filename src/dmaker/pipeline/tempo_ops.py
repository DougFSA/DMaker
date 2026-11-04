"""As operações do `edit_project` para o andamento: `tempo_set` e `tempo_remove` (o andamento do projeto) e
`music_tempo_set` (o andamento da música e o esticamento até a grade).

Cada uma lê o pedido e chama a função pura de `domain.tempo_edits`. O `offset` do projeto aceita `marker:<texto>`, para a
grade nascer no marcador que a pessoa pôs no primeiro tempo. Nenhuma mexe na imagem nem na duração do vídeo (o esticamento
da música muda só o que ela toca), então os marcadores não se mexem. Entram em `EDIT_OPERATIONS` por `TEMPO_OPERATIONS`,
sem tocar o despacho de `pipeline.edits`.
"""

from __future__ import annotations

from collections.abc import Callable

from ..domain.edits import EditError
from ..domain.markers import MarkerError, is_marker_ref, resolve_instant
from ..domain.spec import Project
from ..domain.tempo_edits import MUSIC_TEMPO_FIELDS, remove_tempo, set_music_tempo, set_tempo
from .layout import OriginAggregate

TempoOperation = Callable[[Project, dict, OriginAggregate], Project]


def _op_tempo_set(project: Project, op: dict, layout: OriginAggregate) -> Project:
    fields = {name: op.get(name) for name in ("bpm", "time_signature", "offset")}
    if is_marker_ref(fields["offset"]):
        try:
            fields["offset"] = resolve_instant(fields["offset"], project.markers, "offset")
        except MarkerError as exc:
            raise EditError(str(exc)) from exc
    return set_tempo(project, fields)


def _op_tempo_remove(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return remove_tempo(project)


def _op_music_tempo_set(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return set_music_tempo(project, {name: op[name] for name in MUSIC_TEMPO_FIELDS if name in op})


TEMPO_OPERATIONS: dict[str, TempoOperation] = {
    "tempo_set": _op_tempo_set,
    "tempo_remove": _op_tempo_remove,
    "music_tempo_set": _op_music_tempo_set,
}
