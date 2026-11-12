"""Os arquivos do motor da persona realista (ditto-talkinghead): de onde vêm, onde ficam e se estão todos lá.

Dado puro e contas de caminho, sem importar torch, onnxruntime nem openvino: o registro de modelos e o `doctor` só
precisam saber quais são os arquivos. Os pesos são Apache-2.0 e baixam do Hugging Face numa revisão fixa, conferidos
por tamanho e SHA-256 (`media/downloads.py`).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .downloads import Downloader, RemoteFile

MODEL_ID = "persona-realista"  # o id no registro de modelos (`dmaker models`)
MODEL_FOLDER = "persona-realista"  # dentro de `cache/models`
REPO = "digital-avatar/ditto-talkinghead"
REVISION = "e4a2f60328ee7c32af585ac4b3cce299e4c8e254"  # fixa: o que foi medido e conferido
BASE_URL = f"https://huggingface.co/{REPO}/resolve/{REVISION}"

ONNX_FOLDER = "ditto_onnx"
TORCH_FOLDER = "ditto_pytorch/models"
OPENVINO_FOLDER = "openvino"  # o IR do warp, gerado aqui a partir do warp_network.pth


@dataclass(frozen=True)
class ModelFile:
    folder: str  # subpasta dentro de `persona-realista`
    remote: RemoteFile

    @property
    def relative(self) -> str:
        """O caminho dentro de `cache/models`, com barras normais (o formato do registro de modelos)."""
        return f"{MODEL_FOLDER}/{self.folder}/{self.remote.name}"


def _file(folder: str, name: str, size: int, sha256: str) -> ModelFile:
    return ModelFile(folder, RemoteFile(name, f"{BASE_URL}/{folder}/{name}", size, sha256))


FILES: tuple[ModelFile, ...] = (
    _file(
        ONNX_FOLDER,
        "hubert.onnx",
        1_458_714_493,
        "327a5b90c0bfb9df251c9af91d0bea5e6284dbb0a4d02814f1d3ace6b4c2b5aa",
    ),
    _file(
        ONNX_FOLDER,
        "lmdm_v0.4_hubert.onnx",
        192_453_963,
        "ea6664518746a1c2e13db496ffe97216da715742be83e069a02cc86873c6dcfc",
    ),
    _file(
        ONNX_FOLDER,
        "decoder.onnx",
        221_530_139,
        "94fca15fe5b67885edebfacbcadcac29e79238ac0d9ffbf0d688391cefb890be",
    ),
    _file(
        ONNX_FOLDER,
        "motion_extractor.onnx",
        112_610_626,
        "91bd0c05e9fa2cb4918d32cfe547db1d3f3fbbf79713ffbe207670f422e069a1",
    ),
    _file(
        ONNX_FOLDER,
        "landmark203.onnx",
        114_678_967,
        "babb139e95a783f0df5d296fc069badc4c7fcdacca0d202b21bcd409dfd2f556",
    ),
    _file(
        ONNX_FOLDER,
        "appearance_extractor.onnx",
        3_355_896,
        "9f5823888fc155209d69cf5b3ad69502c553eaa500d28f07fd39a340bc5b7eb6",
    ),
    _file(
        ONNX_FOLDER,
        "stitch_network.onnx",
        185_542,
        "d3629a08268f1125d60c194e6dbd495126424e8de1112f2fc368170660dde043",
    ),
    _file(
        ONNX_FOLDER,
        "face_mesh.onnx",
        4_958_394,
        "bbbb49fac007b7cde79b478c680d171969f23f53ae6cdaf6a3b4264fa18c8479",
    ),
    _file(
        ONNX_FOLDER,
        "blaze_face.onnx",
        418_456,
        "9b217128f6b66f7e11dc3673c22be250d72f68f507430817d0754ef1451eb609",
    ),
    _file(
        TORCH_FOLDER,
        "warp_network.pth",
        182_180_086,
        "2f61a6f265fe344f14132364859a78bdbbc2068577170693da57fb96d636e282",
    ),
)

EXPECTED_SIZE = sum(item.remote.size for item in FILES)


@dataclass(frozen=True)
class DittoPaths:
    """Onde cada peça do motor está, a partir da pasta `persona-realista` (a conta é pura: não confere o disco)."""

    root: Path

    def onnx(self, name: str) -> Path:
        return self.root / ONNX_FOLDER / name

    @property
    def warp_weights(self) -> Path:
        return self.root / TORCH_FOLDER / "warp_network.pth"

    @property
    def warp_head_ir(self) -> Path:
        return self.root / OPENVINO_FOLDER / "warp_head.xml"

    @property
    def warp_tail_ir(self) -> Path:
        return self.root / OPENVINO_FOLDER / "warp_tail.xml"

    @property
    def face_detector(self) -> Path:
        return self.onnx("blaze_face.onnx")

    def missing_files(self) -> list[str]:
        """Os arquivos do registro que não estão no disco (nomes relativos, para a mensagem ao usuário)."""
        return [item.relative for item in FILES if not (self.root / item.folder / item.remote.name).is_file()]

    def has_warp_ir(self) -> bool:
        return self.warp_head_ir.is_file() and self.warp_tail_ir.is_file()


def paths_in(models_dir: Path) -> DittoPaths:
    return DittoPaths(models_dir / MODEL_FOLDER)


def mirror_downloader(source_root: Path) -> Downloader:
    """Um `Downloader` que copia de uma pasta local com a mesma estrutura do repositório (`ditto_onnx/...`), no
    lugar de baixar: serve a testes e a instalar sem internet. O `ensure_file` confere tamanho e SHA-256 do mesmo
    jeito, então uma cópia errada é recusada como um download corrompido."""

    def copy(url: str, destination: Path) -> None:
        relative = url.removeprefix(BASE_URL + "/")
        shutil.copyfile(source_root / relative, destination)

    return copy
