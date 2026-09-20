"""Estado de trilha (mudo, oculto, bloqueado) da vista multitrilha da interface, aplicado à spec.

`apply_track_state` existe porque, como no Shotcut, mudar ou ocultar uma trilha no editor precisa
valer tanto para a prévia ao vivo quanto para o RENDER final: sem isso, o usuário silenciaria uma
faixa na interface e ela continuaria audível no vídeo exportado. `locked` é só da interface (trava
seleção/arraste dos itens da trilha) e não muda nada aqui."""

from __future__ import annotations

from .spec import ImageOverlay, ProgressBar, Project, TextOverlay, VideoOverlay
from .timeline import stack_lanes


def video_overlay_lanes(project: Project) -> dict[int, int]:
    """Faixa (0 = V2, 1 = V3...) de cada sobreposição de vídeo (picture-in-picture) de
    `project.overlays`, pela mesma regra de empilhamento da vista multitrilha
    (`pipeline.timeline_view.stack_lanes`): duas que não se cruzam no tempo dividem a mesma faixa.
    Chave do dicionário devolvido = índice em `project.overlays`."""
    video_indices = [i for i, ov in enumerate(project.overlays) if isinstance(ov, VideoOverlay)]
    intervals = []
    for i in video_indices:
        ov = project.overlays[i]
        end = ov.end if ov.end is not None else float("inf")
        intervals.append((ov.start, end))
    lane_of = stack_lanes(intervals)
    return dict(zip(video_indices, lane_of, strict=True))


def known_track_ids(project: Project) -> set[str]:
    """ids de trilha que fazem sentido para esta spec (as mesmas que `build_timeline_view`
    mostraria): usado pelo lint para avisar de um id desconhecido em `project.tracks`."""
    ids = {"V1", "A1", "TX", "GR", "CC", "MUS"}
    ids.update(f"A{2 + i}" for i in range(len(project.audio.tracks)))
    lanes = video_overlay_lanes(project)
    ids.update(f"V{2 + lane}" for lane in set(lanes.values()))
    return ids


def apply_track_state(project: Project) -> Project:
    """Spec equivalente com o mudo/oculto de `project.tracks` já embutido nos campos que o render
    realmente olha, para o resto do pipeline não precisar saber que trilhas da interface existem:

    - A1 muda -> `audio.mute_clips = True` (mudo do áudio de cada clipe da V1).
    - A<n> muda, n>=2 -> remove `audio.tracks[n-2]` (a faixa externa some da mixagem).
    - MUS muda -> `audio.music = None`.
    - CC oculta -> `captions.enabled = False`.
    - TX oculta -> remove as sobreposições de texto.
    - GR oculta -> remove as sobreposições de imagem e a barra de progresso.
    - V<n> oculta, n>=2 -> remove as sobreposições de vídeo (PiP) daquela faixa
      (`video_overlay_lanes` decide qual PiP é de qual faixa).
    - V1 oculta é ignorada (é a linha do tempo principal; não há como renderizar sem ela) e
      `locked` nunca muda o render, só a edição na interface.

    Nunca modifica `project`; devolve o mesmo objeto quando não há nada a aplicar."""
    tracks = project.tracks
    if not tracks:
        return project

    audio = project.audio
    a1 = tracks.get("A1")
    if a1 and a1.muted and not audio.mute_clips:
        audio = audio.model_copy(update={"mute_clips": True})

    remaining_tracks = [track for i, track in enumerate(audio.tracks) if not _muted(tracks, f"A{2 + i}")]
    if len(remaining_tracks) != len(audio.tracks):
        audio = audio.model_copy(update={"tracks": remaining_tracks})

    if _muted(tracks, "MUS") and audio.music is not None:
        audio = audio.model_copy(update={"music": None})

    captions = project.captions
    if _hidden(tracks, "CC") and captions is not None and captions.enabled:
        captions = captions.model_copy(update={"enabled": False})

    overlays = project.overlays
    tx_hidden = _hidden(tracks, "TX")
    gr_hidden = _hidden(tracks, "GR")
    hidden_lanes = {
        int(track_id[1:]) - 2
        for track_id, state in tracks.items()
        if state.hidden and track_id != "V1" and track_id.startswith("V") and track_id[1:].isdigit()
    }
    if tx_hidden or gr_hidden or hidden_lanes:
        lanes = video_overlay_lanes(project) if hidden_lanes else {}
        overlays = [
            ov
            for i, ov in enumerate(overlays)
            if not (tx_hidden and isinstance(ov, TextOverlay))
            and not (gr_hidden and isinstance(ov, ImageOverlay | ProgressBar))
            and not (isinstance(ov, VideoOverlay) and lanes.get(i) in hidden_lanes)
        ]

    if audio is project.audio and captions is project.captions and overlays is project.overlays:
        return project
    updated = project.model_copy(update={"audio": audio, "captions": captions, "overlays": overlays})
    updated.base_dir = project.base_dir
    return updated


def _muted(tracks: dict, track_id: str) -> bool:
    state = tracks.get(track_id)
    return bool(state and state.muted)


def _hidden(tracks: dict, track_id: str) -> bool:
    state = tracks.get(track_id)
    return bool(state and state.hidden)
