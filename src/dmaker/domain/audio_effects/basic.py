"""Os cinco efeitos básicos: Amplificar, Normalizar, Inverter, Reverter e Repetir.

Os nomes, as faixas e os padrões seguem os do Audacity (que o usuário reconhece); o comportamento é reproduzido
pelos filtros do ffmpeg em `filtergraph.audio_effects.basic`, não copiado do código dele.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from .base import EffectBase, param, register_effect


@register_effect
class Amplify(EffectBase):
    """Sobe ou desce o volume por um ganho em dB; com `prevent_clipping`, o ganho nunca leva o pico além de
    0 dBFS."""

    type: Literal["amplify"] = "amplify"
    label: ClassVar[str] = "Amplificar"
    audacity_name: ClassVar[str] = "Amplify"
    summary: ClassVar[str] = "Muda o volume por um ganho em dB, com a opção de não deixar o som clipar."

    gain_db: float = param(
        0.0,
        label="Amplificação",
        unit="dB",
        hint="Ganho em dB: positivo sobe o volume, negativo desce.",
        ge=-100.0,
        le=100.0,
    )
    prevent_clipping: bool = param(
        False,
        label="Não deixar clipar",
        hint="Limita o ganho para o pico do trecho ficar em 0 dBFS no máximo (como desmarcar "
        "'Permitir clipping' no Audacity).",
    )

    def needs_measure(self) -> bool:
        return self.prevent_clipping and self.gain_db > 0


@register_effect
class Normalize(EffectBase):
    """Leva o pico do trecho a um valor alvo em dBFS, com a opção de tirar antes o deslocamento DC."""

    type: Literal["normalize"] = "normalize"
    label: ClassVar[str] = "Normalizar"
    audacity_name: ClassVar[str] = "Normalize"
    summary: ClassVar[str] = "Ajusta o volume para o pico chegar ao alvo, tirando antes o deslocamento DC."

    peak_db: float = param(
        -1.0,
        label="Pico alvo",
        unit="dBFS",
        hint="Pico máximo depois de normalizar.",
        ge=-100.0,
        le=0.0,
    )
    remove_dc: bool = param(
        True,
        label="Remover deslocamento DC",
        hint="Centra a onda em 0 antes de normalizar.",
    )
    stereo_independent: bool = param(
        False,
        label="Canais independentes",
        hint="Normaliza o canal esquerdo e o direito cada um para o seu pico.",
    )

    def needs_measure(self) -> bool:
        return True


@register_effect
class Invert(EffectBase):
    """Inverte a fase: cada amostra troca de sinal. Soa igual sozinha; muda quando soma com outro som."""

    type: Literal["invert"] = "invert"
    label: ClassVar[str] = "Inverter"
    audacity_name: ClassVar[str] = "Invert"
    summary: ClassVar[str] = "Inverte a fase da onda (troca o sinal de cada amostra)."


@register_effect
class Reverse(EffectBase):
    """Toca o trecho de trás para a frente."""

    type: Literal["reverse"] = "reverse"
    label: ClassVar[str] = "Reverter"
    audacity_name: ClassVar[str] = "Reverse"
    summary: ClassVar[str] = "Toca o trecho de trás para a frente."
    reorders_time: ClassVar[bool] = True


@register_effect
class Repeat(EffectBase):
    """Repete o trecho `times` vezes seguidas, sem pausa entre as cópias."""

    type: Literal["repeat"] = "repeat"
    label: ClassVar[str] = "Repetir"
    audacity_name: ClassVar[str] = "Repeat"
    summary: ClassVar[str] = (
        "Repete o trecho em sequência. Aumenta a duração: só vale em voz gravada e em música."
    )
    changes_duration: ClassVar[bool] = True
    reorders_time: ClassVar[bool] = True

    times: int = param(
        2,
        label="Vezes que toca",
        hint="Quantas vezes o trecho toca no total: 2 dobra a duração. (No Audacity o campo conta as "
        "repetições além da primeira; aqui, as passagens.)",
        ge=1,
        le=100,
    )

    def output_duration(self, duration: float) -> float:
        inside = self.span(duration)
        repeated = duration if inside is None else inside[1] - inside[0]
        return duration + (self.times - 1) * repeated
