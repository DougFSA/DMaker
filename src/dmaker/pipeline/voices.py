"""Serviços de voz usados pela CLI e pelo MCP: clonar, projetar, listar e falar.

Cada função recebe as dependências por parâmetro (biblioteca, runner, transcritor, sintetizador) e, quando
não recebe, usa as reais; assim os dois adaptadores ficam finos e os testes injetam dublês.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from .. import config
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..text.transcribe import Transcriber, WhisperTranscriber
from ..voice.design import VoiceDesign, parse_instruct
from ..voice.kokoro import KokoroSynthesizer
from ..voice.lexicon_store import LexiconStore
from ..voice.library import VoiceLibrary, VoiceProfile
from ..voice.router import RoutingSynthesizer
from ..voice.synth import OmniVoiceSynthesizer, SpeechSynthesizer
from .narration import DEFAULT_STEPS, NarrationResult, NarrationService

PREVIEW_TEXTS = {
    "pt": "Olá, esta é a minha voz. Assim eu soo ao narrar o seu vídeo, com calma e clareza.",
    "en": "Hello, this is my voice. This is how I sound when narrating your video.",
}


def build_synthesizer(device: str = "auto") -> RoutingSynthesizer:
    """Roteador com os dois motores: Kokoro (vozes prontas, rápido) e OmniVoice (clones e vozes projetadas)."""
    return RoutingSynthesizer(
        {"kokoro": KokoroSynthesizer(), "omnivoice": OmniVoiceSynthesizer(device=device)}
    )


@lru_cache(maxsize=1)
def shared_synthesizer() -> RoutingSynthesizer:
    """Um único roteador por processo: os modelos levam segundos a minutos para carregar e ficam na memória."""
    return build_synthesizer()


def profile_dict(profile: VoiceProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "kind": profile.kind,
        "engine": profile.engine,
        "preset": profile.preset,
        "language": profile.language,
        "brand": profile.brand,
        "instruct": profile.instruct,
        "reference": str(profile.reference_path) if profile.reference_path else None,
        "reference_text": profile.reference_text,
        "created": profile.created,
    }


def clone_voice(
    name: str,
    reference_audio: Path,
    reference_text: str | None = None,
    brand: str | None = None,
    language: str = "pt",
    library: VoiceLibrary | None = None,
    runner: FFmpegRunner | None = None,
    transcriber: Transcriber | None = None,
) -> VoiceProfile:
    """Cadastra uma voz a partir de uma gravação; sem texto, o Whisper transcreve a referência."""
    return (library or VoiceLibrary()).save_clone(
        name,
        reference_audio,
        runner or SubprocessRunner(quiet=True),
        transcriber or WhisperTranscriber(),
        reference_text=reference_text,
        brand=brand,
        language=language,
    )


def design_voice(
    name: str,
    gender: str | None = None,
    age: str | None = None,
    pitch: str | None = None,
    accent: str | None = None,
    whisper: bool = False,
    instruct: str | None = None,
    brand: str | None = None,
    language: str = "pt",
    library: VoiceLibrary | None = None,
) -> VoiceProfile:
    """Cadastra uma voz descrita por atributos; `instruct` escrito à mão entra como base, os atributos sobrepõem."""
    base = parse_instruct(instruct) if instruct else VoiceDesign()
    overrides = {"gender": gender, "age": age, "pitch": pitch, "accent": accent}
    changes = {key: value for key, value in overrides.items() if value}
    if whisper:
        changes["whisper"] = True
    design = VoiceDesign.model_validate({**base.model_dump(), **changes})
    return (library or VoiceLibrary()).save_design(name, design.to_instruct(), language=language, brand=brand)


def default_narration_path(text: str) -> Path:
    digest = hashlib.sha1(text.encode()).hexdigest()[:8]
    return config.OUTPUT_DIR / f"narracao-{digest}.wav"


def speak(
    text: str,
    out: Path | None = None,
    voice_id: str | None = None,
    language: str | None = None,
    speed: float = 1.0,
    instruct: str | None = None,
    seed: int | None = None,
    steps: int | None = DEFAULT_STEPS,
    write_srt: bool = False,
    master: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
    library: VoiceLibrary | None = None,
    runner: FFmpegRunner | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    brand: str | None = None,
    lexicons: LexiconStore | None = None,
) -> NarrationResult:
    """Narra `text` com a voz `voice_id` (ou uma voz automática/descrita por `instruct`) e grava o áudio.

    Sem `language`, vale o idioma da voz escolhida (ou português quando não há voz). A pronúncia vem do
    dicionário global mais o da marca `brand` (sem ela, o da marca dona da voz)."""
    voice = (library or VoiceLibrary()).get(voice_id) if voice_id else None
    service = NarrationService(
        synthesizer or shared_synthesizer(),
        runner or SubprocessRunner(quiet=True),
        log=log,
        lexicons=(lexicons or LexiconStore()).for_brand,
    )
    return service.render(
        text,
        out or default_narration_path(text),
        voice,
        language=language or (voice.language if voice else "pt"),
        speed=speed,
        instruct=instruct,
        seed=seed,
        on_progress=on_progress,
        write_srt=write_srt,
        steps=steps,
        master=master,
        brand=brand or (voice.brand if voice else None),
    )


def preview_voice(
    voice_id: str,
    text: str | None = None,
    out: Path | None = None,
    library: VoiceLibrary | None = None,
    runner: FFmpegRunner | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    log: Callable[[str], None] | None = None,
) -> NarrationResult:
    """Amostra curta da voz para o usuário ouvir antes de usar numa narração longa."""
    library = library or VoiceLibrary()
    voice = library.get(voice_id)
    sample = text or PREVIEW_TEXTS.get(voice.language, PREVIEW_TEXTS["pt"])
    destination = out or config.OUTPUT_DIR / f"voz-{voice.id}-amostra.wav"
    return speak(
        sample,
        destination,
        voice_id=voice.id,
        language=voice.language,
        seed=1,
        library=library,
        runner=runner,
        synthesizer=synthesizer,
        log=log,
    )
