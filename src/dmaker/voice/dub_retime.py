"""Linha do tempo esticada da dublagem: em que trechos o vídeo se alonga e onde cada fala cai depois disso.

Funções puras, sem áudio, vídeo nem disco. O plano parte o arquivo em trechos contínuos (`VideoPiece`), cada um com
o fator de esticamento do vídeo (1.0 onde a fala coube), e converte qualquer tempo do arquivo original para o
tempo do arquivo esticado. É a mesma conta que o grafo ffmpeg executa (`filtergraph/dub.py`), o posicionamento das
falas e o tempo da legenda: um só lugar decide, e os três concordam.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MIN_PIECE_SECONDS = 1e-3  # abaixo de um milissegundo o trecho é resíduo de arredondamento, não imagem


@dataclass(frozen=True)
class StretchWindow:
    """Uma janela do arquivo original (segundos) cuja imagem deve durar `factor` vezes mais."""

    start: float
    end: float
    factor: float


@dataclass(frozen=True)
class VideoPiece:
    """Um trecho contínuo do original e quanto ele se alonga (1.0 = intacto)."""

    start: float
    end: float
    factor: float = 1.0

    @property
    def source_seconds(self) -> float:
        return self.end - self.start

    @property
    def output_seconds(self) -> float:
        return self.source_seconds * self.factor

    @property
    def stretched(self) -> bool:
        return self.factor > 1.0


@dataclass(frozen=True)
class RetimePlan:
    """Os trechos que cobrem o arquivo original do começo ao fim, na ordem."""

    pieces: tuple[VideoPiece, ...]

    @property
    def total_seconds(self) -> float:
        """Duração do arquivo esticado: a soma dos trechos, cada um já multiplicado pelo seu fator."""
        return sum(piece.output_seconds for piece in self.pieces)

    @property
    def source_seconds(self) -> float:
        return sum(piece.source_seconds for piece in self.pieces)

    @property
    def stretched_pieces(self) -> tuple[VideoPiece, ...]:
        return tuple(piece for piece in self.pieces if piece.stretched)

    @property
    def is_identity(self) -> bool:
        """Nenhum trecho esticado: o arquivo sai com a duração e a imagem do original."""
        return not self.stretched_pieces

    def retime(self, seconds: float) -> float:
        """Onde o instante `seconds` do original cai no arquivo esticado (contínua e crescente)."""
        if not self.pieces:
            return seconds
        elapsed = 0.0
        for piece in self.pieces:
            if seconds <= piece.end:
                return elapsed + max(0.0, seconds - piece.start) * piece.factor
            elapsed += piece.output_seconds
        return elapsed  # depois do fim do arquivo: cola no último instante


IDENTITY = RetimePlan(())


def _snap(seconds: float, fps: float | None) -> float:
    """Leva o instante ao quadro mais próximo: um corte no meio de um quadro perde ou repete um quadro."""
    if not fps or fps <= 0:
        return seconds
    return round(seconds * fps) / fps


def plan_retime(windows: Sequence[StretchWindow], total: float, fps: float | None = None) -> RetimePlan:
    """Trechos do arquivo de `total` segundos, com as `windows` esticadas e o resto intacto.

    Com `fps`, os cortes caem na grade de quadros, o que mantém o vídeo (que corta por quadro) e o áudio (que
    corta por amostra) com a mesma duração em cada trecho. Janelas fora do arquivo são recortadas, janelas
    sobrepostas cedem ao que veio antes, e fator 1.0 ou janela vazia não geram trecho esticado.
    """
    if total <= 0:
        return IDENTITY
    pieces: list[VideoPiece] = []
    cursor = 0.0
    for window in sorted(windows, key=lambda w: w.start):
        start = _snap(max(window.start, cursor), fps)
        end = min(_snap(window.end, fps), total)  # o último quadro pode arredondar além do fim do arquivo
        if window.factor <= 1.0 or end - start < MIN_PIECE_SECONDS:
            continue
        if start - cursor >= MIN_PIECE_SECONDS:
            pieces.append(VideoPiece(cursor, start))
        pieces.append(VideoPiece(start, end, window.factor))
        cursor = end
    if not pieces:
        return IDENTITY
    if total - cursor >= MIN_PIECE_SECONDS:
        pieces.append(VideoPiece(cursor, total))
    return RetimePlan(tuple(pieces))


def retimed_span(plan: RetimePlan, start: float, seconds: float) -> tuple[float, float]:
    """Início e fim, no arquivo esticado, de uma fala que começa em `start` (original) e toca por `seconds`.

    A voz toca em tempo real (não é esticada com a imagem), então só o início é convertido: o fim é o início
    novo somado à duração com que a fala toca. É o intervalo da voz e da legenda.
    """
    begin = plan.retime(start)
    return begin, begin + seconds
