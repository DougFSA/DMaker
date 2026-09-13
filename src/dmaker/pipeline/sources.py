"""Resolução e inspeção dos arquivos fonte da linha do tempo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import CardSegment, ClipSegment, Project
from ..media.probe import MediaInfo
from .context import Prober


@dataclass(frozen=True)
class Source:
    """Arquivo fonte de um trecho (None para cartões gerados)."""

    path: Path | None
    info: MediaInfo | None

    def stat_key(self) -> tuple[int, int] | None:
        if self.path is None:
            return None
        st = self.path.stat()
        return st.st_mtime_ns, st.st_size


def resolve_sources(project: Project, prober: Prober) -> list[Source]:
    sources: list[Source] = []
    for i, seg in enumerate(project.timeline):
        if isinstance(seg, CardSegment):
            sources.append(Source(None, None))
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
