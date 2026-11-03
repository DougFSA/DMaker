"""Quais faixas de áudio externas soam em cada trecho de clipe e de onde no arquivo: uma conta só,
usada pelo render (`segments.ClipPreparer`) e pela vista de linha do tempo (`timeline_view`), para a
prévia e o vídeo final nunca discordarem sobre o que toca em cada instante. Puro: não toca disco."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain.spec import AudioTrack, ClipSegment
from ..filtergraph.mezzanine import TrackSlice
from .sources import Source

MIN_AUDIBLE_S = 1e-3  # menos que isso é arredondamento, não um trecho em que a faixa soa


def source_covers(source: Source, segment: ClipSegment) -> bool:
    """Se o arquivo da fonte grava algum instante entre o início e o fim do trecho."""
    end = segment.end if segment.end is not None else float("inf")
    return source.offset < end and source.offset + source.info.duration > segment.start


def track_slice(track: AudioTrack, source: Source, segment: ClipSegment) -> TrackSlice | None:
    """Fatia da faixa alinhada ao início do trecho (tempo da sessão -> tempo no arquivo da faixa), ou
    None quando o arquivo não grava nenhum instante do trecho: um gravador em vários arquivos (câmera
    que parte a gravação a cada 30 min) vira várias faixas, e só a que grava aquele momento entra."""
    if not source_covers(source, segment):
        return None
    return TrackSlice(source.path, source.in_point(segment.start), track.volume, source.audio_stream)


def track_slices(
    tracks: Sequence[AudioTrack], session: Mapping[str, Source], segment: ClipSegment
) -> tuple[TrackSlice, ...]:
    """Fatias de todas as faixas externas que soam no trecho, na ordem das faixas da spec."""
    found = (track_slice(track, session[track.source], segment) for track in tracks)
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
