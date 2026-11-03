"""Mapa de tempo de uma edição: para cada pedaço da linha do tempo ANTIGA que continua existindo, onde ele passou a ficar.

É o contrato que deixa os marcadores (e qualquer coisa colada ao tempo final) seguirem as edições: quem tira ou põe
tempo na linha do tempo declara os intervalos removidos e inseridos em tempo antigo, e `shift_markers` cuida do resto.
Tudo puro: recebe números e devolve números, sem tocar disco nem a spec."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .spec import Marker
from .timeline import TIME_EPSILON

_FOREVER = float("inf")


@dataclass(frozen=True)
class Piece:
    """O pedaço [start, end) do tempo antigo, que a edição levou para `start + shift`."""

    start: float
    end: float
    shift: float


@dataclass(frozen=True)
class TimeMap:
    """Os pedaços do tempo antigo que sobraram, em ordem e sem sobreposição. O que não está em nenhum pedaço foi
    removido. `identity()` é a edição que não mexe no tempo (cortar num ponto, mudar uma cor)."""

    pieces: tuple[Piece, ...]

    @classmethod
    def identity(cls) -> TimeMap:
        return cls((Piece(0.0, _FOREVER, 0.0),))

    @classmethod
    def from_changes(
        cls,
        removed: Iterable[tuple[float, float]] = (),
        inserted: Iterable[tuple[float, float]] = (),
    ) -> TimeMap:
        """O mapa de quem tira e põe tempo, tudo em tempo ANTIGO.

        `removed`: intervalos [início, fim) que somem; o que vem depois deles recua. `inserted`: pares
        (instante, duração) em que entra tempo novo; o que está no instante ou depois avança. Os dois valem ao
        mesmo tempo, então uma edição que tira um trecho e põe outro (mover, substituir) descreve as duas coisas."""
        gaps = _merge(sorted((a, b) for a, b in removed if b > a + TIME_EPSILON))
        additions = sorted((at, duration) for at, duration in inserted if duration > TIME_EPSILON)
        cuts = sorted({0.0, *(point for gap in gaps for point in gap), *(at for at, _ in additions)})
        pieces: list[Piece] = []
        for start, end in zip(cuts, [*cuts[1:], _FOREVER], strict=True):
            if any(a <= start + TIME_EPSILON and end <= b + TIME_EPSILON for a, b in gaps):
                continue  # o pedaço inteiro está num trecho removido
            lost = sum(b - a for a, b in gaps if b <= start + TIME_EPSILON)
            gained = sum(duration for at, duration in additions if at <= start + TIME_EPSILON)
            pieces.append(Piece(start, end, gained - lost))
        return cls(_join(pieces))

    def locate(self, instant: float) -> Piece | None:
        """O pedaço que contém o instante (começo incluído, fim excluído), ou nulo se ele foi removido."""
        index = bisect_right([piece.start for piece in self.pieces], instant + TIME_EPSILON) - 1
        if index < 0:
            return None
        piece = self.pieces[index]
        return piece if instant < piece.end - TIME_EPSILON else None

    def move_instant(self, instant: float) -> float | None:
        """Onde o instante passa a ficar, ou nulo se a edição o removeu."""
        piece = self.locate(instant)
        return None if piece is None else max(instant + piece.shift, 0.0)

    def move_region(self, start: float, end: float) -> tuple[float, float] | None:
        """Onde a região [start, end) passa a ficar: encolhe com o que perdeu, cresce com o que ganhou e some se
        perdeu tudo (ou se o que sobrou não cabe mais em ordem)."""
        inside = [
            piece
            for piece in self.pieces
            if piece.end > start + TIME_EPSILON and piece.start < end - TIME_EPSILON
        ]
        if not inside:
            return None
        first, last = inside[0], inside[-1]
        new_start = max(start, first.start) + first.shift
        new_end = min(end, last.end) + last.shift
        if new_end - new_start <= TIME_EPSILON:
            return None
        return max(new_start, 0.0), new_end

    @property
    def is_identity(self) -> bool:
        return all(piece.shift == 0.0 for piece in self.pieces) and len(self.pieces) == 1


def _merge(intervals: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + TIME_EPSILON:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _join(pieces: list[Piece]) -> tuple[Piece, ...]:
    """Cola os pedaços vizinhos que andam o mesmo tanto (um ponto de inserção sem efeito não parte o mapa)."""
    joined: list[Piece] = []
    for piece in pieces:
        previous = joined[-1] if joined else None
        if previous and abs(previous.end - piece.start) <= TIME_EPSILON and previous.shift == piece.shift:
            joined[-1] = Piece(previous.start, piece.end, piece.shift)
        else:
            joined.append(piece)
    return tuple(joined)


# ---------- os marcadores seguindo o mapa ----------


@dataclass(frozen=True)
class ShiftResult:
    markers: list[Marker]
    warnings: list[str]


def shift_markers(markers: Sequence[Marker], time_map: TimeMap) -> ShiftResult:
    """Aplica o mapa aos marcadores: cada um vai para o tempo novo; o que estava num trecho removido some, com um
    aviso que diz qual era. Uma região que perdeu só uma parte encolhe. Mapa de identidade não toca em nada."""
    if time_map.is_identity:
        return ShiftResult(list(markers), [])
    kept: list[Marker] = []
    warnings: list[str] = []
    for marker in markers:
        moved = _moved(marker, time_map)
        if moved is None:
            warnings.append(
                f"O marcador {describe_marker(marker)} estava dentro do trecho removido e foi apagado."
            )
            continue
        kept.append(moved)
    return ShiftResult(kept, warnings)


def _moved(marker: Marker, time_map: TimeMap) -> Marker | None:
    if not marker.is_region:
        instant = time_map.move_instant(marker.begin)
        return None if instant is None else marker.model_copy(update={"at": _clean(instant)})
    region = time_map.move_region(marker.begin, marker.finish)
    if region is None:
        return None
    return marker.model_copy(update={"start": _clean(region[0]), "end": _clean(region[1])})


def _clean(seconds: float) -> float:
    """Microssegundos bastam; sem isso uma conta como 15 - 3 grava 12.000000000000002 na spec."""
    return round(seconds, 6)


def describe_marker(marker: Marker) -> str:
    """O marcador como a pessoa o conhece: o texto entre aspas e onde ele estava."""
    if marker.is_region:
        where = f"de {_seconds(marker.begin)} a {_seconds(marker.finish)} s"
    else:
        where = f"em {_seconds(marker.begin)} s"
    name = f'"{marker.text}"' if marker.text else "sem texto"
    return f"{name} {where}"


def _seconds(value: float) -> str:
    """Segundos com vírgula decimal e sem zeros à toa: 12,5 e 4."""
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")
