"""Vista de linha do tempo multitrilha (estilo Shotcut) a partir da spec já resolvida (`ProjectLayout`).
Puro: só olha para o projeto e o layout, não toca disco nem executa nada.

Ordem das trilhas, de cima para baixo: sobreposições de vídeo (picture-in-picture) em V2, V3... (uma
faixa por grupo de itens que não se sobrepõem no tempo), "TX" (texto), "GR" (imagem + barra de
progresso), "V1" (trechos da linha do tempo, com a sobreposição das transições), "A1" (áudio de cada
clipe de V1), "A2", "A3"... (uma por faixa de `audio.tracks`, fatiada por clipe como no render), "NAR"
(narrações por texto), "MUS" (música) e "CC" (legendas)."""

from __future__ import annotations

from collections.abc import Sequence
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
from ..domain.timeline import stack_lanes as _lane_of
from ..filtergraph.audio import resolve_span
from .layout import ProjectLayout, to_presentation
from .missing import MissingMedia
from .sources import physical_source_names
from .track_slices import track_slice, track_window
from .voiceover import estimate_narration_duration, narration_label


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
    path: str | None = None  # caminho absoluto resolvido (project.resolve); None para cartão/texto
    missing: bool = False  # o arquivo não está no disco: o item abre marcado "fonte não encontrada"


@dataclass
class Track:
    id: str
    kind: Literal["video", "audio", "text", "graphics", "captions"]
    label: str
    items: list[TrackItem] = field(default_factory=list)
    muted: bool = False
    hidden: bool = False
    locked: bool = False


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
                {
                    "id": t.id,
                    "kind": t.kind,
                    "label": t.label,
                    "muted": t.muted,
                    "hidden": t.hidden,
                    "locked": t.locked,
                    "items": [asdict(item) for item in t.items],
                }
                for t in self.tracks
            ],
            "sources": self.sources,
            "warnings": self.warnings,
        }


def stack_lanes(items: list[TrackItem]) -> list[list[TrackItem]]:
    """Distribui itens numa sequência mínima de faixas: um item entra na primeira faixa cujo último
    item termina antes dele começar; senão abre uma faixa nova. Itens que se sobrepõem no tempo
    sempre acabam em faixas diferentes. Empilhamento em si é `domain.timeline.stack_lanes` (também
    usado por `domain.tracks.video_overlay_lanes` para aplicar oculto por trilha no render)."""
    order = sorted(range(len(items)), key=lambda i: items[i].start)
    lane_of = _lane_of([(items[i].start, items[i].end) for i in order])
    lanes: list[list[TrackItem]] = [[] for _ in range(max(lane_of, default=-1) + 1)]
    for position, i in enumerate(order):
        lanes[lane_of[position]].append(items[i])
    return lanes


def _resolve_item_path(project: Project, src: str | None, source: str | None) -> str | None:
    """Caminho absoluto do arquivo por trás de um item da vista (`project.resolve`, o mesmo usado
    pelo render em `pipeline.sources`): o do próprio trecho (`src`) ou o da fonte sincronizada
    nomeada (`source`, primeiro arquivo quando ela tem `parts`). None para cartão e texto, que não
    têm arquivo. É por causa deste caminho que a prévia mostra qualquer projeto (antes, `player.js`
    montava a URL a partir de `src` cru, que quebrava sempre que a fonte era relativa à pasta do
    projeto, como `"cards/abertura.png"`)."""
    if src:
        return str(project.resolve(src))
    if source:
        ref = project.sources.get(source)
        if ref:
            return str(project.resolve(ref.files[0]))
    return None


def _resolve_overlay_image_path(project: Project, src: str | None) -> str | None:
    """Como `_resolve_item_path`, mas preserva `None` para "logo"/"logo:variante" (não é um caminho
    de arquivo: o player resolve pelo tema)."""
    if not src or src == "logo" or src.startswith("logo:"):
        return None
    return str(project.resolve(src))


def _track_state(project: Project, track_id: str) -> tuple[bool, bool, bool]:
    """(muted, hidden, locked) salvos em `project.tracks` para esta trilha, ou tudo `False`."""
    state = project.tracks.get(track_id)
    if state is None:
        return False, False, False
    return state.muted, state.hidden, state.locked


def _resolve_end(end: float | None, total: float) -> float:
    return total if end is None else end


def _item_id(track_id: str, index: int) -> str:
    return f"{track_id}-{index}"


def _segment_label(segment: Segment) -> str:
    label = (
        getattr(segment, "label", None) or getattr(segment, "src", None) or getattr(segment, "source", None)
    )
    return str(label or getattr(segment, "title", "") or "")


def _video_overlay_items(project: Project, overlays: list[Overlay], total: float) -> list[TrackItem]:
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
                path=_resolve_item_path(project, ov.src, ov.source),
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


def _graphics_overlay_items(project: Project, overlays: list[Overlay], total: float) -> list[TrackItem]:
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
                    path=_resolve_overlay_image_path(project, ov.src),
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


def _clip_pieces(project: Project, physical: ProjectLayout, index: int) -> list[dict]:
    """Pedaços físicos de um clipe cuja fonte tem `parts`, um por arquivo que ele atravessa: onde cada
    um começa e termina na linha do tempo, que arquivo toca e em que ponto dele. O item da vista é um
    só por clipe da spec (a edição aponta para ele), mas imagem e som vêm da parte que grava cada
    instante, pela mesma partição do render (`expand_parts`). Vazio para clipe sem `parts`."""
    segment = project.timeline[index]
    if not isinstance(segment, ClipSegment) or not segment.source:
        return []
    ref = project.sources.get(segment.source)
    if ref is None or not ref.parts:
        return []
    pieces = []
    for j, origin in enumerate(physical.origin):
        if origin != index:
            continue
        piece = physical.project.timeline[j]
        source = physical.sources[j]
        start, end = physical.spans[j]
        pieces.append(
            {
                "start": start,
                "end": end,
                "in_point": source.in_point(piece.start),
                "path": str(source.path),
            }
        )
    return pieces


def _v1_items(project: Project, layout: ProjectLayout, physical: ProjectLayout) -> list[TrackItem]:
    items = []
    for i, (segment, (start, end)) in enumerate(zip(project.timeline, layout.spans, strict=True)):
        is_clip = isinstance(segment, ClipSegment)
        pieces = _clip_pieces(project, physical, i)
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
                extra={"pieces": pieces} if pieces else {},
                path=pieces[0]["path"]
                if pieces
                else _resolve_item_path(
                    project, getattr(segment, "src", None), segment.source if is_clip else None
                ),
            )
        )
    return items


def _a1_items(project: Project, layout: ProjectLayout, physical: ProjectLayout) -> list[TrackItem]:
    items = []
    for i, (segment, (start, end)) in enumerate(zip(project.timeline, layout.spans, strict=True)):
        if not isinstance(segment, ClipSegment):
            continue
        muted = segment.mute or segment.volume <= 0 or project.audio.mute_clips
        pieces = _clip_pieces(project, physical, i)
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
                extra={"speed": segment.speed, **({"pieces": pieces} if pieces else {})},
                path=pieces[0]["path"]
                if pieces
                else _resolve_item_path(project, segment.src, segment.source),
            )
        )
    return items


def _track_items(
    project: Project, physical: ProjectLayout, track_id: str, index: int, muted: bool
) -> list[TrackItem]:
    """Um item por trecho de clipe em que a faixa externa `audio.tracks[index]` soa, pela mesma conta
    do render (`pipeline.track_slices`, sobre as partes que `expand_parts` gerou): o arquivo certo, o
    ponto dele em `in_point` (tempo NO ARQUIVO, por isso `extra.offset` é zero) e o volume da faixa.
    Trecho que a faixa não cobre fica sem item; a velocidade do clipe (`extra.speed`) vale para o som."""
    audio_track = project.audio.tracks[index]
    names = physical_source_names(project, audio_track.source)
    found: list[TrackItem] = []
    for j, segment in enumerate(physical.project.timeline):
        if not isinstance(segment, ClipSegment) or not segment.source:
            continue  # o render só mistura faixas externas em clipes de fonte sincronizada
        for name in names:
            source = physical.session.get(name)
            if source is None or source.info is None:
                continue
            piece = track_slice(audio_track, source, segment)
            if piece is None:
                continue
            window = track_window(piece, source.info.duration, segment.speed, physical.spans[j])
            if window is None:
                continue
            found.append(
                TrackItem(
                    id="",  # a posição na trilha só é conhecida depois de ordenar
                    kind="track",
                    index=index,
                    label=audio_track.source,
                    start=window.start,
                    end=window.end,
                    in_point=window.file_in,
                    out_point=window.file_in + (window.end - window.start) * segment.speed,
                    src=None,
                    source=audio_track.source,
                    transition=None,
                    muted=audio_track.volume <= 0 or muted,
                    extra={"offset": 0.0, "speed": segment.speed, "volume": audio_track.volume},
                    path=str(piece.path),
                )
            )
    found.sort(key=lambda item: item.start)
    for position, item in enumerate(found):
        item.id = f"{_item_id(track_id, index)}-{position}"
    return found


def _audio_track_tracks(project: Project, physical: ProjectLayout) -> list[Track]:
    tracks = []
    for i in range(len(project.audio.tracks)):
        track_id = f"A{2 + i}"
        muted, hidden, locked = _track_state(project, track_id)
        tracks.append(
            Track(
                id=track_id,
                kind="audio",
                label=track_id,
                items=_track_items(project, physical, track_id, i, muted),
                muted=muted,
                hidden=hidden,
                locked=locked,
            )
        )
    return tracks


def _narration_track(
    project: Project, layout: ProjectLayout, durations: Sequence[float | None] = ()
) -> Track | None:
    """Uma narração por item. `durations` traz a duração real das já sintetizadas (None ou ausente = a
    estimativa por texto, marcada em `extra["estimated"]`)."""
    if not project.audio.narration:
        return None
    muted, hidden, locked = _track_state(project, "NAR")
    items = []
    for i, narration in enumerate(project.audio.narration):
        known = durations[i] if i < len(durations) else None
        duration = known if known is not None else estimate_narration_duration(project, narration)
        items.append(
            TrackItem(
                id=_item_id("NAR", i),
                kind="narration",
                index=i,
                label=narration_label(narration),
                start=narration.start,
                end=narration.start + duration,
                in_point=0.0,
                out_point=None,
                src=narration.script,
                source=None,
                transition=None,
                muted=narration.volume <= 0 or muted,
                extra={"voice": narration.voice, "estimated": known is None},
                path=str(project.resolve(narration.script)) if narration.script else None,
            )
        )
    return Track(id="NAR", kind="audio", label="NAR", items=items, muted=muted, hidden=hidden, locked=locked)


def _music_track(
    project: Project, layout: ProjectLayout, music_duration: float | None = None
) -> Track | None:
    music = project.audio.music
    if music is None:
        return None
    muted, hidden, locked = _track_state(project, "MUS")
    windows = [resolve_span(s, layout.total, music_duration) for s in music.spans] or [
        (0.0, None, music.start_at)
    ]
    path = str(project.resolve(music.src))
    items = [
        TrackItem(
            id=_item_id("MUS", i),
            kind="music",
            index=i,
            label=music.src,
            start=start,
            end=layout.total if end is None else min(end, layout.total),
            in_point=start_at,
            out_point=None,
            src=music.src,
            source=None,
            transition=None,
            muted=music.volume <= 0 or muted,
            extra={"loop": music.loop, "volume": music.volume},
            path=path,
        )
        for i, (start, end, start_at) in enumerate(windows)
    ]
    return Track(id="MUS", kind="audio", label="MUS", items=items, muted=muted, hidden=hidden, locked=locked)


def _captions_track(project: Project, layout: ProjectLayout) -> Track | None:
    captions = project.captions
    if captions is None or not captions.enabled:
        return None
    _, hidden, locked = _track_state(project, "CC")
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
    return Track(id="CC", kind="captions", label="CC", items=[item], hidden=hidden, locked=locked)


def _flag_missing(tracks: list[Track], missing: MissingMedia) -> None:
    """Marca os itens cujo arquivo (ou algum dos arquivos das partes) está ausente do disco."""
    for track in tracks:
        for item in track.items:
            pieces = [piece["path"] for piece in item.extra.get("pieces", [])]
            item.missing = missing.covers(item.path, *pieces)


def build_timeline_view(
    project: Project,
    layout: ProjectLayout,
    music_duration: float | None = None,
    narration_durations: Sequence[float | None] = (),
    missing: MissingMedia | None = None,
) -> TimelineView:
    """Monta a vista multitrilha: uma faixa por PiP que se sobrepõe, texto, gráficos, a linha do
    tempo principal, o áudio de cada clipe, cada faixa de áudio externa, a música e as legendas.
    Trechos de uma fonte com `parts` aparecem como um item só (agregado pelo trecho original).
    `music_duration` refina spans de música com `tail`; sem ela, a folga bruta é mostrada.
    `narration_durations` (uma por narração, ver `VoiceoverPreparer.cached_durations`) troca a
    estimativa pela duração real das narrações já sintetizadas. Cada item
    ganha `path` (caminho absoluto já resolvido pela spec) e cada trilha carrega o mudo/oculto/
    bloqueio salvo em `project.tracks` (`domain.tracks.apply_track_state` aplica o mesmo estado no
    render, para a prévia e o vídeo final nunca discordarem). `missing` (ver `pipeline/missing.py`) marca
    os itens de arquivos que sumiram do disco e traz um aviso por arquivo."""
    physical = layout  # com as `parts` já partidas: de onde vêm o arquivo e o ponto de cada som
    layout = to_presentation(project, layout)
    total = layout.total
    tracks: list[Track] = []

    for lane_index, lane in enumerate(stack_lanes(_video_overlay_items(project, project.overlays, total))):
        track_id = f"V{2 + lane_index}"
        muted, hidden, locked = _track_state(project, track_id)
        lane_sorted = sorted(lane, key=lambda it: it.start)
        for item in lane_sorted:
            item.id = _item_id(track_id, item.index)
        tracks.append(
            Track(
                id=track_id,
                kind="video",
                label=track_id,
                items=lane_sorted,
                muted=muted,
                hidden=hidden,
                locked=locked,
            )
        )

    tx_muted, tx_hidden, tx_locked = _track_state(project, "TX")
    tracks.append(
        Track(
            id="TX",
            kind="text",
            label="TX",
            items=_text_overlay_items(project.overlays, total),
            muted=tx_muted,
            hidden=tx_hidden,
            locked=tx_locked,
        )
    )
    gr_muted, gr_hidden, gr_locked = _track_state(project, "GR")
    tracks.append(
        Track(
            id="GR",
            kind="graphics",
            label="GR",
            items=_graphics_overlay_items(project, project.overlays, total),
            muted=gr_muted,
            hidden=gr_hidden,
            locked=gr_locked,
        )
    )
    v1_muted, v1_hidden, v1_locked = _track_state(project, "V1")
    tracks.append(
        Track(
            id="V1",
            kind="video",
            label="V1",
            items=_v1_items(project, layout, physical),
            muted=v1_muted,
            hidden=v1_hidden,
            locked=v1_locked,
        )
    )
    a1_muted, a1_hidden, a1_locked = _track_state(project, "A1")
    a1_items = _a1_items(project, layout, physical)
    if a1_muted:
        for item in a1_items:
            item.muted = True
    tracks.append(
        Track(
            id="A1",
            kind="audio",
            label="A1",
            items=a1_items,
            muted=a1_muted,
            hidden=a1_hidden,
            locked=a1_locked,
        )
    )
    tracks.extend(_audio_track_tracks(project, physical))

    narration_track = _narration_track(project, layout, narration_durations)
    if narration_track is not None:
        tracks.append(narration_track)

    music_track = _music_track(project, layout, music_duration)
    if music_track is not None:
        tracks.append(music_track)

    captions_track = _captions_track(project, layout)
    if captions_track is not None:
        tracks.append(captions_track)

    missing = missing or MissingMedia()
    _flag_missing(tracks, missing)
    sources = {
        name: {
            "src": ref.src or ref.parts[0],
            "parts": list(ref.parts),
            "offset": layout.offsets.get(name, 0.0),
            "in_point": 0.0,
            "path": str(project.resolve(ref.src or ref.parts[0])),
            "missing": missing.covers(*(project.resolve(raw) for raw in ref.files)),
        }
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
        warnings=[f"Fonte não encontrada: {path}" for path in sorted(missing.paths, key=str)],
    )
