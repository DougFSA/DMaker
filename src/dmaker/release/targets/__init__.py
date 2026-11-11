"""Um alvo por sistema: o que muda no build de um instalador para o outro entra aqui, sem `if` espalhado no builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..runner import ReleaseError

if TYPE_CHECKING:
    from ..build import PlatformTarget


def target_for(platform: str) -> PlatformTarget:
    """O alvo registrado para o sistema; um novo sistema entra acrescentando uma entrada aqui."""
    from .linux import LinuxTarget
    from .windows import WindowsTarget

    targets = {"windows": WindowsTarget, "linux": LinuxTarget}
    if platform not in targets:
        raise ReleaseError(f"Plataforma sem build: {platform}")
    return targets[platform]()
