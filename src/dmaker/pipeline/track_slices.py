"""Quais faixas de áudio externas soam em cada trecho de clipe e de onde no arquivo: uma conta só,
usada pelo render (`segments.ClipPreparer`) e pela vista de linha do tempo (`timeline_view`), para a
prévia e o vídeo final nunca discordarem sobre o que toca em cada instante. Puro: não toca disco."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import AudioTrack, ClipSegment
from ..filtergraph.mezzanine import TrackSlice
from .sources import Source

MIN_AUDIBLE_S = 1e-3  # menos que isso é arredondamento, não um trecho em que a faixa soa


def source_covers(source: Source, segment: ClipSegment, shift: float = 0.0) -> bool:
    """Se o arquivo da fonte grava algum instante entre o início e o fim do trecho. Com a faixa deslocada em `shift`
    segundos (positivo atrasa o som), o trecho toca o que o arquivo gravou `shift` segundos antes."""
    end = segment.end if segment.end is not None else float("inf")
    return source.offset < end - shift and source.offset + source.info.duration > segment.start - shift


def track_slice(
    track: AudioTrack,
    source: Source,
    segment: ClipSegment,
    processed: Path | None = None,
    duck: tuple = (),
) -> TrackSlice | None:
    """Fatia da faixa alinhada ao início do trecho (tempo da sessão -> tempo no arquivo da faixa), ou
    None quando o arquivo não grava nenhum instante do trecho: um gravador em vários arquivos (câmera
    que parte a gravação a cada 30 min) vira várias faixas, e só a que grava aquele momento entra.
    `processed` é o arquivo da faixa já com os efeitos dela (o mesmo tempo, na faixa 0): a fatia sai dele."""
    shift = track.audio_offset  # segundos da gravação: a faixa toda anda em relação à sessão
    if not source_covers(source, segment, shift):
        return None
    in_point = source.in_point(segment.start) - shift
    if processed is not None:
        return TrackSlice(processed, in_point, track.volume, 0, track.pan, duck)
    return TrackSlice(source.path, in_point, track.volume, source.audio_stream, track.pan, duck)


def track_slices(
    tracks: Sequence[AudioTrack],
    session: Mapping[str, Source],
    segment: ClipSegment,
    processed: Sequence[Path | None] = (),
    ducks: Callable[[int], tuple] | None = None,
) -> tuple[TrackSlice, ...]:
    """Fatias de todas as faixas externas que soam no trecho, na ordem das faixas da spec. `processed` traz, por
    faixa, o arquivo já com efeitos (ver `pipeline.audio_effects.track_audio_overrides`); vazio, tudo sai da fonte."""
    found = (
        track_slice(
            track,
            session[track.source],
            segment,
            processed[index] if index < len(processed) else None,
            ducks(index) if ducks else (),
        )
        for index, track in enumerate(tracks)
    )
    return tuple(piece for piece in found if piece is not None)


@dataclass(frozen=True)
class TrackWindow:
    """Onde, na linha do tempo final, uma fatia soa: de `start` a `end`, tocando o arquivo da faixa a
    partir de `file_in` (o mesmo `-ss` que o mezanino usa)."""

    start: float
    end: float
    file_in: float


def track_window(
    piece: TrackSlice, file_duration: float, speed: float, span: tuple[float, float]
) -> TrackWindow | None:
    """Intervalo do trecho (`span`, na linha do tempo final) em que a fatia realmente soa. Reproduz o
    mezanino: faixa que começa depois do trecho entra atrasada (`adelay`), a que acaba antes dele
    cala no fim do arquivo, e o que sobra passa pela velocidade do clipe junto com o resto do áudio.
    None quando nada da faixa cai dentro do trecho."""
    delay = max(-piece.in_point, 0.0)  # segundos de fonte antes de a faixa começar
    file_in = max(piece.in_point, 0.0)
    consumed = (span[1] - span[0]) * speed  # tempo de fonte que o trecho consome
    audible = min(consumed - delay, file_duration - file_in)
    if audible < MIN_AUDIBLE_S:
        return None
    start = span[0] + delay / speed
    return TrackWindow(start, start + audible / speed, file_in)


def clip_windows(
    track: AudioTrack,
    session: Mapping[str, Source],
    timeline: Sequence,
    spans: Sequence[tuple[float, float]],
    processed: Path | None = None,
) -> list[tuple[ClipSegment, TrackWindow]]:
    """Os clipes que ouvem a faixa externa `track` e a janela em que cada um a ouve na linha do tempo final. `spans` diz onde cada
    trecho da `timeline` cai; `processed` é o arquivo da faixa já com os efeitos dela. É a conta que o Auto Duck e o Vocoder
    fazem para saber quando a faixa soa, a mesma do mezanino."""
    source = session.get(track.source)
    if source is None or source.info is None:
        return []
    found = []
    for index, segment in enumerate(timeline):
        if not isinstance(segment, ClipSegment) or not segment.source or index >= len(spans):
            continue
        piece = track_slice(track, session[track.source], segment, processed)
        window = track_window(piece, source.info.duration, segment.speed, spans[index]) if piece else None
        if window is not None:
            found.append((segment, window))
    return found
