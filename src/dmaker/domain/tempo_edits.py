"""Edição do andamento do projeto (`audio.tempo`) e do andamento da música (`audio.music.bpm`, `beat_offset`,
`stretch_to_tempo`). Tudo puro: cada função devolve um Project NOVO e levanta `EditError` em português quando o pedido não
faz sentido."""

from __future__ import annotations

from typing import Any

from .edits import EditError, _clone
from .spec import Project

TEMPO_FIELDS = ("bpm", "time_signature", "offset")
MUSIC_TEMPO_FIELDS = ("bpm", "beat_offset", "stretch_to_tempo")


def set_tempo(project: Project, fields: dict[str, Any]) -> Project:
    """Define o andamento do projeto, ou muda só os campos dados quando ele já existe. Sem andamento prévio, `bpm` é
    obrigatório (os outros têm padrão: 4/4, tempo 1 em 0 s)."""
    given = {name: fields[name] for name in TEMPO_FIELDS if fields.get(name) is not None}
    current = project.audio.tempo
    if current is None and "bpm" not in given:
        raise EditError(
            "o projeto ainda não tem andamento: informe o `bpm` (e, se quiser, `time_signature` e `offset`)"
        )
    if not given:
        raise EditError("informe ao menos um de: bpm, time_signature, offset")

    def mutate(data: dict) -> None:
        tempo = data["audio"].get("tempo") or {}
        tempo.update(given)
        data["audio"]["tempo"] = tempo

    return _clone(project, mutate)


def remove_tempo(project: Project) -> Project:
    """Tira o andamento do projeto. A régua em compassos, o encaixe nos tempos e as referências `beat:`/`bar:` deixam de
    existir; o que estava gravado em segundos fica onde está."""
    if project.audio.tempo is None:
        raise EditError("o projeto não tem andamento (audio.tempo) para remover")

    def mutate(data: dict) -> None:
        data["audio"].pop("tempo", None)

    return _clone(project, mutate)


def set_music_tempo(project: Project, fields: dict[str, Any]) -> Project:
    """Muda o andamento da música: `bpm`, `beat_offset` (onde cai o primeiro tempo no arquivo) e `stretch_to_tempo`.
    `bpm: null` esquece o andamento (e desliga o esticamento, que dependia dele)."""
    if project.audio.music is None:
        raise EditError("o projeto não tem música (audio.music)")
    given = {name: fields[name] for name in MUSIC_TEMPO_FIELDS if name in fields}
    if not given:
        raise EditError("informe ao menos um de: bpm, beat_offset, stretch_to_tempo")

    def mutate(data: dict) -> None:
        music = data["audio"]["music"]
        for name, value in given.items():
            if value is None:
                music.pop(name, None)
            else:
                music[name] = value
        # esquecer o andamento da música desliga o esticamento que dependia dele; ligar o esticamento sem andamento é
        # pedido errado e a spec o recusa
        if "bpm" in given and given["bpm"] is None and "stretch_to_tempo" not in given:
            music.pop("stretch_to_tempo", None)

    return _clone(project, mutate)
