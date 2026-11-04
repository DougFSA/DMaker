"""O andamento do projeto e a grade que ele desenha: o instante de cada tempo e de cada compasso, o tempo mais perto de um
instante (a conta do encaixe) e as referências `beat:<n>` e `bar:<n>`. Tudo é conta pura sobre `Tempo`: não toca disco,
nem a spec, nem o ffmpeg.

Os números contam a partir de 1, como a música conta (compasso 1, tempo 1). O tempo 1 cai em `offset` segundos do vídeo
final; o andamento é o do tempo da fórmula de compasso (em 6/8 são 6 tempos por compasso, cada um no andamento dado).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

BEAT_PREFIX = "beat:"
BAR_PREFIX = "bar:"

MIN_BPM = 20.0
MAX_BPM = 400.0
# O teto de tempos que uma grade enumera de uma vez: um andamento alto num vídeo longo passa de cem mil, e quem pede isso
# quer outra coisa (o encaixe da interface pede só a janela visível)
MAX_GRID_POINTS = 200_000

_SIGNATURE = re.compile(r"^([1-9]\d?)/(1|2|4|8|16|32)$")


class TempoError(ValueError):
    """Andamento inválido, ou uma referência `beat:`/`bar:` que não faz sentido."""


class Tempo(BaseModel):
    """O andamento do projeto (`audio.tempo`): batidas por minuto, fórmula de compasso e onde cai o tempo 1.

    É um dado do projeto, não um efeito: a régua em compassos, o encaixe, as referências `beat:`/`bar:`, o esticamento da
    música e o cortar no ritmo leem daqui. Sem ele, nada disso existe e o projeto se comporta como sempre se comportou."""

    model_config = ConfigDict(extra="forbid")

    bpm: float = Field(ge=MIN_BPM, le=MAX_BPM)
    time_signature: str = "4/4"
    offset: float = Field(0.0, ge=0, le=3600)  # segundos do vídeo final em que cai o tempo 1 do compasso 1

    @field_validator("time_signature")
    @classmethod
    def _signature(cls, value: str) -> str:
        parse_signature(value)
        return value

    @property
    def period(self) -> float:
        """Quanto dura um tempo, em segundos."""
        return 60.0 / self.bpm

    @property
    def beats_per_bar(self) -> int:
        return parse_signature(self.time_signature)[0]

    @property
    def bar_period(self) -> float:
        return self.period * self.beats_per_bar


def parse_signature(text: str) -> tuple[int, int]:
    """`4/4` -> (4, 4): os tempos por compasso e a figura que vale um tempo. Qualquer outra forma é erro com a regra."""
    match = _SIGNATURE.match(str(text).strip())
    if not match:
        raise TempoError(
            f"fórmula de compasso inválida: {text!r}. Use tempos por compasso e figura, como 4/4, 3/4 ou 6/8"
        )
    return int(match.group(1)), int(match.group(2))


# ---------- a grade ----------


def beat_time(tempo: Tempo, number: float) -> float:
    """O instante do tempo `number` (1 é o primeiro, em `offset`)."""
    return tempo.offset + (number - 1.0) * tempo.period


def bar_time(tempo: Tempo, number: float) -> float:
    """O instante em que começa o compasso `number` (1 é o primeiro, em `offset`)."""
    return tempo.offset + (number - 1.0) * tempo.bar_period


def beat_number_at(tempo: Tempo, instant: float) -> float:
    """Em que tempo (fracionário, contado de 1) cai `instant`; antes do tempo 1 vale menos que 1."""
    return (instant - tempo.offset) / tempo.period + 1.0


def grid_beats(tempo: Tempo, start: float, end: float) -> list[float]:
    """Os instantes de todos os tempos em [start, end], em ordem. Passar do teto de pontos é erro: peça uma janela menor."""
    first = max(math.ceil((start - tempo.offset) / tempo.period - 1e-9), 0)
    last = math.floor((end - tempo.offset) / tempo.period + 1e-9)
    if last - first + 1 > MAX_GRID_POINTS:
        raise TempoError(f"a grade passaria de {MAX_GRID_POINTS} tempos: peça um trecho menor")
    return [round(tempo.offset + n * tempo.period, 6) for n in range(first, last + 1)]


def grid_bars(tempo: Tempo, start: float, end: float) -> list[float]:
    """Os instantes de início de todos os compassos em [start, end], em ordem."""
    step = tempo.bar_period
    first = max(math.ceil((start - tempo.offset) / step - 1e-9), 0)
    last = math.floor((end - tempo.offset) / step + 1e-9)
    if last - first + 1 > MAX_GRID_POINTS:
        raise TempoError(f"a grade passaria de {MAX_GRID_POINTS} compassos: peça um trecho menor")
    return [round(tempo.offset + n * step, 6) for n in range(first, last + 1)]


def nearest_grid_point(tempo: Tempo, instant: float, level: str = "beat") -> float:
    """O tempo (ou o início de compasso, com `level="bar"`) mais perto de `instant`. Antes do tempo 1 vale o próprio
    tempo 1: a grade começa em `offset`."""
    step = tempo.bar_period if level == "bar" else tempo.period
    number = max(round((instant - tempo.offset) / step), 0)
    return round(tempo.offset + number * step, 6)


def snap_to_grid(tempo: Tempo, instant: float, tolerance: float, level: str = "beat") -> float:
    """Cai exatamente no tempo mais perto se ele está a até `tolerance` segundos; senão devolve o próprio instante. É a
    mesma conta do encaixe da linha do tempo (a interface a repete em TypeScript, e os dois têm o mesmo teste)."""
    target = nearest_grid_point(tempo, instant, level)
    return target if abs(target - instant) <= tolerance else instant


def position_label(tempo: Tempo, instant: float) -> str:
    """O instante como compasso.tempo (`9.1` é o primeiro tempo do compasso 9), o jeito de ler a régua em compassos."""
    number = max(math.floor(beat_number_at(tempo, instant) + 1e-9), 1)
    bar, beat = divmod(number - 1, tempo.beats_per_bar)
    return f"{bar + 1}.{beat + 1}"


# ---------- referências beat:<n> e bar:<n> ----------


def is_grid_ref(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return text.startswith(BEAT_PREFIX) or text.startswith(BAR_PREFIX)


@dataclass(frozen=True)
class GridRef:
    unit: str  # "beat" ou "bar"
    number: int


def parse_grid_ref(reference: str) -> GridRef:
    """`beat:17` ou `bar:5` -> a unidade e o número (a partir de 1). O que não for inteiro positivo é erro."""
    text = reference.strip().lower()
    unit = "beat" if text.startswith(BEAT_PREFIX) else "bar"
    body = text[len(BEAT_PREFIX) if unit == "beat" else len(BAR_PREFIX) :].strip()
    if not body.isdigit() or int(body) < 1:
        raise TempoError(f"{unit}: precisa de um número inteiro a partir de 1 (ex.: {unit}:9), não {body!r}")
    return GridRef(unit, int(body))


def grid_instant(tempo: Tempo | None, reference: str) -> float:
    """O instante de `beat:<n>` ou `bar:<n>` na grade do projeto. Sem andamento a referência é recusada, dizendo como
    defini-lo."""
    ref = parse_grid_ref(reference)
    if tempo is None:
        raise TempoError(
            f"{reference.strip()} precisa do andamento do projeto (audio.tempo): defina-o antes, com a operação "
            "tempo_set (bpm, e se quiser time_signature e offset)"
        )
    return round(beat_time(tempo, ref.number) if ref.unit == "beat" else bar_time(tempo, ref.number), 6)
