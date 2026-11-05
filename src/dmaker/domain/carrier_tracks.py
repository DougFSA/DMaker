"""A portadora do Vocoder que vem de outra trilha do projeto: as contas puras (quem pode ouvir quem, o ciclo e onde um item cai
na linha do tempo). Não importa a `spec`: quem monta os pares a partir do projeto é o `Project`, e quem lê o som é o
pipeline (`pipeline/carrier_tracks.py`).

Os ids são os do Auto Duck (`A1`, `A2`..., `MUS`, `NAR`, `VO`, `SFX`), e os limites são os que o DMK-69 deixou: a mesma trilha é
recusada e o `A1` não ouve uma faixa externa. O resto vale, inclusive a cadeia (a voz com portadora na música, e a música com
portadora na narração), desde que não feche um ciclo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .auto_duck import is_external, is_track_id


@dataclass(frozen=True)
class PlacedRun:
    """Um trecho de um item na linha do tempo do projeto: o segundo `item_at` do item toca no segundo `timeline_at` do projeto,
    durante `length` segundos da linha do tempo. `speed` são os segundos de item por segundo da linha do tempo (o clipe a 1,5x
    consome 1,5 s de fonte por segundo de projeto)."""

    item_at: float
    timeline_at: float
    length: float
    speed: float = 1.0

    @property
    def item_length(self) -> float:
        """Quantos segundos do item o trecho consome."""
        return self.length * self.speed

    def key_part(self) -> list[float]:
        """O trecho como números arredondados, para a chave de cache: mover o item na linha do tempo muda a chave."""
        return [
            round(self.item_at, 3),
            round(self.timeline_at, 3),
            round(self.length, 3),
            round(self.speed, 4),
        ]


def check_carrier_pair(host: str, carrier: str) -> str | None:
    """Por que a trilha `host` não pode ouvir a trilha `carrier` como portadora, ou None quando pode."""
    if not is_track_id(carrier):
        return f"trilha desconhecida: {carrier!r}. Use A1, A2 (A3...), MUS, NAR, VO ou SFX, os ids da linha do tempo"
    if carrier == host:
        return f"a trilha {host} não pode ter a si mesma como portadora; escolha outra trilha ou deixe a portadora gerada"
    if host == "A1" and is_external(carrier):
        return (
            f"o A1 já contém as faixas externas, então não usa a {carrier} como portadora; escolha MUS, NAR, VO ou SFX, "
            "ou deixe a portadora gerada"
        )
    return None


def find_cycle(pairs: Sequence[tuple[str, str]]) -> list[str] | None:
    """Um ciclo entre os pares `(trilha que hospeda, trilha portadora)`, na ordem em que se fecha (`MUS`, `NAR`, `MUS`), ou None.
    Cada trilha precisaria do som da outra já processado, e nenhuma pode ficar pronta primeiro."""
    edges: dict[str, set[str]] = {}
    for host, carrier in pairs:
        edges.setdefault(host, set()).add(carrier)
    done: set[str] = set()

    def walk(node: str, trail: list[str]) -> list[str] | None:
        if node in trail:
            return [*trail[trail.index(node) :], node]
        if node in done:
            return None
        for following in sorted(edges.get(node, ())):
            found = walk(following, [*trail, node])
            if found:
                return found
        done.add(node)
        return None

    for start in sorted(edges):
        found = walk(start, [])
        if found:
            return found
    return None
