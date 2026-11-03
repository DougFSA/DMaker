"""Matting de pessoa para trocar o fundo sem chroma key (Robust Video Matting via ONNX Runtime).

O modelo é recorrente: cada quadro recebe o estado do anterior, por isso a máscara não treme como
nos segmentadores quadro a quadro. Este módulo produz quadros RGB já compostos sobre a cor de fundo
(`frames`, a troca de fundo) ou quadros RGBA só com a pessoa (`person_frames`, a camada que passa por cima
de um texto); quem codifica é o runner do ffmpeg (`filtergraph.mezzanine.matte_mezzanine` e
`filtergraph.person_layer`), como nas fotos com movimento. A entrada é decodificada pelo ffmpeg em rawvideo, o que
evita depender do OpenCV.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from .. import config
from .ffmpeg import ffmpeg_path

MATTE_VERSION = "k1"  # muda quando o modelo ou a composição mudam (invalida o cache)
RELEASE_URL = "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/"
# resnet50 (100 MB) separa melhor objetos encostados na pessoa; mobilenetv3 (15 MB) é 2,5x mais rápido
MODEL_FILES = {name: f"rvm_{name}_fp32.onnx" for name in ("resnet50", "mobilenetv3")}
DEFAULT_MODEL = "resnet50"
PREVIEW_MODEL = "mobilenetv3"  # no --preview o recorte da pessoa troca a borda fina por 2,5x de velocidade
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


@dataclass(frozen=True)
class PersonRequest:
    """Arquivo cuja pessoa vira camada: o vídeo todo, do início, com `warmup_frames` quadros de aquecimento no
    começo, que o modelo vê (para a memória dele já conhecer a cena) e a saída não traz."""

    src: Path
    length: float
    width: int
    height: int
    fps: float
    model: str = DEFAULT_MODEL
    downsample: float | None = None
    warmup_frames: int = 0


class Matter(Protocol):
    def frames(self, request: MatteRequest) -> Iterator[bytes]:
        """Quadros RGB24 (largura x altura do pedido), já compostos sobre a cor de fundo."""

    def person_frames(self, request: PersonRequest) -> Iterator[bytes]:
        """Quadros RGBA8 (largura x altura x 4) só com a pessoa, sem os quadros de aquecimento: a cor é a do
        primeiro plano que o modelo prevê e o alfa é o recorte, ambos sem composição (alfa direto)."""


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


# O RVM costuma deixar um pouco de alfa fora da pessoa (uma sombra fraca que apareceria como fantasma sobre as
# letras) e raramente chega a 100 % dentro dela (o texto vazaria de leve pela camisa e pelo rosto). Esta curva de
# níveis zera o ruído de baixo e fecha o de cima; a borda de verdade (cabelo, dedos), que fica no meio, só muda de
# inclinação. Sem desfoque e sem erosão: os dois comem os fios de cabelo que o modelo acertou.
ALPHA_FLOOR = 0.03
ALPHA_CEILING = 0.97


def refine_alpha(alpha: np.ndarray) -> np.ndarray:
    """Níveis do alfa (`ALPHA_FLOOR` vira 0 e `ALPHA_CEILING` vira 1), para a camada da pessoa não deixar rastro."""
    return np.clip((alpha - ALPHA_FLOOR) / (ALPHA_CEILING - ALPHA_FLOOR), 0.0, 1.0)


# Do alfa de 85 % para cima a cor passa do primeiro plano previsto para o pixel do vídeo. Dentro do corpo o primeiro
# plano do modelo difere do pixel por alguns níveis (medido num quadro, onde o alfa passa de 0,99: média de 0,4 e até
# 12 de 255), e o pixel do vídeo é exato e ali não há parede para contaminar a cor, então a pessoa por cima não altera
# o corpo; na borda, abaixo disso, só o primeiro plano vale, que é o que evita o halo.
INTERIOR_FROM = 0.85


def interior_weight(alpha: np.ndarray) -> np.ndarray:
    """Quanto da cor vem do pixel do vídeo (0 na borda, 1 dentro do corpo), com uma curva suave entre os dois."""
    t = np.clip((alpha - INTERIOR_FROM) / (1.0 - INTERIOR_FROM), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def person_rgba(foreground: np.ndarray, alpha: np.ndarray, source: np.ndarray) -> bytes:
    """Quadro RGBA8 da pessoa: `foreground` e `source` (o pixel do vídeo) em (3, H, W) e `alpha` em (1, H, W),
    tudo em 0..1, sem premultiplicar.

    Na borda a cor vem do primeiro plano que o modelo prevê, não dos pixels do vídeo: o pixel da borda do cabelo
    carrega a cor da parede, e é ela que apareceria como halo ao compor a pessoa sobre o texto. Dentro do corpo
    (`interior_weight`) vale o pixel do vídeo. Onde o alfa é zero a cor não vale nada, então recebe uma cor única
    (a média da pessoa no quadro): o arquivo comprime muito mais e a subamostragem de croma da junção com o fundo
    não puxa a borda para o preto."""
    alpha = refine_alpha(alpha)
    inside = interior_weight(alpha)
    person = foreground * (1.0 - inside) + source * inside
    weight = float(alpha.sum())
    fill = (person * alpha).sum(axis=(1, 2)) / weight if weight > 0 else np.zeros(3, np.float32)
    color = np.where(alpha > 0, person, fill.reshape(3, 1, 1).astype(np.float32))
    frame = np.empty((*alpha.shape[1:], 4), np.uint8)
    frame[..., :3] = np.clip(color * 255.0 + 0.5, 0, 255).astype(np.uint8).transpose(1, 2, 0)
    frame[..., 3] = np.clip(alpha[0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return frame.tobytes()


def model_path(model: str = DEFAULT_MODEL, models_dir: Path | None = None) -> Path:
    return (models_dir or config.MODELS_DIR) / MODEL_FILES[model]


def ensure_model(model: str = DEFAULT_MODEL, models_dir: Path | None = None) -> Path:
    """Baixa o modelo na primeira vez, como acontece com o Whisper. `models_dir` deixa o gerenciador
    de modelos apontar para a pasta de cache que ele mede, em vez da padrão."""
    path = model_path(model, models_dir)
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

    def _decoder(self, src: Path, start: float, length: float, fps: float) -> subprocess.Popen:
        # `-ss` antes da entrada busca pelo keyframe (rápido) e o decodificador refina até o instante
        # exato; `fps` fixa a cadência para o número de quadros bater com o codificador (CFR).
        cmd = [
            str(ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{max(start, 0):.3f}",
            "-i",
            str(src),
            "-t",
            f"{length:.3f}",
            "-vf",
            f"fps={fps:g}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-an",
            "pipe:1",
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def _predictions(
        self,
        src: Path,
        start: float,
        length: float,
        width: int,
        height: int,
        fps: float,
        model: str,
        downsample: float | None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Primeiro plano (3, H, W), alfa (1, H, W) e o próprio quadro (3, H, W) de cada passo, em 0..1, com o
        estado recorrente passando de um quadro ao seguinte."""
        session = self._session(model)
        ratio = np.array([downsample or downsample_ratio_for(width, height)], np.float32)
        recurrent = [np.zeros((1, 1, 1, 1), np.float32)] * 4  # estado inicial vazio, como no exemplo oficial
        frame_bytes = width * height * 3
        decoder = self._decoder(src, start, length, fps)
        assert decoder.stdout is not None
        try:
            while True:
                raw = decoder.stdout.read(frame_bytes)
                if len(raw) < frame_bytes:
                    break
                image = np.frombuffer(raw, np.uint8).reshape(height, width, 3)
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
                yield foreground[0], alpha[0], source[0]
        finally:
            decoder.stdout.close()
            decoder.wait()

    def frames(self, request: MatteRequest) -> Iterator[bytes]:
        predictions = self._predictions(
            request.src,
            request.start,
            request.length,
            request.width,
            request.height,
            request.fps,
            request.model,
            request.downsample,
        )
        for foreground, alpha, _ in predictions:
            yield composite(foreground, alpha, request.background)

    def person_frames(self, request: PersonRequest) -> Iterator[bytes]:
        predictions = self._predictions(
            request.src,
            0.0,
            request.length,
            request.width,
            request.height,
            request.fps,
            request.model,
            request.downsample,
        )
        for index, (foreground, alpha, source) in enumerate(predictions):
            if index >= request.warmup_frames:  # o aquecimento só alimenta a memória do modelo
                yield person_rgba(foreground, alpha, source)
