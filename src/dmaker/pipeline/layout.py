"""Camada calculada de um projeto: fontes resolvidas, durações e intervalos na linha do tempo final.
Extraído de `summarize` para ser reaproveitado pelas edições e pela vista multitrilha."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.brand import Theme, load_theme
from ..domain.presets import Preset, get_preset
from ..domain.spec import Project
from ..domain.timeline import segment_duration, timeline_spans, transitions_of
from ..media.ffmpeg import SubprocessRunner
from ..media.probe import probe
from .context import Prober
from .sources import Source, resolve_session, resolve_sources
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


def project_layout(
    project: Project, prober: Prober = probe, offset_finder: OffsetFinder | None = None
) -> ProjectLayout:
    """Resolve fontes (sincronizando as que forem `sync: "auto"`), calcula a duração de cada trecho
    e o intervalo (início, fim) de cada um na linha do tempo final, já descontando transições."""
    theme = load_theme(project.brand, project.theme)
    preset = get_preset(project.output.preset)
    finder = offset_finder or ffmpeg_offset_finder(SubprocessRunner(quiet=True))
    store = (project.base_dir / "sync.json") if project.base_dir else None
    offsets = SyncResolver(finder).resolve(project, store)
    session = resolve_session(project, prober, offsets)
    sources = resolve_sources(project, prober, session)
    durations = [
        segment_duration(seg, s.info, s.offset) for seg, s in zip(project.timeline, sources, strict=True)
    ]
    spans = timeline_spans(durations, transitions_of(project.timeline))
    total = spans[-1][1] if spans else 0.0
    return ProjectLayout(sources, durations, spans, total, offsets, theme, preset)
