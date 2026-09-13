"""Modelo do projeto de edição (spec JSON). É o contrato entre quem pede a edição e o renderizador.

Convenções:
- tempos em segundos; cores em #RRGGBB ou chave do tema (primary, accent, text...);
- tamanhos de texto em px na base 1080 (lado menor do vídeo): escalam com a resolução;
- posições x/y em fração (0..1) do quadro.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config import PROJECTS_DIR


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class ColorAdjust(Strict):
    brightness: float = Field(0.0, ge=-1, le=1)
    contrast: float = Field(1.0, ge=0, le=3)
    saturation: float = Field(1.0, ge=0, le=3)
    gamma: float = Field(1.0, ge=0.1, le=10)
    sharpen: float = Field(0.0, ge=0, le=2)
    denoise: bool = False
    vignette: bool = False
    lut: str | None = None  # arquivo .cube
    extra: str | None = None  # cadeia de filtros ffmpeg de vídeo, para casos especiais

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
        )


XFADE_TYPES = {
    "fade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "smoothleft",
    "smoothright",
    "smoothup",
    "smoothdown",
    "circleopen",
    "circleclose",
    "circlecrop",
    "rectcrop",
    "radial",
    "pixelize",
    "distance",
    "zoomin",
    "fadegrays",
    "squeezev",
    "squeezeh",
    "hlslice",
    "hrslice",
    "vuslice",
    "vdslice",
    "diagtl",
    "diagtr",
    "diagbl",
    "diagbr",
    "hblur",
    "wipetl",
    "wipetr",
    "wipebl",
    "wipebr",
    "coverleft",
    "coverright",
    "coverup",
    "coverdown",
    "revealleft",
    "revealright",
    "revealup",
    "revealdown",
}


class Transition(Strict):
    type: str = "fade"
    duration: float = Field(0.5, gt=0, le=5)

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.lower()
        if v == "cut":
            return v
        if v not in XFADE_TYPES:
            raise ValueError(
                f"Transição desconhecida: {v!r}. Use cut ou um tipo xfade (fade, wipeleft, slideup...)"
            )
        return v


class SegmentBase(Strict):
    label: str | None = None
    transition: Transition | None = None  # entrada deste trecho, a partir do anterior
    fade_in: float = Field(0.0, ge=0)
    fade_out: float = Field(0.0, ge=0)
    reframe: Reframe = Reframe()
    color: ColorAdjust = ColorAdjust()


class ClipSegment(SegmentBase):
    """Trecho de vídeo. Com `src`, start/end são tempos no arquivo. Com `source` (nome em
    `project.sources`), start/end são tempos no relógio da sessão (o da fonte principal): é assim
    que se corta entre câmeras sincronizadas sem calcular pontos de entrada na mão."""

    type: Literal["clip"] = "clip"
    src: str | None = None
    source: str | None = None
    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)
    speed: float = Field(1.0, gt=0, le=8)
    volume: float = Field(1.0, ge=0, le=4)  # áudio da própria câmera
    mute: bool = False

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
    """Cartão gerado (abertura, CTA, encerramento) com o visual do tema."""

    type: Literal["card"] = "card"
    duration: float = Field(3.0, gt=0)
    title: str
    subtitle: str | None = None
    variant: Literal["light", "dark"] | None = None  # None = padrão do tema
    logo: bool = True
    background: str | None = None
    motion: Literal["none", "zoom-in"] = "zoom-in"
    motion_amount: float = Field(0.04, ge=0, le=0.3)


Segment = Annotated[ClipSegment | ImageSegment | CardSegment, Field(discriminator="type")]


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
    animation: Literal["none", "fade", "pop", "slide-up", "typewriter"] | None = None
    style: TextStyle = TextStyle()


class ImageOverlay(Strict):
    type: Literal["image"] = "image"
    src: str = "logo"  # "logo" | "logo:horizontal_dark" | "logo:symbol" | caminho de imagem
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "top", "bottom", "center"] = (
        "top-right"
    )
    width: float = Field(0.22, gt=0, le=1)  # fração da largura do vídeo
    margin: float = Field(40, ge=0)  # px na base 1080
    opacity: float = Field(1.0, ge=0, le=1)
    start: float = Field(0.0, ge=0)
    end: float | None = Field(None, ge=0)
    fade: float = Field(0.3, ge=0)


class ProgressBar(Strict):
    type: Literal["progress-bar"] = "progress-bar"
    color: str | None = None  # None = accent do tema
    height: float = Field(10, gt=0)
    position: Literal["top", "bottom"] = "bottom"
    track_alpha: float = Field(0.25, ge=0, le=1)


class VideoOverlay(Strict):
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
    width: float = Field(0.28, gt=0, le=1)  # fração da largura do vídeo
    aspect: str | None = None  # "16:9", "1:1"...; None = proporção da fonte (círculo força 1:1)
    shape: Literal["rect", "rounded", "circle"] = "rounded"
    radius: float = Field(0.08, ge=0, le=0.5)  # cantos redondos, fração da largura do PiP
    softness: float = Field(0.0, ge=0)  # suavidade da borda da máscara, px na base 1080
    border: float = Field(6, ge=0)  # px na base 1080
    border_color: str = "white"
    shadow: bool = True
    opacity: float = Field(1.0, ge=0, le=1)
    margin: float = Field(40, ge=0)
    volume: float = Field(1.0, ge=0, le=4)  # áudio do PiP misturado (0 = mudo)
    animation: Literal["none", "fade", "slide"] = "fade"
    fade: float = Field(0.3, ge=0)

    @model_validator(mode="after")
    def _origin(self) -> VideoOverlay:
        if bool(self.src) == bool(self.source):
            raise ValueError("sobreposição de vídeo precisa de `src` ou `source`, um dos dois")
        if self.end is not None and self.end <= self.start:
            raise ValueError("end precisa ser maior que start na sobreposição de vídeo")
        if self.aspect is not None:
            parse_aspect(self.aspect)
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


Overlay = Annotated[TextOverlay | ImageOverlay | ProgressBar | VideoOverlay, Field(discriminator="type")]


# ---------- legendas ----------


class CaptionStyle(Strict):
    mode: Literal["karaoke", "classic", "boxed"] = "karaoke"
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
    box_color: str = "#000000"
    box_alpha: float = Field(0.6, ge=0, le=1)


class Captions(Strict):
    source: str = "auto"  # "auto" (transcrição) ou caminho .srt/.vtt/.json
    language: str = "pt"
    model: str = "small"  # tiny | base | small | medium | large-v3
    device: Literal["cpu", "cuda"] = "cpu"
    vocabulary: list[str] = []  # nomes próprios e termos para orientar a transcrição (soma com os do tema)
    replacements: dict[str, str] = {}  # correções de palavras ouvidas errado (soma com as do tema)
    offset: float = 0.0
    enabled: bool = True
    style: CaptionStyle = CaptionStyle()


# ---------- áudio ----------


class Music(Strict):
    src: str
    volume: float = Field(0.18, ge=0, le=2)
    fade_in: float = Field(1.0, ge=0)
    fade_out: float = Field(2.0, ge=0)
    start_at: float = Field(0.0, ge=0)  # de onde começar dentro da música
    loop: bool = True
    ducking: bool = True  # abaixa a música quando há voz
    duck_threshold: float = Field(0.02, gt=0, le=1)
    duck_ratio: float = Field(6, ge=1, le=20)
    duck_release: float = Field(350, ge=10, le=5000)


class AudioTrack(Strict):
    """Faixa externa sincronizada (gravador no altar, mesa do DJ) que segue os cortes dos clipes
    com `source`. É misturada ao áudio das câmeras em cada trecho."""

    source: str
    volume: float = Field(1.0, ge=0, le=4)


class AudioSettings(Strict):
    music: Music | None = None
    tracks: list[AudioTrack] = []
    voice_gain: float = Field(1.0, ge=0, le=4)
    normalize: Literal["two-pass", "fast", "off"] = "two-pass"
    target_lufs: float = Field(-14, ge=-30, le=-5)
    mute_clips: bool = False


# ---------- saída e projeto ----------


class Output(Strict):
    preset: str = "instagram/reels"
    path: str | None = None
    fps: float | None = Field(None, gt=0, le=120)
    encoder: Literal["x264", "auto", "nvenc", "amf", "qsv"] = "x264"  # auto = hardware se houver
    quality: Literal["max", "high", "medium", "draft"] = "high"  # max = x264 slow (mais lento, arquivo menor)
    thumbnail_at: float | None = Field(None, ge=0)
    guides: bool = False  # desenha as zonas seguras (para conferência)


class SourceRef(Strict):
    """Câmera ou gravador que captou o mesmo evento. `sync` é o instante, no relógio da fonte
    principal, em que esta fonte começa; "auto" descobre pelo áudio (correlação)."""

    src: str
    sync: Literal["auto"] | float = 0.0
    audio_stream: int = Field(0, ge=0)
    label: str | None = None


class Project(Strict):
    name: str
    version: int = 1
    output: Output = Output()
    brand: str | None = None
    theme: dict | None = None  # sobrescreve cores/fontes do tema
    sources: dict[str, SourceRef] = {}  # fontes sincronizadas (multicâmera, gravadores)
    master: str | None = None  # fonte principal = relógio da sessão; padrão: a primeira de `sources`
    timeline: list[Segment] = Field(min_length=1)
    overlays: list[Overlay] = []
    captions: Captions | None = None
    audio: AudioSettings = AudioSettings()
    base_dir: Path | None = Field(default=None, exclude=True)

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
        if missing:
            raise ValueError(
                f"fonte(s) desconhecida(s): {', '.join(sorted(set(missing)))} (declare em sources)"
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
        for base in (self.base_dir, PROJECTS_DIR / self.name, Path.cwd()):
            if base and (base / path).exists():
                return (base / path).resolve()
        return ((self.base_dir or Path.cwd()) / path).resolve()

    @classmethod
    def load(cls, path: Path | str) -> Project:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        project = cls.model_validate(data)
        project.base_dir = path.parent.resolve()
        return project

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        return path

    # -- utilidades --
    def texts(self) -> list[tuple[str, str]]:
        """Todos os textos visíveis, com origem, para verificações de estilo."""
        out: list[tuple[str, str]] = []
        for i, seg in enumerate(self.timeline):
            if isinstance(seg, CardSegment):
                out.append((f"timeline[{i}].title", seg.title))
                if seg.subtitle:
                    out.append((f"timeline[{i}].subtitle", seg.subtitle))
        for i, ov in enumerate(self.overlays):
            if isinstance(ov, TextOverlay):
                out.append((f"overlays[{i}].text", ov.text))
                if ov.secondary:
                    out.append((f"overlays[{i}].secondary", ov.secondary))
        return out
