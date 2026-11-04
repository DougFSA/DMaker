"""Os efeitos da família Fading do Audacity: Fade In, Fade Out, Fade Ajustável e Studio Fade Out.

Todos entram na cadeia de efeitos como os outros: valem em qualquer item de áudio, não destroem o arquivo e se desfazem
tirando o efeito da lista. O Fade In e o Fade Out contam a `duration` a partir da borda do item (a ponta de onde vem o
nome); com um intervalo (`start`/`end`) o fade ocupa o intervalo, como a seleção do Audacity, e a `duration` não conta.
As curvas são funções puras em `domain.fade_curves`; o comportamento é reproduzido pelos filtros do ffmpeg em
`filtergraph.audio_effects.fades`, não copiado do código do Audacity.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import model_validator

from ..fade_curves import MID_ADJUST_RANGE
from .base import EPSILON, EffectBase, param, register_effect

FadeCurve = Literal["linear", "logarithmic", "exponential", "sine", "quadratic"]
FadeShape = Literal["up", "down", "s_up", "s_down", "sine_up", "sine_down"]

CURVE_HINT = (
    "linear: reta; logarithmic: abre depressa e achata; exponential: quase mudo até o fim; sine: S suave nas duas "
    "pontas; quadratic: devagar no começo (u ao quadrado)."
)
DURATION_HINT = (
    "Quanto dura o fade, contado da borda do item. Com um intervalo marcado (início e fim), o fade ocupa o "
    "intervalo e este valor não conta."
)


def rebase_edge_fade(
    effect: EffectBase, origin: float, length: float, total: float | None, at_start: bool
) -> EffectBase | None:
    """O fade preso a uma borda do item (sem intervalo) para o pedaço `origin`..`origin + length`. Só fica no pedaço que
    contém a borda dele: o primeiro para o que abre, o último para o que fecha; o fade que a divisão cortou ao meio
    encurta para o que sobrou dentro do pedaço. Sem saber o tamanho do item (`total`), o que fecha fica como está."""
    duration = effect.duration  # type: ignore[attr-defined]
    if at_start:
        remaining = duration - origin
        if remaining <= EPSILON:
            return None
        return effect.model_copy(update={"duration": round(min(remaining, length), 6)})
    if total is None:
        return effect
    if (
        origin + length < total - EPSILON
    ):  # o pedaço acaba antes do fim do item: a borda do fade ficou do outro lado
        return None
    return effect.model_copy(update={"duration": round(min(duration, length), 6)})


class EdgeFade(EffectBase):
    """O que o Fade In e o Fade Out têm em comum: a duração a partir da borda e a curva. Não é um efeito (não se
    registra): as duas subclasses fixam o `type` e a borda."""

    duration: float = param(1.0, label="Duração", unit="s", hint=DURATION_HINT, gt=0, le=3600)
    curve: FadeCurve = param("linear", label="Curva", hint=CURVE_HINT)

    # em qual borda do item o fade mora (a subclasse diz)
    at_start: ClassVar[bool] = True

    def rebased(self, origin: float, length: float, total: float | None = None) -> EdgeFade | None:  # type: ignore[override]
        if self.start is not None or self.end is not None:
            return super().rebased(origin, length)  # type: ignore[return-value]
        return rebase_edge_fade(self, origin, length, total, self.at_start)  # type: ignore[return-value]


@register_effect
class FadeIn(EdgeFade):
    """O som abre do silêncio até o nível original, pela curva escolhida (o Fade In do Audacity, com curva)."""

    type: Literal["fade_in"] = "fade_in"
    label: ClassVar[str] = "Fade In"
    audacity_name: ClassVar[str] = "Fade In"
    summary: ClassVar[str] = "O som abre do silêncio até o nível original, na curva escolhida."
    at_start: ClassVar[bool] = True


@register_effect
class FadeOut(EdgeFade):
    """O som fecha do nível original até o silêncio, pela curva escolhida (o Fade Out do Audacity, com curva)."""

    type: Literal["fade_out"] = "fade_out"
    label: ClassVar[str] = "Fade Out"
    audacity_name: ClassVar[str] = "Fade Out"
    summary: ClassVar[str] = "O som fecha do nível original até o silêncio, na curva escolhida."
    at_start: ClassVar[bool] = False


@register_effect
class AdjustableFade(EffectBase):
    """Fade com ganho inicial e final à escolha (100% para 40%, por exemplo, sem chegar ao silêncio), numa forma de
    subida, descida ou S, com o ajuste do meio (o Fade Ajustável do Audacity). Ocupa o intervalo, ou o item inteiro."""

    type: Literal["adjustable_fade"] = "adjustable_fade"
    label: ClassVar[str] = "Fade Ajustável"
    audacity_name: ClassVar[str] = "Adjustable Fade"
    summary: ClassVar[str] = (
        "Vai de um ganho inicial a um final (em % ou dB) pela forma escolhida, em todo o item ou no intervalo."
    )

    shape: FadeShape = param(
        "up",
        label="Forma",
        hint="up: devagar no começo; down: depressa no começo; s_up e s_down: em S; sine_up e sine_down: quarto de "
        "seno (a do crossfade de potência constante). Com o ajuste do meio em 0, up e down são retas.",
    )
    mid_adjust: float = param(
        0.0,
        label="Ajuste do meio",
        unit="%",
        hint="Entorta a forma: positivo demora a abrir, negativo abre logo, 0 deixa como é.",
        ge=-MID_ADJUST_RANGE,
        le=MID_ADJUST_RANGE,
    )
    start_gain: float = param(
        0.0,
        label="Ganho inicial",
        unit="% ou dB",
        hint="O ganho no começo do fade, na unidade escolhida (100% ou 0 dB é o nível original).",
        ge=-120.0,
        le=400.0,
    )
    end_gain: float = param(
        100.0,
        label="Ganho final",
        unit="% ou dB",
        hint="O ganho no fim do fade, na unidade escolhida.",
        ge=-120.0,
        le=400.0,
    )
    unit: Literal["percent", "db"] = param(
        "percent", label="Unidade", hint="percent: porcentagem do nível original; db: decibéis."
    )

    @model_validator(mode="after")
    def _gains_fit_the_unit(self) -> AdjustableFade:
        for name in ("start_gain", "end_gain"):
            value = getattr(self, name)
            if self.unit == "percent" and value < 0:
                raise ValueError(
                    f"efeito adjustable_fade: {name} em porcentagem vai de 0 a 400 (veio {value:g})"
                )
            if self.unit == "db" and value > 24:
                raise ValueError(f"efeito adjustable_fade: {name} em dB vai de -120 a 24 (veio {value:g})")
        return self


@register_effect
class StudioFadeOut(EffectBase):
    """Fade out de estúdio: o volume fecha numa curva quadrática enquanto um passa-baixa desce dos agudos até o corte
    final, como o fim de uma música de rádio (o Studio Fade Out do Audacity)."""

    type: Literal["studio_fade_out"] = "studio_fade_out"
    label: ClassVar[str] = "Studio Fade Out"
    audacity_name: ClassVar[str] = "Studio Fade Out"
    summary: ClassVar[str] = (
        "Fecha o volume e os agudos juntos até o fim do item, como o fim de música de rádio."
    )

    duration: float = param(3.0, label="Duração", unit="s", hint=DURATION_HINT, gt=0, le=3600)
    final_cutoff: float = param(
        200.0,
        label="Corte final",
        unit="Hz",
        hint="A frequência do passa-baixa no fim do fade. Ele parte de 20 kHz e desce em oitavas iguais até aqui.",
        ge=50.0,
        le=5000.0,
    )

    def rebased(self, origin: float, length: float, total: float | None = None) -> StudioFadeOut | None:  # type: ignore[override]
        if self.start is not None or self.end is not None:
            return super().rebased(origin, length)  # type: ignore[return-value]
        return rebase_edge_fade(self, origin, length, total, at_start=False)  # type: ignore[return-value]
