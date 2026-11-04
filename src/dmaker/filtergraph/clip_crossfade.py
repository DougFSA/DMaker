"""O crossfade de som nas pontas de um clipe do mezanino (o J-cut e o L-cut): as linhas do grafo, puras.

O corte entre dois clipes continua seco para a imagem. Para o som, cada mezanino leva a sua parte do cruzamento: o
clipe que entra recebe, nos primeiros `half` segundos, o som que o clipe anterior ainda teria depois do ponto de saída
(a "cauda"), e o clipe que sai recebe, nos últimos `half` segundos, o som que o seguinte já teria antes do ponto de
entrada (a "cabeça"). Os ganhos dos dois lados seguem a mesma curva (`domain.fade_curves.crossfade_gains`), cada
mezanino com a metade que lhe cabe, e a emenda entre os dois mezaninos fica contínua.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.audio_effects.editing import EnvelopePoint
from ..domain.fade_curves import crossfade_gains, curve_db_points
from .audio_effects.editing import ENVELOPE_FRAME_SAMPLES, envelope_gain_expression
from .common import AUDIO_FMT_MEZZ, Inputs, atempo_chain

# Os dois papéis de um lado do crossfade, na ordem em que `crossfade_gains` devolve os ganhos
LEAVING, ENTERING = 0, 1


@dataclass(frozen=True)
class CrossfadeEdge:
    """Uma ponta do clipe que cruza com o vizinho.

    `half` é a metade do crossfade, em segundos da linha do tempo; `kind` é o tipo (`constant_gain`...). `borrow` são as
    fatias de som do vizinho que entram (a câmera dele e as faixas externas), cada uma com `in_point` no instante do
    arquivo em que começa o som emprestado; `speed` é a velocidade do vizinho (segundos de fonte por segundo de linha
    do tempo), para ler `half * speed` de fonte e voltar a `half` com o `atempo`."""

    kind: str
    half: float
    borrow: tuple[Any, ...]
    speed: float = 1.0


@dataclass(frozen=True)
class ClipCrossfades:
    """O crossfade nas duas pontas de UM clipe: `head` é o corte com o clipe anterior, `tail` o corte com o seguinte."""

    head: CrossfadeEdge | None = None
    tail: CrossfadeEdge | None = None

    def __bool__(self) -> bool:
        return self.head is not None or self.tail is not None


def portion_gain_expression(
    kind: str, role: int, from_u: float, to_u: float, width: float, start_at: float
) -> str:
    """O ganho em dB, como expressão em `t` do ffmpeg, do pedaço `from_u`..`to_u` (de 0 a 1) da curva do crossfade de
    `width` segundos, começando em `start_at` segundos no fluxo. Antes e depois do pedaço vale o ganho da ponta dele."""
    span = to_u - from_u
    points = curve_db_points(
        lambda fraction: crossfade_gains(kind, from_u + span * fraction)[role], span * width
    )
    return envelope_gain_expression([EnvelopePoint(at=round(start_at + at, 6), db=db) for at, db in points])


def gain_filters(expression: str) -> list[str]:
    """Os filtros que aplicam a expressão de ganho em dB quadro a quadro (os mesmos do Envelope: quadros de 64 amostras)."""
    return [
        f"asetnsamples=n={ENVELOPE_FRAME_SAMPLES}:p=0",
        f"volume='pow(10,({expression})/20)':eval=frame:precision=float",
    ]


def crossfade_lines(
    inputs: Inputs,
    body: str,
    out: str,
    duration: float,
    crossfades: ClipCrossfades,
    source_chain: Callable[[float, float, float, float], list[str]],
    tag: str = "mz_xf",
) -> list[str]:
    """Liga o som do clipe em `body` (já com a duração `duration`) a `out`, com as pontas cruzadas.

    O som do próprio clipe abaixa nos últimos `half` segundos (corte com o seguinte) e abre nos primeiros (corte com o
    anterior); o som emprestado de cada vizinho entra com o ganho complementar e se soma. `source_chain(in_point, volume,
    length, pan)` monta o ramo de uma fatia de fonte alinhada a partir do `in_point` (a receita do mezanino)."""
    lines: list[str] = []
    own = body
    borrowed: list[str] = []
    step = 0
    for name, edge in (("h", crossfades.head), ("t", crossfades.tail)):
        if edge is None:
            continue
        width = 2.0 * edge.half
        head = name == "h"
        # a metade de dentro da curva: a cabeça (corte de entrada) é a segunda metade, a cauda (de saída) a primeira
        from_u, to_u = (0.5, 1.0) if head else (0.0, 0.5)
        own_start = 0.0 if head else duration - edge.half
        own_role = ENTERING if head else LEAVING
        borrowed_role = LEAVING if head else ENTERING
        step += 1
        target = f"[{tag}_o{step}]"
        expression = portion_gain_expression(edge.kind, own_role, from_u, to_u, width, own_start)
        lines.append(f"{own}{','.join(gain_filters(expression))}{target}")
        own = target
        length = edge.half * edge.speed
        parts = []
        for k, piece in enumerate(edge.borrow):
            index = inputs.add(piece.path, "-ss", f"{max(piece.in_point, 0):.3f}", "-t", f"{length:.3f}")
            chain = source_chain(min(piece.in_point, 0.0), piece.volume, length, piece.pan)
            label = f"[{tag}_{name}{k}]"
            lines.append(f"[{index}:a:{piece.audio_stream}]" + ",".join(chain) + label)
            parts.append(label)
        joined = f"[{tag}_{name}]"
        if len(parts) == 1:
            lines.append(f"{parts[0]}anull{joined}")
        else:
            lines.append(
                "".join(parts)
                + f"amix=inputs={len(parts)}:duration=longest:dropout_transition=0:normalize=0{joined}"
            )
        shaped = [atempo_chain(edge.speed)] if edge.speed != 1 else []
        shaped.append(AUDIO_FMT_MEZZ)
        # o ganho do som emprestado conta o tempo do próprio fluxo (começa em 0); a cauda do vizinho que entra é
        # empurrada para o fim do clipe depois de ganhar a curva
        shaped += gain_filters(portion_gain_expression(edge.kind, borrowed_role, from_u, to_u, width, 0.0))
        if not head:
            shaped.append(f"adelay={round((duration - edge.half) * 1000)}:all=1")
        ready = f"[{tag}_b{name}]"
        lines.append(f"{joined}{','.join(shaped)}{ready}")
        borrowed.append(ready)
    inputs_label = "".join([own, *borrowed])
    lines.append(
        f"{inputs_label}amix=inputs={1 + len(borrowed)}:duration=first:dropout_transition=0:normalize=0,"
        f"{AUDIO_FMT_MEZZ}{out}"
    )
    return lines


def edge_summary(edge: CrossfadeEdge | None) -> list[Any] | None:
    """A ponta como dados simples para a chave de cache (a receita do mezanino e o pedaço da prévia)."""
    if edge is None:
        return None
    return [
        edge.kind,
        edge.half,
        edge.speed,
        [
            (str(piece.path), round(piece.in_point, 3), piece.volume, piece.audio_stream, piece.pan)
            for piece in edge.borrow
        ],
    ]


def crossfade_signature(crossfades: ClipCrossfades | None) -> list[Any]:
    """O que o crossfade decide no som do clipe, para a chave de cache: vazio sem crossfade (a chave de um clipe sem ele
    não muda, e `MEZZ_VERSION` não precisa subir)."""
    if not crossfades:
        return []
    return [["crossfade", edge_summary(crossfades.head), edge_summary(crossfades.tail)]]


__all__ = [
    "ClipCrossfades",
    "CrossfadeEdge",
    "crossfade_lines",
    "crossfade_signature",
    "gain_filters",
    "portion_gain_expression",
]
