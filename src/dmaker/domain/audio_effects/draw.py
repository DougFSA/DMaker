"""O efeito Desenhar, a Draw Tool do Audacity: põe, no lugar das amostras de um trecho curto, os valores que a pessoa
desenhou no zoom máximo do painel Áudio.

É não destrutivo como os outros: o arquivo não muda, e o desenho vira um efeito da cadeia do item (os valores das amostras
e o instante da primeira). Quem o aplica é o estágio de amostras do `EffectProcessor`, em `filtergraph.audio_effects.draw`,
na taxa dos efeitos (`EFFECT_SAMPLE_RATE`): o que se desenha são amostras dessa grade. O trecho tem limite
(`MAX_DRAW_SAMPLES`), como o Reparar: a ferramenta serve para refazer uma onda curta, não para pintar um áudio.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from .base import EFFECT_SAMPLE_RATE, EPSILON, EffectBase, param, register_effect

# 512 amostras a 48 kHz são 10,7 ms: o zoom máximo do painel mostra umas 300 amostras com 4 pixels cada
MAX_DRAW_SAMPLES = 512


@register_effect
class Draw(EffectBase):
    """Substitui as amostras de um trecho curto (a partir de `start`) pelos `values`, em um canal ou nos dois. O `end`
    é calculado (`start` mais a duração dos valores) e não se informa."""

    type: Literal["draw"] = "draw"
    label: ClassVar[str] = "Desenhar"
    audacity_name: ClassVar[str] = "Draw Tool"
    summary: ClassVar[str] = (
        "Põe no lugar das amostras de um trecho curto os valores desenhados no zoom máximo (até 512 amostras)."
    )
    owns_interval: ClassVar[bool] = True
    needs_selection: ClassVar[bool] = True
    sample_stage: ClassVar[bool] = True

    channel: Literal["both", "left", "right"] = param(
        "both",
        label="Canal",
        hint="both: os dois canais; left: só o esquerdo; right: só o direito (num som mono vale o único canal).",
    )
    values: list[float] = Field(
        default_factory=lambda: [0.0],
        min_length=1,
        max_length=MAX_DRAW_SAMPLES,
        description="O valor de cada amostra desenhada, de -1 a 1, a partir de `start`.",
        json_schema_extra={"label": "Amostras", "unit": "valor de -1 a 1"},
    )

    @field_validator("values")
    @classmethod
    def _inside_full_scale(cls, values: list[float]) -> list[float]:
        for position, value in enumerate(values):
            if not -1.0 <= value <= 1.0:
                raise ValueError(
                    f"efeito draw: a amostra {position} vale {value:g}, fora de -1 a 1 (o fundo de escala)"
                )
        return values

    @model_validator(mode="after")
    def _derived_interval(self) -> Draw:
        if self.start is None:
            raise ValueError("efeito draw: informe `start`, o instante da primeira amostra desenhada")
        self.end = round(self.start + len(self.values) / EFFECT_SAMPLE_RATE, 6)
        return self

    def _cropped(self, first: float, last: float, shift: float) -> Draw | None:
        """O desenho só com o que cai entre `first` e `last` (segundos do item), deslocado `shift`, ou None se nada sobra.
        As amostras são cortadas na grade dos efeitos, então o trecho que sobra continua nas mesmas amostras."""
        assert self.start is not None
        begin = round(self.start * EFFECT_SAMPLE_RATE)
        low = max(round(first * EFFECT_SAMPLE_RATE), begin)
        end_sample = begin + len(self.values)
        high = end_sample if last == float("inf") else min(round(last * EFFECT_SAMPLE_RATE), end_sample)
        if high - low <= 0:
            return None
        kept = self.values[low - begin : high - begin]
        start = round(low / EFFECT_SAMPLE_RATE + shift, 6)
        return self.model_copy(
            update={"values": kept, "start": start, "end": round(start + len(kept) / EFFECT_SAMPLE_RATE, 6)}
        )

    def rebased(self, origin: float, length: float) -> Draw | None:
        """O desenho para um pedaço do item que começa em `origin` e dura `length`: as amostras de dentro andam junto, e
        as de fora saem."""
        if length <= EPSILON:
            return None
        return self._cropped(origin, origin + length, -origin)

    def shifted(self, delta: float) -> Draw:
        """O desenho `delta` segundos mais tarde no item (o Juntar anda o pedaço de depois, sempre para a frente)."""
        moved = self._cropped(0.0, float("inf"), delta)
        assert moved is not None  # com `first` zero o desenho nunca perde amostra
        return moved

    def stitched(self, following: EffectBase, boundary: float) -> Draw | None:
        """Dois desenhos não se juntam: cada um fica no pedaço em que foi feito."""
        return None
