"""Serviço do cadastro de personas: o que a CLI, o MCP e a interface chamam (criar, listar, mostrar, editar, apagar).

Fino sobre `PersonaLibrary`: aqui só entram a conferência da voz na biblioteca de vozes e a forma de dicionário que os
adaptadores devolvem. As contas e as regras ficam na biblioteca e nos motores.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..domain.persona import Persona
from ..domain.spec import Project
from ..persona.engine import capabilities, engine_kinds
from ..persona.library import PersonaLibrary
from ..voice.library import VoiceLibrary


def persona_dict(persona: Persona) -> dict[str, Any]:
    expressions, gestures = capabilities(persona)
    return {
        "id": persona.id,
        "name": persona.name,
        "kind": persona.kind,
        "voice": persona.voice,
        "appearance": persona.appearance,
        "expressions": expressions,
        "gestures": gestures,
        "builtin": persona.builtin,
        "created": persona.created,
    }


def _check_voice(voice: str | None, voices: VoiceLibrary) -> None:
    if voice:
        voices.get(voice)  # levanta a mensagem que lista as vozes que existem


def list_personas(library: PersonaLibrary | None = None) -> list[dict[str, Any]]:
    return [persona_dict(p) for p in (library or PersonaLibrary()).list()]


def get_persona(persona_id: str, library: PersonaLibrary | None = None) -> dict[str, Any]:
    return persona_dict((library or PersonaLibrary()).get(persona_id))


def create_persona(
    name: str,
    kind: str = "2d",
    voice: str | None = None,
    appearance: Mapping[str, Any] | None = None,
    expressions: list[str] | None = None,
    gestures: list[str] | None = None,
    library: PersonaLibrary | None = None,
    voices: VoiceLibrary | None = None,
    photo: str | Path | None = None,
) -> dict[str, Any]:
    """Cria uma persona. `photo` é o arquivo da foto da persona realista (jpg ou png, lado menor de pelo menos 512
    px): é copiado para a pasta da persona, e só esse tipo usa foto."""
    if kind not in engine_kinds():
        raise ValueError(
            f"O tipo de persona {kind!r} não está disponível; tipos disponíveis: {', '.join(engine_kinds())}."
        )
    _check_voice(voice, voices or VoiceLibrary())
    appearance, files = _with_photo(kind, dict(appearance or {}), photo)
    created = (library or PersonaLibrary()).create(
        name, kind, voice, appearance, expressions, gestures, files=files
    )
    return persona_dict(created)


def _with_photo(
    kind: str, appearance: dict[str, Any], photo: str | Path | None
) -> tuple[dict[str, Any], dict[str, Path]]:
    """A aparência com o nome da foto dentro da pasta da persona e o arquivo a copiar para lá."""
    from ..persona.portrait import check_photo_file

    if kind != "realistic":
        if photo is not None:
            raise ValueError(f"Só a persona realista usa foto; o tipo {kind!r} não tem `photo`.")
        return appearance, {}
    if photo is None:
        raise ValueError("A persona realista precisa de uma foto: informe `photo` (um arquivo .jpg ou .png).")
    source = Path(photo)
    check_photo_file(source)  # levanta PhotoError (ValueError) com a mensagem do que corrigir
    stored = "foto" + (".png" if source.suffix.lower() == ".png" else ".jpg")
    return {**appearance, "photo": stored}, {stored: source}


def edit_persona(
    persona_id: str,
    changes: Mapping[str, Any],
    library: PersonaLibrary | None = None,
    voices: VoiceLibrary | None = None,
) -> dict[str, Any]:
    _check_voice(changes.get("voice"), voices or VoiceLibrary())
    return persona_dict((library or PersonaLibrary()).update(persona_id, changes))


def use_persona(
    project: Project,
    persona_id: str,
    text: str,
    placement: str = "segment",
    start: float = 0.0,
    library: PersonaLibrary | None = None,
) -> Project:
    """O projeto com a persona falando `text`: um trecho de tela cheia no fim da linha do tempo (`segment`) ou uma
    sobreposição no canto (`overlay`) a partir de `start`. Devolve uma cópia; quem chama salva."""
    from ..domain.spec import PersonaOverlay, PersonaSegment

    (library or PersonaLibrary()).get(persona_id)  # persona que não existe: a mensagem lista as que existem
    if not text.strip():
        raise ValueError("Escreva o que a persona vai falar.")
    speech = {"text": text.strip()}
    updated = project.model_copy(deep=True)
    updated.base_dir = project.base_dir
    if placement == "segment":
        updated.timeline.append(PersonaSegment.model_validate({"persona": persona_id, "speech": speech}))
    elif placement == "overlay":
        updated.overlays.append(
            PersonaOverlay.model_validate({"persona": persona_id, "speech": speech, "start": start})
        )
    else:
        raise ValueError("O lugar da persona é `segment` (tela cheia) ou `overlay` (no canto).")
    return updated


def remove_persona(persona_id: str, library: PersonaLibrary | None = None) -> None:
    (library or PersonaLibrary()).remove(persona_id)
