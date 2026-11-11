"""O manifesto do pacote: o que entra, de onde vem, para onde vai e por quê. Função pura, sem tocar o disco."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from ..agent.offline import REQUIRED_MODELS
from ..domain.models import REGISTRY, find_model
from .platforms import PLATFORMS, WINDOWS

Target = Literal["program", "data"]
# `repo`: arquivo versionado do clone; `pasta`: da pasta principal (binários e modelos que já estão lá); `build`: o próprio
# build o produz (o Chromium e o FFmpeg do Linux, baixados no contêiner), então não há o que copiar.
Origin = Literal["repo", "pasta", "build"]

# Pastas que são dado de quem usa o editor (ou saída dele): nunca entram no pacote, mesmo que estejam no git.
FORBIDDEN_PARTS = frozenset(
    {"voices", "macros", "projects", "output", "conversations", "plugins", "cache", "__pycache__"}
)
# O que sai de `assets/` e `templates/` para o programa: o que o git versiona.
SHIPPED_REPO_FOLDERS = ("assets", "templates")
MODELS_DEST = "cache/models"


@dataclass(frozen=True)
class ManifestEntry:
    source: str  # relativo à raiz de origem (o clone, para `repo`; a pasta principal, para `pasta`), barras normais
    dest: str  # relativo ao programa ou à pasta dos dados
    target: Target
    origin: Origin
    reason: str


def default_model_ids() -> tuple[str, ...]:
    """Os modelos que o `dmaker models` trata como padrão: os mesmos que o `doctor --offline` exige em disco."""
    return tuple(model_id for model_id, _ in REQUIRED_MODELS)


def is_shippable(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return not any(part in FORBIDDEN_PARTS for part in parts)


def repo_entries(tracked_files: Iterable[str]) -> list[ManifestEntry]:
    """Os arquivos versionados de `assets/` e `templates/`, sem vozes, macros nem dado de cliente."""
    entries = []
    for path in sorted(tracked_files):
        path = path.replace("\\", "/")
        if path.split("/")[0] in SHIPPED_REPO_FOLDERS and is_shippable(path):
            entries.append(ManifestEntry(path, path, "program", "repo", "versionado no git"))
    return entries


def binary_entries(platform: str = WINDOWS.id) -> list[ManifestEntry]:
    spec = PLATFORMS[platform]
    return [
        ManifestEntry(f"bin/{name}", f"bin/{name}", "program", spec.binaries_origin, why)
        for name, why in spec.binaries
    ]


def model_entries(
    model_ids: Iterable[str] | None = None, excluded: Iterable[str] = ()
) -> list[ManifestEntry]:
    """Cada caminho de cada modelo padrão, sem repetir o que dois modelos dividem, para `<dados>/cache/models`.
    Os `excluded` (`--sem-modelo`) ficam de fora: baixam no primeiro uso."""
    entries: dict[str, ManifestEntry] = {}
    skipped = set(excluded)
    for model_id in model_ids if model_ids is not None else default_model_ids():
        if model_id in skipped:
            continue
        spec = find_model(model_id, REGISTRY)
        if spec is None:
            raise ValueError(f"Modelo fora do registro: {model_id}")
        for path in spec.paths:
            entries.setdefault(
                path,
                ManifestEntry(
                    f"{MODELS_DEST}/{path}",
                    f"{MODELS_DEST}/{path}",
                    "data",
                    "pasta",
                    f"{spec.name}: {spec.purpose}",
                ),
            )
    return list(entries.values())


def check_model_ids(model_ids: Iterable[str]) -> None:
    """Recusa um `--sem-modelo` que não é um modelo padrão do pacote: um erro de digitação não pode passar calado."""
    known = set(default_model_ids())
    for model_id in model_ids:
        if model_id not in known:
            raise ValueError(f"Modelo fora do pacote: {model_id}. Os do pacote: {', '.join(sorted(known))}")


def build_manifest(
    tracked_files: Iterable[str], platform: str = WINDOWS.id, excluded_models: Iterable[str] = ()
) -> list[ManifestEntry]:
    excluded = tuple(excluded_models)
    check_model_ids(excluded)
    entries = [*repo_entries(tracked_files), *binary_entries(platform), *model_entries(excluded=excluded)]
    for entry in entries:
        if not is_shippable(
            entry.dest.removeprefix(MODELS_DEST + "/") if entry.target == "data" else entry.dest
        ):
            raise ValueError(f"Entrada proibida no manifesto: {entry.dest}")
    return entries
