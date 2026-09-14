"""Matting de pessoa para trocar o fundo sem chroma key (Robust Video Matting via ONNX Runtime).

O modelo é recorrente: cada quadro recebe o estado do anterior, por isso a máscara não treme como
nos segmentadores quadro a quadro. Este módulo só produz quadros RGB já compostos sobre a cor de
fundo; quem codifica é o runner do ffmpeg (`filtergraph.mezzanine.matte_mezzanine`), como nas fotos
com movimento. A entrada é decodificada pelo ffmpeg em rawvideo, o que evita depender do OpenCV.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..config import MODELS_DIR
from .ffmpeg import ffmpeg_path

MATTE_VERSION = "k1"  # muda quando o modelo ou a composição mudam (invalida o cache)
RELEASE_URL = "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/"
# resnet50 (100 MB) separa melhor objetos encostados na pessoa; mobilenetv3 (15 MB) é 2,5x mais rápido
MODEL_FILES = {name: f"rvm_{name}_fp32.onnx" for name in ("resnet50", "mobilenetv3")}
DEFAULT_MODEL = "resnet50"
# O modelo foi treinado para ver a pessoa em ~512 px no lado maior: abaixo disso perde cabelo,
# acima só fica mais lento sem ganhar borda.
MODEL_WORKING_SIDE = 512


@dataclass(frozen=True)
class MatteRequest:
    """Trecho de um arquivo a recortar: tempos no arquivo, tamanho decodificado e cor de fundo."""

    src: Path
    start: float
    length: float
    width: int
    height: int
    fps: float
    background: tuple[int, int, int]
    model: str = DEFAULT_MODEL
    downsample: float | None = None


class Matter(Protocol):
    def frames(self, request: MatteRequest) -> Iterator[bytes]:
        """Quadros RGB24 (largura x altura do pedido), já compostos sobre a cor de fundo."""


def downsample_ratio_for(width: int, height: int) -> float:
    """Fator de redução interno do modelo para a pessoa ficar com ~512 px (0.25 em 1080p, 1 em 480p)."""
    return min(1.0, MODEL_WORKING_SIDE / max(width, height))


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def tone_of(background: tuple[int, int, int]) -> str:
    """`light` ou `dark` pela luminância percebida (Rec. 601), para textos e legendas se adaptarem ao fundo."""
    r, g, b = background
    return "light" if (0.299 * r + 0.587 * g + 0.114 * b) / 255 >= 0.5 else "dark"


def composite(foreground: np.ndarray, alpha: np.ndarray, background: tuple[int, int, int]) -> bytes:
    """Composição linear `fgr * a + cor * (1 - a)`; `foreground` é (3, H, W) e `alpha` (1, H, W), em 0..1."""
    color = np.asarray(background, dtype=np.float32).reshape(3, 1, 1) / 255.0
    mixed = foreground * alpha + color * (1.0 - alpha)
    frame = np.clip(mixed * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return frame.transpose(1, 2, 0).tobytes()


def model_path(model: str = DEFAULT_MODEL) -> Path:
    return MODELS_DIR / MODEL_FILES[model]


def ensure_model(model: str = DEFAULT_MODEL) -> Path:
    """Baixa o modelo na primeira vez, como acontece com o Whisper."""
    path = model_path(model)
    if path.exists():
        return path
    from ..setup_tools import download

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    download(RELEASE_URL + path.name, partial, path.name)
    partial.replace(path)
    return path


class RvmMatter:
    """Executa o RVM na CPU sobre os quadros decodificados pelo ffmpeg."""

    def _session(self, model: str):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 3  # só erros: o runtime é falante em nível warning
        return ort.InferenceSession(str(ensure_model(model)), options, providers=["CPUExecutionProvider"])

    def _decoder(self, request: MatteRequest) -> subprocess.Popen:
        # `-ss` antes da entrada busca pelo keyframe (rápido) e o decodificador refina até o instante
        # exato; `fps` fixa a cadência para o número de quadros bater com o codificador (CFR).
        cmd = [
            str(ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{max(request.start, 0):.3f}",
            "-i",
            str(request.src),
            "-t",
            f"{request.length:.3f}",
            "-vf",
            f"fps={request.fps:g}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-an",
            "pipe:1",
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def frames(self, request: MatteRequest) -> Iterator[bytes]:
        session = self._session(request.model)
        ratio = np.array(
            [request.downsample or downsample_ratio_for(request.width, request.height)], np.float32
        )
        recurrent = [np.zeros((1, 1, 1, 1), np.float32)] * 4  # estado inicial vazio, como no exemplo oficial
        frame_bytes = request.width * request.height * 3
        decoder = self._decoder(request)
        assert decoder.stdout is not None
        try:
            while True:
                raw = decoder.stdout.read(frame_bytes)
                if len(raw) < frame_bytes:
                    break
                image = np.frombuffer(raw, np.uint8).reshape(request.height, request.width, 3)
                source = image.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
                foreground, alpha, *recurrent = session.run(
                    None,
                    {
                        "src": source,
                        "r1i": recurrent[0],
                        "r2i": recurrent[1],
                        "r3i": recurrent[2],
                        "r4i": recurrent[3],
                        "downsample_ratio": ratio,
                    },
                )
                yield composite(foreground[0], alpha[0], request.background)
        finally:
            decoder.stdout.close()
            decoder.wait()
