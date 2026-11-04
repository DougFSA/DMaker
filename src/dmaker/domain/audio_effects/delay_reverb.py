"""A família Delay and Reverb do Audacity: Atraso, Eco e Reverb.

Os nomes e as faixas seguem os do Audacity (tipo de atraso, número de ecos, fator de decaimento, tamanho da sala,
reverberância, amortecimento, tom grave e agudo, ganho molhado e seco, largura estéreo, só molhado); o comportamento é
reproduzido por filtros do ffmpeg (`adelay`, `rubberband`, `afir`) e por uma resposta ao impulso própria (`media/reverb.py`),
não copiado do código dele.

Como no Audacity, o item mantém a duração e a cauda do eco ou da reverberação é cortada no fim. `extend_tail` estica o
item para a cauda caber, e por isso só vale onde o item pode crescer (voz gravada e música).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from ..echo import DelayEcho, delay_echoes, echo_tail_seconds
from ..reverb import ReverbSettings
from .base import EffectBase, param, register_effect

TAIL_ADVICE = "Desligue `extend_tail`: nos outros itens a cauda é cortada no fim do item, como no Audacity."
TAIL_HINT = (
    "Estica o item para a cauda caber, em vez de cortá-la no fim. Só vale em voz gravada e em música; nos outros "
    "itens a cauda é cortada no fim, como no Audacity."
)
MAX_ECHOES = (
    100  # cada eco é um ramo do grafo (e um `rubberband`, se o tom muda): mais que isto não ajuda ninguém
)
MAX_DELAY_SECONDS = 5.0


@register_effect
class Delay(EffectBase):
    """Repete o som um número fixo de vezes, cada repetição mais baixa e, se pedido, mais aguda ou mais grave que a
    anterior. Regular, bola quicando (as repetições se aproximam) ou bola quicando ao contrário (se afastam)."""

    type: Literal["delay"] = "delay"
    label: ClassVar[str] = "Atraso"
    audacity_name: ClassVar[str] = "Delay"
    summary: ClassVar[str] = (
        "Repete o som um número de vezes, mais baixo a cada repetição: regular, bola quicando ou bola quicando ao contrário, "
        "com mudança de tom opcional por eco."
    )
    duration_advice: ClassVar[str] = TAIL_ADVICE

    delay_type: Literal["regular", "bouncing", "reverse_bouncing"] = param(
        "regular",
        label="Tipo de atraso",
        hint="regular: ecos a intervalos iguais; bouncing: os intervalos encurtam, como uma bola quicando; "
        "reverse_bouncing: os intervalos aumentam.",
    )
    dry_db: float = param(
        0.0,
        label="Ganho do original",
        unit="dB",
        hint="Volume do som original, sem os ecos.",
        ge=-60.0,
        le=6.0,
    )
    delay_seconds: float = param(
        0.5,
        label="Tempo de atraso",
        unit="s",
        hint="Entre o som e o primeiro eco (no regular, entre todos). Nos tipos com bola, é o maior intervalo.",
        ge=0.001,
        le=MAX_DELAY_SECONDS,
    )
    echoes: int = param(
        3, label="Número de ecos", unit="ecos", hint="Quantas repetições.", ge=1, le=MAX_ECHOES
    )
    decay_db: float = param(
        -6.0,
        label="Volume por eco",
        unit="dB",
        hint="Quanto cada eco muda de volume em relação ao anterior (negativo: mais baixo).",
        ge=-40.0,
        le=0.0,
    )
    pitch_semitones: float = param(
        0.0,
        label="Mudança de tom por eco",
        unit="semitons",
        hint="Quanto o tom muda a cada passo (o `rubberband` sem mudar a duração). Cada eco com tom diferente custa uma "
        "passada do `rubberband` sobre o item.",
        ge=-12.0,
        le=12.0,
    )
    pitch_every: int = param(
        1,
        label="Ecos por mudança de tom",
        unit="ecos",
        hint="O tom muda a cada tantos ecos.",
        ge=1,
        le=MAX_ECHOES,
    )
    extend_tail: bool = param(False, label="Esticar o item pela cauda", hint=TAIL_HINT)

    def repetitions(self) -> list[DelayEcho]:
        """As repetições (quando, ganho e tom) como o grafo as monta."""
        return delay_echoes(
            self.delay_type,
            self.delay_seconds,
            self.echoes,
            self.decay_db,
            self.pitch_semitones,
            self.pitch_every,
        )

    def alters_duration(self) -> bool:
        return self.extend_tail

    def output_duration(self, duration: float) -> float:
        return duration + self.repetitions()[-1].at if self.extend_tail else duration


@register_effect
class Echo(EffectBase):
    """Repete o som com realimentação: cada repetição é a anterior vezes o fator de decaimento, até cair a -60 dB."""

    type: Literal["echo"] = "echo"
    label: ClassVar[str] = "Eco"
    audacity_name: ClassVar[str] = "Echo"
    summary: ClassVar[str] = (
        "Repete o som a cada tempo de atraso, cada repetição o fator de decaimento da anterior, até sumir (-60 dB)."
    )
    duration_advice: ClassVar[str] = TAIL_ADVICE

    delay_seconds: float = param(
        1.0,
        label="Tempo de atraso",
        unit="s",
        hint="Entre uma repetição e a seguinte.",
        ge=0.001,
        le=MAX_DELAY_SECONDS,
    )
    decay: float = param(
        0.5,
        label="Fator de decaimento",
        hint="Quanto de cada repetição vem na seguinte: 0,5 é metade da amplitude. 0 não repete; 1 repete sem cair, até "
        "o fim do item.",
        ge=0.0,
        le=1.0,
    )
    extend_tail: bool = param(False, label="Esticar o item pela cauda", hint=TAIL_HINT)

    def alters_duration(self) -> bool:
        return self.extend_tail

    def output_duration(self, duration: float) -> float:
        return duration + echo_tail_seconds(self.delay_seconds, self.decay) if self.extend_tail else duration


@register_effect
class Reverb(EffectBase):
    """Dá ambiente ao som: um reverb do estilo Freeverb (pentes com amortecimento e passa-tudo), cuja resposta a um clique é
    gerada aqui e aplicada por convolução. Os predefinidos do Audacity (Vocal, Banheiro, Sala, Catedral...) são
    predefinições."""

    type: Literal["reverb"] = "reverb"
    label: ClassVar[str] = "Reverb"
    audacity_name: ClassVar[str] = "Reverb"
    summary: ClassVar[str] = (
        "Dá ambiente ao som: tamanho da sala, pré-atraso, reverberância, amortecimento, tom, ganho molhado e seco e largura "
        "estéreo."
    )
    duration_advice: ClassVar[str] = TAIL_ADVICE

    room_size: float = param(
        75.0,
        label="Tamanho da sala",
        unit="%",
        hint="Sala maior: reverberação mais longa e ecos mais espaçados.",
        ge=0.0,
        le=100.0,
    )
    pre_delay_ms: float = param(
        10.0,
        label="Pré-atraso",
        unit="ms",
        hint="Quanto o reverb demora a começar depois do som.",
        ge=0.0,
        le=200.0,
    )
    reverberance: float = param(
        50.0,
        label="Reverberância",
        unit="%",
        hint="Quanto tempo o reverb dura (junto com o tamanho da sala).",
        ge=0.0,
        le=100.0,
    )
    damping: float = param(
        50.0,
        label="Amortecimento",
        unit="%",
        hint="Quanto os agudos morrem antes dos graves: alto soa como uma sala forrada.",
        ge=0.0,
        le=100.0,
    )
    tone_low: float = param(
        100.0,
        label="Tom grave",
        unit="%",
        hint="100: os graves passam inteiros no reverb; menos corta os graves dele.",
        ge=0.0,
        le=100.0,
    )
    tone_high: float = param(
        100.0,
        label="Tom agudo",
        unit="%",
        hint="100: os agudos passam inteiros no reverb; menos corta os agudos dele.",
        ge=0.0,
        le=100.0,
    )
    wet_db: float = param(
        -1.0,
        label="Ganho molhado",
        unit="dB",
        hint="Volume do reverb. 0 dB dá ao som molhado a mesma potência do seco.",
        ge=-60.0,
        le=10.0,
    )
    dry_db: float = param(
        -1.0, label="Ganho seco", unit="dB", hint="Volume do som original.", ge=-60.0, le=10.0
    )
    stereo_width: float = param(
        100.0,
        label="Largura estéreo",
        unit="%",
        hint="0: o mesmo reverb nos dois lados (mono); 100: um reverb diferente em cada lado.",
        ge=0.0,
        le=100.0,
    )
    wet_only: bool = param(False, label="Só molhado", hint="Tira o som original e deixa só o reverb.")
    extend_tail: bool = param(False, label="Esticar o item pela cauda", hint=TAIL_HINT)

    def impulse_settings(self) -> ReverbSettings:
        """O que decide a resposta ao impulso: o seco, o "só molhado" e a cauda ficam de fora."""
        return ReverbSettings(
            self.room_size,
            self.pre_delay_ms,
            self.reverberance,
            self.damping,
            self.tone_low,
            self.tone_high,
            self.wet_db,
            self.stereo_width,
        )

    def alters_duration(self) -> bool:
        return self.extend_tail

    def output_duration(self, duration: float) -> float:
        return duration + self.impulse_settings().tail_seconds() if self.extend_tail else duration
