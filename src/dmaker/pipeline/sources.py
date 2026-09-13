"""Resolução e inspeção dos arquivos fonte: avulsos (`src`) e sincronizados (`sources`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import CardSegment, ClipSegment, Project
from ..media.probe import MediaInfo
from .context import Prober


@dataclass(frozen=True)
class Source:
    """Arquivo fonte de um trecho (None para cartões gerados). `offset` é o instante, no relógio da
    sessão, em que o arquivo começa (0 para arquivos avulsos)."""

    path: Path | None
    info: MediaInfo | None
    offset: float = 0.0
    audio_stream: int = 0
    name: str | None = None

    def stat_key(self) -> tuple[int, int] | None:
        if self.path is None:
            return None
        st = self.path.stat()
        return st.st_mtime_ns, st.st_size

    def in_point(self, session_time: float) -> float:
        """Tempo dentro do arquivo correspondente a um tempo da sessão."""
        return session_time - self.offset


def resolve_session(project: Project, prober: Prober, offsets: dict[str, float]) -> dict[str, Source]:
    """Fontes nomeadas (câmeras e gravadores) com seus deslocamentos."""
    session: dict[str, Source] = {}
    for name, ref in project.sources.items():
        path = project.resolve(ref.src)
        if not path.exists():
            raise FileNotFoundError(
                f"sources.{name}: arquivo não encontrado: {ref.src} (procurado em {path})"
            )
        session[name] = Source(path, prober(path), offsets.get(name, 0.0), ref.audio_stream, name)
    return session


def resolve_sources(
    project: Project, prober: Prober, session: dict[str, Source] | None = None
) -> list[Source]:
    session = session or {}
    sources: list[Source] = []
    for i, seg in enumerate(project.timeline):
        if isinstance(seg, CardSegment):
            sources.append(Source(None, None))
            continue
        if isinstance(seg, ClipSegment) and seg.source:
            if seg.source not in session:
                raise KeyError(f"timeline[{i}]: fonte {seg.source!r} não resolvida")
            source = session[seg.source]
            if source.info is None or not source.info.has_video:
                raise ValueError(f"timeline[{i}]: a fonte {seg.source!r} não tem vídeo.")
            sources.append(source)
            continue
        path = project.resolve(seg.src)
        if not path.exists():
            raise FileNotFoundError(f"timeline[{i}]: fonte não encontrada: {seg.src} (procurado em {path})")
        info = prober(path)
        if isinstance(seg, ClipSegment):
            if info.is_image:
                raise ValueError(f'timeline[{i}]: {seg.src} é uma imagem; use "type": "image".')
            if not info.has_video:
                raise ValueError(f"timeline[{i}]: {seg.src} não tem vídeo.")
        sources.append(Source(path, info))
    return sources
