"""Ferramentas de montagem comuns aos dois sistemas: restrições do pip, ambiente isolado e cópia da árvore do pacote."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from .platforms import PACKAGE_EXTRAS

# O Python portátil não pode enxergar nada da máquina de quem monta o pacote: sem isto o pip do build achou o
# `site-packages` do usuário, deu os pacotes dele por instalados e chegou a desinstalá-los de lá. Vale para todo
# `pip` e todo `python` do build, no Windows e dentro do contêiner do Linux.
ISOLATED_ENV = {"PYTHONNOUSERSITE": "1", "PYTHONPATH": "", "PYTHONHOME": "", "PIP_USER": "0"}


def constraints_from_freeze(freeze_text: str, own_name: str = "dmaker") -> str:
    """Do `pip freeze` do ambiente de desenvolvimento, as linhas `pacote==versão` (menos o próprio DMaker), que fixam
    no pacote as mesmas versões que passam nos testes. Linhas editáveis ou por caminho não servem de restrição."""
    pinned = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)$")
    kept = []
    for line in freeze_text.splitlines():
        match = pinned.match(line.strip())
        if match and match.group(1).lower().replace("_", "-") != own_name:
            kept.append(line.strip())
    return "\n".join(kept) + "\n"


def wheel_requirement(wheel: Path | str, extras: Iterable[str] = PACKAGE_EXTRAS) -> str:
    return f"{wheel}[{','.join(extras)}]"


def link_or_copy(source: Path, destination: Path) -> None:
    """Hardlink quando dá (mesmo volume: instantâneo e sem ocupar disco), cópia quando não."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def stage_tree(source: Path, destination: Path) -> int:
    """Leva uma pasta (ou um arquivo) para o destino e devolve quantos arquivos foram."""
    if source.is_file():
        link_or_copy(source, destination)
        return 1
    count = 0
    for folder, _dirs, names in os.walk(source):
        relative = Path(folder).relative_to(source)
        (destination / relative).mkdir(parents=True, exist_ok=True)
        for name in names:
            link_or_copy(Path(folder) / name, destination / relative / name)
            count += 1
    return count


def tree_size(path: Path) -> int:
    """Os bytes de um arquivo ou de uma pasta inteira."""
    if path.is_file():
        return path.stat().st_size
    return sum(
        (Path(folder) / name).stat().st_size for folder, _dirs, names in os.walk(path) for name in names
    )


def longest_relative_path(root: Path) -> int:
    """O comprimento do caminho relativo mais longo de uma árvore (arquivo ou pasta), com a barra de cada nível."""
    longest = 0
    for folder, dirs, names in os.walk(root):
        relative = Path(folder).relative_to(root)
        for name in [*dirs, *names]:
            longest = max(longest, len(str(relative / name)))
    return longest
