"""Importar áudio bruto (PCM sem cabeçalho) para um projeto: o "Import Raw Data" do Audacity.

O arquivo bruto não muda. O ffmpeg lê os bytes como a pessoa descreveu (codificação, ordem dos bytes, canais, taxa) e
grava um WAV na pasta do projeto; esse WAV entra em `audio.voiceover` como voz gravada, no instante pedido. Se o
projeto ainda não existe, nasce um projeto só de áudio (WAV de 16 bits) para receber o arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import AudioSettings, Output, Project, VoiceoverClip
from ..filtergraph.raw_import import MAX_RAW_CHANNELS, RAW_ENCODINGS, raw_duration, raw_import_command
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from .context import Prober
from .projects import project_path

NEW_PROJECT_PRESET = "audio/wav"


class RawImportError(ValueError):
    """Pedido de importação que não dá para atender (arquivo ausente, WAV que já existe, valor fora da faixa)."""


@dataclass(frozen=True)
class RawImport:
    """O que a importação fez: o WAV gerado (e o nome dele na spec), a duração e se o projeto foi criado agora."""

    wav: Path
    source: str  # o `src` gravado em `audio.voiceover`, relativo à pasta do projeto
    duration: float
    created_project: bool


def raw_wav_path(project_dir: Path, raw: Path, name: str | None = None) -> Path:
    """Onde o WAV da importação fica: na pasta do projeto, com o nome dado ou o do arquivo bruto."""
    stem = (name or raw.stem).strip()
    if not stem or any(char in stem for char in '\\/:*?"<>|'):
        raise RawImportError('o nome do WAV não pode ter / \\ : * ? " < > |')
    return project_dir / f"{stem}.wav"


def import_raw_audio(
    name_or_path: str | Path,
    raw: Path,
    *,
    encoding: str = "s16",
    byte_order: str = "little",
    channels: int = 1,
    sample_rate: int = 44100,
    offset_bytes: int = 0,
    percent: float = 100.0,
    start: float = 0.0,
    volume: float = 1.0,
    name: str | None = None,
    overwrite: bool = False,
    runner: FFmpegRunner | None = None,
    prober: Prober = probe,
) -> RawImport:
    """Converte `raw` num WAV da pasta do projeto e o põe em `audio.voiceover`. O arquivo bruto não é alterado."""
    if not raw.exists():
        raise RawImportError(f"arquivo bruto não encontrado: {raw}")
    if encoding not in RAW_ENCODINGS:
        raise RawImportError(f"codificação desconhecida: {encoding!r} (use {', '.join(RAW_ENCODINGS)})")
    if not 1 <= channels <= MAX_RAW_CHANNELS:
        raise RawImportError(f"canais de 1 a {MAX_RAW_CHANNELS}, veio {channels}")
    if not 8000 <= sample_rate <= 192000:
        raise RawImportError(f"taxa de amostragem de 8000 a 192000 Hz, veio {sample_rate}")
    if not 0 < percent <= 100:
        raise RawImportError(
            f"a quantidade a importar vai de 0 (exclusive) a 100 por cento, veio {percent:g}"
        )
    if offset_bytes < 0:
        raise RawImportError("o deslocamento inicial não pode ser negativo")
    spec_path = project_path(name_or_path)
    created = not spec_path.exists()
    if created and Path(str(name_or_path)).suffix == ".json":
        raise RawImportError(f"projeto não encontrado: {spec_path}")
    project = _new_project(spec_path.parent.name) if created else Project.load(spec_path)
    project_dir = spec_path.parent
    wav = raw_wav_path(project_dir, raw, name)
    if wav.exists() and not overwrite:
        raise RawImportError(
            f"o arquivo {wav.name} já existe na pasta do projeto: escolha outro nome (name) ou use overwrite"
        )
    available = raw_duration(raw.stat().st_size, encoding, channels, sample_rate, offset_bytes)
    if available <= 0:
        raise RawImportError("o arquivo não tem amostras depois do deslocamento inicial")
    duration = available * percent / 100
    project_dir.mkdir(parents=True, exist_ok=True)
    command = raw_import_command(
        raw,
        wav,
        encoding=encoding,
        byte_order=byte_order,
        channels=channels,
        sample_rate=sample_rate,
        offset_bytes=offset_bytes,
        duration=duration if percent < 100 else None,
    )
    (runner or SubprocessRunner(quiet=True)).run(command)
    project.base_dir = project_dir
    source = wav.name
    voiceover = [
        clip for clip in project.audio.voiceover if clip.src != source
    ]  # reimportar troca, não repete
    voiceover.append(VoiceoverClip(src=source, start=start, volume=volume))
    updated = project.model_copy(update={"audio": project.audio.model_copy(update={"voiceover": voiceover})})
    updated.base_dir = project_dir
    updated.save(spec_path)
    return RawImport(wav, source, duration, created)


def _new_project(name: str) -> Project:
    """Projeto só de áudio, vazio, para receber a primeira importação."""
    return Project(name=name, output=Output(preset=NEW_PROJECT_PRESET), audio=AudioSettings(), timeline=[])
