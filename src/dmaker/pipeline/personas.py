"""Serviço do cadastro de personas: o que a CLI, o MCP e a interface chamam (criar, listar, mostrar, editar, apagar).

Fino sobre `PersonaLibrary`: aqui só entram a conferência da voz na biblioteca de vozes e a forma de dicionário que os
adaptadores devolvem. As contas e as regras ficam na biblioteca e nos motores.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.persona import Persona
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
) -> dict[str, Any]:
    if kind not in engine_kinds():
        raise ValueError(
            f"O tipo de persona {kind!r} não está disponível; tipos disponíveis: {', '.join(engine_kinds())}."
        )
    _check_voice(voice, voices or VoiceLibrary())
    created = (library or PersonaLibrary()).create(name, kind, voice, appearance, expressions, gestures)
    return persona_dict(created)


def edit_persona(
    persona_id: str,
    changes: Mapping[str, Any],
    library: PersonaLibrary | None = None,
    voices: VoiceLibrary | None = None,
) -> dict[str, Any]:
    _check_voice(changes.get("voice"), voices or VoiceLibrary())
    return persona_dict((library or PersonaLibrary()).update(persona_id, changes))


def remove_persona(persona_id: str, library: PersonaLibrary | None = None) -> None:
    (library or PersonaLibrary()).remove(persona_id)
