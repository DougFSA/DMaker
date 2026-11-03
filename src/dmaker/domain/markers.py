"""Contas puras sobre os marcadores: achar um pelo nome (`marker:refrão`), listar os grupos e gerar os regulares
(a cada N segundos ou em N partes iguais, com prefixo e numeração). Não toca disco nem a spec."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Literal

from .spec import Marker
from .timeline import TIME_EPSILON

MARKER_PREFIX = "marker:"
MAX_REGULAR_MARKERS = (
    10_000  # um intervalo de milissegundos num vídeo longo gera milhões; é quase sempre engano
)


class MarkerError(ValueError):
    """Marcador inexistente, ambíguo ou pedido de marcadores regulares que não faz sentido."""


def is_marker_ref(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(MARKER_PREFIX)


def _fold(text: str) -> str:
    """Minúsculas, sem acento e com os espaços juntos: `Refrão  Final` e `refrao final` são o mesmo nome."""
    plain = unicodedata.normalize("NFD", text)
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return " ".join(plain.casefold().split())


def marker_groups(markers: Sequence[Marker]) -> list[str]:
    """Os grupos que existem, na ordem em que aparecem (o grupo vazio é a trilha padrão)."""
    return list(dict.fromkeys(marker.group for marker in markers))


def marker_track_id(group: str) -> str:
    """O id da trilha de um grupo na vista da linha do tempo: `MK` para o padrão, `MK:<grupo>` para os nomeados."""
    return f"MK:{group}" if group else "MK"


def _split_ref(markers: Sequence[Marker], reference: str) -> tuple[str | None, str]:
    """Separa `marker:grupo/texto` em (grupo, texto). A barra só separa quando o que vem antes é um grupo que
    existe; senão o texto inteiro é o nome (um marcador pode ter `/` no texto)."""
    body = reference.strip()[len(MARKER_PREFIX) :].strip()
    group, slash, text = body.partition("/")
    if slash and group.strip() in set(marker_groups(markers)):
        return group.strip(), text.strip()
    return None, body


def find_marker(markers: Sequence[Marker], reference: str) -> int:
    """O índice do marcador a que `marker:<texto>` (ou `marker:<grupo>/<texto>`) se refere.

    Procura o texto igual e, se não achar, o texto sem diferenciar maiúscula, acento e espaço. Dois marcadores com o
    mesmo nome é erro (a mensagem lista os dois, para a pessoa escolher pelo grupo); nome que não existe também."""
    if not is_marker_ref(reference):
        raise MarkerError(f"referência de marcador inválida: {reference!r} (use marker:<texto>)")
    group, text = _split_ref(markers, reference)
    if not text:
        raise MarkerError("marker: precisa do texto do marcador (ex.: marker:refrão)")
    candidates = [
        (index, marker)
        for index, marker in enumerate(markers)
        if (group is None or marker.group == group) and marker.text
    ]
    for matches in (
        [pair for pair in candidates if pair[1].text.strip() == text],
        [pair for pair in candidates if _fold(pair[1].text) == _fold(text)],
    ):
        if len(matches) == 1:
            return matches[0][0]
        if len(matches) > 1:
            options = "; ".join(_option(marker) for _, marker in matches)
            raise MarkerError(
                f"há {len(matches)} marcadores chamados {text!r} ({options}): "
                "diga o grupo, no formato marker:<grupo>/<texto>"
            )
    names = ", ".join(sorted({marker.text for _, marker in candidates})) or "nenhum marcador com texto"
    raise MarkerError(f"não existe o marcador {text!r} (os marcadores do projeto: {names})")


def _option(marker: Marker) -> str:
    where = f"{marker.begin:g} s" if not marker.is_region else f"{marker.begin:g} a {marker.finish:g} s"
    return f"grupo {marker.group!r} em {where}" if marker.group else f"em {where}"


def marker_instant(markers: Sequence[Marker], reference: str) -> float:
    """O instante do marcador citado: o próprio instante, ou o começo de uma região."""
    return markers[find_marker(markers, reference)].begin


def resolve_instant(value: object, markers: Sequence[Marker], what: str = "instante") -> float:
    """Um instante dado como número ou como `marker:<texto>`; qualquer outra coisa é erro com o nome do campo."""
    if is_marker_ref(value):
        return marker_instant(markers, str(value))
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MarkerError(f"{what} precisa ser um número de segundos ou marker:<texto>, não {value!r}")
    return float(value)


# ---------- marcadores regulares ----------


def regular_markers(
    total: float,
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
) -> list[Marker]:
    """Marcadores a cada `interval` segundos ou em `parts` partes iguais, de `start` até `end` (o fim do vídeo,
    se omitido), numerados a partir de `first_number` com `digits` casas (`Parte 01`, `Parte 02`...).

    Cada marcador cobre um intervalo (`kind="region"`, como o "Regular Interval Labels" do Audacity) ou marca o
    começo dele (`kind="instant"`). Com `interval`, o que sobra no fim vira uma última região mais curta."""
    if (interval is None) == (parts is None):
        raise MarkerError(
            "informe `interval` (segundos entre os marcadores) ou `parts` (quantas partes iguais), um só"
        )
    stop = total if end is None else end
    if start < 0 or stop <= start:
        raise MarkerError(f"o trecho a marcar é inválido: de {start:g} s a {stop:g} s")
    if stop > total + TIME_EPSILON:
        raise MarkerError(f"o trecho a marcar passa do fim do vídeo ({total:g} s)")
    length = stop - start
    if parts is not None:
        if parts < 1:
            raise MarkerError("`parts` precisa ser pelo menos 1")
        edges = [start + length * i / parts for i in range(parts)] + [stop]
    else:
        assert interval is not None
        if interval <= 0:
            raise MarkerError("`interval` precisa ser maior que zero")
        count = int(length / interval + TIME_EPSILON)
        edges = [start + interval * i for i in range(count + 1)]
        if stop - edges[-1] > TIME_EPSILON:
            edges.append(stop)  # a sobra no fim vira a última região, mais curta
        else:
            edges[-1] = stop
    if len(edges) - 1 > MAX_REGULAR_MARKERS:
        raise MarkerError(f"isso criaria mais de {MAX_REGULAR_MARKERS} marcadores: aumente o intervalo")
    markers: list[Marker] = []
    for offset, (begin, finish) in enumerate(zip(edges, edges[1:], strict=False)):
        text = f"{prefix}{first_number + offset:0{max(digits, 1)}d}"
        begin, finish = round(begin, 6), round(finish, 6)
        if kind == "instant":
            markers.append(Marker(at=begin, text=text, color=color, group=group))
        else:
            markers.append(Marker(start=begin, end=finish, text=text, color=color, group=group))
    return markers
