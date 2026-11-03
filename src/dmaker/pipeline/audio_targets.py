"""Acha o item de áudio que uma operação de edição de onda mexe e liga o tempo da linha do tempo ao tempo dele.

A conta pura (`domain.audio_targets`) só precisa das janelas; aqui elas saem do que o render usa: o intervalo de cada
clipe, o PiP, a voz gravada (com a duração depois dos efeitos), a música (as janelas de `spans`) e as fatias da
faixa externa em cada clipe. Assim o que se edita é o que se ouve."""

from __future__ import annotations

import math

from ..domain.audio_effects import chain_duration
from ..domain.audio_targets import AudioTarget, TargetKind, Window, parse_target
from ..domain.edits import EditError
from ..domain.spec import ClipSegment, Project, VideoOverlay
from ..filtergraph.audio import resolve_span
from .layout import OriginAggregate
from .timeline_view import track_slice_windows
from .voicefiles import play_length

OPEN_END = math.inf  # o item não tem fim conhecido (a narração ainda não foi sintetizada)
PARTS_BLOCKER = (
    "a fonte deste trecho tem várias partes (`parts`) e o render processa o som parte a parte, então o tempo do "
    "item recomeça em cada uma; edite o som dele por `set_field` ou junte as partes antes"
)


def _out_of_range(label: str, index: int, count: int) -> EditError:
    return EditError(f"índice de {label} fora do intervalo: {index} (0 a {count - 1})")


def _total(layout: OriginAggregate) -> float:
    """A duração do projeto: a do layout (num projeto só de áudio ela vem do som dos itens, não de trechos de vídeo)."""
    if layout.physical is not None:
        return layout.physical.total
    return layout.spans[-1][1] if layout.spans else 0.0


def resolve_audio_target(project: Project, layout: OriginAggregate, target: object) -> AudioTarget:
    """O alvo escrito como o caminho dele na spec (`timeline.2`, `audio.voiceover.0`...), já com as janelas."""
    kind, index = parse_target(target)
    path = str(target)
    builder = _BUILDERS[kind]
    return builder(project, layout, path, index)


def _clip(project: Project, layout: OriginAggregate, path: str, index: int | None) -> AudioTarget:
    assert index is not None
    if not 0 <= index < len(project.timeline):
        raise _out_of_range("trecho", index, len(project.timeline))
    segment = project.timeline[index]
    if not isinstance(segment, ClipSegment):
        raise EditError(f"{path}: só o trecho de vídeo (clipe) tem som para editar")
    start, end = layout.spans[index]
    reference = project.sources.get(segment.source) if segment.source else None
    blocker = PARTS_BLOCKER if reference is not None and reference.parts else None
    return AudioTarget(
        path,
        "clip",
        index,
        f"clipe {index}",
        (Window(start, end, 0.0, segment.speed),),
        (end - start) * segment.speed,
        blocker,
    )


def _pip(project: Project, layout: OriginAggregate, path: str, index: int | None) -> AudioTarget:
    assert index is not None
    if not 0 <= index < len(project.overlays):
        raise _out_of_range("sobreposição", index, len(project.overlays))
    overlay = project.overlays[index]
    if not isinstance(overlay, VideoOverlay):
        raise EditError(f"{path}: só a sobreposição de vídeo (PiP) tem som para editar")
    end = _total(layout) if overlay.end is None else overlay.end
    return AudioTarget(
        path, "pip", index, f"PiP {index}", (Window(overlay.start, end, 0.0, 1.0),), end - overlay.start
    )


def _voiceover(project: Project, layout: OriginAggregate, path: str, index: int | None) -> AudioTarget:
    assert index is not None
    clips = project.audio.voiceover
    if not 0 <= index < len(clips):
        raise _out_of_range("voz gravada", index, len(clips))
    clip = clips[index]
    length = voiceover_length(project, layout, index)
    end = OPEN_END if length is None else clip.start + length
    return AudioTarget(
        path, "voiceover", index, f"voz gravada {index}", (Window(clip.start, end, 0.0, 1.0),), length
    )


def voiceover_length(project: Project, layout: OriginAggregate, index: int) -> float | None:
    """Quanto toca a voz gravada `index` depois dos efeitos dela, ou None se o arquivo não está lá para medir."""
    clip = project.audio.voiceover[index]
    path = project.resolve(clip.src)
    if not path.exists() or layout.physical is None:
        return None
    try:
        info = layout.physical.prober(path)
    except (OSError, ValueError, RuntimeError):
        return None
    return chain_duration(clip.effects, play_length(clip, info.duration))


def _narration(project: Project, layout: OriginAggregate, path: str, index: int | None) -> AudioTarget:
    assert index is not None
    items = project.audio.narration
    if not 0 <= index < len(items):
        raise _out_of_range("narração", index, len(items))
    # a duração real só se sabe depois de sintetizar: o item vale do começo dele até onde a fala for
    return AudioTarget(
        path, "narration", index, f"narração {index}", (Window(items[index].start, OPEN_END, 0.0, 1.0),)
    )


def _music(project: Project, layout: OriginAggregate, path: str, index: int | None) -> AudioTarget:
    music = project.audio.music
    if music is None:
        raise EditError("o projeto não tem música (audio.music)")
    total = _total(layout)
    duration = None
    if any(span.tail for span in music.spans) and layout.physical is not None:
        duration = layout.physical.prober(project.resolve(music.src)).duration
    windows = []
    for span in music.spans:
        start, end, start_at = resolve_span(span, total, duration)
        windows.append(Window(start, total if end is None else min(end, total), start_at, 1.0))
    if not windows:
        windows.append(Window(0.0, total, music.start_at, 1.0))
    return AudioTarget(path, "music", None, "música", tuple(windows))


def _track(project: Project, layout: OriginAggregate, path: str, index: int | None) -> AudioTarget:
    assert index is not None
    if not 0 <= index < len(project.audio.tracks):
        raise _out_of_range("faixa externa", index, len(project.audio.tracks))
    plays = track_slice_windows(project, layout.physical, index) if layout.physical else []
    windows = tuple(Window(p.window.start, p.window.end, p.window.file_in, p.speed) for p in plays)
    if not windows:
        raise EditError(f"{path}: a faixa externa não soa em nenhum trecho do vídeo")
    return AudioTarget(path, "track", index, f"faixa A{2 + index}", windows)


def _master(project: Project, layout: OriginAggregate, path: str, index: int | None) -> AudioTarget:
    total = _total(layout)
    return AudioTarget(path, "master", None, "mistura", (Window(0.0, total, 0.0, 1.0),), total)


_BUILDERS = {
    "clip": _clip,
    "pip": _pip,
    "voiceover": _voiceover,
    "narration": _narration,
    "music": _music,
    "track": _track,
    "master": _master,
}

# o fecho da conta de tipos: um tipo novo de alvo precisa de um construtor aqui
assert set(_BUILDERS) == set(TargetKind.__args__)  # type: ignore[attr-defined]
