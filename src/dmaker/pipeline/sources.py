"""Resolução e inspeção dos arquivos fonte: avulsos (`src`) e sincronizados (`sources`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import CardSegment, ClipSegment, Project, VideoOverlay
from ..media.probe import MediaInfo
from .context import Prober
from .partsync import PartOffsets

EPS = 1e-6  # tolerância de ponto flutuante ao conferir cobertura contínua entre partes


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


def resolve_session(
    project: Project,
    prober: Prober,
    offsets: dict[str, float],
    part_offsets: PartOffsets | None = None,
) -> dict[str, Source]:
    """Fontes nomeadas (câmeras e gravadores) com seus deslocamentos. Fonte com `parts` vira uma
    entrada por parte, com nome interno `nome#k` (o início de cada uma vem de `part_offsets`)."""
    part_offsets = part_offsets or {}
    session: dict[str, Source] = {}
    for name, ref in project.sources.items():
        if ref.parts:
            starts = part_offsets.get(name)
            if starts is None or len(starts) != len(ref.parts):
                raise ValueError(f"sources.{name}: sincronização das partes não foi calculada")
            for k, (filename, start) in enumerate(zip(ref.parts, starts, strict=True)):
                path = project.resolve(filename)
                if not path.exists():
                    raise FileNotFoundError(
                        f"sources.{name}: parte {k} não encontrada: {filename} (procurado em {path})"
                    )
                key = f"{name}#{k}"
                session[key] = Source(path, prober(path), start, ref.audio_stream, key)
            continue
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


def _coverage(session: dict[str, Source], name: str, count: int) -> list[tuple[float, float]]:
    """Intervalo (início, fim) de cada parte de `name` no relógio da sessão, na ordem das partes."""
    spans = []
    for k in range(count):
        source = session[f"{name}#{k}"]
        assert source.info is not None
        spans.append((source.offset, source.offset + source.info.duration))
    return spans


def _split_clip_over_parts(
    index: int, segment: ClipSegment, coverage: list[tuple[float, float]]
) -> list[ClipSegment]:
    """Divide `segment` (com `source` numa fonte com `parts`) em um pedaço por parte que ele cobre,
    cada um apontando para `nome#k`. Transição e fades ficam só na primeira/última peça: as demais
    fronteiras são cortes internos do mesmo trecho, não transições visíveis."""
    name = segment.source
    assert name is not None
    end = segment.end if segment.end is not None else coverage[-1][1]
    pieces: list[tuple[int, float, float]] = []
    for k, (start, stop) in enumerate(coverage):
        piece_start, piece_end = max(segment.start, start), min(end, stop)
        if piece_end > piece_start:
            pieces.append((k, piece_start, piece_end))
    ranges = ", ".join(f"{a:.2f}s-{b:.2f}s" for a, b in coverage)
    if (
        not pieces
        or abs(pieces[0][1] - segment.start) > EPS
        or abs(pieces[-1][2] - end) > EPS
        or any(abs(b[1] - a[2]) > EPS for a, b in zip(pieces, pieces[1:], strict=False))
    ):
        raise ValueError(
            f"timeline[{index}]: fonte {name!r} não cobre {segment.start:.2f}s a {end:.2f}s inteiro "
            f"da sessão: partes cobrem {ranges}"
        )
    last = len(pieces) - 1
    return [
        segment.model_copy(
            update={
                "source": f"{name}#{k}",
                "start": piece_start,
                "end": piece_end,
                "transition": segment.transition if i == 0 else None,
                "fade_in": segment.fade_in if i == 0 else 0.0,
                "fade_out": segment.fade_out if i == last else 0.0,
            }
        )
        for i, (k, piece_start, piece_end) in enumerate(pieces)
    ]


def _overlay_part(
    overlay: VideoOverlay, coverage: list[tuple[float, float]], warn: Callable[[str], None]
) -> int:
    """Parte que cobre o início da sobreposição; avisa (sem partir o PiP) se ele não couber inteiro
    numa parte só."""
    duration = (overlay.end - overlay.start) if overlay.end is not None else None
    for k, (start, stop) in enumerate(coverage):
        if start <= overlay.offset < stop:
            if duration is not None and overlay.offset + duration > stop + EPS:
                warn(f"sobreposição com source={overlay.source!r}: passa do fim da parte {k}; confira o PiP")
            return k
    warn(f"sobreposição com source={overlay.source!r}: offset {overlay.offset:.2f}s fora de todas as partes")
    return 0


def expand_parts(
    project: Project,
    session: dict[str, Source],
    part_offsets: PartOffsets,
    log: Callable[[str], None] | None = None,
) -> tuple[Project, list[int]]:
    """Projeto físico: clipes e faixas com `source` numa fonte de `parts` partidos nas fronteiras dos
    arquivos, cada pedaço apontando para `nome#k`. `origin[j]` é o índice, na linha do tempo
    ORIGINAL, de que o trecho físico `j` veio (para quem apresenta ao usuário agregar de volta).
    Sem nenhuma fonte com `parts`, devolve o projeto igual e a identidade."""
    parted = {name for name, ref in project.sources.items() if ref.parts}
    if not parted:
        return project, list(range(len(project.timeline)))
    warn = log or (lambda message: None)
    coverage = {name: _coverage(session, name, len(project.sources[name].parts)) for name in parted}

    timeline: list = []
    origin: list[int] = []
    for i, segment in enumerate(project.timeline):
        if isinstance(segment, ClipSegment) and segment.source in parted:
            pieces = _split_clip_over_parts(i, segment, coverage[segment.source])
            timeline.extend(pieces)
            origin.extend([i] * len(pieces))
        else:
            timeline.append(segment)
            origin.append(i)

    tracks = []
    for track in project.audio.tracks:
        if track.source in parted:
            tracks.extend(
                track.model_copy(update={"source": f"{track.source}#{k}"})
                for k in range(len(coverage[track.source]))
            )
        else:
            tracks.append(track)

    overlays = []
    for overlay in project.overlays:
        if isinstance(overlay, VideoOverlay) and overlay.source in parted:
            k = _overlay_part(overlay, coverage[overlay.source], warn)
            overlays.append(overlay.model_copy(update={"source": f"{overlay.source}#{k}"}))
        else:
            overlays.append(overlay)

    physical = project.model_copy(
        update={
            "timeline": timeline,
            "overlays": overlays,
            "audio": project.audio.model_copy(update={"tracks": tracks}),
        }
    )
    physical.base_dir = project.base_dir
    return physical, origin
