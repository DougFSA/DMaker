"""Avisos do crossfade de som entre clipes vizinhos, antes de renderizar (o `validate_project` e o resumo leem daqui).

Usam a mesma conta do render (`domain.audio_crossfade.plan_cut`), só que sobre as sondas das fontes: quando o cruzamento
não vai valer, ou vai encurtar, a pessoa sabe antes de esperar o render. As faixas externas de uma sessão multicâmera
não entram na conta daqui (o render as considera e pode achar mais som do que este aviso supõe).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.audio_crossfade import CutSide, plan_cut
from ..domain.spec import ClipSegment, Project
from ..media.probe import MediaInfo


def _side(segment: ClipSegment, info: MediaInfo, offset: float, length: float, leaving: bool) -> CutSide:
    if segment.audio_offset:
        return CutSide(True, 0.0, length, "ele tem o som deslocado (audio_offset)")
    if segment.audio_mode != "original":
        return CutSide(True, 0.0, length, f"ele usa o som isolado ({segment.audio_mode})")
    audible = (info.has_audio and not segment.mute and segment.volume > 0) or bool(segment.source)
    in_point = segment.start - offset
    if leaving:
        room = max(info.duration - (in_point + length * segment.speed), 0.0) / segment.speed
    else:
        room = max(in_point, 0.0) / segment.speed
    return CutSide(audible, room, length)


def crossfade_warnings(
    project: Project,
    durations: Sequence[float],
    infos: Sequence[MediaInfo | None],
    offsets: Sequence[float] | None,
) -> list[str]:
    """Os avisos de cada `audio_crossfade` da linha do tempo: o que o torna sem efeito e o quanto ele encurta."""
    warnings: list[str] = []
    timeline = project.timeline
    for index, segment in enumerate(timeline):
        if not isinstance(segment, ClipSegment) or segment.audio_crossfade is None:
            continue
        where = f"timeline[{index}]"
        if index == 0:
            warnings.append(f"{where}.audio_crossfade é ignorado: não existe trecho anterior.")
            continue
        previous = timeline[index - 1]
        if not isinstance(previous, ClipSegment):
            warnings.append(
                f"{where}.audio_crossfade é ignorado: o trecho anterior não é um clipe de vídeo, não tem som para cruzar."
            )
            continue
        if segment.transition is not None and segment.transition.type != "cut":
            warnings.append(
                f"{where}.audio_crossfade é ignorado: o corte tem transição de imagem, que já cruza o som."
            )
            continue
        before, after = infos[index - 1], infos[index]
        if before is None or after is None:
            continue
        shifts = offsets or [0.0] * len(timeline)
        plan = plan_cut(
            segment.audio_crossfade.duration,
            _side(previous, before, shifts[index - 1], durations[index - 1], leaving=True),
            _side(segment, after, shifts[index], durations[index], leaving=False),
            where,
        )
        if plan.note:
            warnings.append(plan.note)
    return warnings
