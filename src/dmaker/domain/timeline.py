"""Contas puras sobre a linha do tempo: duração dos trechos, transições, intervalos e tom do fundo."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..media.probe import MediaInfo
from .spec import ClipSegment, HtmlOverlay, Segment, TextOverlay, Transition

# folga das contas em segundos e quadros: 0.1 * 30 dá 3.0000000000000004, e sem ela o `ceil` pularia um quadro
TIME_EPSILON = 1e-6


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


# ---------- texto atrás da pessoa: janela da linha do tempo ----------


def merge_intervals(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """Junta os intervalos que se sobrepõem ou se encostam, em ordem: dois títulos seguidos atrás da pessoa
    viram uma só janela de recorte, em vez de duas (e de dois aquecimentos do modelo)."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + TIME_EPSILON:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def behind_person_intervals(overlays: Sequence[object], total: float) -> list[tuple[float, float]]:
    """Onde a pessoa recortada precisa aparecer por cima: o intervalo de cada texto ou composição em HTML
    `behind-person`, cortado no vídeo e já juntado. Só esses intervalos pagam o custo do recorte."""
    spans: list[tuple[float, float]] = []
    for overlay in overlays:
        if isinstance(overlay, TextOverlay | HtmlOverlay) and overlay.layer == "behind-person":
            end = min(overlay.end if overlay.end is not None else total, total)
            if end > overlay.start:
                spans.append((overlay.start, end))
    return merge_intervals(spans)


def frame_range(start: float, end: float, fps: float) -> tuple[int, int]:
    """Quadros do vídeo final que o intervalo [start, end) mostra: o primeiro e o seguinte ao último. É a mesma
    regra do libass para o texto (aparece no quadro cujo instante cai dentro do evento), então a pessoa e o
    texto começam e terminam no mesmo quadro."""
    first = max(math.ceil(start * fps - TIME_EPSILON), 0)
    stop = max(math.ceil(end * fps - TIME_EPSILON), first)
    return first, stop


@dataclass(frozen=True)
class TimelineWindow:
    """O pedaço da linha do tempo final que a camada da pessoa precisa renderizar: quais trechos e transições
    caem nele e onde, para o recorte sair do mesmo quadro que a montagem final mostra.

    `origin` é o instante (no tempo final) em que o pedaço começa, já contando o `seek` pulado no primeiro
    trecho; `durations` e `transitions` descrevem só os trechos `first` a `last` (a transição do primeiro é
    sempre `None`) e `overlaps` é quanto cada um desses trechos entra no anterior no vídeo final (o que as
    transições efetivamente duram ali). O pedaço começa `warmup_frames` quadros antes do primeiro quadro do efeito:
    são quadros que o recortador vê para aquecer a memória do modelo e que ele descarta."""

    first: int
    last: int
    origin: float
    seek: float
    warmup_frames: int
    first_frame: int
    frame_count: int
    durations: tuple[float, ...]
    transitions: tuple[Transition | None, ...]
    overlaps: tuple[float, ...]

    @property
    def rendered_frames(self) -> int:
        return self.warmup_frames + self.frame_count


def timeline_window(
    durations: Sequence[float],
    transitions: Sequence[Transition | None],
    start: float,
    end: float,
    fps: float,
    warmup_frames: int,
) -> TimelineWindow | None:
    """Janela do intervalo [start, end) na linha do tempo final, ou None se ele não cobre nenhum quadro.

    Entram os trechos que aparecem em algum quadro do intervalo (o anterior também, se uma transição o mistura
    com o seguinte ali). O primeiro é aberto com `seek` quadros pulados, para não decodificar a gravação inteira
    até chegar ao intervalo; o aquecimento nunca passa do que existe antes do intervalo dentro desse trecho,
    porque a memória de uma cena não serve de aquecimento para a cena seguinte."""
    spans = timeline_spans(list(durations), list(transitions))
    first_frame, stop = frame_range(start, end, fps)
    if stop <= first_frame:
        return None
    window_start, window_end = first_frame / fps, stop / fps
    inside = [
        i
        for i, (a, b) in enumerate(spans)
        if b > window_start + TIME_EPSILON and a < window_end - TIME_EPSILON
    ]
    if not inside:
        return None
    first, last = inside[0], inside[-1]
    frames_before = max(round((window_start - spans[first][0]) * fps), 0)
    warmup = min(warmup_frames, frames_before)
    seek = (frames_before - warmup) / fps
    return TimelineWindow(
        first=first,
        last=last,
        origin=spans[first][0] + seek,
        seek=seek,
        warmup_frames=warmup,
        first_frame=first_frame,
        frame_count=stop - first_frame,
        durations=(durations[first] - seek, *durations[first + 1 : last + 1]),
        transitions=(None, *transitions[first + 1 : last + 1]),
        overlaps=tuple(round(spans[i - 1][1] - spans[i][0], 6) for i in range(first + 1, last + 1)),
    )
