"""Onde cada item de áudio cai na linha do tempo do projeto (`AudioItem.placement`), para o Vocoder achar o trecho da trilha
portadora que toca junto com ele. Cada trilha hospedeira tem a sua conta, mas todas devolvem `PlacedRun`.

Sem a passada prévia das portadoras (`ctx.carrier_tracks`, que só existe quando um efeito usa `carrier_track`) ninguém lê o
resultado, então as contas que dependem da linha do tempo devolvem vazio e nada é calculado.
"""

from __future__ import annotations

from ..domain.carrier_tracks import PlacedRun
from ..domain.music_tempo import music_grid
from ..filtergraph.audio import resolve_span
from .context import RenderContext
from .track_slices import clip_windows


def clip_placement(ctx: RenderContext, index: int, duration: float, speed: float) -> tuple[PlacedRun, ...]:
    """Onde o som da câmera do clipe `index` cai na linha do tempo: o item (o trecho da fonte, no tempo dela e antes da velocidade)
    começa onde o clipe começa e toca por `duration` segundos do projeto."""
    tracks = ctx.carrier_tracks
    if tracks is None or not 0 <= index < len(tracks.spans):
        return ()
    return (PlacedRun(0.0, tracks.spans[index][0], duration, speed),)


def track_placement(ctx: RenderContext, track_index: int) -> tuple[PlacedRun, ...]:
    """Onde o arquivo inteiro da faixa externa física `track_index` toca: um trecho por clipe que a ouve (a partir de `file_in` do
    arquivo, por `window.end - window.start` segundos do projeto, na velocidade do clipe)."""
    tracks = ctx.carrier_tracks
    if tracks is None or track_index >= len(ctx.project.audio.tracks):
        return ()
    track = ctx.project.audio.tracks[track_index]
    return tuple(
        PlacedRun(window.file_in, window.start, window.end - window.start, segment.speed)
        for segment, window in clip_windows(track, ctx.session, ctx.project.timeline, tracks.spans)
    )


def music_placement(ctx: RenderContext, item_duration: float) -> tuple[PlacedRun, ...]:
    """Onde a música toca: um trecho por janela (`spans`, ou a música toda cobrindo o vídeo). O item é o arquivo inteiro, então um
    `loop` que repete o arquivo não tem como repetir a portadora: ela vale na primeira passada e o render avisa."""
    tracks = ctx.carrier_tracks
    music = ctx.project.audio.music
    if tracks is None or music is None:
        return ()
    total = tracks.inputs.total
    grid = music_grid(ctx.project.audio)
    windows = music.spans or [None]
    runs = []
    for window in windows:
        if window is None:
            start, end, start_at = 0.0, total, music.start_at
        else:
            start, window_end, start_at = resolve_span(window, total, item_duration)
            end = total if window_end is None else min(window_end, total)
        entry = grid.entry_delay(start, start_at) if grid else 0.0
        length = max(end - start - entry, 0.0)
        available = max(item_duration - start_at, 0.0)
        if music.loop and length > available + 1e-3:
            ctx.warn(
                "Vocoder: a música está em loop e o arquivo processado é um só; a portadora de outra trilha vale na primeira "
                "passada da música, e o que repete depois fica sem ela."
            )
            length = available
        if length > 0:
            runs.append(PlacedRun(start_at, start + entry, length))
    return tuple(runs)
