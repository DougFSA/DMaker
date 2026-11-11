"""Cortar no ritmo: para cada fronteira entre dois trechos, a batida mais perto dentro de uma tolerância.

Função pura sobre instantes: ela só propõe quanto cada corte andaria. Quem aplica (apara os dois trechos vizinhos) é
`pipeline/beat_cut.py`, pelas operações de apara que o editor já tem.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass

# Já está na batida se o corte cai a menos de 5 ms dela: abaixo disso nenhum ouvido (e menos de meio quadro a 60 fps) vê.
ON_BEAT_SECONDS = 0.005


@dataclass(frozen=True)
class BoundaryProposal:
    """O que fazer com uma fronteira: `index` é o trecho que termina nela, `boundary` o instante dela hoje, `beat` a
    batida mais perto (ou None) e `shift` quanto a fronteira andaria para cair nela (positivo: depois). `reason`
    explica por que a fronteira não anda, quando ela não anda."""

    index: int
    boundary: float
    beat: float | None
    shift: float | None
    reason: str | None = None

    @property
    def moves(self) -> bool:
        return self.beat is not None and self.shift is not None and abs(self.shift) > ON_BEAT_SECONDS

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "boundary_s": round(self.boundary, 6),
            "beat_s": None if self.beat is None else round(self.beat, 6),
            "shift_s": None if self.shift is None else round(self.shift, 6),
            "reason": self.reason,
        }


def nearest_beat(beats: Sequence[float], instant: float) -> float | None:
    """A batida mais perto de `instant` (`beats` em ordem crescente), ou None se não há nenhuma."""
    if not beats:
        return None
    position = bisect_left(beats, instant)
    candidates = beats[max(position - 1, 0) : position + 1]
    return min(candidates, key=lambda beat: abs(beat - instant))


def propose_beat_cuts(
    boundaries: Sequence[tuple[int, float]],
    beats: Sequence[float],
    tolerance: float,
    skipped: dict[int, str] | None = None,
) -> list[BoundaryProposal]:
    """Uma proposta por fronteira (`(índice do trecho que termina, instante)`): a batida mais perto se ela está a
    até `tolerance` segundos, senão nenhuma. `skipped` traz as fronteiras que não podem andar (uma transição entre os
    trechos, um deles não ser um clipe), com o motivo, e elas ficam como estão."""
    ordered = sorted(beats)
    reasons = skipped or {}
    proposals = []
    for index, boundary in boundaries:
        if index in reasons:
            proposals.append(BoundaryProposal(index, boundary, None, None, reasons[index]))
            continue
        beat = nearest_beat(ordered, boundary)
        if beat is None or abs(beat - boundary) > tolerance:
            proposals.append(
                BoundaryProposal(index, boundary, None, None, f"nenhuma batida a menos de {tolerance:g} s")
            )
        else:
            proposals.append(BoundaryProposal(index, boundary, beat, beat - boundary))
    return proposals
