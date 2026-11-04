"""Despacha operações de edição pontual sobre a spec: calcula o layout atual e chama a função pura
correspondente em `domain.edits`. Aberto para extensão: um tipo de operação novo é uma entrada nova
em `EDIT_OPERATIONS`, sem tocar no dispatcher.

Uma operação que tira ou põe tempo na linha do tempo também faz os marcadores acompanharem: ou devolve um
`EditOutcome` com o `TimeMap` dos intervalos que mexeu, ou registra um construtor em `EDIT_TIME_MAPS`
(`edit_time.py`). Operação que não mexe no tempo não declara nada."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.edits import (
    EditError,
    duplicate_overlay,
    duplicate_segment,
    insert_segment,
    move_segment,
    remove_overlay,
    remove_segment,
    set_field,
    set_overlay_span,
    split_segment,
    trim_segment,
)
from ..domain.effect_edits import apply_effect_op
from ..domain.marker_edits import add_marker, marker_index, remove_marker, set_group_markers, set_marker
from ..domain.markers import MarkerError, is_marker_ref, resolve_instant
from ..domain.spec import ClipSegment, Project
from ..domain.time_map import shift_markers
from ..media.ffmpeg import FFmpegError, SubprocessRunner
from ..media.probe import probe
from .audio_edit_ops import AUDIO_OPERATIONS
from .context import Prober
from .edit_outcome import EditOutcome, EditReport
from .edit_time import EDIT_TIME_MAPS, EditChange, owned_intervals
from .layout import OriginAggregate, aggregate_by_origin, project_layout
from .missing import MissingMedia
from .restoration_ops import RESTORATION_OPERATIONS
from .sample_reader import FFmpegSampleReader, SampleReader
from .sync import OffsetFinder

__all__ = ["EDIT_OPERATIONS", "EditOutcome", "EditReport", "apply_edit", "apply_edit_report"]


Operation = Callable[[Project, dict, OriginAggregate], Project | EditOutcome]


def _clip_media_duration(project: Project, layout: OriginAggregate, index: int) -> float | None:
    """Limite de `end` do trecho (tempo do arquivo; tempo da sessão quando a fonte é sincronizada,
    já que `offset` é 0 para arquivos avulsos; para fonte com `parts`, o fim da última parte)."""
    segment = project.timeline[index]
    if not isinstance(segment, ClipSegment):
        return None
    return layout.media_limits[index]


def _locate_marker(project: Project, op: dict, layout: OriginAggregate) -> tuple[int, float]:
    """O trecho e o ponto, desde o começo dele, em que o marcador citado em `at` cai. Sem `index` na operação, o
    trecho é o que contém o marcador; com `index`, o marcador precisa estar dentro dele."""
    try:
        instant = resolve_instant(op["at"], project.markers, "at")
    except MarkerError as exc:
        raise EditError(str(exc)) from exc
    owned = owned_intervals(layout.spans)
    index = op.get("index")
    if index is None:
        index = next((i for i, (start, end) in enumerate(owned) if start <= instant < end), None)
        if index is None:
            raise EditError(
                f"o marcador está em {instant:g} s, fora da linha do tempo (0 a {owned[-1][1]:g} s)"
            )
    elif not 0 <= index < len(layout.spans):
        raise EditError(f"índice de trecho fora do intervalo: {index} (0 a {len(layout.spans) - 1})")
    return index, instant - layout.spans[index][0]


def _op_split(project: Project, op: dict, layout: OriginAggregate) -> Project:
    if is_marker_ref(op["at"]):
        index, at = _locate_marker(project, op, layout)
        return split_segment(project, index, at, layout.durations)
    return split_segment(project, op["index"], op["at"], layout.durations)


def _op_remove(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return remove_segment(project, op["index"])


def _op_move(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return move_segment(project, op["index"], op["to"])


def _op_trim(project: Project, op: dict, layout: OriginAggregate) -> Project:
    index = op["index"]
    media_duration = _clip_media_duration(project, layout, index)
    return trim_segment(project, index, op["side"], op["delta"], layout.durations, media_duration)


def _op_duplicate(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return duplicate_segment(project, op["index"])


def _op_insert(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return insert_segment(project, op["index"], op["segment"])


def _op_overlay_span(project: Project, op: dict, layout: OriginAggregate) -> Project:
    try:
        start = resolve_instant(op["start"], project.markers, "start")
        end = op.get("end")
        end = None if end is None else resolve_instant(end, project.markers, "end")
    except MarkerError as exc:
        raise EditError(str(exc)) from exc
    return set_overlay_span(project, op["index"], start, end)


def _op_overlay_remove(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return remove_overlay(project, op["index"])


def _op_overlay_duplicate(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return duplicate_overlay(project, op["index"])


def _op_set_field(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return set_field(project, op["path"], op.get("value"))


def _op_audio_effect(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return apply_effect_op(project, op)


def _op_marker_add(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return add_marker(project, op)


def _op_marker_set(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return set_marker(project, marker_index(project, op), op)


def _op_marker_remove(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return remove_marker(project, marker_index(project, op))


def _op_marker_group_set(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return set_group_markers(project, str(op.get("group", "")), op.get("markers") or [])


EDIT_OPERATIONS: dict[str, Operation] = {
    "split": _op_split,
    "remove": _op_remove,
    "move": _op_move,
    "trim": _op_trim,
    "duplicate": _op_duplicate,
    "insert": _op_insert,
    "overlay_span": _op_overlay_span,
    "overlay_remove": _op_overlay_remove,
    "overlay_duplicate": _op_overlay_duplicate,
    "set_field": _op_set_field,
    "audio_effect": _op_audio_effect,
    "marker_add": _op_marker_add,
    "marker_set": _op_marker_set,
    "marker_remove": _op_marker_remove,
    "marker_group_set": _op_marker_group_set,
    # edição de onda (silenciar, cortar, envelope, canais, colar, dividir, juntar, aparar, deslocar, trilha): não
    # mexem na imagem nem na duração do vídeo, então não declaram tempo e os marcadores ficam onde estão
    **AUDIO_OPERATIONS,
    # limpeza e reparo (perfil de ruído, Truncar Silêncio): leem o som, então usam o leitor de amostras da edição; o
    # Truncar Silêncio no clipe corta a imagem junto e declara o tempo que tirou
    **RESTORATION_OPERATIONS,
}


def apply_edit_report(
    project: Project,
    op: dict,
    prober: Prober = probe,
    offset_finder: OffsetFinder | None = None,
    sample_reader: SampleReader | None = None,
) -> EditReport:
    """Calcula o layout atual do projeto e aplica a operação `op["type"]` sobre a spec, devolvendo o projeto novo
    com os marcadores já acompanhando a edição, mais os avisos (um marcador que estava num trecho cortado some).
    Parâmetro ausente ou do tipo errado em `op` vira EditError. As operações que leem o som (perfil de ruído, Truncar
    Silêncio) usam `sample_reader`; sem ele, decodificam com o ffmpeg."""
    op_type = op.get("type")
    handler = EDIT_OPERATIONS.get(op_type)
    if handler is None:
        raise EditError(
            f"operação de edição desconhecida: {op_type!r}. Use uma de: {', '.join(sorted(EDIT_OPERATIONS))}"
        )
    # a edição também acontece com uma fonte ausente: é assim que a pessoa corta, move ou troca o arquivo dela
    layout = aggregate_by_origin(
        project, project_layout(project, prober, offset_finder, MissingMedia.scan(project))
    )
    layout.reader = sample_reader or FFmpegSampleReader(SubprocessRunner(quiet=True))
    try:
        result = handler(project, op, layout)
    except EditError:
        raise
    except (KeyError, TypeError) as exc:
        raise EditError(f"parâmetros inválidos para a operação {op_type!r}: {exc}") from exc
    outcome = result if isinstance(result, EditOutcome) else EditOutcome(result)
    return _follow_markers(project, outcome, op, layout, prober, offset_finder)


def apply_edit(
    project: Project, op: dict, prober: Prober = probe, offset_finder: OffsetFinder | None = None
) -> Project:
    """Como `apply_edit_report`, só com o projeto novo: para quem não mostra os avisos."""
    return apply_edit_report(project, op, prober, offset_finder).project


def _follow_markers(
    before: Project,
    outcome: EditOutcome,
    op: dict,
    before_layout: OriginAggregate,
    prober: Prober,
    offset_finder: OffsetFinder | None,
) -> EditReport:
    """Desloca os marcadores pelo tempo que a edição mexeu. Sem marcador não há conta nenhuma (nem a segunda leitura
    das fontes); uma edição que não declara tempo deixa os marcadores onde estão."""
    after = outcome.project
    notes = outcome.notes
    if not after.markers:
        return EditReport(after, notes=notes)
    time_map = outcome.time_map
    if time_map is None:
        builder = EDIT_TIME_MAPS.get(op["type"])
        if builder is None:
            return EditReport(after, notes=notes)

        def calculate_after() -> OriginAggregate:
            layout = project_layout(after, prober, offset_finder, MissingMedia.scan(after))
            return aggregate_by_origin(after, layout)

        try:
            time_map = builder(EditChange(op, before, after, before_layout, calculate_after))
        except (FileNotFoundError, KeyError, ValueError, FFmpegError):
            time_map = None
        if time_map is None:
            return EditReport(
                after,
                ["Os marcadores não acompanharam esta mudança na linha do tempo: confira a posição deles."],
                notes=notes,
            )
    shifted = shift_markers(after.markers, time_map)
    return EditReport(
        after.model_copy(update={"markers": shifted.markers}), shifted.warnings, time_map, notes
    )
