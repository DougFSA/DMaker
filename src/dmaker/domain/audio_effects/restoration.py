"""Os efeitos de limpeza e reparo: Redução de Ruído, Remover Cliques, Corrigir Clipping e Reparar.

São a família "Noise Removal and Repair" do Audacity, com os nomes, as faixas e os padrões dele. O Truncar Silêncio
dessa família não é um efeito: ele encurta o item (e, no clipe, a imagem junto), então é uma operação de edição
(`audio_truncate_silence`), como o Cortar. Por isso são quatro efeitos e uma operação. O comportamento é reproduzido
pelo ffmpeg (cliques e clipping) e por contas em numpy (ruído e reparo) em `filtergraph.audio_effects.restoration`,
não copiado do código do Audacity.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import model_validator

from .base import EFFECT_SAMPLE_RATE, EffectBase, param, register_effect

# O Reparar conserta de uma amostra a 128 (o limite do Audacity). A 48 kHz são 2,7 ms: um estalo, não um trecho de som
MAX_REPAIR_SAMPLES = 128
AUTO_PROFILE = "auto"  # o perfil é o trecho mais quieto do próprio item


@register_effect
class NoiseReduction(EffectBase):
    """Atenua o chiado de fundo a partir de um perfil: o espectro de um trecho que só tem o ruído. O perfil é o
    nome de um trecho guardado no projeto (`audio.noise_profiles`) ou `auto`, o trecho mais quieto do item."""

    type: Literal["noise_reduction"] = "noise_reduction"
    label: ClassVar[str] = "Redução de ruído"
    audacity_name: ClassVar[str] = "Noise Reduction"
    summary: ClassVar[str] = (
        "Tira o chiado de fundo a partir de um perfil de ruído (um trecho só de ruído, ou o mais quieto do item)."
    )
    sample_stage: ClassVar[bool] = True

    reduction_db: float = param(
        12.0,
        label="Redução de ruído",
        unit="dB",
        hint="Quanto o ruído cai. Mais que 12 a 18 dB deixa a fala metálica.",
        ge=0.0,
        le=48.0,
    )
    sensitivity: float = param(
        6.0,
        label="Sensibilidade",
        unit="dB",
        hint="Margem acima do ruído do perfil a partir da qual o som conta como fala. Alta: tira mais ruído e "
        "pode levar um pouco da fala; baixa: deixa mais ruído.",
        ge=0.0,
        le=24.0,
    )
    smoothing_bands: int = param(
        3,
        label="Suavização de frequência",
        unit="bandas",
        hint="Alarga a média entre frequências vizinhas. Mais bandas tiram o chiado metálico de sobra, "
        "com menos precisão.",
        ge=0,
        le=12,
    )
    profile: str = param(
        AUTO_PROFILE,
        label="Perfil de ruído",
        hint="`auto` usa o trecho mais quieto do item; ou o nome de um perfil guardado "
        "(`audio.noise_profiles`, criado por `noise_profile`).",
        kind="profile",
        min_length=1,
    )

    def noise_profile(self) -> str | None:
        return self.profile


@register_effect
class ClickRemoval(EffectBase):
    """Tira estalos curtos (cliques de boca, de disco, de emenda) interpolando o som em volta."""

    type: Literal["click_removal"] = "click_removal"
    label: ClassVar[str] = "Remover cliques"
    audacity_name: ClassVar[str] = "Click Removal"
    summary: ClassVar[str] = "Tira estalos curtos (cliques de boca, de disco, de emenda)."

    threshold: int = param(
        200,
        label="Limiar",
        hint="Quanto menor, mais cliques são pegos (e mais risco de mexer na fala). Abaixo de 200 o detector já "
        "está na sensibilidade máxima.",
        ge=0,
        le=900,
    )
    max_spike_width: int = param(
        20,
        label="Largura máxima do pico",
        unit="amostras",
        hint="O clique mais largo que ainda é consertado. Mais largo que isso é tratado como som.",
        ge=0,
        le=40,
    )


@register_effect
class ClipFix(EffectBase):
    """Reconstrói os picos achatados de um som que estourou (clipping), a partir da onda em volta deles."""

    type: Literal["clip_fix"] = "clip_fix"
    label: ClassVar[str] = "Corrigir clipping"
    audacity_name: ClassVar[str] = "Clip Fix"
    summary: ClassVar[str] = "Reconstrói os picos achatados de um som que estourou."

    threshold_percent: float = param(
        100.0,
        label="Limiar de clipping",
        unit="%",
        hint="A partir de que nível (% do máximo) a amostra conta como achatada. Se o pico foi cortado em 70%, "
        "use 70.",
        ge=0.0,
        le=100.0,
    )
    reduce_db: float = param(
        0.0,
        label="Reduzir volume",
        unit="dB",
        hint="Baixa o volume depois de reconstruir, para os picos refeitos caberem sem estourar de novo.",
        ge=0.0,
        le=100.0,
    )


@register_effect
class Repair(EffectBase):
    """Refaz um trecho curtíssimo (até 128 amostras, 2,7 ms) com a onda de antes e de depois dele: o estalo que o
    Remover cliques não pegou. Exige o intervalo (`start` e `end`)."""

    type: Literal["repair"] = "repair"
    label: ClassVar[str] = "Reparar"
    audacity_name: ClassVar[str] = "Repair"
    summary: ClassVar[str] = (
        "Refaz um trecho de até 128 amostras (2,7 ms) com o som de antes e de depois dele."
    )
    owns_interval: ClassVar[bool] = True
    needs_selection: ClassVar[bool] = True
    sample_stage: ClassVar[bool] = True

    @model_validator(mode="after")
    def _short_interval(self) -> Repair:
        if self.start is None or self.end is None:
            raise ValueError("efeito repair: informe `start` e `end`, o trecho curto que será refeito")
        samples = round((self.end - self.start) * EFFECT_SAMPLE_RATE)
        if samples > MAX_REPAIR_SAMPLES:
            raise ValueError(
                f"efeito repair: o trecho tem {samples} amostras ({(self.end - self.start) * 1000:.1f} ms) e o "
                f"Reparar conserta no máximo {MAX_REPAIR_SAMPLES} ({MAX_REPAIR_SAMPLES / EFFECT_SAMPLE_RATE * 1000:.1f} ms). "
                "Selecione só o estalo, ou use Remover cliques"
            )
        return self
