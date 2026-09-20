"""Corte automático de multicâmera: alterna câmeras por fase da cerimônia (reconhecida por termos
na transcrição), atrai as trocas para pausas da fala e respeita a cobertura real de cada câmera.
Tudo puro: recebe cobertura, falas e regras, devolve a lista de clipes e avisos, sem tocar ffmpeg.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

_EPSILON = 1e-6


@dataclass(frozen=True)
class Coverage:
    """Intervalo em tempo da sessão em que a câmera tem imagem (uma câmera pode ter vários)."""

    camera: str
    start: float
    end: float


@dataclass(frozen=True)
class Speech:
    """Trecho de fala transcrita, em tempo da sessão."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class PhaseRule:
    """Regra de reconhecimento de uma fase da cerimônia pelos termos ditos na fala.

    A fase começa na primeira fala que contém qualquer termo de `match` (sem acento e sem caixa) e
    dura até a próxima fase reconhecida ou até `max_duration`, o que vier primeiro. As regras vêm
    na ordem do rito: uma fase anterior à corrente não reabre. `main` é a câmera
    principal da fase (None usa a principal do bloco); `cadence` é (segundos na principal, segundos
    na outra).
    """

    name: str
    match: tuple[str, ...]
    main: str | None = None
    cadence: tuple[float, float] = (40.0, 30.0)
    max_duration: float | None = None


@dataclass(frozen=True)
class MulticamPlan:
    """Parâmetros de um bloco multicâmera: câmeras disponíveis, ritmo padrão e fases reconhecidas."""

    cameras: tuple[str, ...]
    main: str
    audio: str
    cadence: tuple[float, float] = (40.0, 30.0)
    phases: tuple[PhaseRule, ...] = ()
    min_clip: float = 4.0
    snap_window: float = 5.0
    pause: float = 0.6


@dataclass(frozen=True)
class PlannedClip:
    """Um trecho do corte automático: câmera, intervalo em tempo da sessão, fase e se fica mudo."""

    camera: str
    start: float
    end: float
    label: str
    mute: bool


@dataclass(frozen=True)
class _Window:
    """Janela contínua com uma câmera principal e uma cadência fixas (uma fase, ou "geral")."""

    label: str
    main: str
    cadence: tuple[float, float]
    start: float
    end: float


def fold(text: str) -> str:
    """Minúsculas e sem acento, para reconhecer termos ditos independente de caixa/acentuação."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _match_rule(text: str, phases: tuple[PhaseRule, ...]) -> PhaseRule | None:
    folded = fold(text)
    for rule in phases:
        if any(fold(term) in folded for term in rule.match):
            return rule
    return None


def _phase_events(
    plan: MulticamPlan, speech: list[Speech], start: float, end: float
) -> list[tuple[float, PhaseRule]]:
    """Instante em que cada fase abre: a primeira fala que casa com uma regra POSTERIOR à fase
    corrente (as regras vêm na ordem do rito). Repetir o termo da fase aberta não a reabre, e uma
    fase anterior não volta: senão cada "em nome do Pai" da troca de alianças reabriria a saudação
    e cada "aliança" da bênção reiniciaria a cadência, picotando o corte."""
    events: list[tuple[float, PhaseRule]] = []
    current = -1
    for s in sorted(speech, key=lambda item: item.start):
        if not start <= s.start < end:
            continue
        rule = _match_rule(s.text, plan.phases)
        if rule is None or plan.phases.index(rule) <= current:
            continue
        events.append((s.start, rule))
        current = plan.phases.index(rule)
    return events


def _phase_windows(plan: MulticamPlan, speech: list[Speech], start: float, end: float) -> list[_Window]:
    """Divide [start, end] em janelas de câmera principal/cadência: uma por fase reconhecida, com
    "geral" (main/cadence do bloco) antes da primeira fase e nas sobras de fases com `max_duration`."""
    events = _phase_events(plan, speech, start, end)
    windows: list[_Window] = []
    cursor = start
    if not events or events[0][0] > cursor:
        first_end = events[0][0] if events else end
        windows.append(_Window("geral", plan.main, plan.cadence, cursor, first_end))
        cursor = first_end
    for i, (t, rule) in enumerate(events):
        next_start = events[i + 1][0] if i + 1 < len(events) else end
        window_end = next_start
        capped = rule.max_duration is not None and t + rule.max_duration < window_end
        if capped:
            window_end = t + rule.max_duration
        windows.append(_Window(rule.name, rule.main or plan.main, rule.cadence, t, window_end))
        cursor = window_end
        if capped and window_end < next_start:
            windows.append(_Window("geral", plan.main, plan.cadence, window_end, next_start))
            cursor = next_start
    return [w for w in windows if w.end - w.start > _EPSILON]


def phase_windows(
    plan: MulticamPlan, speech: list[Speech], start: float, end: float
) -> list[tuple[str, float, float]]:
    """Fases reconhecidas em [start, end] pela fala, com o instante da sessão em que cada uma abre e
    fecha; para quem apresenta o plano ao usuário sem recalcular a lógica interna de `plan_cuts`."""
    return [(w.label, w.start, w.end) for w in _phase_windows(plan, speech, start, end)]


def _alternate(window: _Window, cameras: tuple[str, ...]) -> list[PlannedClip]:
    """Alterna principal/outra dentro da janela, começando pela principal; com mais de duas câmeras,
    revezam as secundárias."""
    others = [c for c in cameras if c != window.main] or [window.main]
    clips: list[PlannedClip] = []
    t = window.start
    turn_main = True
    other_index = 0
    while t < window.end - _EPSILON:
        if turn_main:
            camera, duration = window.main, window.cadence[0]
        else:
            camera, duration = others[other_index % len(others)], window.cadence[1]
            other_index += 1
        segment_end = min(t + duration, window.end)
        clips.append(PlannedClip(camera, t, segment_end, window.label, False))
        t = segment_end
        turn_main = not turn_main
    return clips


def _pauses(speech: list[Speech], pause: float) -> list[tuple[float, float]]:
    """Intervalos sem fala (>= `pause`) entre falas consecutivas, em ordem."""
    ordered = sorted(speech, key=lambda s: s.start)
    gaps = []
    for a, b in zip(ordered, ordered[1:], strict=False):
        if b.start - a.end >= pause:
            gaps.append((a.end, b.start))
    return gaps


def _snap_cuts(
    clips: list[PlannedClip], pauses: list[tuple[float, float]], window: float
) -> list[PlannedClip]:
    """Atrai cada ponto de troca interno para o meio da pausa de fala mais próxima dentro de ±`window`."""
    if len(clips) <= 1:
        return clips
    adjusted: list[float] = []
    previous = clips[0].start
    for clip in clips[1:]:
        boundary = clip.start
        midpoints = [(a + b) / 2 for a, b in pauses if abs((a + b) / 2 - boundary) <= window]
        snapped = min(midpoints, key=lambda m: abs(m - boundary)) if midpoints else boundary
        snapped = max(snapped, previous + _EPSILON)
        adjusted.append(snapped)
        previous = snapped
    starts = [clips[0].start, *adjusted]
    ends = [*adjusted, clips[-1].end]
    return [PlannedClip(c.camera, s, e, c.label, c.mute) for c, s, e in zip(clips, starts, ends, strict=True)]


def _covers_fully(camera: str, start: float, end: float, coverage: list[Coverage]) -> bool:
    """Se a câmera tem imagem em todo o intervalo [start, end], juntando seus trechos de cobertura."""
    if end - start <= _EPSILON:
        return True
    intervals = sorted(
        (c.start, c.end) for c in coverage if c.camera == camera and c.end > start and c.start < end
    )
    cursor = start
    for a, b in intervals:
        if a > cursor + _EPSILON:
            return False
        cursor = max(cursor, b)
        if cursor >= end - _EPSILON:
            return True
    return cursor >= end - _EPSILON


def _split_by_coverage(
    clip: PlannedClip, coverage: list[Coverage], cameras: tuple[str, ...]
) -> tuple[list[PlannedClip], list[str]]:
    """Parte o clipe nas fronteiras de cobertura: usa a câmera escolhida onde ela cobre, outra que
    cubra onde não cobre, e pula (com aviso) onde nenhuma cobre."""
    candidates = [clip.camera, *cameras]
    points = {clip.start, clip.end}
    for cov in coverage:
        if clip.start < cov.start < clip.end:
            points.add(cov.start)
        if clip.start < cov.end < clip.end:
            points.add(cov.end)
    ordered_points = sorted(points)

    pieces: list[tuple[float, float, str | None]] = []
    for a, b in zip(ordered_points, ordered_points[1:], strict=False):
        chosen = next((cam for cam in candidates if _covers_fully(cam, a, b, coverage)), None)
        pieces.append((a, b, chosen))

    merged: list[PlannedClip] = []
    warnings: list[str] = []
    gap_start: float | None = None
    for a, b, cam in pieces:
        if cam is None:
            gap_start = a if gap_start is None else gap_start
            continue
        if gap_start is not None:
            warnings.append(f"sem imagem de {gap_start:.2f} a {a:.2f}")
            gap_start = None
        if merged and merged[-1].camera == cam and abs(merged[-1].end - a) < _EPSILON:
            merged[-1] = PlannedClip(cam, merged[-1].start, b, clip.label, False)
        else:
            merged.append(PlannedClip(cam, a, b, clip.label, False))
    if gap_start is not None:
        warnings.append(f"sem imagem de {gap_start:.2f} a {clip.end:.2f}")
    return merged, warnings


def _touches(a: PlannedClip, b: PlannedClip) -> bool:
    return abs(a.end - b.start) < _EPSILON


def _merge_short_clips(clips: list[PlannedClip], min_clip: float) -> list[PlannedClip]:
    """Funde clipes menores que `min_clip` ao vizinho contíguo da mesma câmera, ou absorve no anterior
    (ou no seguinte, se não houver anterior contíguo)."""
    result = list(clips)
    i = 0
    while i < len(result):
        clip = result[i]
        if clip.end - clip.start >= min_clip - _EPSILON:
            i += 1
            continue
        prev = result[i - 1] if i > 0 and _touches(result[i - 1], clip) else None
        nxt = result[i + 1] if i + 1 < len(result) and _touches(clip, result[i + 1]) else None
        same_camera_neighbor = prev if prev is not None and prev.camera == clip.camera else None
        if same_camera_neighbor is None and nxt is not None and nxt.camera == clip.camera:
            same_camera_neighbor = nxt
        if same_camera_neighbor is prev and prev is not None:
            result[i - 1] = PlannedClip(prev.camera, prev.start, clip.end, prev.label, prev.mute)
            del result[i]
        elif same_camera_neighbor is nxt and nxt is not None:
            result[i + 1] = PlannedClip(nxt.camera, clip.start, nxt.end, nxt.label, nxt.mute)
            del result[i]
        elif prev is not None:
            result[i - 1] = PlannedClip(prev.camera, prev.start, clip.end, prev.label, prev.mute)
            del result[i]
        elif nxt is not None:
            result[i + 1] = PlannedClip(nxt.camera, clip.start, nxt.end, nxt.label, nxt.mute)
            del result[i]
        else:
            i += 1  # clipe isolado entre buracos: nada para fundir
    return result


def plan_cuts(
    plan: MulticamPlan, coverage: list[Coverage], speech: list[Speech], start: float, end: float
) -> tuple[list[PlannedClip], list[str]]:
    """Gera o corte automático de [start, end]: clipes contínuos (exceto buracos de cobertura
    avisados) alternando câmeras por fase, com trocas atraídas para pausas da fala."""
    if end - start <= _EPSILON:
        return [], []

    windows = _phase_windows(plan, speech, start, end)
    raw_clips = [c for window in windows for c in _alternate(window, plan.cameras)]

    pauses = _pauses(speech, plan.pause)
    snapped = _snap_cuts(raw_clips, pauses, plan.snap_window)

    resolved: list[PlannedClip] = []
    warnings: list[str] = []
    for clip in snapped:
        pieces, clip_warnings = _split_by_coverage(clip, coverage, plan.cameras)
        resolved.extend(pieces)
        warnings.extend(clip_warnings)

    merged = _merge_short_clips(resolved, plan.min_clip)
    final = [
        PlannedClip(c.camera, c.start, c.end, c.label, _covers_fully(plan.audio, c.start, c.end, coverage))
        for c in merged
    ]
    return final, warnings


def default_wedding_phases() -> tuple[PhaseRule, ...]:
    """Fases do rito católico de casamento, reconhecidas por termos ditos na celebração (ordem de
    exemplo; o objetivo é reconhecer o momento, não ser exaustivo)."""
    return (
        PhaseRule("acolhida", ("acolher os noivos", "entrada dos noivos"), cadence=(30.0, 40.0)),
        PhaseRule("saudacao", ("em nome do pai",)),
        PhaseRule(
            "leitura", ("leitura do livro", "leitura da carta", "palavra do senhor"), cadence=(50.0, 30.0)
        ),
        PhaseRule("salmo", ("salmo", "responsorial")),
        PhaseRule("evangelho", ("proclamação do evangelho", "evangelho de jesus cristo")),
        PhaseRule("homilia", ("palavra da salvação", "glória a vós senhor"), cadence=(40.0, 40.0)),
        PhaseRule("consentimento", ("vos pergunto", "livre e espontânea vontade"), cadence=(45.0, 25.0)),
        PhaseRule("votos", ("te recebo", "recebo-te"), cadence=(60.0, 20.0)),
        PhaseRule(
            "aliancas",
            (
                "abencoai estas aliancas",
                "recebe esta alianca",
                "recebei estas aliancas",
                "entrega das aliancas",
            ),
            cadence=(40.0, 30.0),
        ),
        PhaseRule("preces", ("rezemos ao senhor", "preces"), cadence=(30.0, 40.0)),
        PhaseRule("bencao", ("bênção nupcial", "derrame suas bênçãos"), cadence=(45.0, 25.0)),
        PhaseRule("assinaturas", ("assinar", "assinatura"), cadence=(35.0, 35.0)),
        PhaseRule(
            "encerramento", ("pode beijar", "beijar a noiva", "beijar a sua esposa"), cadence=(30.0, 30.0)
        ),
    )
