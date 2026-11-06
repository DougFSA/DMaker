"""A família Distortion and Modulation do Audacity: Distorção, Phaser, Tremolo, Wahwah e Vocoder.

Os nomes e as faixas dos controles seguem os do Audacity. O Tremolo é um filtro do ffmpeg (`volume` com o LFO por expressão);
a Distorção, o Phaser, o Wahwah e o Vocoder trabalham sobre as amostras em numpy (`media/distortion.py`, `media/modulation.py`,
`media/vocoder.py`), porque o ffmpeg não tem filtro que reproduza o controle deles: ver `filtergraph.audio_effects.distortion_modulation`.
Por isso os quatro não valem em `audio.master_effects`, que roda dentro do grafo ao vivo.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from ..auto_duck import is_track_id
from ..generators import normalized_params, parse_generator
from .base import SHOWN_WHEN_FILLED, EffectBase, param, register_effect

# O Vocoder gera a portadora na duração do item, e o gerador de som vai até 10 minutos
MAX_VOCODER_SECONDS = 600.0
DEFAULT_CARRIER_PARAMS: dict[str, Any] = {"waveform": "sawtooth", "frequency_hz": 110.0, "amplitude_db": -6.0}

DistortionKind = Literal[
    "hard_clip",
    "soft_clip",
    "soft_overdrive",
    "medium_overdrive",
    "hard_overdrive",
    "cubic",
    "even_harmonics",
    "expand_compress",
    "leveller",
    "rectifier",
    "hard_limiter",
    "bit_crusher",
]
KIND_HINT = (
    "hard_clip: corte seco no limiar; soft_clip: corte arredondado; soft_overdrive, medium_overdrive e hard_overdrive: "
    "saturação de dureza crescente; cubic: curva cúbica (harmônicos ímpares); even_harmonics: harmônicos pares (calor de "
    "válvula); expand_compress: expande ou comprime o nível; leveller: nivela, sobe o baixo e achata o alto; rectifier: "
    "retificador; hard_limiter: limitador seco, com o limiar levado a -1 dBFS; bit_crusher: reduz bits e taxa."
)


@register_effect
class Distortion(EffectBase):
    """Deforma a onda por uma curva de transferência: ganho de entrada, a curva (repetida `repeats` vezes), filtro de corrente
    contínua e nível de saída. O tipo diz a curva."""

    type: Literal["distortion"] = "distortion"
    label: ClassVar[str] = "Distorção"
    audacity_name: ClassVar[str] = "Distortion"
    summary: ClassVar[str] = (
        "Deforma a onda: corte seco ou suave, overdrive, cúbica, harmônicos pares, retificador, limitador seco e bit crusher, "
        "com ganho de entrada, nível de saída e filtro de corrente contínua."
    )
    sample_stage: ClassVar[bool] = True

    kind: DistortionKind = param("hard_clip", label="Tipo", hint=KIND_HINT)
    drive_db: float = param(
        0.0,
        label="Ganho de entrada",
        unit="dB",
        hint="Quanto o som sobe antes da curva: mais ganho, mais distorção.",
        ge=0.0,
        le=48.0,
    )
    threshold_db: float = param(
        -6.0,
        label="Limiar",
        unit="dB",
        hint="Onde a curva começa a segurar o som (os tipos de corte, overdrive, cúbico e limitador).",
        ge=-100.0,
        le=0.0,
    )
    amount: float = param(
        50.0,
        label="Quantidade",
        unit="%",
        hint="soft_clip: a dureza do joelho; even_harmonics: a parte de segundo harmônico; expand_compress: acima de 50 "
        "comprime e abaixo expande; rectifier: a parte de onda completa. Os outros tipos não usam.",
        ge=0.0,
        le=100.0,
    )
    repeats: int = param(
        1, label="Repetições", unit="vezes", hint="Quantas vezes a curva é aplicada em seguida.", ge=1, le=5
    )
    bits: int = param(
        8,
        label="Bits",
        unit="bits",
        hint="A resolução do bit crusher.",
        ge=1,
        le=24,
        shown_when={"kind": "bit_crusher"},
    )
    downsample: int = param(
        1,
        label="Redução de taxa",
        unit="x",
        hint="O bit crusher repete cada amostra por esse tanto de quadros (1: sem redução).",
        ge=1,
        le=64,
        shown_when={"kind": "bit_crusher"},
    )
    dc_filter: bool = param(
        True,
        label="Filtro de corrente contínua",
        hint="Tira o desvio de zero que algumas curvas criam (passa-alta de 10 Hz).",
    )
    hiss_db: float = param(
        -100.0,
        label="Chiado",
        unit="dB",
        hint="Ruído branco somado depois da curva, para o som de rádio velho (-100: sem chiado).",
        ge=-100.0,
        le=-20.0,
    )
    output_db: float = param(
        0.0,
        label="Nível de saída",
        unit="dB",
        hint="Ganho depois da distorção. Acima de 0 o som pode passar de 0 dBFS.",
        ge=-60.0,
        le=24.0,
    )


@register_effect
class Phaser(EffectBase):
    """O fazedor de ondas: mistura o som com uma cópia passada por uma cadeia de passa-tudo cuja frequência um LFO varre, o que
    cava entalhes que passeiam pelo espectro."""

    type: Literal["phaser"] = "phaser"
    label: ClassVar[str] = "Phaser"
    audacity_name: ClassVar[str] = "Phaser"
    summary: ClassVar[str] = (
        "Entalhes que passeiam pelo espectro: estágios, mistura, frequência e fase do LFO, profundidade, realimentação."
    )
    sample_stage: ClassVar[bool] = True

    stages: int = param(
        2,
        label="Estágios",
        unit="estágios",
        hint="Quantos passa-tudo em série (par, de 2 a 24): cada par cava um entalhe.",
        ge=2,
        le=24,
    )
    dry_wet: float = param(
        128.0,
        label="Seco/molhado",
        hint="0: só o som original; 255: só o som processado; 128: metade e metade.",
        ge=0.0,
        le=255.0,
    )
    lfo_hz: float = param(
        0.4,
        label="Frequência do LFO",
        unit="Hz",
        hint="Quantas vezes por segundo a varredura vai e volta.",
        ge=0.001,
        le=4.0,
    )
    phase_degrees: float = param(
        0.0, label="Fase inicial do LFO", unit="graus", hint="Onde a varredura começa.", ge=0.0, le=359.0
    )
    depth: float = param(
        100.0, label="Profundidade", hint="Quanto a varredura anda (0 a 255).", ge=0.0, le=255.0
    )
    feedback_percent: float = param(
        0.0,
        label="Realimentação",
        unit="%",
        hint="Parte do som processado que volta para a entrada: entalhes mais fundos e ressonantes.",
        ge=-100.0,
        le=100.0,
    )
    output_db: float = param(
        -6.0,
        label="Ganho de saída",
        unit="dB",
        hint="Ganho depois do efeito (o padrão do Audacity é -6 dB).",
        ge=-30.0,
        le=30.0,
    )

    @model_validator(mode="after")
    def _even_stages(self) -> Phaser:
        if self.stages % 2:
            raise ValueError(f"efeito phaser: os estágios são pares (de 2 a 24); recebeu {self.stages}")
        return self


@register_effect
class Tremolo(EffectBase):
    """Faz o volume oscilar: o ganho vai de `1 - intensidade` ao nível original, no ritmo da frequência e da onda."""

    type: Literal["tremolo"] = "tremolo"
    label: ClassVar[str] = "Tremolo"
    audacity_name: ClassVar[str] = "Tremolo"
    summary: ClassVar[str] = (
        "Faz o volume oscilar em onda senoidal, triangular, dente de serra (e invertida) ou quadrada: frequência, fase e intensidade."
    )

    waveform: Literal["sine", "triangle", "sawtooth", "inverse_sawtooth", "square"] = param(
        "sine",
        label="Onda",
        hint="sine, triangle, sawtooth (dente de serra), inverse_sawtooth (dente de serra invertido) ou square (quadrada).",
    )
    frequency_hz: float = param(
        4.0, label="Frequência", unit="Hz", hint="Oscilações por segundo.", ge=0.001, le=100.0
    )
    phase_degrees: float = param(
        0.0, label="Fase inicial", unit="graus", hint="Onde a onda começa.", ge=0.0, le=360.0
    )
    depth: float = param(
        40.0,
        label="Intensidade",
        unit="%",
        hint="Quanto o volume cai no ponto mais baixo: 50 deixa o volume oscilar entre metade e o nível original; "
        "100 chega ao silêncio.",
        ge=0.0,
        le=100.0,
    )


@register_effect
class Wahwah(EffectBase):
    """Um filtro passa-banda ressonante cujo centro um LFO varre: o som do pedal de wah-wah."""

    type: Literal["wahwah"] = "wahwah"
    label: ClassVar[str] = "Wahwah"
    audacity_name: ClassVar[str] = "Wahwah"
    summary: ClassVar[str] = (
        "Um passa-banda ressonante varrido por um LFO: frequência e fase do LFO, profundidade, ressonância e deslocamento."
    )
    sample_stage: ClassVar[bool] = True

    lfo_hz: float = param(
        1.5,
        label="Frequência do LFO",
        unit="Hz",
        hint="Quantas vezes por segundo o pedal vai e volta.",
        ge=0.1,
        le=4.0,
    )
    phase_degrees: float = param(
        0.0, label="Fase inicial do LFO", unit="graus", hint="Onde a varredura começa.", ge=0.0, le=359.0
    )
    depth: float = param(
        70.0, label="Profundidade", unit="%", hint="Quanto o centro do filtro anda.", ge=0.0, le=100.0
    )
    resonance: float = param(
        2.5, label="Ressonância", hint="O Q do filtro: maior é mais estreito e mais vocal.", ge=0.1, le=10.0
    )
    offset: float = param(
        30.0,
        label="Deslocamento de frequência",
        unit="%",
        hint="O ponto mais grave da varredura, em porcentagem do caminho de 300 Hz a 2,5 kHz.",
        ge=0.0,
        le=100.0,
    )
    output_db: float = param(
        -6.0, label="Ganho de saída", unit="dB", hint="Ganho depois do efeito.", ge=-30.0, le=30.0
    )


class CarrierSound(BaseModel):
    """A portadora gerada do Vocoder: um gerador de som do DMK-58 (`tone`, `noise`, `pluck`...) e os parâmetros dele. Os que
    faltam ficam no padrão do gerador."""

    model_config = ConfigDict(extra="forbid")

    generator: str = "tone"
    # vazio: a dente de serra de 110 Hz quando o gerador é o Tom; nos outros geradores, os padrões deles
    params: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _known_generator(self) -> CarrierSound:
        if self.params is None:
            self.params = dict(DEFAULT_CARRIER_PARAMS) if self.generator == "tone" else {}
        self.params = normalized_params(self.generator, self.params)
        if parse_generator(self.generator, self.params).files():
            raise ValueError(
                f"vocoder: a portadora {self.generator!r} lê arquivos do projeto e não vale aqui; use um gerador "
                "de sinal (tone, noise, chirp, pluck...)"
            )
        return self


@register_effect
class Vocoder(EffectBase):
    """A voz do item desenha o espectro de uma portadora (por padrão uma onda dente de serra de 110 Hz): o clássico som de
    robô. A fala continua inteligível porque o ritmo e as vogais vêm da voz; o timbre, da portadora."""

    type: Literal["vocoder"] = "vocoder"
    label: ClassVar[str] = "Vocoder"
    audacity_name: ClassVar[str] = "Vocoder"
    summary: ClassVar[str] = (
        "A voz modula uma portadora (dente de serra, por exemplo): som de robô. Número de bandas, distância, ruído branco e "
        "agulhas de radar para as consoantes."
    )
    sample_stage: ClassVar[bool] = True

    carrier: CarrierSound = param(
        CarrierSound(),
        label="Portadora",
        hint="O som que a voz modula: um gerador de som (`generator`) com os parâmetros dele (`params`). O padrão é uma "
        "dente de serra de 110 Hz.",
        kind="carrier",
        shown_when={"carrier_track": None},
    )
    carrier_track: str | None = param(
        None,
        label="Trilha da portadora",
        hint="De que trilha do projeto vem a portadora (A1, A2..., MUS, NAR, VO ou SFX): a voz canta na harmonia dela. "
        "Vazio: a portadora gerada. Com uma trilha escolhida, os controles da portadora gerada (onda e frequência) ficam "
        "escondidos e os valores ficam guardados. A trilha é lida antes dos abaixamentos do Auto Duck; se ela não existe "
        "ou ainda não toca, o efeito usa a portadora gerada.",
        kind="carrier_track",
    )
    carrier_ignores_mute: bool = param(
        False,
        label="Ouvir a trilha mesmo muda",
        hint="Ligado: o mudo e o solo só tiram a trilha da mistura, e o Vocoder continua ouvindo a portadora dela. Desligado: a "
        "trilha que não soa não serve de portadora, e o efeito usa a portadora gerada.",
        shown_when={"carrier_track": SHOWN_WHEN_FILLED},
    )
    bands: int = param(
        40,
        label="Bandas",
        unit="bandas",
        hint="Em quantas faixas de frequência a voz é dividida. Mais bandas, fala mais nítida.",
        ge=1,
        le=50,
    )
    distance: float = param(
        20.0,
        label="Distância",
        hint="A largura de cada banda em relação ao espaço entre elas. 20 deixa cada frequência em duas bandas vizinhas.",
        ge=1.0,
        le=120.0,
    )
    original_level: float = param(
        0.0,
        label="Amplitude do original",
        unit="%",
        hint="Quanto da voz original volta misturada.",
        ge=0.0,
        le=100.0,
    )
    noise_level: float = param(
        25.0,
        label="Ruído branco",
        unit="%",
        hint="Ruído somado à portadora para as consoantes (s, f, x) saírem; sem ele elas somem.",
        ge=0.0,
        le=100.0,
    )
    radar_level: float = param(
        0.0,
        label="Agulhas de radar",
        unit="%",
        hint="Pulsos curtos somados à portadora, que enchem o espectro todo e ajudam as consoantes.",
        ge=0.0,
        le=100.0,
    )
    radar_hz: float = param(
        30.0, label="Frequência das agulhas", unit="Hz", hint="Quantos pulsos por segundo.", ge=1.0, le=1000.0
    )
    output_db: float = param(
        -3.0, label="Ganho de saída", unit="dB", hint="Ganho depois do efeito.", ge=-30.0, le=30.0
    )

    @field_validator("carrier_track")
    @classmethod
    def _track(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not is_track_id(value):
            raise ValueError(
                f"vocoder: trilha desconhecida: {value!r}. Use A1, A2 (A3...), MUS, NAR, VO ou SFX, os ids da linha do tempo"
            )
        return value

    @model_serializer(mode="wrap")
    def _omit_unset_track(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Sem trilha, e sem a escolha de ouvi-la muda, os campos somem do dump: o efeito de um projeto que nunca os usou segue
        com os mesmos bytes e o mesmo hash."""
        data = handler(self)
        if data.get("carrier_track") is None:
            data.pop("carrier_track", None)
        if not data.get("carrier_ignores_mute"):
            data.pop("carrier_ignores_mute", None)
        return data

    def carrier_sound(self) -> tuple[str, dict[str, Any]]:
        return self.carrier.generator, dict(self.carrier.params or {})

    def carrier_track_id(self) -> str | None:
        return self.carrier_track

    def hears_silenced_carrier(self) -> bool:
        return self.carrier_ignores_mute

    def refusal(self, duration: float) -> str | None:
        if duration > MAX_VOCODER_SECONDS:
            return (
                f"vocoder: o item dura {duration / 60:.1f} minutos e a portadora gerada vai até "
                f"{MAX_VOCODER_SECONDS / 60:.0f}. Use `start` e `end` para tratar um trecho"
            )
        return None
