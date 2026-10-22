"""Biblioteca de vozes: clones (a partir de uma gravação de referência) e vozes projetadas por descrição.

Cada voz é uma pasta `assets/voices/<id>/` com `voice.json` e, nos clones, `reference.wav`
(mono, 24 kHz, curta), que é o formato que o modelo de voz espera. Além das vozes gravadas em disco,
a biblioteca expõe as vozes prontas do Kokoro (embutidas no código, sem pasta e não removíveis).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
import wave
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..config import VOICES_DIR
from ..domain.spec import Strict
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner
from ..media.wavio import wav_duration
from ..text.transcribe import Transcriber
from .reference import KEEP_WHOLE_SECONDS, MAX_WINDOWS, WINDOW_SECONDS, select_best_window

REFERENCE_FILE = "reference.wav"
PROFILE_FILE = "voice.json"
REFERENCE_SAMPLE_RATE = 24000  # taxa nativa do modelo de voz; evita reamostrar a cada fala
SILENCE_THRESHOLD_DB = -45  # abaixo disso é respiração e ruído de sala, não fala
SILENCE_KEPT_SECONDS = 0.15  # um respiro curto na ponta evita cortar a consoante inicial


class VoiceNotFoundError(ValueError):
    """Voz inexistente na biblioteca (a mensagem lista as que existem)."""


class VoiceProfile(Strict):
    id: str
    name: str
    kind: Literal["clone", "design", "preset"]
    engine: Literal["omnivoice", "kokoro"] = "omnivoice"
    preset: str | None = None  # nome da voz pronta dentro do motor (ex.: "pf_dora" no Kokoro)
    language: str = "pt"
    reference: str | None = None  # nome do arquivo dentro da pasta da voz
    reference_text: str | None = None
    instruct: str | None = None
    brand: str | None = None
    created: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    folder: Path | None = Field(default=None, exclude=True)  # preenchido pela biblioteca ao carregar

    @property
    def reference_path(self) -> Path | None:
        if self.reference is None or self.folder is None:
            return None
        return self.folder / self.reference

    def fingerprint(self) -> str:
        """Identidade do som da voz: muda se a referência, o texto dela ou a descrição mudarem."""
        digest = hashlib.sha256()
        digest.update(
            f"{self.id}|{self.engine}|{self.kind}|{self.preset or ''}|{self.language}|{self.instruct or ''}|".encode()
        )
        digest.update((self.reference_text or "").encode())
        path = self.reference_path
        if path is not None and path.exists():
            digest.update(path.read_bytes())
        return digest.hexdigest()[:16]


# Vozes do Kokoro-82M em português do Brasil (os nomes vêm do arquivo de vozes do modelo).
BUILTIN_PRESETS: tuple[VoiceProfile, ...] = (
    VoiceProfile(
        id="dora",
        name="Dora (feminina)",
        kind="preset",
        engine="kokoro",
        preset="pf_dora",
        created="2025-01-28",
    ),
    VoiceProfile(
        id="alex",
        name="Alex (masculino)",
        kind="preset",
        engine="kokoro",
        preset="pm_alex",
        created="2025-01-28",
    ),
    VoiceProfile(
        id="santa",
        name="Santa (masculino)",
        kind="preset",
        engine="kokoro",
        preset="pm_santa",
        created="2025-01-28",
    ),
)
_BUILTIN_BY_ID = {voice.id: voice for voice in BUILTIN_PRESETS}


def slugify(name: str) -> str:
    """Nome livre vira id de pasta: sem acento, minúsculas, hifens."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if not slug:
        raise ValueError(f"O nome {name!r} não gera um id válido; use letras ou números.")
    return slug


def reference_command(source: Path, destination: Path) -> FFmpegCommand:
    """Prepara a referência: mono 24 kHz e sem silêncio nas pontas (a escolha do trecho vem depois)."""
    trim = f"silenceremove=start_periods=1:start_threshold={SILENCE_THRESHOLD_DB}dB:start_silence={SILENCE_KEPT_SECONDS}"
    # O silêncio do fim sai invertendo o áudio, aparando o "começo" e invertendo de volta.
    graph = f"{trim},areverse,{trim},areverse"
    args = [
        "-i",
        str(source),
        "-vn",
        "-af",
        graph,
        "-ac",
        "1",
        "-ar",
        str(REFERENCE_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        "-t",  # teto de gravação aproveitada, para o custo de transcrever as janelas ter limite
        f"{MAX_WINDOWS * WINDOW_SECONDS:g}",
        str(destination),
    ]
    return FFmpegCommand(args, label="referência de voz")


def _duration_or_zero(wav: Path) -> float:
    """Duração da referência preparada; ilegível conta como curta (o ffmpeg real sempre grava um WAV válido)."""
    try:
        return wav_duration(wav)
    except (wave.Error, EOFError, OSError):
        return 0.0


class VoiceLibrary:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or VOICES_DIR

    def _folder(self, voice_id: str) -> Path:
        return self.root / voice_id

    def _load(self, folder: Path) -> VoiceProfile:
        profile = VoiceProfile.model_validate_json((folder / PROFILE_FILE).read_text(encoding="utf-8"))
        return profile.model_copy(update={"folder": folder})

    def list(self, brand: str | None = None, presets: bool = True) -> list[VoiceProfile]:
        """Todas as vozes (as prontas primeiro); com `brand`, as dessa marca mais as sem marca
        (servem para qualquer uma). `presets=False` devolve só as gravadas em disco."""
        stored: list[VoiceProfile] = []
        if self.root.exists():
            stored = [self._load(p.parent) for p in sorted(self.root.glob(f"*/{PROFILE_FILE}"))]
        profiles = [*BUILTIN_PRESETS, *stored] if presets else stored
        if brand is None:
            return profiles
        return [p for p in profiles if p.brand in (brand, None)]

    def get(self, voice_id: str) -> VoiceProfile:
        if voice_id in _BUILTIN_BY_ID:
            return _BUILTIN_BY_ID[voice_id]
        folder = self._folder(voice_id)
        if not (folder / PROFILE_FILE).exists():
            known = ", ".join(p.id for p in self.list()) or "nenhuma voz cadastrada"
            raise VoiceNotFoundError(f"Voz {voice_id!r} não encontrada. Vozes disponíveis: {known}.")
        return self._load(folder)

    def _reserve(self, name: str) -> tuple[str, Path]:
        voice_id = slugify(name)
        if voice_id in _BUILTIN_BY_ID:
            raise ValueError(f"{voice_id!r} é o nome de uma voz pronta; escolha outro nome.")
        folder = self._folder(voice_id)
        if (folder / PROFILE_FILE).exists():
            raise ValueError(f"Já existe a voz {voice_id!r}. Remova-a antes ou escolha outro nome.")
        return voice_id, folder

    def _write(self, profile: VoiceProfile, folder: Path) -> VoiceProfile:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PROFILE_FILE).write_text(profile.model_dump_json(indent=1), encoding="utf-8")
        return profile.model_copy(update={"folder": folder})

    def save_clone(
        self,
        name: str,
        reference_audio: Path,
        runner: FFmpegRunner,
        transcriber: Transcriber | None,
        reference_text: str | None = None,
        brand: str | None = None,
        language: str = "pt",
    ) -> VoiceProfile:
        """Cadastra uma voz clonada; sem `reference_text`, o texto da referência é transcrito.

        Gravações de até 20 s valem inteiras. As maiores são cortadas na janela de 15 s com mais fala
        (como no VoiceStudio): o texto passado não alinha com um trecho, então é descartado e o
        transcritor é obrigatório.
        """
        if not reference_audio.exists():
            raise FileNotFoundError(f"Referência de voz não encontrada: {reference_audio}")
        voice_id, folder = self._reserve(name)
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / REFERENCE_FILE
        try:
            runner.run(reference_command(reference_audio, destination))
            if _duration_or_zero(destination) > KEEP_WHOLE_SECONDS:
                if transcriber is None:
                    raise ValueError(
                        f"A gravação tem mais de {KEEP_WHOLE_SECONDS:g} s; para escolher o melhor trecho é "
                        "preciso o transcritor (faster-whisper). Corte a gravação ou instale o extra captions."
                    )
                text = select_best_window(destination, transcriber, language)
            else:
                text = (reference_text or "").strip() or self._transcribe(transcriber, destination, language)
            profile = VoiceProfile(
                id=voice_id,
                name=name.strip(),
                kind="clone",
                language=language,
                reference=REFERENCE_FILE,
                reference_text=text,
                brand=brand,
            )
            return self._write(profile, folder)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)  # não deixa uma voz pela metade na biblioteca
            raise

    @staticmethod
    def _transcribe(transcriber: Transcriber | None, wav: Path, language: str) -> str | None:
        """Texto falado na referência; o modelo de voz precisa dele para clonar bem."""
        if transcriber is None:
            return None
        transcript = transcriber.transcribe(wav, language)
        return " ".join(cue.text.strip() for cue in transcript.cues).strip() or None

    def save_design(
        self, name: str, instruct: str, language: str = "pt", brand: str | None = None
    ) -> VoiceProfile:
        """Cadastra uma voz criada por descrição (ver `voice.design`), sem gravação de referência."""
        if not instruct.strip():
            raise ValueError("A descrição da voz (instruct) não pode ficar vazia.")
        voice_id, folder = self._reserve(name)
        profile = VoiceProfile(
            id=voice_id, name=name.strip(), kind="design", language=language, instruct=instruct, brand=brand
        )
        return self._write(profile, folder)

    def remove(self, voice_id: str) -> None:
        if voice_id in _BUILTIN_BY_ID:
            raise ValueError(f"{voice_id!r} é uma voz pronta e não pode ser removida.")
        self.get(voice_id)
        shutil.rmtree(self._folder(voice_id))
