"""Auto Duck: abaixar uma trilha enquanto OUTRA fala. A regra na spec e as contas da curva de volume, tudo puro.

O Auto Duck do Audacity abaixa o volume das trilhas selecionadas pela hora em que a trilha de controle passa de um
nível. Aqui cada regra (`audio.ducks`) diz qual trilha abaixa (`background`) e qual a comanda (`key`), pelos ids de
trilha da vista multitrilha: `A1` (o som dos trechos), `A2`, `A3`... (as faixas externas), `MUS`, `NAR`, `VO` e `SFX`.
A regra vale entre quaisquer duas trilhas, com uma exceção que vem de onde cada som é misturado: `A1` já contém as faixas
externas, então não abaixa sob uma delas (abaixe a faixa externa de fundo sob a chave).

A chave `A1` é o som dos próprios trechos (a câmera com os efeitos e o volume do clipe), sem as faixas externas e sem os
PiPs: é isso que permite a faixa externa abaixar sob a câmera, e vale para toda regra com chave `A1`, de qualquer fundo.
Uma faixa externa vive dentro do mezanino do clipe, que é montado antes da narração, da música e dos efeitos existirem;
por isso a chave de uma regra de fundo externo é medida antes dos mezaninos (ver `AutoDuck.measured_early`).

O `music.ducking` antigo (o `sidechaincompress`, ligado por padrão) continua igual enquanto não há regra para a
música. Uma regra com `background: "MUS"` o substitui: os dois não rodam juntos.

Tudo o que não precisa de ffmpeg está aqui, em funções puras que recebem números e devolvem números: as janelas em que
a trilha-chave soa, a curva de ganho da trilha de fundo (reta em dB entre os pontos, como o Envelope) e o pedaço dela
que cai num clipe.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# As trilhas de áudio da vista (`domain/tracks.py`): A1, A2... (A<n> é a faixa externa n-2), MUS, NAR, VO e SFX
_TRACK_ID = re.compile(r"^(A[1-9]\d{0,2}|MUS|NAR|VO|SFX)$")
# Toda rampa dura ao menos isto: um degrau de ganho de uma amostra estala, e 5 ms já é um degrau que o ouvido não separa
MIN_RAMP_SECONDS = 0.005
EPSILON = 1e-6

Region = tuple[float, float]
Point = tuple[float, float]  # (instante em segundos, ganho em dB)


def is_track_id(value: str) -> bool:
    return bool(_TRACK_ID.match(value))


def external_index(track_id: str) -> int | None:
    """A posição em `audio.tracks` da faixa externa `A<n>` (n >= 2), ou None para qualquer outra trilha. `A1` é o som dos
    trechos, não uma faixa externa."""
    if track_id.startswith("A") and track_id[1:].isdigit() and int(track_id[1:]) >= 2:
        return int(track_id[1:]) - 2
    return None


def is_external(track_id: str) -> bool:
    return external_index(track_id) is not None


class AutoDuck(BaseModel):
    """Uma regra: a trilha `background` abaixa `amount_db` enquanto a trilha `key` soa acima de `threshold_db`.

    Os padrões e os nomes são os do Auto Duck do Audacity (-12 dB, limiar -30 dB RMS, pausa máxima de 1 s, descida e subida
    de 0,5 s). `outer_fade_down` começa ANTES de a chave soar (a descida termina quando ela começa) e `outer_fade_up` termina
    DEPOIS de ela calar; `inner_fade_down` e `inner_fade_up` fazem a mesma rampa por DENTRO do trecho em que a chave soa."""

    model_config = ConfigDict(extra="forbid")

    background: str = Field(description="A trilha que abaixa (A1, A2..., MUS, NAR, VO ou SFX).")
    key: str = Field(description="A trilha que comanda: o fundo abaixa quando ela soa.")
    amount_db: float = Field(-12.0, ge=-100.0, le=0.0, description="Quanto o fundo abaixa, em dB.")
    threshold_db: float = Field(
        -30.0, ge=-100.0, le=0.0, description="Nível RMS (dBFS) a partir do qual a chave conta como som."
    )
    max_pause: float = Field(
        1.0,
        ge=0.0,
        le=60.0,
        description="Pausa da chave, em segundos, que ainda não deixa o fundo voltar. Nunca menor que a soma das "
        "rampas de fora.",
    )
    outer_fade_down: float = Field(
        0.5, ge=0.0, le=10.0, description="Descida antes da chave soar, em segundos."
    )
    inner_fade_down: float = Field(0.0, ge=0.0, le=10.0, description="Descida dentro do trecho da chave.")
    inner_fade_up: float = Field(0.0, ge=0.0, le=10.0, description="Subida dentro do trecho da chave.")
    outer_fade_up: float = Field(
        0.5, ge=0.0, le=10.0, description="Subida depois da chave calar, em segundos."
    )

    @field_validator("background", "key")
    @classmethod
    def _track(cls, value: str) -> str:
        value = value.strip()
        if not is_track_id(value):
            raise ValueError(
                f"trilha desconhecida: {value!r}. Use A1, A2 (A3...), MUS, NAR, VO ou SFX, os ids da linha do tempo"
            )
        return value

    @model_validator(mode="after")
    def _pair(self) -> AutoDuck:
        if self.key == self.background:
            raise ValueError(
                f"Auto Duck: a trilha {self.key} não abaixa sob ela mesma; escolha outra para comandar"
            )
        if self.background == "A1" and is_external(self.key):
            raise ValueError(
                f"Auto Duck: A1 já contém as faixas externas, então não abaixa sob {self.key}: abaixá-lo abaixaria a "
                f"própria {self.key}. Para a câmera aparecer por cima dela, abaixe a faixa externa {self.key} sob o A1"
            )
        return self

    @property
    def settle_pause(self) -> float:
        """A pausa que de fato separa duas regiões: a `max_pause`, ou a soma das rampas de fora quando esta é maior (a
        subida de uma e a descida da outra não cabem numa pausa menor, e o fundo nunca chegaria a voltar)."""
        return max(self.max_pause, self.outer_fade_down + self.outer_fade_up)

    @property
    def measured_early(self) -> bool:
        """Se a chave se mede antes de os mezaninos existirem: a chave `A1` (só a câmera) e a externa vêm do arquivo, e as
        outras (`MUS`, `NAR`, `VO`, `SFX`) vêm da cópia da mixagem quando o fundo é uma faixa externa, porque ela é
        abaixada dentro do clipe. Nos demais fundos a medida espera a mixagem pronta (`finish_ducks`)."""
        return self.key == "A1" or is_external(self.key) or is_external(self.background)

    @property
    def is_music_rule(self) -> bool:
        """Se a regra abaixa a música: o caso do `music.ducking` antigo, que ela substitui."""
        return self.background == "MUS"


# ---------- onde a chave soa ----------


def sound_runs(levels_db: Sequence[float] | np.ndarray, window: float, threshold_db: float) -> list[Region]:
    """Os trechos seguidos em que o nível RMS de cada janela de `window` segundos está no limiar ou acima, em segundos
    desde o começo da medida. Cada janela vale o seu intervalo inteiro (a que passa do limiar conta toda)."""
    above = np.asarray(levels_db, dtype=np.float64) >= threshold_db
    if not above.any():
        return []
    edges = np.diff(np.concatenate([[0], above.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [(float(first * window), float(last * window)) for first, last in zip(starts, ends, strict=True)]


def merge_runs(runs: Sequence[Region], pause: float) -> list[Region]:
    """Junta os trechos separados por uma pausa de até `pause` segundos: o fundo só volta numa pausa maior que ela. Os
    trechos podem vir em qualquer ordem."""
    merged: list[Region] = []
    for first, last in sorted(runs):
        if merged and first - merged[-1][1] <= pause + EPSILON:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return merged


def key_regions(runs: Sequence[Region], rule: AutoDuck) -> list[Region]:
    """As regiões em que a chave comanda: os trechos que soam, juntados pela pausa da regra."""
    return merge_runs(runs, rule.settle_pause)


def clip_runs(
    file_runs: Sequence[Region], start: float, end: float, file_in: float, speed: float
) -> list[Region]:
    """Os trechos do arquivo que um clipe toca (de `file_in`, durante `end - start` segundos da linha do tempo, na
    velocidade `speed`), no tempo da linha do tempo final."""
    heard_until = file_in + (end - start) * speed
    mapped = []
    for first, last in file_runs:
        low, high = max(first, file_in), min(last, heard_until)
        if high > low:
            mapped.append((start + (low - file_in) / speed, start + (high - file_in) / speed))
    return mapped


def camera_runs(
    file_runs: Sequence[Region], span: tuple[float, float], speed: float, file_in: float, lead: float = 0.0
) -> list[Region]:
    """Os trechos em que a câmera de um clipe soa na linha do tempo final: `file_runs` são os trechos do arquivo da câmera
    (no tempo dele), `span` é onde o clipe cai, `file_in` o ponto do arquivo em que o clipe começa a ouvir e `lead` o
    silêncio, em segundos de fonte, que antecede o som (o som deslocado para antes do começo do arquivo). Só o som do
    próprio clipe: as faixas externas e os PiPs não entram."""
    return clip_runs(file_runs, span[0] + lead / speed, span[1], file_in, speed)


# ---------- a curva de ganho do fundo ----------


def duck_points(regions: Sequence[Region], rule: AutoDuck) -> list[Point]:
    """A curva de ganho do fundo, como pontos `(instante, dB)` ligados por retas em dB, com o ganho da ponta fora deles.

    Para cada região da chave `[a, b]`: 0 dB em `a - outer_fade_down`, `amount_db` em `a + inner_fade_down`, `amount_db`
    em `b - inner_fade_up` e 0 dB em `b + outer_fade_up`. As rampas de dentro nunca passam de metade da região, e cada
    rampa dura ao menos `MIN_RAMP_SECONDS` (um degrau seco estalaria). Antes da primeira região e depois da última o ganho
    é 0 dB. O instante nunca é negativo: o que cairia antes de 0 vira o ganho que a curva tem em 0."""
    points: list[Point] = []
    for first, last in regions:
        half = (last - first) / 2.0
        inner_down, inner_up = min(rule.inner_fade_down, half), min(rule.inner_fade_up, half)
        down = max(rule.outer_fade_down, MIN_RAMP_SECONDS - inner_down, 0.0)
        up = max(rule.outer_fade_up, MIN_RAMP_SECONDS - inner_up, 0.0)
        points += [
            (first - down, 0.0),
            (first + inner_down, rule.amount_db),
            (last - inner_up, rule.amount_db),
            (last + up, 0.0),
        ]
    return _strictly_increasing(clip_points(points, 0.0, float("inf")))


def _strictly_increasing(points: Sequence[Point]) -> list[Point]:
    """Os pontos em ordem de instante e sem dois no mesmo instante (a expressão do ffmpeg divide pela diferença)."""
    ordered: list[Point] = []
    for instant, gain in sorted(points):
        if ordered and instant <= ordered[-1][0] + EPSILON:
            instant = ordered[-1][0] + EPSILON
        ordered.append((instant, gain))
    return ordered


def gain_at(points: Sequence[Point], instant: float) -> float:
    """O ganho (dB) da curva num instante: reta em dB entre os pontos e o ganho da ponta fora deles. 0 dB sem pontos."""
    if not points:
        return 0.0
    times = [point[0] for point in points]
    return float(np.interp(instant, times, [point[1] for point in points]))


def clip_points(points: Sequence[Point], low: float, high: float) -> list[Point]:
    """A mesma curva restrita a `[low, high]`: os pontos de dentro ficam, e uma borda que corta a curva em andamento ganha
    um ponto com o valor que a curva tinha ali, para o som do pedaço ser o mesmo de antes de recortar."""
    if not points:
        return []
    result = [point for point in points if low < point[0] < high]
    if any(point[0] <= low for point in points):
        result.append((low, gain_at(points, low)))
    if any(point[0] >= high for point in points):
        result.append((high, gain_at(points, high)))
    return sorted(result)


def slice_points(points: Sequence[Point], first: float, last: float, scale: float = 1.0) -> list[Point]:
    """O pedaço da curva que cai em `[first, last]` (segundos do projeto), no tempo do pedaço: o instante vira
    `(t - first) * scale`. `scale` é a velocidade do clipe (segundos de fonte por segundo do projeto), porque o ganho de
    uma faixa externa é aplicado no tempo da fonte, antes de a velocidade valer. Vazio quando a curva é 0 dB o tempo todo
    no pedaço: o pedaço não leva filtro nenhum, e o hash dele é o de sempre."""
    if not points or last <= first:
        return []
    clipped = clip_points(points, first, last)
    if all(abs(gain) < 1e-9 for _, gain in clipped):
        return []
    return [(round((instant - first) * scale, 6), round(gain, 6)) for instant, gain in clipped]


def is_flat(points: Sequence[Point]) -> bool:
    """Se o ganho é o mesmo em toda a curva (um `volume` constante basta)."""
    return len({round(gain, 6) for _, gain in points}) <= 1


def total_reduction_seconds(regions: Sequence[Region]) -> float:
    """Quantos segundos a chave soa, no total (para o resumo da regra)."""
    return float(sum(last - first for first, last in regions))
