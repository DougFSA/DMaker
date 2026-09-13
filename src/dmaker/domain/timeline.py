"""Contas puras sobre a linha do tempo: duração dos trechos, transições, intervalos e tom do fundo."""

from __future__ import annotations

from ..media.probe import MediaInfo
from .spec import ClipSegment, Segment, Transition


def segment_duration(segment: Segment, info: MediaInfo | None) -> float:
    """Duração do trecho no tempo final (já descontada a velocidade)."""
    if isinstance(segment, ClipSegment):
        if info is None:
            raise ValueError("clipe sem informação de mídia")
        end = segment.end if segment.end is not None else info.duration
        end = min(end, info.duration) if info.duration else end
        return max(end - segment.start, 0.0) / segment.speed
    return segment.duration


def transitions_of(segments: list[Segment]) -> list[Transition | None]:
    """Transição de entrada de cada trecho; a do primeiro é sempre ignorada."""
    return [None] + [seg.transition for seg in segments[1:]]


def effective_transition(tr: Transition | None, previous_total: float, duration: float) -> float:
    """Duração real da transição: nunca passa de metade do que já existe nem de metade do trecho."""
    if tr is None or tr.type == "cut":
        return 0.0
    return min(tr.duration, previous_total * 0.5, duration * 0.5)


def timeline_spans(durations: list[float], transitions: list[Transition | None]) -> list[tuple[float, float]]:
    """Intervalo (início, fim) de cada trecho no tempo final, descontando as transições."""
    spans: list[tuple[float, float]] = []
    total = 0.0
    for i, dur in enumerate(durations):
        d = effective_transition(transitions[i], total, dur) if i else 0.0
        start = total - d
        spans.append((start, start + dur))
        total = start + dur
    return spans


def timeline_total(durations: list[float], transitions: list[Transition | None]) -> float:
    spans = timeline_spans(durations, transitions)
    return spans[-1][1] if spans else 0.0


def tone_for(
    start: float, end: float, spans: list[tuple[float, float]], tones: list[str | None]
) -> str | None:
    """Tom dominante (>= 85% do tempo) dos trechos sob um texto; None se for vídeo/foto ou se os tons
    se dividirem. Trechos que só encostam no texto durante uma transição não mudam o resultado."""
    length = end - start
    if length <= 0:
        return None
    cover: dict[str | None, float] = {}
    for i, (a, b) in enumerate(spans):
        overlap = min(b, end) - max(a, start)
        if overlap > 0:
            cover[tones[i]] = cover.get(tones[i], 0.0) + overlap
    if not cover:
        return None
    tone, covered = max(cover.items(), key=lambda kv: kv[1])
    return tone if covered >= 0.85 * length else None
