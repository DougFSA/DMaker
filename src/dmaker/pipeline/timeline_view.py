"""Vista de linha do tempo multitrilha (estilo Shotcut) a partir da spec já resolvida (`ProjectLayout`).
Puro: só olha para o projeto e o layout, não toca disco nem executa nada.

Ordem das trilhas, de cima para baixo: sobreposições de vídeo (picture-in-picture) em V2, V3... (uma
faixa por grupo de itens que não se sobrepõem no tempo), "TX" (texto), "GR" (imagem + barra de
progresso), "V1" (trechos da linha do tempo, com a sobreposição das transições), "A1" (áudio de cada
clipe de V1), "A2", "A3"... (uma por faixa de `audio.tracks`), "MUS" (música) e "CC" (legendas)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from ..domain.spec import (
    ClipSegment,
    ImageOverlay,
    Overlay,
    ProgressBar,
    Project,
    Segment,
    TextOverlay,
    VideoOverlay,
)
from .layout import ProjectLayout


@dataclass
class TrackItem:
    id: str
    kind: str
    index: int  # posição de origem (timeline, overlays ou audio.tracks)
    label: str
    start: float
    end: float
    in_point: float
    out_point: float | None
    src: str | None
    source: str | None
    transition: dict | None
    muted: bool
    extra: dict = field(default_factory=dict)


@dataclass
class Track:
    id: str
    kind: Literal["video", "audio", "text", "graphics", "captions"]
    label: str
    items: list[TrackItem] = field(default_factory=list)


@dataclass
class TimelineView:
    total: float
    fps: float
    width: int
    height: int
    tracks: list[Track] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "tracks": [
                {"id": t.id, "kind": t.kind, "label": t.label, "items": [asdict(item) for item in t.items]}
                for t in self.tracks
            ],
            "sources": self.sources,
            "warnings": self.warnings,
        }


def stack_lanes(items: list[TrackItem]) -> list[list[TrackItem]]:
    """Distribui itens numa sequência mínima de faixas: um item entra na primeira faixa cujo último
    item termina antes dele começar; senão abre uma faixa nova. Itens que se sobrepõem no tempo
    sempre acabam em faixas diferentes."""
    lanes: list[list[TrackItem]] = []
    for item in sorted(items, key=lambda it: it.start):
        for lane in lanes:
            if lane[-1].end <= item.start:
                lane.append(item)
                break
        else:
            lanes.append([item])
    return lanes


def _resolve_end(end: float | None, total: float) -> float:
    return total if end is None else end


def _item_id(track_id: str, index: int) -> str:
    return f"{track_id}-{index}"


def _segment_label(segment: Segment) -> str:
    label = (
        getattr(segment, "label", None) or getattr(segment, "src", None) or getattr(segment, "source", None)
    )
    return str(label or getattr(segment, "title", "") or "")


def _video_overlay_items(overlays: list[Overlay], total: float) -> list[TrackItem]:
    items = []
    for i, ov in enumerate(overlays):
        if not isinstance(ov, VideoOverlay):
            continue
        end = _resolve_end(ov.end, total)
        items.append(
            TrackItem(
                id="",  # a trilha (faixa/lane) só é conhecida depois do stack_lanes
                kind="video",
                index=i,
                label=ov.src or ov.source or "picture-in-picture",
                start=ov.start,
                end=end,
                in_point=ov.offset,
                out_point=ov.offset + (end - ov.start),
                src=ov.src,
                source=ov.source,
                transition=None,
                muted=ov.volume <= 0,
                extra={"position": ov.position, "shape": ov.shape},
            )
        )
    return items


def _text_overlay_items(overlays: list[Overlay], total: float) -> list[TrackItem]:
    items = []
    for i, ov in enumerate(overlays):
        if not isinstance(ov, TextOverlay):
            continue
        items.append(
            TrackItem(
                id=_item_id("TX", i),
                kind="text",
                index=i,
                label=ov.text,
                start=ov.start,
                end=_resolve_end(ov.end, total),
                in_point=0.0,
                out_point=None,
                src=None,
                source=None,
                transition=None,
                muted=False,
                extra={"role": ov.role},
            )
        )
    return items


def _graphics_overlay_items(overlays: list[Overlay], total: float) -> list[TrackItem]:
    items = []
    for i, ov in enumerate(overlays):
        if isinstance(ov, ImageOverlay):
            items.append(
                TrackItem(
                    id=_item_id("GR", i),
                    kind="image",
                    index=i,
                    label=ov.src,
                    start=ov.start,
                    end=_resolve_end(ov.end, total),
                    in_point=0.0,
                    out_point=None,
                    src=ov.src,
                    source=None,
                    transition=None,
                    muted=False,
                    extra={"position": ov.position},
                )
            )
        elif isinstance(ov, ProgressBar):
            items.append(
                TrackItem(
                    id=_item_id("GR", i),
                    kind="progress-bar",
                    index=i,
                    label="progress-bar",
                    start=0.0,
                    end=total,
                    in_point=0.0,
                    out_point=None,
                    src=None,
                    source=None,
                    transition=None,
                    muted=False,
                    extra={"position": ov.position},
                )
            )
    return items


def _v1_items(project: Project, layout: ProjectLayout) -> list[TrackItem]:
    items = []
    for i, (segment, (start, end)) in enumerate(zip(project.timeline, layout.spans, strict=True)):
        is_clip = isinstance(segment, ClipSegment)
        items.append(
            TrackItem(
                id=_item_id("V1", i),
                kind=segment.type,
                index=i,
                label=_segment_label(segment),
                start=start,
                end=end,
                in_point=segment.start if is_clip else 0.0,
                out_point=segment.end if is_clip else None,
                src=getattr(segment, "src", None),
                source=segment.source if is_clip else None,
                transition=segment.transition.model_dump() if segment.transition else None,
                muted=is_clip and (segment.mute or segment.volume <= 0),
                extra={},
            )
        )
    return items


def _a1_items(project: Project, layout: ProjectLayout) -> list[TrackItem]:
    items = []
    for i, (segment, (start, end)) in enumerate(zip(project.timeline, layout.spans, strict=True)):
        if not isinstance(segment, ClipSegment):
            continue
        muted = segment.mute or segment.volume <= 0 or project.audio.mute_clips
        items.append(
            TrackItem(
                id=_item_id("A1", i),
                kind="clip-audio",
                index=i,
                label=_segment_label(segment),
                start=start,
                end=end,
                in_point=segment.start,
                out_point=segment.end,
                src=segment.src,
                source=segment.source,
                transition=None,
                muted=muted,
                extra={"speed": segment.speed},
            )
        )
    return items


def _audio_track_tracks(project: Project, layout: ProjectLayout) -> list[Track]:
    tracks = []
    for i, audio_track in enumerate(project.audio.tracks):
        track_id = f"A{2 + i}"
        item = TrackItem(
            id=_item_id(track_id, i),
            kind="track",
            index=i,
            label=audio_track.source,
            start=0.0,
            end=layout.total,
            in_point=0.0,
            out_point=None,
            src=None,
            source=audio_track.source,
            transition=None,
            muted=audio_track.volume <= 0,
            extra={"offset": layout.offsets.get(audio_track.source, 0.0)},
        )
        tracks.append(Track(id=track_id, kind="audio", label=track_id, items=[item]))
    return tracks


def _music_track(project: Project, layout: ProjectLayout) -> Track | None:
    music = project.audio.music
    if music is None:
        return None
    item = TrackItem(
        id=_item_id("MUS", 0),
        kind="music",
        index=0,
        label=music.src,
        start=0.0,
        end=layout.total,
        in_point=music.start_at,
        out_point=None,
        src=music.src,
        source=None,
        transition=None,
        muted=music.volume <= 0,
        extra={"loop": music.loop},
    )
    return Track(id="MUS", kind="audio", label="MUS", items=[item])


def _captions_track(project: Project, layout: ProjectLayout) -> Track | None:
    captions = project.captions
    if captions is None or not captions.enabled:
        return None
    item = TrackItem(
        id=_item_id("CC", 0),
        kind="captions",
        index=0,
        label=captions.source,
        start=0.0,
        end=layout.total,
        in_point=0.0,
        out_point=None,
        src=None,
        source=None,
        transition=None,
        muted=False,
        extra={},
    )
    return Track(id="CC", kind="captions", label="CC", items=[item])


def build_timeline_view(project: Project, layout: ProjectLayout) -> TimelineView:
    """Monta a vista multitrilha: uma faixa por PiP que se sobrepõe, texto, gráficos, a linha do
    tempo principal, o áudio de cada clipe, cada faixa de áudio externa, a música e as legendas."""
    total = layout.total
    tracks: list[Track] = []

    for lane_index, lane in enumerate(stack_lanes(_video_overlay_items(project.overlays, total))):
        track_id = f"V{2 + lane_index}"
        lane_sorted = sorted(lane, key=lambda it: it.start)
        for item in lane_sorted:
            item.id = _item_id(track_id, item.index)
        tracks.append(Track(id=track_id, kind="video", label=track_id, items=lane_sorted))

    tracks.append(Track(id="TX", kind="text", label="TX", items=_text_overlay_items(project.overlays, total)))
    tracks.append(
        Track(id="GR", kind="graphics", label="GR", items=_graphics_overlay_items(project.overlays, total))
    )
    tracks.append(Track(id="V1", kind="video", label="V1", items=_v1_items(project, layout)))
    tracks.append(Track(id="A1", kind="audio", label="A1", items=_a1_items(project, layout)))
    tracks.extend(_audio_track_tracks(project, layout))

    music_track = _music_track(project, layout)
    if music_track is not None:
        tracks.append(music_track)

    captions_track = _captions_track(project, layout)
    if captions_track is not None:
        tracks.append(captions_track)

    sources = {
        name: {"src": ref.src, "offset": layout.offsets.get(name, 0.0), "in_point": 0.0}
        for name, ref in project.sources.items()
    }
    fps = project.output.fps or layout.preset.fps
    return TimelineView(
        total=total,
        fps=fps,
        width=layout.preset.width,
        height=layout.preset.height,
        tracks=tracks,
        sources=sources,
        warnings=[],
    )
