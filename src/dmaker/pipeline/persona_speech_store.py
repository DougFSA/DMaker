"""A duração real da fala de cada persona do projeto, guardada ao lado dele depois da primeira síntese.

Antes de sintetizar, a duração de um trecho de persona é uma estimativa pelo tamanho do texto (serve à vista da linha
do tempo, não ao render). Depois do render a duração real é conhecida: este arquivo (`persona_speech.json`, na pasta do
projeto, como o `sync.json`) a guarda para a linha do tempo, o QA e a prévia usarem o número certo sem sintetizar de
novo. A chave é a da própria fala (persona, voz e o que ela diz): mudar o texto ou a voz volta à estimativa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..domain.persona import Persona, PersonaSpeech, estimate_speech_seconds
from ..domain.spec import PersonaOverlay, PersonaSegment, Project
from ..media.probe import MediaInfo
from ..persona.library import PersonaLibrary, PersonaNotFoundError
from .cache_key import cache_key
from .context import Prober
from .sources import Source

STORE_FILE = "persona_speech.json"


def speech_key(persona: Persona, speech: PersonaSpeech) -> str:
    """A identidade da fala: a mesma que o `PersonaStage` usa para guardar a fala por render (fora do dry-run)."""
    return cache_key(persona.id, persona.voice, speech.model_dump(mode="json"), False)


def _store_path(base_dir: Path | None) -> Path | None:
    return (base_dir / STORE_FILE) if base_dir else None


def load_durations(base_dir: Path | None) -> dict[str, float]:
    path = _store_path(base_dir)
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # um arquivo estragado só devolve a estimativa
    return {k: float(v) for k, v in data.items() if isinstance(v, int | float)}


def save_duration(base_dir: Path | None, key: str, duration: float) -> None:
    """Guarda a duração real. Projeto sem pasta (em memória) não tem onde guardar, e isso não é erro."""
    path = _store_path(base_dir)
    if path is None or not base_dir.is_dir():
        return
    durations = load_durations(base_dir)
    if durations.get(key) == round(duration, 6):
        return
    durations[key] = round(duration, 6)
    try:
        path.write_text(json.dumps(durations, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # só uma otimização da vista: sem ela volta a estimativa


def spoken_info(duration: float) -> MediaInfo:
    """O áudio da fala visto como mídia: só a duração importa para as contas da linha do tempo."""
    return MediaInfo(Path(), duration, 0, 0, 0.0, False, True, False)


def with_spoken_durations(
    project: Project,
    sources: list[Source],
    library: PersonaLibrary | None = None,
    prober: Prober | None = None,
) -> list[Source]:
    """As fontes dos trechos de persona com a duração real da fala: a do áudio dado (medida no arquivo) ou a da
    síntese, quando ela já foi feita neste projeto."""
    durations = load_durations(project.base_dir)
    library = library or PersonaLibrary()
    result = list(sources)
    for index, segment in enumerate(project.timeline):
        if not isinstance(segment, PersonaSegment):
            continue
        if segment.speech.audio:
            audio = project.resolve(segment.speech.audio)
            if prober is not None and audio.is_file():
                result[index] = replace(result[index], info=replace(prober(audio), has_video=False))
            continue
        try:
            persona = library.get(segment.persona)
        except PersonaNotFoundError:
            continue  # a validação do projeto é quem acusa a persona que não existe
        real = durations.get(speech_key(persona, segment.speech))
        if real is not None:
            result[index] = replace(result[index], info=spoken_info(real))
    return result


@dataclass(frozen=True)
class PersonaView:
    """O que a vista da linha do tempo sabe das personas do projeto: o nome de cada uma e, para as sobrepostas, quanto
    dura a fala (a real quando já foi sintetizada, senão a estimada pelo texto)."""

    names: dict[str, str] = field(default_factory=dict)
    overlay_seconds: dict[int, float] = field(default_factory=dict)


def persona_view(project: Project, library: PersonaLibrary | None = None) -> PersonaView:
    durations = load_durations(project.base_dir)
    library = library or PersonaLibrary()
    names: dict[str, str] = {}
    seconds: dict[int, float] = {}
    for index, item in enumerate([*project.timeline, *project.overlays]):
        if not isinstance(item, PersonaSegment | PersonaOverlay):
            continue
        try:
            persona = library.get(item.persona)
        except PersonaNotFoundError:
            continue
        names[persona.id] = persona.name
        if isinstance(item, PersonaOverlay):
            real = durations.get(speech_key(persona, item.speech))
            estimate = estimate_speech_seconds(item.speech.text or "", item.speech.speed)
            seconds[index - len(project.timeline)] = real if real is not None else estimate
    return PersonaView(names, seconds)
