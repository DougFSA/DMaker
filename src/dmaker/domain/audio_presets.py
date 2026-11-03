"""Presets de saída só de áudio: um por formato de arquivo (WAV, MP3, FLAC, OGG, Opus, M4A, AIFF).

O preset de vídeo (`domain/presets.py`) descreve um quadro; o de áudio descreve como o som é gravado no arquivo:
taxa de amostragem, canais, profundidade de bits (formatos sem perda) e taxa de bits ou qualidade (formatos com
perda), com os mesmos padrões e opções da janela de exportação do Audacity. É dado puro: quem monta os argumentos
do ffmpeg é `filtergraph/audio_output.py`, e quem renderiza é `pipeline/audio_render.py`.

Formato novo entra por registro (`register_audio_preset`), sem tocar nos outros: um preset novo diz qual codec,
quais profundidades, quais modos de taxa de bits e que estilo de etiqueta (`metadata_style`) o contêiner usa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AUDIO_PRESET_PREFIX = "audio/"

BitrateMode = Literal["cbr", "vbr", "abr"]

# o mesmo padrão do resto da mixagem (`filtergraph/common.py`): não há motivo para reamostrar na saída
DEFAULT_SAMPLE_RATE = 48000
CHANNEL_NAMES = {1: "mono", 2: "estéreo"}


class AudioFormatError(ValueError):
    """Opção de formato que o preset não aceita (profundidade num MP3, taxa de 44,1 kHz num Opus...)."""


@dataclass(frozen=True)
class AudioPreset:
    """Um formato de arquivo de áudio e o que ele aceita de opções.

    `bit_depths` não vazio = formato sem perda com profundidade escolhível; `bitrate_modes` não vazio = formato
    com perda com taxa de bits ou qualidade. `sample_rates` vazio = qualquer taxa. `quality_range` é a faixa
    da qualidade do modo VBR (`-q:a`) do codec, de (melhor, pior) como o ffmpeg a escreve."""

    id: str
    name: str
    format: str  # sufixo do id: "mp3"
    extension: str  # ".mp3"
    muxer: str  # valor de `-f`
    metadata_style: Literal["id3v23", "vorbis", "mp4", "riff", "aiff"]
    lossless: bool = False
    bit_depths: tuple[int, ...] = ()
    bit_depth: int | None = None  # padrão quando o formato tem profundidade
    bitrate_modes: tuple[BitrateMode, ...] = ()
    bitrate_mode: BitrateMode | None = None
    bitrate_k: int | None = None  # padrão do CBR e do ABR
    quality: float | None = None  # padrão do VBR
    quality_range: tuple[float, float] = (0, 9)
    sample_rate: int = DEFAULT_SAMPLE_RATE
    sample_rates: tuple[int, ...] = ()
    channels: int = 2
    max_channels: int = 2
    notes: str = ""

    @property
    def resolution(self) -> str:
        """Como o formato aparece onde o vídeo mostra `1080x1920`: taxa e canais."""
        return f"{self.sample_rate / 1000:g} kHz {CHANNEL_NAMES[self.channels]}"

    @property
    def platform(self) -> str:
        return "Áudio"

    @property
    def default_label(self) -> str:
        """O padrão do formato em uma frase curta: `16 bits`, `CBR 192 kbps` ou `VBR, qualidade 5`."""
        if self.bit_depths:
            return "32 bits (ponto flutuante)" if self.bit_depth == 32 else f"{self.bit_depth} bits"
        if self.bitrate_mode == "vbr" and self.quality is not None:
            return f"VBR, qualidade {self.quality:g}"
        return f"{(self.bitrate_mode or '').upper()} {self.bitrate_k} kbps".strip()


@dataclass(frozen=True)
class AudioEncoding:
    """O que a codificação usa de fato: o padrão do preset com as escolhas do projeto por cima."""

    preset: AudioPreset
    sample_rate: int
    channels: int
    bit_depth: int | None
    bitrate_mode: BitrateMode | None
    bitrate_k: int | None
    quality: float | None


AUDIO_PRESETS: dict[str, AudioPreset] = {}

AUDIO_ALIASES: dict[str, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mp3",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "vorbis": "audio/ogg",
    "opus": "audio/opus",
    "m4a": "audio/m4a",
    "aac": "audio/m4a",
    "aiff": "audio/aiff",
    "aif": "audio/aiff",
}


def register_audio_preset(preset: AudioPreset, aliases: tuple[str, ...] = ()) -> AudioPreset:
    """Põe um formato no catálogo. O id precisa começar por `audio/`, que é o que separa o preset de áudio do de
    vídeo (`is_audio_preset`)."""
    if not preset.id.startswith(AUDIO_PRESET_PREFIX):
        raise ValueError(f"o id de um preset de áudio começa por {AUDIO_PRESET_PREFIX!r}: {preset.id!r}")
    AUDIO_PRESETS[preset.id] = preset
    for alias in aliases:
        AUDIO_ALIASES[alias] = preset.id
    return preset


def is_audio_preset(name: str | None) -> bool:
    """Se o nome (id ou apelido) é de um preset de áudio, sem levantar erro para um nome qualquer."""
    if not name:
        return False
    key = name.strip().lower()
    return AUDIO_ALIASES.get(key, key) in AUDIO_PRESETS


def get_audio_preset(name: str) -> AudioPreset:
    key = name.strip().lower()
    key = AUDIO_ALIASES.get(key, key)
    if key not in AUDIO_PRESETS:
        options = ", ".join(sorted(AUDIO_PRESETS))
        raise KeyError(f"Preset de áudio desconhecido: {name!r}. Opções: {options}")
    return AUDIO_PRESETS[key]


def list_audio_presets() -> list[AudioPreset]:
    return list(AUDIO_PRESETS.values())


# ---------- os formatos ----------

register_audio_preset(
    AudioPreset(
        "audio/wav",
        "WAV",
        "wav",
        ".wav",
        "wav",
        "riff",
        lossless=True,
        bit_depths=(16, 24, 32),
        bit_depth=16,
        notes="Sem perda. 16 e 24 bits inteiros; 32 é ponto flutuante.",
    )
)
register_audio_preset(
    AudioPreset(
        "audio/mp3",
        "MP3",
        "mp3",
        ".mp3",
        "mp3",
        "id3v23",
        bitrate_modes=("cbr", "vbr", "abr"),
        bitrate_mode="cbr",
        bitrate_k=192,
        quality=2,
        quality_range=(0, 9),
        notes="Com perda. CBR, VBR (qualidade 0 a 9, 0 é a melhor) ou ABR. Etiquetas ID3v2.3.",
    )
)
register_audio_preset(
    AudioPreset(
        "audio/flac",
        "FLAC",
        "flac",
        ".flac",
        "flac",
        "vorbis",
        lossless=True,
        bit_depths=(16, 24),
        bit_depth=16,
        notes="Sem perda e comprimido. 16 ou 24 bits. Etiquetas Vorbis.",
    )
)
register_audio_preset(
    AudioPreset(
        "audio/ogg",
        "OGG Vorbis",
        "ogg",
        ".ogg",
        "ogg",
        "vorbis",
        bitrate_modes=("vbr", "abr", "cbr"),
        bitrate_mode="vbr",
        bitrate_k=160,
        quality=5,
        quality_range=(-1, 10),
        notes="Com perda. Qualidade 0 a 10 (padrão 5, como o Audacity), ABR ou CBR. Etiquetas Vorbis.",
    )
)
register_audio_preset(
    AudioPreset(
        "audio/opus",
        "Opus",
        "opus",
        ".opus",
        "opus",
        "vorbis",
        bitrate_modes=("vbr", "cbr", "abr"),
        bitrate_mode="vbr",
        bitrate_k=128,
        sample_rates=(8000, 12000, 16000, 24000, 48000),
        notes="Com perda, o melhor para voz em pouca taxa de bits. Só aceita 8, 12, 16, 24 e 48 kHz.",
    )
)
register_audio_preset(
    AudioPreset(
        "audio/m4a",
        "M4A (AAC)",
        "m4a",
        ".m4a",
        "ipod",
        "mp4",
        bitrate_modes=("cbr",),
        bitrate_mode="cbr",
        bitrate_k=192,
        notes="Com perda, AAC no contêiner MP4. Taxa de bits constante.",
    )
)
register_audio_preset(
    AudioPreset(
        "audio/aiff",
        "AIFF",
        "aiff",
        ".aiff",
        "aiff",
        "aiff",
        lossless=True,
        bit_depths=(16, 24, 32),
        bit_depth=16,
        notes="Sem perda, o formato de áudio do Mac. 16 e 24 bits inteiros; 32 é ponto flutuante.",
    )
)


# ---------- as escolhas do projeto sobre o padrão ----------


@dataclass(frozen=True)
class EncodingChoices:
    """As escolhas que o projeto (`Output.audio_format`) faz por cima do padrão do preset; `None` = o padrão."""

    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    bitrate_mode: BitrateMode | None = None
    bitrate_k: int | None = None
    quality: float | None = None

    @property
    def empty(self) -> bool:
        return all(value is None for value in self.__dict__.values())


def resolve_encoding(preset: AudioPreset, choices: EncodingChoices | None = None) -> AudioEncoding:
    """A codificação do preset com as escolhas por cima, ou um `AudioFormatError` em português dizendo o que o
    formato não aceita. Uma opção que não faz sentido no formato (profundidade num MP3) é recusada em vez de
    ignorada: a pessoa pediu 24 bits e ia receber um arquivo que não os tem."""
    choices = choices or EncodingChoices()
    name = preset.name
    sample_rate = choices.sample_rate or preset.sample_rate
    if preset.sample_rates and sample_rate not in preset.sample_rates:
        allowed = ", ".join(f"{rate / 1000:g}" for rate in preset.sample_rates)
        raise AudioFormatError(f"{name} só aceita estas taxas de amostragem (kHz): {allowed}")
    channels = choices.channels or preset.channels
    if channels > preset.max_channels:
        raise AudioFormatError(f"{name} aceita no máximo {preset.max_channels} canais")

    bit_depth = choices.bit_depth if choices.bit_depth is not None else preset.bit_depth
    if choices.bit_depth is not None and choices.bit_depth not in preset.bit_depths:
        if not preset.bit_depths:
            raise AudioFormatError(f"{name} é um formato com perda e não tem profundidade de bits")
        allowed = ", ".join(str(depth) for depth in preset.bit_depths)
        raise AudioFormatError(f"{name} aceita estas profundidades de bits: {allowed}")

    lossy_choices = (choices.bitrate_mode, choices.bitrate_k, choices.quality)
    if not preset.bitrate_modes:
        if any(value is not None for value in lossy_choices):
            raise AudioFormatError(f"{name} é um formato sem perda e não tem taxa de bits nem qualidade")
        return AudioEncoding(preset, sample_rate, channels, bit_depth, None, None, None)

    mode = choices.bitrate_mode or preset.bitrate_mode
    if mode not in preset.bitrate_modes:
        allowed = ", ".join(preset.bitrate_modes)
        raise AudioFormatError(f"{name} aceita estes modos de taxa de bits: {allowed}")
    low, high = sorted(preset.quality_range)
    if choices.quality is not None and not low <= choices.quality <= high:
        raise AudioFormatError(
            f"a qualidade do {name} vai de {preset.quality_range[0]:g} a {preset.quality_range[1]:g}"
        )
    return AudioEncoding(
        preset,
        sample_rate,
        channels,
        None,
        mode,
        choices.bitrate_k or preset.bitrate_k,
        choices.quality if choices.quality is not None else preset.quality,
    )
