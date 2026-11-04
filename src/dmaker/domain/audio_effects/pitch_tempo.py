"""A família Pitch and Tempo do Audacity: Mudar Tom, Mudar Velocidade e Tom, Mudar Andamento, Esticar Gradualmente e
Paulstretch.

Os nomes das unidades e as faixas seguem as do Audacity (semitons e centavos, nota para nota, porcentagem, RPM de
vinil, BPM, duração de origem para duração de destino); o comportamento é reproduzido pelo `rubberband` e pelo
`asetrate` do ffmpeg e por uma função em numpy (`media/paulstretch.py`), não copiado do código dele.

Cada unidade é um modo (`mode`) e os campos de cada modo só aparecem na interface quando o modo é o dele
(`shown_when`). Mudar Tom não muda a duração e vale em qualquer item; os outros quatro mudam, então a spec só os aceita
onde o item pode crescer (voz gravada e música), e no clipe a velocidade é o `speed` dele.
"""

from __future__ import annotations

import math
from typing import ClassVar, Literal

from pydantic import model_validator

from ..pitch_tempo import (
    MAX_PITCH_SEMITONES,
    MAX_TIME_RATIO,
    MIN_TIME_RATIO,
    NOTE_NAMES,
    bpm_ratio,
    effective_ratio,
    length_ratio,
    note_to_note_semitones,
    percent_ratio,
    rpm_ratio,
    semitone_ratio,
    sliding_duration,
    sliding_steps,
)
from .base import EFFECT_SAMPLE_RATE, EffectBase, param, register_effect

NoteName = Literal[NOTE_NAMES]  # type: ignore[valid-type]

# Teto da saída do Paulstretch: ele guarda o sinal esticado inteiro na memória (uns 55 MB por minuto estéreo em ponto
# flutuante de 32 bits), então acima de 20 minutos a máquina do Douglas, com pouca memória livre, não aguenta
PAULSTRETCH_MAX_SECONDS = 20 * 60.0

SPEED_ADVICE = "Para acelerar ou desacelerar o som junto com a imagem, use o `speed` do próprio clipe; na narração, o `speed` dela."
_RATIO_RANGE = f"de {MIN_TIME_RATIO:g} a {MAX_TIME_RATIO:g} vezes"


def _inside(duration: float, effect: EffectBase) -> float:
    """Quanto do sinal o efeito cobre: o intervalo (`start`/`end`) ou o sinal todo."""
    span = effect.span(duration)
    return duration if span is None else span[1] - span[0]


def _require_ratio(name: str, ratio: float) -> None:
    if not MIN_TIME_RATIO <= ratio <= MAX_TIME_RATIO:
        raise ValueError(
            f"efeito {name}: a razão {ratio:.3g} fica fora do que o efeito aceita ({_RATIO_RANGE})"
        )


@register_effect
class ChangePitch(EffectBase):
    """Muda o tom sem mudar a duração (o Mudar Tom do Audacity), em semitons e centavos, de nota para nota ou em
    porcentagem."""

    type: Literal["change_pitch"] = "change_pitch"
    label: ClassVar[str] = "Mudar Tom"
    audacity_name: ClassVar[str] = "Change Pitch"
    summary: ClassVar[str] = (
        "Sobe ou desce o tom sem mudar a duração: em semitons e centavos, de nota para nota ou em porcentagem."
    )

    mode: Literal["semitones", "notes", "percent"] = param(
        "semitones",
        label="Unidade",
        hint="semitones: semitons e centavos; notes: de uma nota para outra; percent: porcentagem da frequência.",
    )
    semitones: float = param(
        0.0,
        label="Semitons",
        unit="semitons",
        hint="Positivo sobe o tom, negativo desce. 12 semitons são uma oitava.",
        ge=-MAX_PITCH_SEMITONES,
        le=MAX_PITCH_SEMITONES,
        shown_when={"mode": "semitones"},
    )
    cents: float = param(
        0.0,
        label="Centavos",
        unit="centavos",
        hint="Ajuste fino somado aos semitons: 100 centavos são um semitom.",
        ge=-100.0,
        le=100.0,
        shown_when={"mode": "semitones"},
    )
    from_note: NoteName = param(
        "A",
        label="Da nota",
        hint="A nota do som de origem.",
        shown_when={"mode": "notes"},
    )
    from_octave: int = param(
        4,
        label="Oitava de origem",
        hint="A oitava da nota de origem.",
        ge=0,
        le=8,
        shown_when={"mode": "notes"},
    )
    to_note: NoteName = param(
        "B",
        label="Para a nota",
        hint="A nota a que o som deve chegar.",
        shown_when={"mode": "notes"},
    )
    to_octave: int = param(
        4,
        label="Oitava de destino",
        hint="A oitava da nota de destino.",
        ge=0,
        le=8,
        shown_when={"mode": "notes"},
    )
    percent: float = param(
        0.0,
        label="Mudança de frequência",
        unit="%",
        hint="+100 dobra a frequência (sobe uma oitava) e -50 a reduz à metade (desce uma oitava).",
        ge=-90.0,
        le=1500.0,
        shown_when={"mode": "percent"},
    )
    preserve_formants: bool = param(
        False,
        label="Preservar formantes",
        hint="Mantém o timbre da voz ao mudar o tom, para ela não ficar de esquilo nem de gigante.",
    )

    @model_validator(mode="after")
    def _within_range(self) -> ChangePitch:
        if abs(self.pitch_semitones()) > MAX_PITCH_SEMITONES + 1:
            raise ValueError(
                f"efeito change_pitch: o tom pode andar até {MAX_PITCH_SEMITONES:g} semitons para cada lado "
                f"(veio {self.pitch_semitones():+.1f})"
            )
        return self

    def pitch_ratio(self) -> float:
        """A razão de frequência pedida, pela unidade escolhida."""
        if self.mode == "percent":
            return percent_ratio(self.percent)
        return semitone_ratio(self.pitch_semitones())

    def pitch_semitones(self) -> float:
        """O mesmo deslocamento em semitons, qualquer que seja a unidade usada."""
        if self.mode == "notes":
            return note_to_note_semitones(self.from_note, self.from_octave, self.to_note, self.to_octave)
        if self.mode == "percent":
            return 12.0 * math.log2(percent_ratio(self.percent))
        return self.semitones + self.cents / 100.0


@register_effect
class ChangeSpeed(EffectBase):
    """Muda a velocidade e o tom juntos, como um disco de vinil que gira mais depressa ou mais devagar (o Mudar
    Velocidade do Audacity). Muda a duração."""

    type: Literal["change_speed"] = "change_speed"
    label: ClassVar[str] = "Mudar Velocidade e Tom"
    audacity_name: ClassVar[str] = "Change Speed"
    summary: ClassVar[str] = (
        "Acelera ou desacelera o som e o tom juntos, como um vinil: por porcentagem ou de RPM para RPM. "
        "Muda a duração: só vale em voz gravada e em música."
    )
    changes_duration: ClassVar[bool] = True
    duration_advice: ClassVar[str] = SPEED_ADVICE

    mode: Literal["percent", "rpm"] = param(
        "percent", label="Unidade", hint="percent: porcentagem; rpm: de uma rotação de vinil para outra."
    )
    percent: float = param(
        0.0,
        label="Mudança de velocidade",
        unit="%",
        hint="+100 toca duas vezes mais depressa (uma oitava acima) e -50 toca na metade da velocidade.",
        ge=-90.0,
        le=900.0,
        shown_when={"mode": "percent"},
    )
    rpm_from: float = param(
        45.0,
        label="RPM de origem",
        unit="RPM",
        hint="A rotação em que o disco foi gravado: 33⅓ (33,3333), 45 ou 78.",
        ge=1.0,
        le=200.0,
        shown_when={"mode": "rpm"},
    )
    rpm_to: float = param(
        33.333333,
        label="RPM de destino",
        unit="RPM",
        hint="A rotação em que ele é tocado: 33⅓ (33,3333), 45 ou 78. De 45 para 33⅓ o som fica mais lento e mais grave.",
        ge=1.0,
        le=200.0,
        shown_when={"mode": "rpm"},
    )

    @model_validator(mode="after")
    def _within_range(self) -> ChangeSpeed:
        _require_ratio("change_speed", self.requested_ratio())
        return self

    def requested_ratio(self) -> float:
        """A razão de velocidade pedida: 2 toca duas vezes mais depressa."""
        if self.mode == "rpm":
            return rpm_ratio(self.rpm_from, self.rpm_to)
        return percent_ratio(self.percent)

    def output_duration(self, duration: float) -> float:
        # a razão que vale é a da taxa inteira que o `asetrate` recebe, não a pedida
        ratio = effective_ratio(self.requested_ratio(), EFFECT_SAMPLE_RATE)
        covered = _inside(duration, self)
        return duration - covered + covered / ratio


@register_effect
class ChangeTempo(EffectBase):
    """Muda o andamento sem mudar o tom (o Mudar Andamento do Audacity), por porcentagem, de BPM para BPM ou de uma
    duração para outra. Muda a duração."""

    type: Literal["change_tempo"] = "change_tempo"
    label: ClassVar[str] = "Mudar Andamento"
    audacity_name: ClassVar[str] = "Change Tempo"
    summary: ClassVar[str] = (
        "Acelera ou desacelera sem mudar o tom: por porcentagem, de BPM para BPM ou de uma duração para outra. "
        "Muda a duração: só vale em voz gravada e em música."
    )
    changes_duration: ClassVar[bool] = True
    duration_advice: ClassVar[str] = SPEED_ADVICE

    mode: Literal["percent", "bpm", "duration"] = param(
        "percent",
        label="Unidade",
        hint="percent: porcentagem; bpm: de um andamento para outro; duration: de uma duração para outra.",
    )
    percent: float = param(
        0.0,
        label="Mudança de andamento",
        unit="%",
        hint="+100 toca duas vezes mais depressa e -50 toca na metade da velocidade, sem mudar o tom.",
        ge=-90.0,
        le=900.0,
        shown_when={"mode": "percent"},
    )
    bpm_from: float = param(
        120.0,
        label="BPM de origem",
        unit="BPM",
        hint="O andamento da música como ela está.",
        ge=1.0,
        le=999.0,
        shown_when={"mode": "bpm"},
    )
    bpm_to: float = param(
        128.0,
        label="BPM de destino",
        unit="BPM",
        hint="O andamento a que ela deve chegar. De 120 a 128 a música fica 120/128 do que durava.",
        ge=1.0,
        le=999.0,
        shown_when={"mode": "bpm"},
    )
    length_from: float = param(
        10.0,
        label="Duração de origem",
        unit="s",
        hint="Quanto o trecho dura agora.",
        gt=0,
        le=36000.0,
        shown_when={"mode": "duration"},
    )
    length_to: float = param(
        10.0,
        label="Duração de destino",
        unit="s",
        hint="Quanto o trecho deve durar depois.",
        gt=0,
        le=36000.0,
        shown_when={"mode": "duration"},
    )

    @model_validator(mode="after")
    def _within_range(self) -> ChangeTempo:
        _require_ratio("change_tempo", self.tempo_ratio())
        return self

    @classmethod
    def between_bpm(cls, bpm_from: float, bpm_to: float) -> ChangeTempo:
        """O efeito que leva uma música de `bpm_from` a `bpm_to` (é o que o ajuste de andamento do projeto usa)."""
        return cls(mode="bpm", bpm_from=bpm_from, bpm_to=bpm_to)

    def tempo_ratio(self) -> float:
        """A razão de andamento pedida: 1,0667 toca 6,7% mais depressa."""
        if self.mode == "bpm":
            return bpm_ratio(self.bpm_from, self.bpm_to)
        if self.mode == "duration":
            return length_ratio(self.length_from, self.length_to)
        return percent_ratio(self.percent)

    def output_duration(self, duration: float) -> float:
        covered = _inside(duration, self)
        return duration - covered + covered / self.tempo_ratio()


@register_effect
class SlidingStretch(EffectBase):
    """O andamento e o tom variam do início ao fim do trecho, em linha reta (o Esticar Gradualmente do Audacity): dá
    para desacelerar até quase parar, como um disco que perde a rotação. Muda a duração."""

    type: Literal["sliding_stretch"] = "sliding_stretch"
    label: ClassVar[str] = "Esticar Gradualmente"
    audacity_name: ClassVar[str] = "Sliding Stretch"
    summary: ClassVar[str] = (
        "O andamento e o tom mudam aos poucos do início ao fim do trecho. "
        "Muda a duração: só vale em voz gravada e em música."
    )
    changes_duration: ClassVar[bool] = True
    duration_advice: ClassVar[str] = SPEED_ADVICE

    tempo_start: float = param(
        0.0,
        label="Andamento no início",
        unit="%",
        hint="Mudança de andamento no começo do trecho: 0 não muda, -50 toca na metade da velocidade.",
        ge=-90.0,
        le=900.0,
    )
    tempo_end: float = param(
        -50.0,
        label="Andamento no fim",
        unit="%",
        hint="Mudança de andamento no fim do trecho. O andamento varia em linha reta entre os dois.",
        ge=-90.0,
        le=900.0,
    )
    pitch_start: float = param(
        0.0,
        label="Tom no início",
        unit="semitons",
        hint="Deslocamento do tom no começo do trecho, sem mudar a duração.",
        ge=-MAX_PITCH_SEMITONES,
        le=MAX_PITCH_SEMITONES,
    )
    pitch_end: float = param(
        -12.0,
        label="Tom no fim",
        unit="semitons",
        hint="Deslocamento do tom no fim do trecho. O tom varia em linha reta, em semitons, entre os dois.",
        ge=-MAX_PITCH_SEMITONES,
        le=MAX_PITCH_SEMITONES,
    )
    preserve_formants: bool = param(
        False,
        label="Preservar formantes",
        hint="Mantém o timbre da voz enquanto o tom muda.",
    )

    @model_validator(mode="after")
    def _within_range(self) -> SlidingStretch:
        for name in ("tempo_start", "tempo_end"):
            _require_ratio("sliding_stretch", percent_ratio(getattr(self, name)))
        return self

    def output_duration(self, duration: float) -> float:
        covered = _inside(duration, self)
        steps = sliding_steps(
            covered,
            percent_ratio(self.tempo_start),
            percent_ratio(self.tempo_end),
            self.pitch_start,
            self.pitch_end,
        )
        return duration - covered + sliding_duration(steps)


@register_effect
class Paulstretch(EffectBase):
    """Estica o som por um fator enorme sem mudar o tom, até virar uma textura contínua e etérea (o Paulstretch do
    Audacity, pelo algoritmo público de Paul Nasca). Roda sobre as amostras, em blocos. Muda a duração."""

    type: Literal["paulstretch"] = "paulstretch"
    label: ClassVar[str] = "Paulstretch"
    audacity_name: ClassVar[str] = "Paulstretch"
    summary: ClassVar[str] = (
        "Estica o som por um fator grande, até virar uma textura contínua (abertura etérea). "
        f"Muda a duração: só vale em voz gravada e em música, e a saída vai até {PAULSTRETCH_MAX_SECONDS / 60:g} minutos."
    )
    changes_duration: ClassVar[bool] = True
    sample_stage: ClassVar[bool] = True
    duration_advice: ClassVar[str] = SPEED_ADVICE

    stretch_factor: float = param(
        10.0,
        label="Fator de esticamento",
        unit="vezes",
        hint="Quantas vezes o som fica mais longo: 8 transforma 5 s em 40 s.",
        ge=1.0,
        le=1000.0,
    )
    time_resolution: float = param(
        0.25,
        label="Resolução de tempo",
        unit="s",
        hint="O tamanho da janela de análise: menor guarda mais do ritmo, maior deixa o som mais liso e contínuo.",
        ge=0.01,
        le=10.0,
    )

    def output_duration(self, duration: float) -> float:
        covered = _inside(duration, self)
        return duration - covered + covered * self.stretch_factor

    def refusal(self, duration: float) -> str | None:
        return paulstretch_refusal(self.output_duration(duration))


def paulstretch_refusal(output_seconds: float) -> str | None:
    """Por que uma saída de `output_seconds` segundos passa do teto do Paulstretch, ou None quando cabe."""
    if output_seconds <= PAULSTRETCH_MAX_SECONDS:
        return None
    return (
        f"Paulstretch: a saída teria {output_seconds / 60:.1f} minutos e o teto é de {PAULSTRETCH_MAX_SECONDS / 60:g} "
        "(o resultado fica inteiro na memória). Use um fator menor ou aplique em um trecho mais curto."
    )
