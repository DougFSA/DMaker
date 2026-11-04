"""As operações do `edit_project` para sons gerados: `generated_add`, `generated_set`, `generated_remove` e o bipe de censura
(`censor_beep`).

Cada uma lê o pedido, traduz os instantes (que aceitam `marker:<texto>`) e chama a função pura de `domain.generated_edits`.
O bipe é uma edição só: silencia a palavra no item e põe um Tom de 1 kHz no mesmo intervalo, num passo do desfazer. Nenhuma
mexe na imagem nem na duração do vídeo, então os marcadores não se mexem. Uma operação nova entra por uma linha em
`GENERATED_OPERATIONS`, sem tocar o despacho de `pipeline.edits`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..domain.edits import EditError
from ..domain.generated_edits import add_generated, remove_generated, set_generated
from ..domain.markers import MarkerError, find_marker, is_marker_ref, resolve_instant
from ..domain.spec import Project
from .audio_edit_ops import _op_silence
from .censor import BEEP_FREQUENCY_HZ, BEEP_LEVEL_DB, SpeechWordSource, WordSource, word_interval
from .layout import OriginAggregate

GeneratedOperation = Callable[[Project, dict, OriginAggregate], Project]

# Os campos do pedido que não são do item: o resto vai para o item como veio e o item o valida
_OP_ONLY = ("type", "index", "region", "end")


def _instant(project: Project, value: Any, name: str) -> float:
    try:
        return resolve_instant(value, project.markers, name, project.audio.tempo)
    except MarkerError as exc:
        raise EditError(str(exc)) from exc


def _item_fields(project: Project, op: Mapping) -> dict[str, Any]:
    """Os campos do item que o pedido traz, com `start` resolvido. `region` (um marcador de região) dá o começo e a duração,
    e `end` no lugar de `duration` também; o que o pedido não diz fica para o item decidir (padrão do gerador)."""
    fields = {key: value for key, value in op.items() if key not in _OP_ONLY}
    if op.get("region") is not None:
        reference = op["region"]
        if not is_marker_ref(reference):
            raise EditError(f"`region` é uma referência de marcador (marker:<texto>), não {reference!r}")
        try:
            marker = project.markers[find_marker(project.markers, reference)]
        except MarkerError as exc:
            raise EditError(str(exc)) from exc
        if not marker.is_region:
            raise EditError(f"{reference} é um instante, não uma região: use `start` e `duration`")
        fields["start"], fields["duration"] = marker.begin, marker.finish - marker.begin
    else:
        if "start" in fields:
            fields["start"] = _instant(project, fields["start"], "start")
        if op.get("end") is not None:
            end = _instant(project, op["end"], "end")
            begin = fields.get("start", 0.0)
            if end <= begin:
                raise EditError(f"`end` ({end:g}) precisa ser maior que `start` ({begin:g})")
            fields["duration"] = round(end - begin, 6)
    return fields


def _index(op: Mapping) -> int:
    index = op.get("index")
    if not isinstance(index, int) or isinstance(index, bool):
        raise EditError("informe o `index` do som gerado (0 é o primeiro)")
    return index


def _op_generated_add(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return add_generated(project, _item_fields(project, op))


def _op_generated_set(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return set_generated(project, _index(op), _item_fields(project, op))


def _op_generated_remove(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return remove_generated(project, _index(op))


# ---------- bipe de censura ----------


def _words(layout: OriginAggregate) -> WordSource:
    """A fonte de palavras que `apply_edit_report` pôs no layout, ou a transcrição local (Whisper) quando ninguém injetou."""
    return layout.words or SpeechWordSource()


def _beep_interval(project: Project, op: Mapping, layout: OriginAggregate) -> tuple[float, float]:
    """O intervalo a bipar, em segundos da linha do tempo: o da palavra (`word`, achada na transcrição do `target`), o da
    região de marcador (`region`) ou o de `start` e `end`. `margin` alarga o intervalo dos dois lados."""
    word = op.get("word")
    if word is not None:
        target = op.get("target")
        if not isinstance(target, str):
            raise EditError(
                "informe o `target`, o item onde a palavra foi dita (por exemplo audio.voiceover.0)"
            )
        words = _words(layout).words(
            project,
            target,
            str(op.get("language", "pt")),
            None if op.get("search_from") is None else _instant(project, op["search_from"], "search_from"),
            None if op.get("search_to") is None else _instant(project, op["search_to"], "search_to"),
        )
        occurrence = op.get("occurrence")
        begin, end = word_interval(words, str(word), occurrence if isinstance(occurrence, int) else None)
    else:
        fields = _item_fields(project, {key: value for key, value in op.items() if key != "duration"})
        if "start" not in fields or "duration" not in fields:
            raise EditError(
                "diga o que bipar: `word` (a palavra), `region` (um marcador de região) ou `start` e `end`"
            )
        begin, end = fields["start"], fields["start"] + fields["duration"]
    margin = float(op.get("margin", 0.0) or 0.0)
    if margin < 0:
        raise EditError("`margin` é uma folga em segundos e não pode ser negativa")
    return round(max(begin - margin, 0.0), 3), round(end + margin, 3)


def _op_censor_beep(project: Project, op: dict, layout: OriginAggregate) -> Project:
    """O bipe de censura: silencia o `target` no intervalo e acrescenta um Tom no mesmo intervalo (1 kHz, a -12 dBFS, ou o
    que `frequency_hz` e `amplitude_db` disserem). Num passo só: a palavra some do item e o bipe cobre exatamente o lugar dela."""
    target = op.get("target")
    if not isinstance(target, str) or not target:
        raise EditError(
            "informe o `target`, o item onde está o que se quer bipar (por exemplo audio.voiceover.0)"
        )
    begin, end = _beep_interval(project, op, layout)
    silenced = _op_silence(
        project, {"type": "audio_silence", "target": target, "start": begin, "end": end}, layout
    )
    tone = {
        "generator": "tone",
        "params": {
            "waveform": "sine",
            "frequency_hz": float(op.get("frequency_hz", BEEP_FREQUENCY_HZ)),
            "amplitude_db": float(op.get("amplitude_db", BEEP_LEVEL_DB)),
        },
        "start": begin,
        "duration": round(end - begin, 3),
    }
    return add_generated(silenced, tone)


GENERATED_OPERATIONS: dict[str, GeneratedOperation] = {
    "generated_add": _op_generated_add,
    "generated_set": _op_generated_set,
    "generated_remove": _op_generated_remove,
    "censor_beep": _op_censor_beep,
}
