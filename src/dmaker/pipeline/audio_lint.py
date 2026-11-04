"""Avisos de áudio de um projeto: a saída em arquivo de áudio (ou opções de áudio onde elas não valem) e os perfis de
ruído que a Redução de ruído usa."""

from __future__ import annotations

from ..domain.audio_effects.restoration import AUTO_PROFILE
from ..domain.audio_presets import is_audio_preset
from ..domain.noise_profile_edits import referenced_profiles
from ..domain.spec import Project
from .audio_duration import NOTHING_TO_PLAY

NORMALIZE_OFF_WARNING = "audio.normalize está desligado: o arquivo sai sem normalização de loudness."


def noise_profile_warnings(project: Project) -> list[str]:
    """Os efeitos de Redução de ruído que apontam para um perfil que não existe: o render falharia nele."""
    known = project.audio.noise_profiles
    missing = sorted(
        {name for name in referenced_profiles(project) if name != AUTO_PROFILE and name not in known}
    )
    return [
        f"a Redução de ruído aponta para o perfil {name!r}, que não existe em audio.noise_profiles "
        f"(perfis: {', '.join(sorted(known)) or 'nenhum'}). Crie com `noise_profile` ou use {AUTO_PROFILE!r}."
        for name in missing
    ]


def audio_output_warnings(project: Project, total: float) -> list[str]:
    """O que a saída de áudio ignora, o que falta para ela ter duração e as opções de áudio sem preset de áudio.

    São avisos, não erros: a spec continua válida e o render de áudio segue sem o que não vale para ele."""
    output = project.output
    warnings: list[str] = []
    if not is_audio_preset(output.preset):
        if output.audio_format is not None:
            warnings.append(
                f"output.audio_format só vale com um preset de áudio (audio/mp3, audio/wav...); "
                f"com {output.preset} ele é ignorado."
            )
        if output.metadata is not None:
            warnings.append(
                f"output.metadata só vale com um preset de áudio (audio/mp3, audio/wav...); "
                f"com {output.preset} ele é ignorado."
            )
        return warnings
    if not project.timeline and total <= 0:
        warnings.append(NOTHING_TO_PLAY + ".")
    if project.overlays or project.captions is not None:
        warnings.append(
            "a saída é só de áudio: sobreposições, legendas e acabamentos de imagem não entram no arquivo."
        )
    if project.audio.normalize == "off":
        warnings.append(NORMALIZE_OFF_WARNING)
    return warnings
