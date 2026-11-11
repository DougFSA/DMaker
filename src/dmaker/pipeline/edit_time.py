"""O tempo que cada edição de trechos tira ou põe na linha do tempo, como um `TimeMap` (ver `domain/time_map.py`).

As edições que mexem em trechos (remover, mover, duplicar, inserir, aparar, mudar um campo) comparam a linha do tempo
de antes com a de depois, trecho a trecho, e dizem para onde cada pedaço do tempo antigo foi. Uma operação nova que
tira ou põe tempo faz uma de duas coisas: devolve o próprio `TimeMap` (`EditOutcome`, em `edits.py`), quando sabe
exatamente os intervalos, ou registra um construtor em `EDIT_TIME_MAPS`, quando só a comparação das duas linhas do
tempo responde. Operação que não mexe no tempo (cortar num ponto, sobreposições, marcadores) não declara nada."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property

from ..domain.spec import ClipSegment, Project
from ..domain.time_map import Piece, TimeMap
from ..domain.timeline import TIME_EPSILON
from .layout import OriginAggregate

_FOREVER = float("inf")


@dataclass(frozen=True)
class EditChange:
    """Uma edição já feita: a operação, os dois projetos e a linha do tempo calculada antes e depois. A de depois só
    é calculada (e só uma vez) se o construtor a pedir: olhar as fontes de novo custa, e muita edição não precisa."""

    op: Mapping
    before_project: Project
    after_project: Project
    before: OriginAggregate
    calculate_after: Callable[[], OriginAggregate]

    @cached_property
    def after(self) -> OriginAggregate:
        return self.calculate_after()


# devolve o mapa de tempo da edição, ou nulo quando não dá para saber (o chamador avisa a pessoa)
TimeMapBuilder = Callable[[EditChange], TimeMap | None]


def owned_intervals(spans: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """O pedaço do tempo final que cada trecho "possui": do começo dele ao começo do seguinte (o último, até o fim).
    O tempo de uma transição pertence ao trecho que entra, então os pedaços nunca se sobrepõem."""
    owned = [(start, spans[index + 1][0]) for index, (start, _) in enumerate(spans[:-1])]
    if spans:
        owned.append(spans[-1])
    return owned


def segment_time_map(
    before: Sequence[tuple[float, float]],
    after: Sequence[tuple[float, float]],
    pairs: Sequence[tuple[int, int]],
    head_trims: Mapping[int, float] | None = None,
) -> TimeMap:
    """O mapa de tempo de uma edição que mantém trechos inteiros: `pairs` liga o trecho antigo `i` ao novo `k`, e o
    conteúdo dele anda do começo do pedaço antigo para o do novo. O que não está em nenhum par foi removido.

    `head_trims[i]` é quanto a edição tirou do começo do trecho `i` (negativo: acrescentou): o conteúdo que sobra anda
    junto com o corte, em vez de ficar parado. Quando o último trecho antigo sobrevive inteiro e continua sendo o último, o
    pedaço dele vai até o infinito, para um marcador no fim exato do vídeo (ou depois dele) seguir o fim."""
    old, new = owned_intervals(before), owned_intervals(after)
    trims = head_trims or {}
    pieces: list[Piece] = []
    for i, k in pairs:
        old_start, old_end = old[i]
        new_start, new_end = new[k]
        head = trims.get(i, 0.0)
        kept_from = old_start + max(head, 0.0)
        kept_to = old_start + min(old_end - old_start, (new_end - new_start) + head)
        if kept_to <= kept_from:
            continue
        reaches_the_end = i == len(old) - 1 and k == len(new) - 1 and kept_to >= old_end - 1e-9
        pieces.append(
            Piece(kept_from, _FOREVER if reaches_the_end else kept_to, new_start - old_start - head)
        )
    return TimeMap(tuple(sorted(pieces, key=lambda piece: piece.start)))


# ---------- um construtor por operação que mexe em trechos ----------


def _count(change: EditChange) -> int:
    return len(change.before.spans)


def _remove(change: EditChange) -> TimeMap | None:
    gone = change.op["index"]
    pairs = [(i, i if i < gone else i - 1) for i in range(_count(change)) if i != gone]
    return segment_time_map(change.before.spans, change.after.spans, pairs)


def _move(change: EditChange) -> TimeMap | None:
    order = list(range(_count(change)))
    order.insert(change.op["to"], order.pop(change.op["index"]))
    pairs = [(old, new) for new, old in enumerate(order)]
    return segment_time_map(change.before.spans, change.after.spans, pairs)


def _duplicate(change: EditChange) -> TimeMap | None:
    copied = change.op["index"]
    pairs = [(i, i if i <= copied else i + 1) for i in range(_count(change))]
    return segment_time_map(change.before.spans, change.after.spans, pairs)


def _insert(change: EditChange) -> TimeMap | None:
    at = change.op["index"]
    pairs = [(i, i if i < at else i + 1) for i in range(_count(change))]
    return segment_time_map(change.before.spans, change.after.spans, pairs)


def _trim(change: EditChange) -> TimeMap | None:
    pairs = [(i, i) for i in range(_count(change))]
    index = change.op["index"]
    head: dict[int, float] = {}
    if change.op["side"] == "in":
        old_start, old_end = owned_intervals(change.before.spans)[index]
        new_start, new_end = owned_intervals(change.after.spans)[index]
        head[index] = (old_end - old_start) - (new_end - new_start)
    return segment_time_map(change.before.spans, change.after.spans, pairs, head)


# os caminhos de `set_field` que podem mudar a duração de um trecho ou o número deles
_TIMELINE_ROOTS = ("timeline", "sources", "master", "multicam")


def _same_count(change: EditChange) -> TimeMap | None:
    """Mudar um campo de um trecho (`set_field`): com o mesmo número de trechos, cada um muda de duração no fim dele.
    Se a lista de trechos mudou de tamanho não há como casar os trechos, e a pessoa é avisada. Um campo que não é da
    linha do tempo (cor de marcador, volume da música) não mexe no tempo, e nem se calcula a linha de depois."""
    if str(change.op.get("path", "")).split(".")[0] not in _TIMELINE_ROOTS:
        return TimeMap.identity()
    if len(change.before.spans) != len(change.after.spans):
        return None
    pairs = [(i, i) for i in range(_count(change))]
    return segment_time_map(change.before.spans, change.after.spans, pairs)


def restored_gap_time_map(
    before: Project, after: Project, before_layout: OriginAggregate, after_layout: OriginAggregate
) -> TimeMap:
    """O tempo que volta à linha do tempo quando um corte é desfeito (`restore_gap`): o trecho devolvido entra no fim
    do primeiro trecho que mudou de tamanho (ou no começo dele, se foi a entrada que cresceu), e tudo o que vem depois
    avança. Os dois trechos que se juntam contam como um só, por isso o tempo inserido é a diferença dos totais."""
    old, new = owned_intervals(before_layout.spans), owned_intervals(after_layout.spans)
    gap = new[-1][1] - old[-1][1]
    for index in range(min(len(old), len(new))):
        if abs((new[index][1] - new[index][0]) - (old[index][1] - old[index][0])) <= TIME_EPSILON:
            continue
        first, second = before.timeline[index], after.timeline[index]
        grew_at_head = (
            isinstance(first, ClipSegment) and isinstance(second, ClipSegment) and second.start < first.start
        )
        return TimeMap.from_changes(inserted=[(old[index][0] if grew_at_head else old[index][1], gap)])
    return TimeMap.identity()


EDIT_TIME_MAPS: dict[str, TimeMapBuilder] = {
    "remove": _remove,
    "move": _move,
    "duplicate": _duplicate,
    "insert": _insert,
    "trim": _trim,
    "set_field": _same_count,
}
