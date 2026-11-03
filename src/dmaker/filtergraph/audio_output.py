"""Argumentos do ffmpeg para gravar o áudio de um projeto num arquivo (WAV, MP3, FLAC, OGG, Opus, M4A, AIFF).

Funções puras: recebem a codificação já resolvida (`AudioEncoding`) e as etiquetas, e devolvem filtros e opções.
Nenhuma delas abre arquivo nem executa nada; quem executa é o `FFmpegRunner` do pipeline. A saída nunca leva
vídeo: todo comando de áudio traz `-vn`, para um arquivo de som não herdar imagem de nenhuma entrada.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..domain.audio_presets import AudioEncoding
from .common import LOUDNORM_TRUE_PEAK_DB

# a variação de volume (LRA) acima da qual o `loudnorm` desiste do ganho linear e trabalha de forma dinâmica
LOUDNORM_LINEAR_MAX_LRA = 11.0

# Samples inteiros de 16 bits perdem a parte baixa do float da mixagem; o dither triangular com realce de
# agudos troca a distorção dessa quantização por um chiado muito baixo e fora da faixa mais sensível do ouvido
# (é o que o Audacity faz por padrão ao exportar para 16 bits).
DITHER_16_BIT = "triangular_hp"

_PCM_CODECS = {
    "wav": {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"},
    "aiff": {16: "pcm_s16be", 24: "pcm_s24be", 32: "pcm_f32be"},
}

# o Opus chama o modo de taxa de bits de outro jeito: constante, variável ou variável limitada (a média do ABR)
_OPUS_VBR = {"cbr": "off", "vbr": "on", "abr": "constrained"}


def downmix_filter(channels: int) -> str | None:
    """Mono a partir do estéreo com pesos iguais: a soma das duas metades não passa de 1, então não clipa, e o
    centro da mixagem (a voz) fica no mesmo nível. Estéreo não precisa de filtro (a mixagem já é estéreo)."""
    return "pan=mono|c0=0.5*c0+0.5*c1" if channels == 1 else None


def format_filters(encoding: AudioEncoding) -> list[str]:
    """Filtros que levam a mixagem (48 kHz, estéreo, ponto flutuante) ao formato do arquivo: canais, taxa de
    amostragem e, nos formatos de 16 bits inteiros, o dither. Vazio quando a mixagem já está no formato."""
    filters: list[str] = []
    downmix = downmix_filter(encoding.channels)
    if downmix:
        filters.append(downmix)
    resample = []
    if encoding.sample_rate != 48000:
        resample.append(f"out_sample_rate={encoding.sample_rate}")
    if encoding.bit_depth == 16 and encoding.preset.format in ("wav", "flac", "aiff"):
        resample += ["out_sample_fmt=s16", f"dither_method={DITHER_16_BIT}"]
    if resample:
        filters.append("aresample=" + ":".join(resample))
    return filters


def _codec_args(encoding: AudioEncoding) -> list[str]:
    preset = encoding.preset
    name = preset.format
    if name in _PCM_CODECS:
        return ["-c:a", _PCM_CODECS[name][encoding.bit_depth or 16]]
    if name == "flac":
        # `s32` com 24 bits úteis é o jeito do ffmpeg gravar FLAC de 24 bits; 16 bits usa `s16`
        return ["-c:a", "flac", "-sample_fmt", "s32" if encoding.bit_depth == 24 else "s16"]
    bitrate = f"{encoding.bitrate_k}k" if encoding.bitrate_k else None
    mode = encoding.bitrate_mode
    if name == "mp3":
        args = ["-c:a", "libmp3lame"]
        if mode == "vbr":
            return [*args, "-q:a", f"{encoding.quality:g}"]
        # ABR do LAME: a taxa pedida é a média, e o codificador varia em volta dela
        return [*args, *(["-abr", "1"] if mode == "abr" else []), "-b:a", str(bitrate)]
    if name == "ogg":
        args = ["-c:a", "libvorbis"]
        if mode == "vbr":
            return [*args, "-q:a", f"{encoding.quality:g}"]
        # CBR do Vorbis: o piso e o teto iguais à taxa pedida; ABR deixa só a média
        limits = ["-minrate", str(bitrate), "-maxrate", str(bitrate)] if mode == "cbr" else []
        return [*args, "-b:a", str(bitrate), *limits]
    if name == "opus":
        return ["-c:a", "libopus", "-b:a", str(bitrate), "-vbr", _OPUS_VBR[mode or "vbr"]]
    if name == "m4a":
        return ["-c:a", "aac", "-b:a", str(bitrate)]
    raise ValueError(f"formato de áudio sem codificador registrado: {name}")


def _container_args(encoding: AudioEncoding) -> list[str]:
    preset = encoding.preset
    args = ["-f", preset.muxer]
    if preset.metadata_style == "id3v23":
        # ID3v2.3 é a versão que todo tocador e editor lê; a 2.4 (padrão do ffmpeg) ainda falha em alguns
        args += ["-id3v2_version", "3"]
    if preset.metadata_style == "mp4":
        args += ["-movflags", "+faststart"]  # o índice no começo: o arquivo toca antes de baixar inteiro
    return args


def encode_args(
    encoding: AudioEncoding,
    tags: Sequence[tuple[str, str]],
    out: Path | str,
    *,
    duration: float | None = None,
) -> list[str]:
    """As opções de saída de um arquivo de áudio: sem vídeo, codec e taxa do preset, etiquetas e o destino.

    `duration` fixa o tamanho do arquivo (`-t`), que o corte de uma região usa para sair com a duração pedida."""
    args = ["-vn", "-map_metadata", "-1", *_codec_args(encoding)]
    args += ["-ar", str(encoding.sample_rate), "-ac", str(encoding.channels)]
    for key, value in tags:
        args += ["-metadata", f"{key}={value}"]
    args += _container_args(encoding)
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    args.append(str(out))
    return args


def trim_filter(start: float, end: float | None) -> str:
    """O pedaço `[start, end)` da mixagem, com o tempo zerado no começo dele (senão o arquivo nasceria com um
    vazio antes do som, do tamanho de `start`)."""
    stop = "" if end is None else f":end={end:.6f}"
    return f"atrim=start={start:.6f}{stop},asetpts=PTS-STARTPTS"


def linear_normalization_applies(measured: Mapping[str, object], target_lufs: float) -> bool:
    """Se o `loudnorm` de duas passadas aplica mesmo um ganho linear a este áudio. Ele só o faz quando o pico
    verdadeiro, depois do ganho, cabe no teto, a variação de volume (LRA) cabe no limite e a medição tem números
    de verdade (um sinal perfeitamente constante mede LRA 0, e o filtro trata isso como medição ausente); senão cai
    no modo dinâmico, e um ganho único (o das trilhas exportadas) deixa de ser igual ao do arquivo da mixagem."""
    try:
        loudness = float(str(measured["input_i"]))
        peak = float(str(measured["input_tp"]))
        variation = float(str(measured["input_lra"]))
        threshold = float(str(measured["input_thresh"]))
    except (KeyError, TypeError, ValueError):
        return False
    measurable = loudness != 0 and variation != 0 and threshold != -70 and peak != 99
    fits = peak + (target_lufs - loudness) <= LOUDNORM_TRUE_PEAK_DB and variation <= LOUDNORM_LINEAR_MAX_LRA
    return measurable and fits
