"""Trilhas separadas da dublagem: onde ficam, o que contêm e o .zip para levar a outro editor.

Só a parte de arquivos e nomes; quem sintetiza as falas e roda o ffmpeg é o `DubbingService`.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..filtergraph.dub_stems import StemOutputs

STEMS_SUFFIX = ".trilhas"
VOICE_DUBBED_NAME = "voz-dublada.wav"
BACKGROUND_NAME = "fundo.wav"
VOICE_ORIGINAL_NAME = "voz-original.wav"


@dataclass(frozen=True)
class StemsOptions:
    """Como exportar as trilhas: a pasta (padrão: ao lado da dublagem) e se também vai um .zip."""

    out_dir: Path | None = None
    make_zip: bool = False


@dataclass(frozen=True)
class DubStems:
    folder: Path
    outputs: StemOutputs
    duration: float  # segundos, a mesma do vídeo original
    original_voice_db: (
        float | None
    )  # o quanto o vídeo dublado atenua a voz original; a trilha sai sem atenuar
    zip_path: Path | None = None

    @property
    def files(self) -> list[Path]:
        return [self.outputs.voice_dubbed, self.outputs.background, self.outputs.voice_original]


def stem_outputs(folder: Path) -> StemOutputs:
    return StemOutputs(folder / VOICE_DUBBED_NAME, folder / BACKGROUND_NAME, folder / VOICE_ORIGINAL_NAME)


def zip_path_for(folder: Path) -> Path:
    """O .zip fica ao lado da pasta e leva o mesmo nome."""
    return folder.parent / f"{folder.name}.zip"


def zip_stems(stems: DubStems) -> Path:
    """Junta as três trilhas num .zip. Nível 1: o áudio quase não comprime, e a voz dublada, cheia de
    silêncio, comprime bem mesmo assim; mais que isso só gasta tempo."""
    target = zip_path_for(stems.folder)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in stems.files:
            archive.write(path, arcname=path.name)
    return target
