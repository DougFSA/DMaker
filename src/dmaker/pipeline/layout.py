"""Camada calculada de um projeto: fontes resolvidas, durações e intervalos na linha do tempo final.
Extraído de `summarize` para ser reaproveitado pelas edições e pela vista multitrilha.

`sources`/`durations`/`spans` se referem à linha do tempo FÍSICA (`project`): fontes com `parts`
já partem os trechos nas fronteiras dos arquivos, então o projeto físico pode ter mais trechos do
que a spec original. `origin[j]` é o índice, na timeline original, de que o trecho físico `j` veio;
`aggregate_by_origin` devolve a visão por trecho original (duração somada, intervalo do primeiro ao
último pedaço) para quem apresenta ao usuário (resumo, vista de linha do tempo, edições, QA)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..domain.brand import Theme, load_theme
from ..domain.presets import Preset, get_preset
from ..domain.spec import Project
from ..domain.timeline import segment_duration, timeline_spans, transitions_of
from ..media.ffmpeg import SubprocessRunner
from ..media.probe import probe
from .context import Prober
from .sources import Source, expand_parts, resolve_session, resolve_sources
from .sync import OffsetFinder, SyncResolver, ffmpeg_offset_finder


@dataclass
class ProjectLayout:
    """Tudo que depende de olhar para as fontes e calcular tempos, sem opinar sobre avisos ou render."""

    sources: list[Source]
    durations: list[float]
    spans: list[tuple[float, float]]
    total: float
    offsets: dict[str, float]  # fontes sincronizadas: início no relógio da sessão
    theme: Theme
    preset: Preset
    project: Project  # projeto FÍSICO (parts já partidas); quem renderiza usa este, não o original
    origin: list[int] = field(default_factory=list)  # trecho físico -> índice na timeline original
    warnings: list[str] = field(default_factory=list)  # avisos da sincronização (ex.: cadeia por relógio)
    session: dict[str, Source] = field(default_factory=dict)  # fontes nomeadas (`nome#k` nas partes)


def project_layout(
    project: Project, prober: Prober = probe, offset_finder: OffsetFinder | None = None
) -> ProjectLayout:
    """Resolve fontes (sincronizando as que forem `sync: "auto"`, encadeando as fontes com `parts`),
    parte a linha do tempo nas fronteiras dos arquivos e calcula duração/intervalo de cada trecho
    físico, já descontando transições."""
    theme = load_theme(project.brand, project.theme)
    preset = get_preset(project.output.preset)
    finder = offset_finder or ffmpeg_offset_finder(SubprocessRunner(quiet=True))
    store = (project.base_dir / "sync.json") if project.base_dir else None
    resolution = SyncResolver(finder, prober=prober).resolve(project, store)
    session = resolve_session(project, prober, resolution.offsets, resolution.parts)
    physical, origin = expand_parts(project, session, resolution.parts)
    sources = resolve_sources(physical, prober, session)
    durations = [
        segment_duration(seg, s.info, s.offset) for seg, s in zip(physical.timeline, sources, strict=True)
    ]
    spans = timeline_spans(durations, transitions_of(physical.timeline))
    total = spans[-1][1] if spans else 0.0
    return ProjectLayout(
        sources,
        durations,
        spans,
        total,
        resolution.offsets,
        theme,
        preset,
        physical,
        origin,
        resolution.warnings,
        session,
    )


@dataclass
class OriginAggregate:
    """Visão por trecho ORIGINAL de um `ProjectLayout` físico: duração somada, intervalo do primeiro
    ao último pedaço e a fonte (com a duração da cobertura inteira, não só a da primeira parte) que
    o trecho usa. `media_limits[i]` é até onde o trecho pode crescer (fim coberto pela fonte)."""

    durations: list[float]
    spans: list[tuple[float, float]]
    sources: list[Source]
    media_limits: list[float | None]


def aggregate_by_origin(project: Project, layout: ProjectLayout) -> OriginAggregate:
    """Agrega os campos físicos de `layout` de volta para o tamanho da timeline ORIGINAL de
    `project`, usando `layout.origin`. Sem trechos partidos, é uma cópia trecho a trecho."""
    count = len(project.timeline)
    durations = [0.0] * count
    starts: list[float | None] = [None] * count
    ends: list[float | None] = [None] * count
    first: list[Source | None] = [None] * count
    last: list[Source | None] = [None] * count
    for j, o in enumerate(layout.origin):
        durations[o] += layout.durations[j]
        start, end = layout.spans[j]
        starts[o] = start if starts[o] is None else min(starts[o], start)
        ends[o] = end if ends[o] is None else max(ends[o], end)
        if first[o] is None:
            first[o] = layout.sources[j]
        last[o] = layout.sources[j]
    spans = [(starts[i] or 0.0, ends[i] or 0.0) for i in range(count)]

    sources: list[Source] = []
    media_limits: list[float | None] = []
    for first_piece, last_piece in zip(first, last, strict=True):
        if (
            first_piece is None
            or first_piece.info is None
            or last_piece is None
            or last_piece.info is None
            or first_piece is last_piece
        ):
            sources.append(first_piece if first_piece is not None else Source(None, None))
            media_limits.append(
                (first_piece.offset + first_piece.info.duration) if first_piece and first_piece.info else None
            )
            continue
        limit = last_piece.offset + last_piece.info.duration
        merged_info = replace(first_piece.info, duration=max(limit - first_piece.offset, 0.0))
        sources.append(
            Source(
                first_piece.path, merged_info, first_piece.offset, first_piece.audio_stream, first_piece.name
            )
        )
        media_limits.append(limit)
    return OriginAggregate(durations, spans, sources, media_limits)


def to_presentation(project: Project, layout: ProjectLayout) -> ProjectLayout:
    """`layout` com `sources`/`durations`/`spans` agregados por trecho original: o que `summarize`,
    `timeline_view` e o relatório de QA mostram ao usuário (índices batem com a spec, não com o
    projeto físico)."""
    agg = aggregate_by_origin(project, layout)
    return replace(layout, sources=agg.sources, durations=agg.durations, spans=agg.spans)
