"""Modelo do projeto de edição (spec JSON). É o contrato entre quem pede a edição e o renderizador.

Convenções:
- tempos em segundos; cores em #RRGGBB ou chave do tema (primary, accent, text...);
- tamanhos de texto em px na base 1080 (lado menor do vídeo): escalam com a resolução;
- posições x/y em fração (0..1) do quadro;
- regiões nomeadas (`regions`): retângulos do quadro, em fração, que as sobreposições usam por nome
  (`region`) em vez de x/y/width.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from .. import config
from .atomic_file import read_bytes_retrying, write_bytes_atomic
from .audio_effects import AudioEffect
from .audio_presets import (
    AudioFormatError,
    EncodingChoices,
    get_audio_preset,
    is_audio_preset,
    resolve_encoding,
)
from .auto_duck import AutoDuck
from .curves import Curve
from .generators import normalized_params
from .transitions import all_transition_names


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- cadeia de efeitos de áudio ----------

# onde um efeito que muda a duração do item (Repetir) é aceito; a mensagem de recusa cita estes lugares
GROWABLE_AUDIO = "voz gravada (audio.voiceover) e música (audio.music)"


class EffectsOwner(Strict):
    """Item da spec que tem uma lista de efeitos de áudio (`effects`, ou `master_effects` no barramento final).

    Fica de fora do dump a lista vazia: um projeto sem efeitos gera exatamente os mesmos bytes e o mesmo hash de
    cache de antes de o campo existir. E recusa, na hora de carregar a spec, o efeito que muda a duração onde o
    item não pode crescer (os vídeos, as faixas externas e a narração têm a duração presa ao resto da edição)."""

    effect_fields: ClassVar[tuple[str, ...]] = ("effects",)
    effects_place: ClassVar[str] = "item"  # como a mensagem de recusa chama o lugar
    effects_may_grow: ClassVar[bool] = False  # se um efeito que muda a duração é aceito aqui
    # campos de mixagem (deslocamento, pan) que ficam fora do dump enquanto valem o padrão, pelo mesmo motivo da
    # lista vazia: o hash de cache e o `spec.json` de um projeto antigo seguem idênticos
    omitted_at_default: ClassVar[dict[str, Any]] = {}

    @model_validator(mode="after")
    def _effects_fit_here(self) -> EffectsOwner:
        if self.effects_may_grow:
            return self
        for name in self.effect_fields:
            for effect in getattr(self, name):
                if effect.alters_duration():
                    raise ValueError(
                        f"{self.effects_place}: o efeito {effect.label} muda a duração do item e não vale "
                        f"aqui. Ele vale em {GROWABLE_AUDIO}."
                    )
        return self

    @model_serializer(mode="wrap")
    def _omit_empty_effects(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        for name in self.effect_fields:
            if name in data and not data[name]:
                del data[name]
        for name, default in self.omitted_at_default.items():
            if name in data and data[name] == default:
                del data[name]
        return data


# Quanto o som de um clipe, de um PiP ou de uma faixa externa pode andar em relação à imagem (segundos): o
# bastante para corrigir uma câmera dessincronizada, sem deixar uma troca de arquivo passar por deslocamento
MAX_AUDIO_OFFSET = 60.0


# Camada de uma sobreposição na pilha de profundidade: "front" fica na frente de tudo; "behind-person" fica entre o
# fundo e a pessoa recortada (título que parece estar no cenário). É um Literal, e não um booleano, porque outras
# sobreposições (a composição em HTML) vão usar o mesmo campo e podem ganhar camadas novas.
OverlayLayer = Literal["front", "behind-person"]


# ---------- efeitos sonoros ----------

# Teto do `volume` de um efeito (1 = o nível padrão, 6 dB abaixo da voz): num só lugar para a spec e o modelo
# "explicativo" (`sons` de cada assunto) recusarem o mesmo valor.
SFX_VOLUME_MAX = 1.5


class SfxCue(Strict):
    """Efeito sonoro solto num instante da linha do tempo (item de `audio.sfx`).

    `sound` é um nome da biblioteca (whoosh, whip, pop, click, riser, impact, ding) ou o caminho de um
    arquivo de áudio. `volume` 1 é o nível padrão: o pico do efeito fica 6 dB abaixo do pico da voz (ver
    `filtergraph/sfx.py`); até 1,5 ele sobe, ainda sem passar da voz."""

    sound: str = Field(min_length=1)
    at: float = Field(ge=0)  # instante do vídeo final, em segundos
    volume: float = Field(1.0, ge=0, le=SFX_VOLUME_MAX)


class EntrySound(Strict):
    """Som que toca na entrada de uma sobreposição (texto, imagem, vídeo) ou no começo de uma transição.

    Sem `sound`, vale o som padrão do tipo (ver `domain/sfx.py`). `offset` desloca o instante em relação à
    entrada: negativo antecipa o som, como num whoosh que chega um instante antes do elemento."""

    sound: str | None = Field(None, min_length=1)
    volume: float = Field(1.0, ge=0, le=SFX_VOLUME_MAX)
    offset: float = Field(0.0, ge=-2, le=2)


# `true` liga o som padrão do tipo, uma string escolhe o som, um objeto ajusta volume e deslocamento;
# ausente ou `false` não toca nada (o som automático é opt-in)
SoundSpec = bool | str | EntrySound


# ---------- trechos da linha do tempo ----------


class Reframe(Strict):
    """Como encaixar a fonte no formato de saída."""

    mode: Literal["auto", "crop", "pad", "blur", "brand", "stretch"] = "auto"
    focus: tuple[float, float] = (0.5, 0.5)  # ponto de interesse para o corte (0..1)
    zoom: float = Field(1.0, ge=1.0, le=3.0)
    pad_color: str = "#000000"
    blur: float = Field(28.0, ge=1, le=100)
    # modo brand: fonte inteira sobre fundo gerado com o visual do tema, com sombra (e cantos redondos em imagens)
    margin: float = Field(0.05, ge=0, le=0.3)  # fração da largura livre em cada lado
    radius: float = Field(0.018, ge=0, le=0.2)  # cantos redondos, fração do lado menor (só imagens)
    variant: Literal["light", "dark"] | None = None  # fundo claro/escuro; None = padrão do tema


class Matte(Strict):
    """Troca o fundo atrás da pessoa por uma cor lisa (matting de vídeo por rede neural, sem chroma key).
    Serve para quem gravou em casa e quer o fundo branco ou na cor da marca."""

    background: str = "#FFFFFF"  # hex ou chave do tema (primary, accent, mint, white)
    # resnet50 separa melhor o que encosta na pessoa (cadeira, encosto); mobilenetv3 é 2,5x mais rápido
    model: Literal["resnet50", "mobilenetv3"] = "resnet50"
    downsample: float | None = Field(None, gt=0, le=1)  # None = escolhido pela resolução


class ColorAdjust(Strict):
    """Cor e acabamento de um trecho (ou de um look). Os quatro últimos campos são efeitos de acabamento de
    câmera e filme: 0 desliga e 1 é o máximo (ver `filtergraph/finish.py`, que justifica cada um)."""

    brightness: float = Field(0.0, ge=-1, le=1)
    contrast: float = Field(1.0, ge=0, le=3)
    saturation: float = Field(1.0, ge=0, le=3)
    gamma: float = Field(1.0, ge=0.1, le=10)
    sharpen: float = Field(0.0, ge=0, le=2)
    denoise: bool = False
    # true é a vinheta de sempre; um número de 0 a 1 ajusta a intensidade (0.4 equivale a true)
    vignette: bool | float = False
    lut: str | None = None  # arquivo .cube
    extra: str | None = None  # cadeia de filtros ffmpeg de vídeo, para casos especiais
    glow: float = Field(0.0, ge=0, le=1)  # brilho suave nas altas luzes
    aberration: float = Field(0.0, ge=0, le=1)  # aberração cromática (separação de vermelho e azul)
    light_leak: float = Field(0.0, ge=0, le=1)  # vazamento de luz quente que cruza o quadro
    grain: float = Field(0.0, ge=0, le=1)  # granulação de filme (animada, sempre igual a cada render)

    @field_validator("vignette")
    @classmethod
    def _vignette_range(cls, v: bool | float) -> bool | float:
        if not isinstance(v, bool) and not 0 <= v <= 1:
            raise ValueError("vignette: use true/false ou uma intensidade de 0 a 1")
        return v

    def is_identity(self) -> bool:
        return (
            self.brightness == 0
            and self.contrast == 1
            and self.saturation == 1
            and self.gamma == 1
            and self.sharpen == 0
            and not self.denoise
            and not self.vignette
            and not self.lut
            and not self.extra
            and not (self.glow or self.aberration or self.light_leak or self.grain)
        )


class Transition(Strict):
    """Como um trecho entra a partir do anterior: o tipo (xfade ou de movimento) e o ritmo (`curve`)."""

    type: str = "fade"
    duration: float = Field(0.5, gt=0, le=5)
    curve: Curve = "linear"
    sound: SoundSpec | None = None  # som no começo da transição (ver `EntrySound`)

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.lower()
        if v == "cut":
            return v
        if v not in all_transition_names():
            raise ValueError(
                f"Transição desconhecida: {v!r}. Use cut, um tipo xfade (fade, wipeleft, slideup...) "
                "ou uma de movimento (crosszoom, whippan, blurslide, filmburn, lightleak)"
            )
        return v


class AudioCrossfade(Strict):
    """Crossfade do SOM no corte entre este clipe e o anterior, independente da imagem (que continua trocando no
    quadro exato): o som de cada lado vem da sobra da fonte além do ponto de entrada e do de saída, e os dois se cruzam
    por `duration` segundos, metade antes do corte e metade depois (o J-cut e o L-cut do vídeo). `curve` é o tipo do
    crossfade: `constant_gain` soma as amplitudes (sons iguais e em fase), `constant_power_1` e `constant_power_2` somam as
    potências (sons diferentes, a escolha de quase todo corte entre falas)."""

    duration: float = Field(0.5, gt=0, le=5)
    curve: Literal["constant_gain", "constant_power_1", "constant_power_2"] = "constant_power_1"


class SegmentBase(Strict):
    label: str | None = None
    transition: Transition | None = None  # entrada deste trecho, a partir do anterior
    fade_in: float = Field(0.0, ge=0)
    fade_out: float = Field(0.0, ge=0)
    reframe: Reframe = Reframe()
    color: ColorAdjust = ColorAdjust()
    # nome de um look (ver `domain/looks.py`) só deste trecho; "nenhum" desliga o do projeto. Sem ele, vale o
    # `look` do projeto, a não ser que o trecho traga ajuste de cor próprio em `color`
    look: str | None = None


class ClipSegment(SegmentBase, EffectsOwner):
    """Trecho de vídeo. Com `src`, start/end são tempos no arquivo. Com `source` (nome em
    `project.sources`), start/end são tempos no relógio da sessão (o da fonte principal): é assim
    que se corta entre câmeras sincronizadas sem calcular pontos de entrada na mão.

    `audio_mode` escolhe qual parte do áudio da própria câmera entra no trecho, por isolamento vocal
    (Demucs, lento na CPU e guardado em cache): `original` é o áudio como gravado; `voice` é só a voz,
    limpa de música e ruído; `background` é só o fundo (música e ambiente), útil para dublar ou trocar a
    fala. Não mexe nas faixas externas (`audio.tracks`)."""

    type: Literal["clip"] = "clip"
    src: str | None = None
    source: str | None = None
    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)
    speed: float = Field(1.0, gt=0, le=8)
    volume: float = Field(1.0, ge=0, le=4)  # áudio da própria câmera
    mute: bool = False
    matte: Matte | None = None  # fundo substituído por cor lisa (pessoa recortada)
    audio_mode: Literal["original", "voice", "background"] = "original"
    # fade de áudio curto nas duas pontas do clipe, sem escurecer a imagem (ao contrário de fade_in/fade_out):
    # tira o estalo de um corte seco no meio da fala, como os de `autocut`. 0 = sem fade
    audio_fade: float = Field(0.0, ge=0, le=0.5)
    # desloca o som em relação à imagem, em segundos da linha do tempo: positivo atrasa o som (a fala chega depois
    # do lábio), negativo adianta. O som pode vir de fora de `start`/`end` na fonte; onde a fonte não tem som, sai silêncio
    audio_offset: float = Field(0.0, ge=-MAX_AUDIO_OFFSET, le=MAX_AUDIO_OFFSET)
    # equilíbrio esquerda/direita do som do trecho, de -1 (tudo à esquerda) a 1 (tudo à direita)
    pan: float = Field(0.0, ge=-1, le=1)
    # cadeia de efeitos no som da própria câmera do trecho (ver `domain/audio_effects`), em ordem
    effects: list[AudioEffect] = []
    # crossfade do som no corte com o clipe anterior (ver `AudioCrossfade`); vazio, fora do dump e do hash
    audio_crossfade: AudioCrossfade | None = None

    effects_place: ClassVar[str] = "clipe"
    omitted_at_default: ClassVar[dict[str, Any]] = {"audio_offset": 0.0, "pan": 0.0, "audio_crossfade": None}

    @model_validator(mode="after")
    def _range(self) -> ClipSegment:
        if bool(self.src) == bool(self.source):
            raise ValueError("clipe precisa de `src` (arquivo) ou `source` (fonte sincronizada), um dos dois")
        if self.end is not None and self.end <= self.start:
            raise ValueError(
                f"end ({self.end}) precisa ser maior que start ({self.start}) em {self.src or self.source}"
            )
        return self

    @property
    def origin(self) -> str:
        return self.src or self.source or ""


class ImageSegment(SegmentBase):
    type: Literal["image"] = "image"
    src: str
    duration: float = Field(3.0, gt=0)
    motion: Literal["none", "zoom-in", "zoom-out", "pan-left", "pan-right"] = "zoom-in"
    motion_amount: float = Field(0.12, ge=0, le=0.6)


class CardSegment(SegmentBase):
    """Cartão gerado (abertura, CTA, encerramento) com o visual do tema, ou por um layout da marca
    (`layout` + `fields`; ver seção "card_layouts" do brand.json)."""

    type: Literal["card"] = "card"
    duration: float = Field(3.0, gt=0)
    title: str = ""
    subtitle: str | None = None
    variant: Literal["light", "dark"] | None = None  # None = padrão do tema
    logo: bool = True
    background: str | None = None
    motion: Literal["none", "zoom-in"] = "zoom-in"
    motion_amount: float = Field(0.04, ge=0, le=0.3)
    layout: str | None = None  # nome de um layout em `card_layouts` do brand.json da marca
    fields: dict[str, str | list[str]] = {}  # campos que preenchem o layout ({{campo}} e listas)
    # cor lisa: sem as curvas e os brilhos do tema, e sem exigir título. É o fundo de apoio atrás de um
    # quadro de vídeo ou de uma imagem (modelo "explicativo"), onde a decoração só atrapalharia
    flat: bool = False

    @model_validator(mode="after")
    def _title_or_layout(self) -> CardSegment:
        if not self.layout and not self.title.strip() and not self.flat:
            raise ValueError(
                "cartão precisa de `title` (ou `layout` com `fields`, cartão por layout da marca, "
                "ou `flat: true` para um fundo de cor lisa)"
            )
        return self


Segment = Annotated[ClipSegment | ImageSegment | CardSegment, Field(discriminator="type")]


# ---------- regiões nomeadas ----------

_EDGE_TOLERANCE = 1e-6  # folga das contas de ponto flutuante ao conferir se a região cabe no quadro


class Region(Strict):
    """Retângulo nomeado do quadro, em fração (0..1) da largura e da altura. `x`/`y` são o CENTRO, a mesma
    convenção de `x`/`y` nas sobreposições. Quem monta um layout (o modelo "explicativo") declara as
    regiões uma vez e as sobreposições se encaixam nelas por nome (`region`), sem conta de pixel."""

    x: float = Field(gt=0, lt=1)
    y: float = Field(gt=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _inside_frame(self) -> Region:
        for axis, center, size in (("horizontal", self.x, self.width), ("vertical", self.y, self.height)):
            if center - size / 2 < -_EDGE_TOLERANCE or center + size / 2 > 1 + _EDGE_TOLERANCE:
                raise ValueError(
                    f"região fora do quadro no eixo {axis}: centro {center:g} e tamanho {size:g} "
                    "passam da borda (x/y são o centro, em fração)"
                )
        return self


# ---------- sobreposições ----------


class TextStyle(Strict):
    font: str | None = None
    weight: Literal["light", "regular", "medium", "semibold", "bold", "extrabold"] | None = None
    size: float | None = Field(None, gt=0)
    color: str | None = None
    outline_color: str | None = None
    outline: float | None = Field(None, ge=0)
    shadow: float | None = Field(None, ge=0)
    box: bool | None = None
    box_color: str | None = None
    box_alpha: float | None = Field(None, ge=0, le=1)
    box_radius: float | None = Field(None, ge=0)
    box_padding: float | None = Field(None, ge=0)
    # "block": um retângulo em volta do texto todo (padrão); "rounded": uma caixa por linha, emendadas
    # com curvas (estilo TikTok), com raio e margem da marca; pedi-la já liga a `box`
    box_shape: Literal["block", "rounded"] | None = None
    uppercase: bool | None = None
    align: Literal["left", "center", "right"] | None = None
    max_width: float | None = Field(None, gt=0, le=1)  # fração da largura
    spacing: float | None = None


class TextOverlay(Strict):
    type: Literal["text"] = "text"
    text: str
    secondary: str | None = None  # segunda linha (ex.: cargo no lower-third)
    role: Literal["hook", "title", "subtitle", "cta", "lower-third", "custom"] = "title"
    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)
    position: Literal["top", "center", "bottom"] | None = None
    x: float | None = Field(None, ge=0, le=1)
    y: float | None = Field(None, ge=0, le=1)
    region: str | None = None  # nome em `regions`: o texto se centra na região (no lugar de position/x/y)
    animation: Literal["none", "fade", "pop", "slide-up", "typewriter"] | None = None
    style: TextStyle = TextStyle()
    sound: SoundSpec | None = None  # som na entrada do texto (em `start`)
    # "behind-person": o texto vai entre o fundo e a pessoa, que o recorte (RVM) põe por cima só no intervalo dele
    layer: OverlayLayer = "front"

    @model_validator(mode="after")
    def _region_or_position(self) -> TextOverlay:
        if self.region and (self.x is not None or self.y is not None or self.position is not None):
            raise ValueError(
                "texto com `region` não leva `position`, `x` nem `y`: a região já define o lugar"
            )
        return self


class ImageOverlay(Strict):
    type: Literal["image"] = "image"
    src: str = "logo"  # "logo" | "logo:horizontal_dark" | "logo:symbol" | caminho de imagem
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "top", "bottom", "center"] = (
        "top-right"
    )
    x: float | None = Field(None, ge=0, le=1)  # centro, fração do quadro (x e y juntos; sobrescreve position)
    y: float | None = Field(None, ge=0, le=1)
    # nome em `regions`: a imagem inteira cabe na região, centrada e sem distorcer (no lugar de
    # position/x/y; a largura vem da região)
    region: str | None = None
    width: float = Field(0.22, gt=0, le=1)  # fração da largura do vídeo
    margin: float = Field(40, ge=0)  # px na base 1080
    safe_zone: bool = True  # False cola no canto do quadro, só com a margem (ignora a interface do app)
    opacity: float = Field(1.0, ge=0, le=1)
    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)
    fade: float = Field(0.3, ge=0)
    sound: SoundSpec | None = None  # som na entrada da imagem (em `start`)
    # "circle" recorta a imagem num círculo (o maior quadrado central dela), como a foto no meio do audiograma
    shape: Literal["rect", "circle"] = "rect"

    @model_validator(mode="after")
    def _place(self) -> ImageOverlay:
        if (self.x is None) != (self.y is None):
            raise ValueError("imagem: informe `x` e `y` juntos (o centro da imagem)")
        if self.region and self.x is not None:
            raise ValueError("imagem com `region` não leva `x` nem `y`: a região já define o lugar")
        return self


class ProgressBar(Strict):
    type: Literal["progress-bar"] = "progress-bar"
    color: str | None = None  # None = accent do tema
    height: float = Field(10, gt=0)
    position: Literal["top", "bottom"] = "bottom"
    track_alpha: float = Field(0.25, ge=0, le=1)


class VideoOverlay(EffectsOwner):
    """Picture-in-picture: um segundo vídeo (webcam, câmera 2) sobre a linha do tempo, como no
    Shotcut (Size & Position + Crop Circle/Mask): retângulo, formato, borda, sombra e o áudio misturado."""

    type: Literal["video"] = "video"
    src: str | None = None
    source: str | None = None  # fonte sincronizada; `offset` vira o tempo da sessão mostrado em `start`
    start: float = Field(0.0, ge=0)  # na linha do tempo
    end: float | None = Field(None, ge=0)
    offset: float = Field(0.0, ge=0)  # ponto de entrada no arquivo (src) ou tempo da sessão (source)
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "top", "bottom", "center"] = (
        "bottom-right"
    )
    x: float | None = Field(None, ge=0, le=1)  # centro, fração do quadro (sobrescreve position)
    y: float | None = Field(None, ge=0, le=1)
    # nome em `regions`: o quadro ocupa a região (no lugar de position/x/y/width). Sem `aspect`, o vídeo
    # preenche a região inteira cortando o excesso; com `aspect`, o quadro dessa proporção cabe nela
    region: str | None = None
    width: float = Field(0.28, gt=0, le=1)  # fração da largura do vídeo
    aspect: str | None = None  # "16:9", "1:1"...; None = proporção da fonte (círculo força 1:1)
    # onde cortar quando a proporção do quadro difere da fonte, como em `reframe.focus`: (0.5, 0.5) mantém
    # o centro; (0.5, 0.3) sobe a janela para um rosto de vídeo vertical, que fica no terço de cima
    focus: tuple[float, float] = (0.5, 0.5)
    shape: Literal["rect", "rounded", "circle"] = "rounded"
    radius: float = Field(0.08, ge=0, le=0.5)  # cantos redondos, fração da largura do PiP
    softness: float = Field(0.0, ge=0)  # suavidade da borda da máscara, px na base 1080
    border: float = Field(6, ge=0)  # px na base 1080
    border_color: str = "white"
    shadow: bool = True
    opacity: float = Field(1.0, ge=0, le=1)
    margin: float = Field(40, ge=0)
    volume: float = Field(1.0, ge=0, le=4)  # áudio do PiP misturado (0 = mudo)
    # desloca o som do PiP em relação à imagem dele (positivo atrasa o som), como em `ClipSegment.audio_offset`
    audio_offset: float = Field(0.0, ge=-MAX_AUDIO_OFFSET, le=MAX_AUDIO_OFFSET)
    effects: list[AudioEffect] = []  # cadeia de efeitos no áudio do PiP, em ordem
    animation: Literal["none", "fade", "slide"] = "fade"
    fade: float = Field(0.3, ge=0)
    sound: SoundSpec | None = None  # som na entrada do quadro (em `start`)

    effects_place: ClassVar[str] = "sobreposição de vídeo (PiP)"
    omitted_at_default: ClassVar[dict[str, Any]] = {"audio_offset": 0.0}

    @model_validator(mode="after")
    def _origin(self) -> VideoOverlay:
        if bool(self.src) == bool(self.source):
            raise ValueError("sobreposição de vídeo precisa de `src` ou `source`, um dos dois")
        if self.end is not None and self.end <= self.start:
            raise ValueError("end precisa ser maior que start na sobreposição de vídeo")
        if self.aspect is not None:
            parse_aspect(self.aspect)
        if self.region and (self.x is not None or self.y is not None):
            raise ValueError("vídeo com `region` não leva `x` nem `y`: a região já define o lugar")
        if not all(0 <= v <= 1 for v in self.focus):
            raise ValueError("focus do vídeo precisa ter os dois valores entre 0 e 1")
        return self


def parse_aspect(value: str) -> float:
    """ "16:9" -> 1.777..."""
    try:
        w, h = value.replace("/", ":").split(":")
        ratio = float(w) / float(h)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"proporção inválida: {value!r} (use algo como 16:9)") from exc
    if ratio <= 0:
        raise ValueError(f"proporção inválida: {value!r}")
    return ratio


class AudiogramOverlay(Strict):
    """Audiograma: a forma de onda ou as barras de frequência do áudio, animadas no ritmo dele. Serve para
    divulgar um trecho de podcast, entrevista ou áudio de WhatsApp, quando não há vídeo.

    `style`: `wave` (linha de onda), `bars` (barras simétricas, as graves no meio) ou `circle` (barras em
    volta de um círculo; `inner_radius` é onde elas começam, e é ali que cabe a foto). `follow` escolhe o
    áudio que a animação acompanha: `voice` (clipes, narração e `audio.voiceover`, sem a música), `mix` (o
    áudio final) ou `auto` (a voz, quando o projeto tem alguma; senão a mistura, como num visualizador de
    música). Seguir a voz mantém a onda parada nas pausas da fala mesmo com trilha de fundo.

    `color` é uma chave do tema ou um hex (sem ele, a cor de destaque da marca). O lugar vem de `region`,
    de `x`/`y` (o centro, em fração do quadro) ou de `position`; `width` e `height` são frações do quadro
    (sem `height`, a proporção própria do estilo). No círculo, o desenho cabe no menor lado da caixa."""

    type: Literal["audiogram"] = "audiogram"
    style: Literal["wave", "bars", "circle"] = "bars"
    follow: Literal["auto", "voice", "mix"] = "auto"
    color: str | None = None
    position: (
        Literal["top-left", "top-right", "bottom-left", "bottom-right", "top", "bottom", "center"] | None
    ) = None
    x: float | None = Field(None, ge=0, le=1)
    y: float | None = Field(None, ge=0, le=1)
    region: str | None = (
        None  # nome em `regions`: o desenho ocupa a região (no lugar de position/x/y/width/height)
    )
    width: float = Field(0.8, gt=0, le=1)  # fração da largura do quadro
    height: float | None = Field(None, gt=0, le=1)  # fração da altura do quadro; None = proporção do estilo
    inner_radius: float = Field(
        0.6, ge=0.1, le=0.95
    )  # só no círculo: fração do raio externo onde as barras começam
    margin: float = Field(40, ge=0)  # px na base 1080, a partir de `position`
    safe_zone: bool = True  # False ignora a área coberta pela interface do app
    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _place(self) -> AudiogramOverlay:
        if (self.x is None) != (self.y is None):
            raise ValueError("audiograma: informe `x` e `y` juntos (o centro do desenho)")
        if self.region and (self.x is not None or self.position is not None):
            raise ValueError(
                "audiograma com `region` não leva `position`, `x` nem `y`: a região já define o lugar"
            )
        if self.end is not None and self.end <= self.start:
            raise ValueError("end precisa ser maior que start no audiograma")
        return self


class MotionBlur(Strict):
    """Borrão de movimento da composição em HTML: o DMaker captura `subframes` instantes dentro do tempo em que o
    "obturador" fica aberto e tira a média, como a câmera faz. `shutter` é a fração do intervalo entre dois
    quadros em que ele fica aberto (0,5 é o obturador de 180 graus do cinema; 1 borra de um quadro ao seguinte).
    O custo do render cresce na proporção de `subframes`."""

    subframes: int = Field(5, ge=2, le=16)
    shutter: float = Field(0.5, gt=0, le=1)


PageSize = Annotated[int, Field(ge=16, le=8192)]


class CaptionAnchor(Strict):
    """Prende a composição a uma palavra da legenda: ela aparece quando a palavra é dita e ocupa o lugar dela na
    tela (um círculo em volta, um sublinhado). `occurrence` escolhe qual vez que a palavra aparece, `hold`
    diz até quando fica (`line`: enquanto a linha da legenda está na tela; `word`: só enquanto a palavra é dita)
    e `margin` é a folga em volta da palavra, em px na base 1080, para o traço caber."""

    word: str = Field(min_length=1)
    occurrence: int = Field(1, ge=1, le=50)
    hold: Literal["word", "line"] = "line"
    margin: float = Field(24.0, ge=0, le=400)

    @field_validator("hold", mode="before")
    @classmethod
    def _hold_in_portuguese(cls, value: object) -> object:
        """`palavra` e `linha` (como o formulário do infográfico os mostra) valem como `word` e `line`."""
        return {"palavra": "word", "linha": "line"}.get(value, value) if isinstance(value, str) else value


class HtmlOverlay(Strict):
    """Composição animada escrita em HTML, CSS e JavaScript (inclusive three.js e Lottie), renderizada quadro a
    quadro com fundo transparente por cima do vídeo: títulos animados, gráficos, mapas, objetos em 3D.

    `src` é um arquivo `.html` (a página inteira nele) ou uma pasta com `index.html` e os arquivos que a página usa;
    no lugar dele, `infographic` usa um modelo pronto pelo nome (`contador`, `barra`...) e `data` leva os seus
    parâmetros. O lugar vem de `region` (uma região nomeada) ou do centro `x`/`y` com `width`/`height` (frações do
    quadro; sem nada, o quadro todo). A página é desenhada com o tamanho da área em px na base 1080 (`size` muda
    isso: o resultado é então ajustado à área). `data` é entregue à página como `dmaker.data`. A página não
    acessa a internet: só os arquivos locais dela e os de `files`. `layer: "behind-person"` põe a composição
    atrás da pessoa. `anchor` prende a composição a uma palavra da legenda."""

    type: Literal["html"] = "html"
    src: str | None = Field(None, min_length=1)
    # nome de um modelo pronto de `templates/html/` (ver `domain/infographics.py`); exatamente um entre src e infographic
    infographic: str | None = Field(None, min_length=1)
    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)
    region: str | None = None  # nome em `regions`: a composição ocupa a região (no lugar de x/y/width/height)
    x: float | None = Field(None, ge=0, le=1)  # centro da área, fração do quadro (x e y juntos)
    y: float | None = Field(None, ge=0, le=1)
    width: float = Field(1.0, gt=0, le=1)  # fração da largura do quadro
    height: float = Field(1.0, gt=0, le=1)  # fração da altura do quadro
    size: tuple[PageSize, PageSize] | None = None  # largura e altura da página, em px na base 1080
    data: dict[str, Any] = {}  # entregue à página como `dmaker.data` (entra na chave do cache)
    # arquivos de fora da pasta da composição que a página pode ler, por nome: `{"foto": "C:/fotos/a.png"}` fica
    # em `/_dmaker/files/foto.png`. Entram na chave do cache pelo conteúdo.
    files: dict[str, str] = {}
    anchor: CaptionAnchor | None = None
    motion_blur: MotionBlur | None = None
    layer: OverlayLayer = "front"
    sound: SoundSpec | None = None  # som na entrada da composição (em `start`)

    @field_validator("motion_blur", mode="before")
    @classmethod
    def _blur_shorthand(cls, value: object) -> object:
        """`true` liga o borrão com os valores padrão e `false` o desliga, para o pedido em uma palavra."""
        if value is True:
            return {}
        if value is False:
            return None
        return value

    @model_validator(mode="after")
    def _place(self) -> HtmlOverlay:
        if (self.src is None) == (self.infographic is None):
            raise ValueError(
                "composição html: informe `src` (a pasta ou o arquivo da composição) ou `infographic` "
                "(o nome de um modelo pronto), um dos dois e não os dois"
            )
        if (self.x is None) != (self.y is None):
            raise ValueError("composição html: informe `x` e `y` juntos (o centro da área)")
        if self.region and self.x is not None:
            raise ValueError("composição html com `region` não leva `x` nem `y`: a região já define o lugar")
        if self.anchor and (self.region or self.x is not None):
            raise ValueError(
                "composição html presa a uma palavra da legenda (`anchor`) não leva `region` nem `x`/`y`: "
                "o lugar vem da palavra"
            )
        if self.end is not None and self.end <= self.start:
            raise ValueError("end precisa ser maior que start na composição html")
        return self


Overlay = Annotated[
    TextOverlay | ImageOverlay | ProgressBar | VideoOverlay | AudiogramOverlay | HtmlOverlay,
    Field(discriminator="type"),
]


# ---------- legendas ----------


class CaptionStyle(Strict):
    # "rounded": caixa arredondada por linha (estilo TikTok) com o destaque da palavra ativa por cima
    mode: Literal["karaoke", "classic", "boxed", "rounded"] = "karaoke"
    font: str | None = None
    weight: Literal["light", "regular", "medium", "semibold", "bold", "extrabold"] = "bold"
    size: float = Field(72, gt=0)
    color: str = "white"
    highlight_color: str | None = None  # None = tema (caption_highlight)
    outline_color: str | None = None  # None = tema (caption_outline)
    outline: float = Field(5, ge=0)
    shadow: float = Field(2, ge=0)
    uppercase: bool = True
    max_words: int = Field(4, ge=1, le=12)
    max_chars: int = Field(22, ge=4, le=80)
    y: float | None = Field(None, ge=0, le=1)  # fração da altura (âncora no centro); None = automático
    pop: bool = False  # aumentar a palavra ativa desloca a linha; fica desligado por padrão
    box_color: str = "#000000"  # hex ou chave do tema (primary, accent...)
    box_alpha: float = Field(0.6, ge=0, le=1)
    # acompanha o tom (claro/escuro) do cartão ou fundo gerado que passa por baixo. False: a legenda mantém
    # sempre o estilo de quem está sobre vídeo, como quando fica sobre o quadro do rosto e o fundo do tema
    # só aparece ao redor dele
    follow_background: bool = True


class Captions(Strict):
    # "auto" (transcrição), "narration" (o texto das narrações de `audio.narration`, sem Whisper)
    # ou caminho .srt/.vtt/.json
    source: str = "auto"
    language: str = "pt"
    model: str = "small"  # tiny | base | small | medium | large-v3
    device: Literal["cpu", "cuda"] = "cpu"
    vocabulary: list[str] = []  # nomes próprios e termos para orientar a transcrição (soma com os do tema)
    replacements: dict[str, str] = {}  # correções de palavras ouvidas errado (soma com as do tema)
    offset: float = 0.0
    enabled: bool = True
    style: CaptionStyle = CaptionStyle()


# ---------- áudio ----------


class MusicSpan(Strict):
    """Janela da linha do tempo em que a música toca (trilha só na abertura e no encerramento, por
    exemplo). `start`/`end` são instantes do vídeo final; `start_at` é de onde começar na música.

    `from_end` conta `start`/`end` a partir do fim do vídeo (útil quando a duração final só se sabe
    depois de planejada, como num casamento com corte automático): `start: 33.5, from_end: true` começa
    33.5 s antes do fim; `end` continua None = até o fim do vídeo, ou, informado, também contado do fim
    (por isso `end` menor que `start` é o normal nesse modo, não um erro). `tail` toca o FINAL da
    música, terminando junto com a janela: `start_at` deixa de ser o ponto de entrada e vira uma folga
    a partir do fim da faixa (padrão 0)."""

    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)  # None = até o fim do vídeo (ou, com from_end, o próprio fim)
    start_at: float = Field(0.0, ge=0)  # com tail=true, vira a folga antes do fim da música
    fade_in: float = Field(1.0, ge=0)
    fade_out: float = Field(2.0, ge=0)
    from_end: bool = False  # start/end contados a partir do fim do vídeo, não do começo
    tail: bool = False  # ancora start_at no final da música (precisa da duração da música para resolver)

    @model_validator(mode="after")
    def _check_window(self):
        if self.end is None:
            return self
        if self.from_end:
            if self.end >= self.start:
                raise ValueError(
                    f"música: com from_end, end ({self.end}) precisa ser menor que start ({self.start}) "
                    "(contados a partir do fim do vídeo, quanto menor mais perto do fim)"
                )
        elif self.end <= self.start:
            raise ValueError(f"música: end ({self.end}) precisa ser maior que start ({self.start})")
        return self


class Music(EffectsOwner):
    src: str
    volume: float = Field(0.18, ge=0, le=2)
    fade_in: float = Field(1.0, ge=0)
    fade_out: float = Field(2.0, ge=0)
    start_at: float = Field(0.0, ge=0)  # de onde começar dentro da música
    spans: list[MusicSpan] = []  # vazio = a música cobre o vídeo inteiro
    loop: bool = True
    ducking: bool = True  # abaixa a música quando há voz
    duck_threshold: float = Field(0.02, gt=0, le=1)
    duck_ratio: float = Field(6, ge=1, le=20)
    duck_release: float = Field(350, ge=10, le=5000)
    pan: float = Field(0.0, ge=-1, le=1)  # equilíbrio esquerda/direita, de -1 a 1
    effects: list[AudioEffect] = []  # cadeia de efeitos na música inteira (antes das janelas e do loop)

    effects_place: ClassVar[str] = "música"
    effects_may_grow: ClassVar[bool] = True
    omitted_at_default: ClassVar[dict[str, Any]] = {"pan": 0.0}


class AudioTrack(EffectsOwner):
    """Faixa externa sincronizada (gravador no altar, mesa do DJ) que segue os cortes dos clipes
    com `source`. É misturada ao áudio das câmeras em cada trecho."""

    source: str
    volume: float = Field(1.0, ge=0, le=4)
    # desloca a faixa em relação à sessão, em segundos: positivo atrasa o som da faixa (corrige um gravador que
    # começou adiantado em relação às câmeras), negativo adianta
    audio_offset: float = Field(0.0, ge=-MAX_AUDIO_OFFSET, le=MAX_AUDIO_OFFSET)
    pan: float = Field(0.0, ge=-1, le=1)  # equilíbrio esquerda/direita, de -1 a 1
    effects: list[
        AudioEffect
    ] = []  # cadeia de efeitos no arquivo inteiro da faixa, antes de fatiar por trecho

    effects_place: ClassVar[str] = "faixa externa (audio.tracks)"
    omitted_at_default: ClassVar[dict[str, Any]] = {"audio_offset": 0.0, "pan": 0.0}


class Narration(EffectsOwner):
    """Fala sintetizada por texto, misturada como voz do vídeo (a música abaixa sob ela). O texto vem de
    `text` ou de `script` (arquivo .txt relativo ao projeto, como os outros caminhos), nunca dos dois.
    `voice` é o id de uma voz de `assets/voices`; sem ela, a voz automática do motor."""

    text: str | None = None
    script: str | None = None
    voice: str | None = None
    instruct: str | None = None  # descrição do jeito de falar (ver o guia, "Voz e narração")
    start: float = Field(0.0, ge=0)  # instante do vídeo final em que a fala começa
    volume: float = Field(1.0, ge=0, le=4)
    speed: float = Field(1.0, ge=0.5, le=2)
    language: str = "pt"
    seed: int | None = None  # fixa a síntese: o mesmo texto soa igual a cada render
    pan: float = Field(0.0, ge=-1, le=1)  # equilíbrio esquerda/direita, de -1 a 1
    effects: list[AudioEffect] = []  # cadeia de efeitos na fala já sintetizada

    effects_place: ClassVar[str] = "narração (audio.narration)"
    omitted_at_default: ClassVar[dict[str, Any]] = {"pan": 0.0}

    @model_validator(mode="after")
    def _one_source(self) -> Narration:
        if bool(self.text and self.text.strip()) == bool(self.script):
            raise ValueError(
                "narração precisa de `text` (o texto) ou `script` (um arquivo .txt), um dos dois"
            )
        return self


class VoiceoverClip(EffectsOwner):
    """Arquivo de áudio gravado (corte de podcast, entrevista, áudio de WhatsApp) posto na linha do tempo como
    voz do vídeo, sem precisar de um trecho de vídeo nem de uma fonte sincronizada. Entra no mesmo barramento
    de voz da narração: a música abaixa sob ele, os efeitos sonoros se nivelam por ele e a legenda `auto` o
    transcreve. `src` é relativo à spec; `start` é o instante do vídeo final em que o áudio começa;
    `offset` e `end` aparam o arquivo (ponto de entrada e de saída, em segundos do próprio arquivo, `end`
    None = até o fim dele)."""

    src: str = Field(min_length=1)
    start: float = Field(0.0, ge=0)
    offset: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)
    volume: float = Field(1.0, ge=0, le=4)
    pan: float = Field(0.0, ge=-1, le=1)  # equilíbrio esquerda/direita, de -1 a 1
    effects: list[AudioEffect] = []  # cadeia de efeitos no trecho do arquivo (de `offset` a `end`), em ordem

    effects_place: ClassVar[str] = "voz gravada (audio.voiceover)"
    effects_may_grow: ClassVar[bool] = True
    omitted_at_default: ClassVar[dict[str, Any]] = {"pan": 0.0}

    @model_validator(mode="after")
    def _range(self) -> VoiceoverClip:
        if self.end is not None and self.end <= self.offset:
            raise ValueError(f"end ({self.end}) precisa ser maior que offset ({self.offset}) em {self.src}")
        return self


# Teto da duração de um som gerado: dez minutos. O som nasce inteiro em memória (float, estéreo, 48 kHz: uns 23 MB por
# minuto) antes de ir para o cache, e um gerador de teste ou de efeito não pede mais que isso.
GENERATED_MAX_SECONDS = 600.0


class GeneratedSound(EffectsOwner):
    """Som sintetizado posto na linha do tempo (item de `audio.generated`): um tom, um ruído, um bipe, um metrônomo.

    `generator` é o tipo registrado (`domain/generators`) e `params` os parâmetros dele, completados com os padrões na hora
    de carregar (dois pedidos iguais dão a mesma spec). `start` e `duration` são do vídeo final. Entra no barramento dos
    efeitos sonoros (`SFX`): soma depois do ducking e antes do loudnorm, sem abaixar a música. O nível é o do gerador
    (`amplitude_db`) vezes o `volume`, sem nivelar contra a voz como os sons da biblioteca; a cadeia de efeitos vale nele."""

    generator: str = Field(min_length=1)
    params: dict[str, Any] = {}
    start: float = Field(0.0, ge=0)
    duration: float = Field(gt=0, le=GENERATED_MAX_SECONDS)
    volume: float = Field(1.0, ge=0, le=4)
    pan: float = Field(0.0, ge=-1, le=1)  # equilíbrio esquerda/direita, de -1 a 1
    effects: list[AudioEffect] = []  # cadeia de efeitos no som já gerado

    effects_place: ClassVar[str] = "som gerado (audio.generated)"
    omitted_at_default: ClassVar[dict[str, Any]] = {"pan": 0.0}

    @model_validator(mode="after")
    def _params_fit_generator(self) -> GeneratedSound:
        try:
            self.params = normalized_params(self.generator, self.params)
        except ValueError as exc:
            raise ValueError(f"audio.generated: {exc}") from exc
        return self


class NoiseProfile(Strict):
    """Um trecho que só tem o chiado de fundo, guardado com um nome para a Redução de ruído (`noise_reduction`) usar.
    `target` é o item de onde o trecho vem (`audio.voiceover.0`, `timeline.2`...), como em `edit_project`; `start` e
    `end` são segundos do item, e não da linha do tempo, para o perfil seguir o item quando ele muda de lugar. O
    espectro do trecho é medido na hora de processar e nunca fica na spec."""

    target: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> NoiseProfile:
        if self.end <= self.start:
            raise ValueError(
                f"perfil de ruído: end ({self.end:g}) precisa ser maior que start ({self.start:g})"
            )
        return self


class AudioSettings(EffectsOwner):
    music: Music | None = None
    tracks: list[AudioTrack] = []
    narration: list[Narration] = []  # falas sintetizadas por texto, somadas à voz antes da música
    # arquivos de áudio gravados (podcast, WhatsApp) como voz do vídeo, no mesmo barramento da narração
    voiceover: list[VoiceoverClip] = []
    # efeitos sonoros soltos (whoosh, pop...): entram na mixagem antes da normalização, sem abaixar a música
    # e abaixo da voz; os sons de entrada das sobreposições (`sound`) se juntam a estes
    sfx: list[SfxCue] = []
    voice_gain: float = Field(1.0, ge=0, le=4)
    normalize: Literal["two-pass", "fast", "off"] = "two-pass"
    target_lufs: float = Field(-14, ge=-30, le=-5)
    mute_clips: bool = False
    # cadeia de efeitos na mistura inteira: depois da música, da voz e dos efeitos sonoros e antes da
    # normalização final, que continua valendo por cima
    master_effects: list[AudioEffect] = []
    # ganho (dB) e equilíbrio (-1 a 1) do barramento dos efeitos sonoros: o que o estado da trilha SFX
    # (`Project.tracks`) vira na hora de renderizar, junto com o mudo (-120 dB). Ficam fora do dump no padrão
    sfx_gain_db: float = Field(0.0, ge=-120, le=24)
    sfx_pan: float = Field(0.0, ge=-1, le=1)
    # perfis de ruído com nome (ver `NoiseProfile`): a Redução de ruído aponta um deles por `profile`. Vazio fica fora do
    # dump, então um projeto sem perfil gera os mesmos bytes e o mesmo hash de antes de o campo existir
    noise_profiles: dict[str, NoiseProfile] = {}
    # regras do Auto Duck (ver `AutoDuck`): uma trilha abaixa enquanto OUTRA soa. A regra da música (`background: "MUS"`)
    # substitui o `music.ducking` antigo. Vazio fica fora do dump, pelo mesmo motivo dos perfis de ruído
    ducks: list[AutoDuck] = []
    # sons sintetizados (tom, ruído, bipe, metrônomo...), no barramento dos efeitos sonoros (SFX). Vazio fica fora do
    # dump, então um projeto sem som gerado mantém os mesmos bytes e o mesmo hash
    generated: list[GeneratedSound] = []

    effect_fields: ClassVar[tuple[str, ...]] = ("master_effects",)
    effects_place: ClassVar[str] = "áudio mestre (audio.master_effects)"
    omitted_at_default: ClassVar[dict[str, Any]] = {
        "sfx_gain_db": 0.0,
        "sfx_pan": 0.0,
        "noise_profiles": {},
        "ducks": [],
        "generated": [],
    }

    @model_validator(mode="after")
    def _master_runs_live(self) -> AudioSettings:
        """O áudio mestre roda dentro do grafo ao vivo da mistura; um efeito de amostras (Redução de ruído, Reparar)
        precisa do sinal na memória e vale nos itens."""
        for effect in self.master_effects:
            if effect.sample_stage:
                raise ValueError(
                    f"{self.effects_place}: o efeito {effect.label} trabalha sobre as amostras do item e não vale "
                    "na mistura inteira. Ponha-o no clipe, na voz gravada ou na faixa que tem o ruído"
                )
        return self


# ---------- saída e projeto ----------


class AudioFormat(Strict):
    """Escolhas do arquivo de áudio por cima do padrão do preset (`audio/mp3`, `audio/wav`...): o que não vem aqui
    fica como o preset define (`domain/audio_presets.py`). `bit_depth` vale nos formatos sem perda (32 é ponto
    flutuante); `bitrate_mode`, `bitrate_k` e `quality` valem nos com perda (VBR usa a qualidade, CBR e ABR a
    taxa de bits)."""

    sample_rate: int | None = Field(None, ge=8000, le=192000)
    channels: Literal[1, 2] | None = None
    bit_depth: Literal[16, 24, 32] | None = None
    bitrate_mode: Literal["cbr", "vbr", "abr"] | None = None
    bitrate_k: int | None = Field(None, ge=8, le=512)  # kbps
    quality: float | None = Field(None, ge=-1, le=10)

    def choices(self) -> EncodingChoices:
        return EncodingChoices(
            self.sample_rate, self.channels, self.bit_depth, self.bitrate_mode, self.bitrate_k, self.quality
        )


class AudioMetadata(Strict):
    """Etiquetas do arquivo de áudio, as da janela "Edit Metadata Tags" do Audacity. Cada formato as grava do seu
    jeito (ID3v2.3 no MP3, comentários Vorbis no FLAC, OGG e Opus, atoms no M4A, INFO no WAV). O que a marca
    define em `brand.json` (`metadata`) é o ponto de partida, e o que vem aqui vale por cima."""

    artist: str | None = None
    title: str | None = None
    album: str | None = None
    track: str | None = None  # "3" ou "3/12"
    year: str | None = None
    genre: str | None = None
    comment: str | None = None

    @field_validator("track", "year", mode="before")
    @classmethod
    def _number_as_text(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int) and not isinstance(v, bool) else v


class Output(Strict):
    # um preset de vídeo (`instagram/reels`) ou de áudio (`audio/mp3`): o de áudio tira a imagem do render
    preset: str = "instagram/reels"
    path: str | None = None
    fps: float | None = Field(None, gt=0, le=120)
    encoder: Literal["x264", "auto", "nvenc", "amf", "qsv"] = "x264"  # auto = hardware se houver
    quality: Literal["max", "high", "medium", "draft"] = "high"  # max = x264 slow (mais lento, arquivo menor)
    thumbnail_at: float | None = Field(None, ge=0)
    guides: bool = False  # desenha as zonas seguras (para conferência)
    audio_format: AudioFormat | None = (
        None  # só com preset de áudio: taxa, canais, profundidade, taxa de bits
    )
    metadata: AudioMetadata | None = None  # etiquetas do arquivo de áudio (artista, título, álbum...)

    @model_validator(mode="after")
    def _audio_format_fits_preset(self) -> Output:
        if self.audio_format is not None and is_audio_preset(self.preset):
            try:
                resolve_encoding(get_audio_preset(self.preset), self.audio_format.choices())
            except AudioFormatError as exc:
                raise ValueError(f"output.audio_format: {exc}") from exc
        return self


class SourceRef(Strict):
    """Câmera ou gravador que captou o mesmo evento. `sync` é o instante, no relógio da fonte
    principal, em que esta fonte (ou, com `parts`, a primeira parte dela) começa; "auto" descobre
    pelo áudio (correlação). Uma câmera que grava em vários arquivos em sequência (a Canon parte a
    cada 30 min, o celular para e volta) usa `parts` em vez de `src`: o pipeline liga as partes em
    cadeia pelo áudio sozinho, sem precisar declarar uma fonte por arquivo."""

    src: str | None = None
    parts: list[str] = []  # arquivos da mesma câmera, em sequência (alternativa a `src`)
    sync: Literal["auto"] | float = 0.0
    audio_stream: int = Field(0, ge=0)
    label: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> SourceRef:
        if bool(self.src) == bool(self.parts):
            raise ValueError(
                "fonte precisa de `src` (um arquivo) ou `parts` (arquivos em sequência), um dos dois"
            )
        return self

    @property
    def files(self) -> list[str]:
        """Arquivos da fonte, em ordem (uma lista de um elemento só quando é `src`)."""
        return list(self.parts) if self.parts else [self.src]  # type: ignore[list-item]


class PhaseRuleSpec(Strict):
    """Regra de reconhecimento de uma fase da cerimônia pelos termos ditos na fala (ver `PhaseRule`
    em `domain/multicam.py`, que esta classe espelha na spec)."""

    name: str
    match: list[str] = Field(min_length=1)
    main: str | None = None  # None = câmera principal do bloco
    cadence: tuple[float, float] = (40.0, 30.0)
    max_duration: float | None = Field(None, gt=0)


class MulticamBlock(Strict):
    """Trecho da linha do tempo ainda por planejar: `plan_multicam` transcreve a câmera de áudio,
    reconhece as fases pela fala e substitui o bloco por clipes alternando as câmeras."""

    at: int = Field(ge=0)  # índice da timeline onde os clipes planejados entram (o resto desloca)
    cameras: list[str] = Field(min_length=1)  # nomes em `sources`
    main: str  # câmera principal (mais tempo em tela)
    audio: str  # fonte cujo áudio é a referência (fala transcrita); clipes ficam mute onde ela cobre
    cadence: tuple[float, float] = (40.0, 30.0)
    phases: Literal["casamento"] | list[PhaseRuleSpec] = "casamento"
    min_clip: float = Field(4.0, gt=0)
    snap_window: float = Field(5.0, ge=0)
    pause: float = Field(0.6, ge=0)
    start: float | None = None  # relógio da sessão; None = início da cobertura mais cedo das câmeras
    end: float | None = None  # None = fim da cobertura mais tarde
    transition_in: Transition | None = None  # transição do primeiro clipe planejado
    label: str | None = None  # rótulo dos clipes (padrão: nome da fase)


class TrackState(Strict):
    """Mudo/oculto/bloqueio de uma trilha da vista multitrilha (interface), estilo Shotcut. `muted`
    e `hidden` valem para a prévia E para o render (`domain.tracks.apply_track_state`); `locked` só
    trava a edição na interface, o render ignora."""

    muted: bool = False
    hidden: bool = False
    locked: bool = False
    # controles de mixagem das trilhas de áudio (A1, A2..., MUS, NAR, VO, SFX), como no cabeçalho de trilha do
    # Audacity: ganho em dB, equilíbrio de -1 (esquerda) a 1 (direita) e solo (com alguma trilha em solo, as outras
    # trilhas de áudio ficam mudas). Valem para a prévia E para o render e ficam fora do dump no padrão
    gain_db: float = Field(0.0, ge=-60, le=24)
    pan: float = Field(0.0, ge=-1, le=1)
    solo: bool = False

    @model_serializer(mode="wrap")
    def _omit_mix_defaults(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        for name, default in (("gain_db", 0.0), ("pan", 0.0), ("solo", False)):
            if name in data and data[name] == default:
                del data[name]
        return data


MARKER_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class Marker(Strict):
    """Marcador da trilha MK: um instante (`at`) ou uma região (`start` e `end`) da linha do tempo FINAL, com texto,
    cor e grupo. Cada grupo é uma trilha de marcadores (a "label track" do Audacity); o grupo vazio é a trilha padrão.
    `low_hz` e `high_hz` guardam a faixa de frequência de um marcador espectral do Audacity, para a ida e volta do
    arquivo dele não perder nada. Os marcadores seguem as edições que mexem no tempo (cortes, aparas)."""

    at: float | None = Field(None, ge=0)
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, ge=0)
    text: str = ""
    color: str | None = None  # #RRGGBB; sem cor, a interface usa a do tema
    group: str = ""
    low_hz: float | None = Field(None, ge=0)
    high_hz: float | None = Field(None, ge=0)

    @field_validator("color")
    @classmethod
    def _hex_color(cls, v: str | None) -> str | None:
        if v is not None and not MARKER_COLOR.match(v):
            raise ValueError("color do marcador precisa ser #RRGGBB (ex.: #e0a020)")
        return v

    @field_validator("group")
    @classmethod
    def _group_name(cls, v: str) -> str:
        v = v.strip()
        if "/" in v:
            raise ValueError(
                "o nome do grupo não pode ter `/` (a barra separa grupo e texto em marker:grupo/texto)"
            )
        return v

    @model_validator(mode="after")
    def _instant_or_region(self) -> Marker:
        if self.at is not None:
            if self.start is not None or self.end is not None:
                raise ValueError("marcador com `at` (instante) não tem `start` nem `end` (região)")
            return self
        if self.start is None or self.end is None:
            raise ValueError("marcador precisa de `at` (instante) ou de `start` e `end` (região)")
        if self.end <= self.start:
            raise ValueError("`end` do marcador precisa ser maior que `start` (para um instante, use `at`)")
        return self

    @property
    def is_region(self) -> bool:
        return self.at is None

    @property
    def begin(self) -> float:
        """Onde o marcador começa: o instante, ou o início da região."""
        return self.at if self.at is not None else self.start  # type: ignore[return-value]

    @property
    def finish(self) -> float:
        """Onde o marcador termina: o próprio instante, ou o fim da região."""
        return self.at if self.at is not None else self.end  # type: ignore[return-value]


class Project(Strict):
    name: str
    version: int = 1
    output: Output = Output()
    brand: str | None = None
    theme: dict | None = None  # sobrescreve cores/fontes do tema
    sources: dict[str, SourceRef] = {}  # fontes sincronizadas (multicâmera, gravadores)
    master: str | None = None  # fonte principal = relógio da sessão; padrão: a primeira de `sources`
    # os trechos de vídeo; só um projeto com saída de áudio (`audio/mp3`...) pode ficar sem nenhum, e então o som dos
    # itens de `audio` (narração, voz gravada, música) é o que dá a duração
    timeline: list[Segment] = []
    look: str | None = None  # acabamento visual de todos os trechos, por nome (ver `domain/looks.py`)
    overlays: list[Overlay] = []
    captions: Captions | None = None
    audio: AudioSettings = AudioSettings()
    multicam: MulticamBlock | None = None  # trecho ainda por planejar; `plan_multicam` o substitui
    tracks: dict[str, TrackState] = {}  # mudo/oculto/bloqueio por trilha (ids da vista: V1, A1, A2...,
    # MUS, CC, TX, GR, V2, V3...); ver `domain.tracks.apply_track_state`
    # retângulos nomeados do quadro (ex.: "topo", "rosto" no modelo "explicativo"); as sobreposições se
    # encaixam neles por `region`, e infográficos e composições usam o mesmo nome (ver `domain.regions`)
    regions: dict[str, Region] = {}
    # trilha de marcadores no tempo FINAL: não entra em hash de mezanino nem na receita da prévia (não muda a imagem
    # nem o som), e `to_bytes` a omite quando vazia para o `spec.json` de um projeto antigo seguir idêntico
    markers: list[Marker] = []
    base_dir: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _timeline_needed(self) -> Project:
        if not self.timeline and not is_audio_preset(self.output.preset):
            raise ValueError(
                "timeline precisa de pelo menos um trecho; só um projeto com saída de áudio "
                "(output.preset: audio/mp3, audio/wav...) pode ficar sem trechos de vídeo"
            )
        return self

    @model_validator(mode="after")
    def _region_refs(self) -> Project:
        used = {ov.region for ov in self.overlays if getattr(ov, "region", None)}
        unknown = sorted(used - set(self.regions))
        if unknown:
            known = ", ".join(sorted(self.regions)) or "nenhuma declarada"
            raise ValueError(
                f"região desconhecida: {', '.join(unknown)} (declare em `regions`; regiões do projeto: {known})"
            )
        return self

    @model_validator(mode="after")
    def _session_refs(self) -> Project:
        names = set(self.sources)
        if self.master and self.master not in names:
            raise ValueError(f"master {self.master!r} não está em sources")
        missing = [
            seg.source
            for seg in self.timeline
            if isinstance(seg, ClipSegment) and seg.source and seg.source not in names
        ]
        missing += [t.source for t in self.audio.tracks if t.source not in names]
        missing += [
            ov.source
            for ov in self.overlays
            if isinstance(ov, VideoOverlay) and ov.source and ov.source not in names
        ]
        if self.multicam:
            missing += [c for c in self.multicam.cameras if c not in names]
            missing += [s for s in (self.multicam.main, self.multicam.audio) if s not in names]
        if missing:
            raise ValueError(
                f"fonte(s) desconhecida(s): {', '.join(sorted(set(missing)))} (declare em sources)"
            )
        if self.multicam:
            if self.multicam.main not in self.multicam.cameras:
                raise ValueError(f"multicam.main {self.multicam.main!r} precisa estar em multicam.cameras")
            if self.multicam.at > len(self.timeline):
                raise ValueError(
                    f"multicam.at ({self.multicam.at}) além do fim da timeline ({len(self.timeline)})"
                )
        return self

    @property
    def master_source(self) -> str | None:
        if not self.sources:
            return None
        return self.master or next(iter(self.sources))

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip()
        if not v or any(ch in v for ch in '\\/:*?"<>|'):
            raise ValueError('name precisa ser um nome de arquivo válido (sem / \\ : * ? " < > |)')
        return v

    # -- caminhos --
    def resolve(self, p: str | Path) -> Path:
        path = Path(p).expanduser()
        if path.is_absolute():
            return path
        for base in (self.base_dir, config.PROJECTS_DIR / self.name, Path.cwd()):
            if base and (base / path).exists():
                return (base / path).resolve()
        return ((self.base_dir or Path.cwd()) / path).resolve()

    @classmethod
    def load(cls, path: Path | str) -> Project:
        path = Path(path)
        return cls.from_bytes(read_bytes_retrying(path), path.parent.resolve())

    @classmethod
    def from_bytes(cls, data: bytes, base_dir: Path) -> Project:
        """O projeto de um `spec.json` já lido: quem também precisa da revisão dos bytes lê uma vez só."""
        project = cls.model_validate(json.loads(data.decode("utf-8")))
        project.base_dir = base_dir
        return project

    def to_bytes(self) -> bytes:
        """Os bytes que `save` grava; a revisão do arquivo depois de salvo é a deste conteúdo."""
        # sem marcador o campo não vai para o arquivo: o `spec.json` de um projeto antigo não muda ao ser salvo de novo
        exclude = None if self.markers else {"markers"}
        return self.model_dump_json(indent=2, exclude_none=True, exclude=exclude).encode("utf-8")

    def save(self, path: Path | str) -> Path:
        """Grava por troca atômica: a interface, o MCP e a CLI escrevem a mesma spec e nenhum lê metade dela."""
        path = Path(path)
        write_bytes_atomic(path, self.to_bytes())
        return path

    # -- utilidades --
    def texts(self) -> list[tuple[str, str]]:
        """Todos os textos visíveis, com origem, para verificações de estilo."""
        out: list[tuple[str, str]] = []
        for i, seg in enumerate(self.timeline):
            if isinstance(seg, CardSegment):
                if seg.title:
                    out.append((f"timeline[{i}].title", seg.title))
                if seg.subtitle:
                    out.append((f"timeline[{i}].subtitle", seg.subtitle))
                for field_name, value in seg.fields.items():
                    if isinstance(value, str):
                        out.append((f"timeline[{i}].fields.{field_name}", value))
        if self.captions and self.captions.source == "narration":  # o texto falado aparece como legenda
            out += [
                (f"audio.narration[{i}].text", n.text) for i, n in enumerate(self.audio.narration) if n.text
            ]
        for i, ov in enumerate(self.overlays):
            if isinstance(ov, TextOverlay):
                out.append((f"overlays[{i}].text", ov.text))
                if ov.secondary:
                    out.append((f"overlays[{i}].secondary", ov.secondary))
        return out
