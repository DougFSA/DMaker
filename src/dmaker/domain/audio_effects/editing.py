"""Os efeitos de edição de onda: Silenciar, Cortar, Envelope de volume e Canais.

São o que o Audacity faz com a seleção (Silence Audio, Delete, a ferramenta Envelope, Stereo to Mono e Swap
Channels). Entram na mesma cadeia dos outros efeitos, então valem em qualquer item de áudio, não destroem o arquivo
original e se desfazem tirando o efeito da lista. O comportamento é reproduzido pelos filtros do ffmpeg em
`filtergraph.audio_effects.editing`, não copiado do código do Audacity.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import EPSILON, EffectBase, param, register_effect

MAX_ENVELOPE_POINTS = (
    100  # a expressão do volume cresce com os pontos; passar disso já não é um desenho à mão
)


@register_effect
class Silence(EffectBase):
    """Zera o som do intervalo sem mexer na duração (o "Silence Audio" do Audacity, a forma "Split Delete": o
    buraco fica onde estava). Sem intervalo, silencia o item inteiro."""

    type: Literal["silence"] = "silence"
    label: ClassVar[str] = "Silenciar"
    audacity_name: ClassVar[str] = "Silence Audio"
    summary: ClassVar[str] = "Zera o som do intervalo, sem mudar a duração do item."


@register_effect
class Cut(EffectBase):
    """Tira o intervalo do som e o que vem depois recua (o "Delete" do Audacity). Em item preso à imagem (clipe,
    PiP) e na narração a duração não pode mudar, então o fim completa com silêncio (`keep_length`); na voz gravada e
    na música o item encolhe."""

    type: Literal["cut"] = "cut"
    label: ClassVar[str] = "Cortar"
    audacity_name: ClassVar[str] = "Delete"
    summary: ClassVar[str] = (
        "Tira o intervalo do som e o resto recua. Onde a duração é presa à imagem, o fim completa com silêncio."
    )
    owns_interval: ClassVar[bool] = True
    needs_selection: ClassVar[bool] = True
    reorders_time: ClassVar[bool] = True

    keep_length: bool = param(
        True,
        label="Completar com silêncio no fim",
        hint="Mantém a duração do item, preenchendo com silêncio o que o corte tirou. Desligado, o item "
        "encolhe (só vale em voz gravada e em música).",
    )

    @model_validator(mode="after")
    def _needs_interval(self) -> Cut:
        if self.start is None or self.end is None:
            raise ValueError("efeito cut: informe `start` e `end`, o intervalo que sai do som")
        return self

    def alters_duration(self) -> bool:
        return not self.keep_length

    def output_duration(self, duration: float) -> float:
        if self.keep_length or self.start is None or self.end is None:
            return duration
        return duration - (min(self.end, duration) - min(self.start, duration))


class EnvelopePoint(BaseModel):
    """Um ponto do envelope: o instante no item (segundos) e o ganho nele (dB)."""

    model_config = ConfigDict(extra="forbid")

    at: float = Field(ge=0)
    db: float = Field(ge=-120, le=24)


@register_effect
class Envelope(EffectBase):
    """Curva de volume ao longo do item: pontos (instante no item, ganho em dB) ligados por retas em dB, como a
    ferramenta Envelope do Audacity. Antes do primeiro ponto e depois do último vale o ganho do ponto mais perto."""

    type: Literal["envelope"] = "envelope"
    label: ClassVar[str] = "Envelope de volume"
    audacity_name: ClassVar[str] = "Envelope Tool"
    summary: ClassVar[str] = (
        "Desenha o volume ao longo do item por pontos (instante e ganho em dB), com retas entre eles."
    )
    owns_interval: ClassVar[bool] = True
    needs_selection: ClassVar[bool] = True

    points: list[EnvelopePoint] = Field(
        default_factory=lambda: [EnvelopePoint(at=0.0, db=0.0), EnvelopePoint(at=1.0, db=0.0)],
        min_length=1,
        max_length=MAX_ENVELOPE_POINTS,
        description="Os pontos da curva: `at` em segundos desde o começo do item, `db` o ganho nesse instante.",
        json_schema_extra={"label": "Pontos", "unit": "s / dB"},
    )

    @model_validator(mode="after")
    def _ordered_points(self) -> Envelope:
        if self.start is not None or self.end is not None:
            raise ValueError("efeito envelope: os pontos já dizem onde ele age; não use `start` nem `end`")
        ordered = sorted(self.points, key=lambda point: point.at)
        for before, after in zip(ordered, ordered[1:], strict=False):
            if after.at - before.at <= EPSILON:
                raise ValueError(
                    f"efeito envelope: dois pontos no mesmo instante ({after.at:g} s); use instantes diferentes"
                )
        self.points = ordered
        return self

    def gain_db_at(self, instant: float) -> float:
        """O ganho da curva num instante do item: reta em dB entre os pontos, e o ganho da ponta fora deles."""
        points = self.points
        if instant <= points[0].at:
            return points[0].db
        for before, after in zip(points, points[1:], strict=False):
            if instant <= after.at:
                fraction = (instant - before.at) / (after.at - before.at)
                return before.db + (after.db - before.db) * fraction
        return points[-1].db

    def rebased(self, origin: float, length: float, total: float | None = None) -> Envelope | None:
        """A curva para um pedaço do item: os pontos de dentro andam, e as pontas ganham o valor que a curva tinha
        ali, para o som do pedaço ser o mesmo de antes."""
        if length <= EPSILON:
            return None
        inside = [
            EnvelopePoint(at=round(point.at - origin, 6), db=point.db)
            for point in self.points
            if EPSILON < point.at - origin < length - EPSILON
        ]
        ends = (
            EnvelopePoint(at=0.0, db=round(self.gain_db_at(origin), 6)),
            EnvelopePoint(at=round(length, 6), db=round(self.gain_db_at(origin + length), 6)),
        )
        return self.model_copy(update={"points": [ends[0], *inside, ends[1]]})

    def shifted(self, delta: float) -> Envelope:
        moved = [EnvelopePoint(at=round(point.at + delta, 6), db=point.db) for point in self.points]
        return self.model_copy(update={"points": [point for point in moved if point.at >= 0]})

    def stitched(self, following: EffectBase, boundary: float) -> Envelope | None:
        """As duas curvas numa só (a de depois andou `boundary`); o ponto da emenda aparece uma vez."""
        if not isinstance(following, Envelope) or following.enabled != self.enabled:
            return None
        later = [EnvelopePoint(at=round(p.at + boundary, 6), db=p.db) for p in following.points]
        merged = list(self.points)
        for point in later:
            if abs(point.at - merged[-1].at) <= EPSILON and abs(point.db - merged[-1].db) <= EPSILON:
                continue
            merged.append(point)
        return self.model_copy(update={"points": merged})


@register_effect
class Channels(EffectBase):
    """Mexe nos canais do item: mistura os dois em mono, troca esquerdo e direito, ou usa um canal só nos dois
    lados (o caso do microfone de lapela gravado só em um canal)."""

    type: Literal["channels"] = "channels"
    label: ClassVar[str] = "Canais"
    audacity_name: ClassVar[str] = "Stereo to Mono / Swap Channels"
    summary: ClassVar[str] = (
        "Mistura em mono, troca os canais, ou usa só o esquerdo ou só o direito nos dois lados."
    )

    mode: Literal["mono", "swap", "left", "right"] = param(
        "mono",
        label="Modo",
        hint="mono: mistura os dois canais; swap: troca esquerdo e direito; left: o canal esquerdo sai nos "
        "dois lados; right: o canal direito sai nos dois lados.",
    )
