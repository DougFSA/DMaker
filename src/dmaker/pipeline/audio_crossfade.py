"""O crossfade de som entre clipes vizinhos (J-cut e L-cut): olha para as fontes e diz o que cada mezanino leva.

A conta de quanto o cruzamento dura é pura (`domain.audio_crossfade.plan_cut`) e o grafo também
(`filtergraph.clip_crossfade`). Este módulo liga os dois à linha do tempo: para cada clipe, acha o corte de entrada (com o
anterior) e o de saída (com o seguinte), mede a sobra de som das fontes, escolhe as fatias de som que o vizinho empresta
e avisa quando o cruzamento encurta. O render (mezanino) e a prévia da linha do tempo usam o mesmo caminho.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..domain.audio_crossfade import CutPlan, CutSide, plan_cut
from ..domain.spec import ClipSegment, Segment
from ..filtergraph.clip_crossfade import ClipCrossfades, CrossfadeEdge, crossfade_signature
from ..filtergraph.mezzanine import TrackSlice, uses_camera_audio
from .sources import Source


@dataclass(frozen=True)
class CutNeighbors:
    """A linha do tempo como o crossfade a lê: os trechos, as fontes resolvidas e a duração de cada um, mais quem diz
    quais fatias de faixa externa soam em cada trecho (render e prévia calculam isto de jeitos um pouco diferentes)."""

    segments: Sequence[Segment]
    sources: Sequence[Source]
    durations: Sequence[float]
    slices: Callable[[int], tuple[TrackSlice, ...]]


def wants_crossfade(index: int, neighbors: CutNeighbors) -> bool:
    """Se o corte de entrada do trecho `index` pede crossfade de som e é um corte seco (com uma transição de imagem, o
    `acrossfade` da montagem já cruza o som, e o campo não vale)."""
    segment = neighbors.segments[index]
    if index == 0 or not isinstance(segment, ClipSegment) or segment.audio_crossfade is None:
        return False
    transition = segment.transition
    return transition is None or transition.type == "cut"


def in_point_of(segment: ClipSegment, source: Source) -> float:
    """O ponto do arquivo onde o trecho começa."""
    return source.in_point(segment.start) if segment.source else segment.start


def _side(neighbors: CutNeighbors, index: int, leaving: bool) -> CutSide:
    """Um lado do corte para a conta: quanto som a fonte tem do lado do corte, e se vale o crossfade neste trecho."""
    segment, source = neighbors.segments[index], neighbors.sources[index]
    length = neighbors.durations[index]
    if not isinstance(segment, ClipSegment) or source.path is None or source.info is None:
        return CutSide(False, 0.0, length)
    if segment.audio_offset:
        return CutSide(True, 0.0, length, "ele tem o som deslocado (audio_offset)")
    if segment.audio_mode != "original":
        return CutSide(True, 0.0, length, f"ele usa o som isolado ({segment.audio_mode})")
    audible = uses_camera_audio(segment, source.info) or bool(neighbors.slices(index))
    in_point = in_point_of(segment, source)
    if leaving:
        room = max(source.info.duration - (in_point + length * segment.speed), 0.0) / segment.speed
    else:
        room = max(in_point, 0.0) / segment.speed
    return CutSide(audible, room, length)


def cut_plan(index: int, neighbors: CutNeighbors) -> CutPlan:
    """O crossfade do corte entre o trecho `index - 1` (que sai) e o `index` (que entra)."""
    segment = neighbors.segments[index]
    assert isinstance(segment, ClipSegment) and segment.audio_crossfade is not None
    return plan_cut(
        segment.audio_crossfade.duration,
        _side(neighbors, index - 1, leaving=True),
        _side(neighbors, index, leaving=False),
        f"timeline[{index}]",
    )


def _borrowed(neighbors: CutNeighbors, index: int, shift: float) -> tuple[TrackSlice, ...]:
    """O som do trecho `index` a partir de `shift` segundos de fonte do ponto de entrada dele: a câmera e as faixas
    externas que soam nele, como o mezanino as lê, só que deslocadas."""
    segment, source = neighbors.segments[index], neighbors.sources[index]
    assert isinstance(segment, ClipSegment) and source.path is not None and source.info is not None
    pieces: list[TrackSlice] = []
    if uses_camera_audio(segment, source.info):
        pieces.append(
            TrackSlice(
                source.path,
                in_point_of(segment, source) + shift,
                segment.volume,
                source.audio_stream,
                segment.pan,
            )
        )
    for track in neighbors.slices(index):
        pieces.append(
            TrackSlice(track.path, track.in_point + shift, track.volume, track.audio_stream, track.pan)
        )
    return tuple(pieces)


def clip_crossfades(
    index: int, neighbors: CutNeighbors, warn: Callable[[str], None]
) -> ClipCrossfades | None:
    """O crossfade nas duas pontas do trecho `index`, ou None quando nenhuma delas cruza. A nota de cada corte que não saiu
    como pedido sai por `warn` uma vez só, do trecho que entra (o que sai calcula o mesmo corte em silêncio)."""
    head = tail = None
    segments = neighbors.segments
    if wants_crossfade(index, neighbors):
        plan = cut_plan(index, neighbors)
        if plan.note:
            warn(plan.note)
        if plan.half > 0:
            previous = segments[index - 1]
            assert isinstance(previous, ClipSegment)
            shift = neighbors.durations[index - 1] * previous.speed
            head = CrossfadeEdge(
                _kind(segments[index]),
                plan.half,
                _borrowed(neighbors, index - 1, shift),
                previous.speed,
            )
    elif (
        index > 0 and isinstance(segments[index], ClipSegment) and segments[index].audio_crossfade is not None
    ):  # type: ignore[union-attr]
        warn(
            f"timeline[{index}]: o crossfade de som é ignorado: o corte tem transição de imagem, que já cruza o som."
        )
    follower = index + 1
    if follower < len(segments) and wants_crossfade(follower, neighbors):
        plan = cut_plan(follower, neighbors)
        if plan.half > 0:
            nxt = segments[follower]
            assert isinstance(nxt, ClipSegment)
            tail = CrossfadeEdge(
                _kind(nxt), plan.half, _borrowed(neighbors, follower, -plan.half * nxt.speed), nxt.speed
            )
    if head is None and tail is None:
        return None
    return ClipCrossfades(head, tail)


def _kind(segment: Segment) -> str:
    assert isinstance(segment, ClipSegment) and segment.audio_crossfade is not None
    return segment.audio_crossfade.curve


def _stamp(path: Any) -> list[int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return [stat.st_mtime_ns, stat.st_size]


def crossfade_key_parts(crossfades: ClipCrossfades | None) -> list:
    """O que o crossfade decide no som do trecho, para a chave de cache do mezanino e do pedaço da prévia: a receita (tipo,
    metades, fatias emprestadas) e a data dos arquivos de onde o som é emprestado. Vazio sem crossfade, e então a chave de
    um clipe sem o campo é a de sempre (o `MEZZ_VERSION` não sobe)."""
    signature = crossfade_signature(crossfades)
    if not signature or crossfades is None:
        return []
    stamps = [
        _stamp(piece.path) for edge in (crossfades.head, crossfades.tail) if edge for piece in edge.borrow
    ]
    return [signature, stamps]
