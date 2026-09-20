"""Contas puras sobre a linha do tempo: duração dos trechos, transições, intervalos e tom do fundo."""

from __future__ import annotations

from ..media.probe import MediaInfo
from .spec import ClipSegment, Segment, Transition


def segment_duration(segment: Segment, info: MediaInfo | None, offset: float = 0.0) -> float:
    """Duração do trecho no tempo final (já descontada a velocidade). `offset` é onde a fonte
    começa no relógio da sessão (clipes sincronizados); para arquivo avulso é 0."""
    if isinstance(segment, ClipSegment):
        if info is None:
            raise ValueError("clipe sem informação de mídia")
        coverage_end = offset + info.duration if info.duration else None
        end = segment.end if segment.end is not None else coverage_end
        if end is None:
            raise ValueError("clipe sem duração conhecida: informe end")
        if coverage_end is not None:
            end = min(end, coverage_end)
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


def stack_lanes(intervals: list[tuple[float, float]]) -> list[int]:
    """Número de faixa (0, 1, 2...) de cada intervalo (início, fim): greedy por ordem de início,
    reaproveitando a primeira faixa já livre; dois intervalos que se sobrepõem no tempo nunca
    dividem a mesma faixa. Base de `pipeline.timeline_view.stack_lanes` (que agrupa objetos
    `TrackItem` da vista) e de `domain.tracks.video_overlay_lanes` (que decide a V2/V3... de cada
    picture-in-picture ao aplicar mudo/oculto por trilha no render)."""
    order = sorted(range(len(intervals)), key=lambda i: intervals[i][0])
    lane_ends: list[float] = []
    lane_of = [0] * len(intervals)
    for i in order:
        start, end = intervals[i]
        for lane, lane_end in enumerate(lane_ends):
            if lane_end <= start:
                lane_ends[lane] = end
                lane_of[i] = lane
                break
        else:
            lane_of[i] = len(lane_ends)
            lane_ends.append(end)
    return lane_of


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
