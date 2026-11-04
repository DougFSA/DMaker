"""Edição dos perfis de ruído do projeto (`audio.noise_profiles`): criar, trocar e remover. Tudo puro: cada função devolve
um Project NOVO e levanta `EditError` em português quando o pedido não faz sentido."""

from __future__ import annotations

from typing import Any

from .audio_effects.restoration import AUTO_PROFILE
from .edits import EditError, _clone
from .spec import Project

MAX_NAME_LENGTH = 40


def check_profile_name(name: Any) -> str:
    """O nome de um perfil: texto não vazio, sem espaço nas pontas, e que não seja `auto` (o perfil que não é guardado)."""
    if not isinstance(name, str) or not name.strip():
        raise EditError("o perfil de ruído precisa de um `name` (texto não vazio)")
    if name != name.strip() or len(name) > MAX_NAME_LENGTH:
        raise EditError(
            f"o nome do perfil não pode ter espaço nas pontas nem passar de {MAX_NAME_LENGTH} letras"
        )
    if name == AUTO_PROFILE:
        raise EditError(
            f"{AUTO_PROFILE!r} é o perfil automático (o trecho mais quieto do item) e não é guardado: escolha outro nome"
        )
    return name


def set_noise_profile(project: Project, name: str, target: str, start: float, end: float) -> Project:
    """Cria o perfil `name` (ou troca o trecho dele): o trecho de `start` a `end` (segundos do item) de `target`."""
    check_profile_name(name)

    def mutate(data: dict) -> None:
        data["audio"].setdefault("noise_profiles", {})[name] = {
            "target": target,
            "start": round(start, 6),
            "end": round(end, 6),
        }

    return _clone(project, mutate)


def referenced_profiles(project: Project) -> list[str]:
    """O perfil que cada efeito de Redução de ruído do projeto pede (`auto` incluído), um por efeito, em qualquer item."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "noise_reduction":
                found.append(str(node.get("profile", AUTO_PROFILE)))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(project.model_dump(mode="json"))
    return found


def profile_users(project: Project, name: str) -> int:
    """Quantos efeitos de Redução de ruído do projeto apontam para o perfil `name`."""
    return sum(1 for reference in referenced_profiles(project) if reference == name)


def remove_noise_profile(project: Project, name: str) -> Project:
    """Apaga o perfil `name`. Recusa se ele não existe ou se algum efeito ainda o usa."""
    if name not in project.audio.noise_profiles:
        known = ", ".join(sorted(project.audio.noise_profiles)) or "nenhum"
        raise EditError(f"não há o perfil de ruído {name!r} (perfis: {known})")
    users = profile_users(project, name)
    if users:
        raise EditError(
            f"o perfil {name!r} é usado por {users} efeito(s) de Redução de ruído: troque o perfil deles "
            f"(ou use {AUTO_PROFILE!r}) ou tire os efeitos antes de apagá-lo"
        )

    def mutate(data: dict) -> None:
        del data["audio"]["noise_profiles"][name]

    return _clone(project, mutate)
