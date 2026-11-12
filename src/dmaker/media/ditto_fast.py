"""O caminho rápido do ditto: o warp e o decoder no OpenVINO (GPU integrada Intel quando há), o resto como o original.

O ditto original roda tudo em ONNX Runtime ou TensorRT (placa NVIDIA). Numa máquina sem placa, o warp e o decoder
são o que mais pesa por quadro, e o OpenVINO os leva para o vídeo integrado Iris Xe (medido: 4,3 s por quadro em
regime, contra mais de 20 na CPU). O warp tem uma parte que o OpenVINO não faz bem (`grid_sample` em 5D) e que fica
em torch na CPU; as convoluções antes e depois dela vão para o OpenVINO. Por isso o `warp_network.pth` é lido também
na hora de desenhar, e não só para gerar o IR.

Os imports pesados (torch, openvino) ficam dentro das funções: só o processo que desenha precisa deles.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .ditto_models import DittoPaths

Log = Callable[[str], None]

TORCH_THREADS = (
    4  # medido: mais threads de torch disputam a CPU com o ONNX Runtime (hubert, lmdm) e atrasam o conjunto
)
WARP_HEAD_INPUT = (
    1,
    110,
    16,
    64,
    64,
)  # características já deformadas e o mapa de calor, como o warp as monta
WARP_TAIL_INPUT = ((1, 512, 64, 64), (1, 1, 64, 64))  # características deformadas e mapa de oclusão


@dataclass(frozen=True)
class Accelerator:
    """Onde o OpenVINO calcula e com que precisão."""

    device: str  # "GPU" ou "CPU"
    precision: str  # "f16" ou "f32"

    @property
    def describe(self) -> str:
        where = "GPU integrada" if self.device == "GPU" else "CPU"
        return f"{where} ({self.precision})"


def choose_accelerator(available_devices: list[str]) -> Accelerator:
    """GPU em f16 quando o OpenVINO enxerga uma (metade da memória e das contas, e a qualidade medida é a mesma);
    sem ela, CPU em f32, que é a precisão em que o modelo foi treinado e a CPU não ganha nada com f16."""
    if "GPU" in available_devices:
        return Accelerator("GPU", "f16")
    return Accelerator("CPU", "f32")


def detect_accelerator() -> Accelerator:
    import openvino as ov

    return choose_accelerator(list(ov.Core().available_devices))


def compile_options(accelerator: Accelerator, cache_dir: Path) -> dict[str, str]:
    """As opções de compilação do OpenVINO, cada uma com a razão dela."""
    return {
        # Os quadros vêm um de cada vez, em sequência: LATENCY minimiza o tempo de cada inferência, o que importa
        # aqui; THROUGHPUT abriria vários fluxos para um volume de pedidos que não existe.
        "PERFORMANCE_HINT": "LATENCY",
        # Compilar os kernels da GPU custa minutos; com o cache em disco a segunda execução só os carrega.
        "CACHE_DIR": str(cache_dir),
        # Dita a precisão das contas: f16 na GPU (metade da banda de memória, que é o limite do vídeo integrado) e
        # f32 na CPU. Sem a dica, a CPU poderia escolher bf16 sozinha e mudar a imagem de uma máquina para outra.
        "INFERENCE_PRECISION_HINT": accelerator.precision,
    }


def compile_model(core: Any, model: Any, accelerator: Accelerator, cache_dir: Path) -> Any:
    return core.compile_model(model, accelerator.device, compile_options(accelerator, cache_dir))


def _head_and_tail_modules(warp: Any) -> tuple[Any, Any]:
    """A cabeça (hourglass, máscara e oclusão) e a cauda (as duas últimas convoluções) do warp, como módulos torch
    que a conversão para IR enxerga. O que fica entre as duas (`grid_sample` 5D) não é convertido."""
    import torch
    import torch.nn.functional as functional

    dense_motion = warp.dense_motion_network

    class Head(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.hourglass, self.mask, self.occlusion = (
                dense_motion.hourglass,
                dense_motion.mask,
                dense_motion.occlusion,
            )

        def forward(self, x: Any) -> Any:
            hidden = self.hourglass(x)
            mask = functional.softmax(self.mask(hidden), dim=1)
            occlusion = torch.sigmoid(self.occlusion(hidden.reshape(1, -1, 64, 64)))
            return mask, occlusion

    class Tail(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.third, self.fourth = warp.third, warp.fourth

        def forward(self, x: Any, occlusion: Any) -> Any:
            return self.fourth(self.third(x)) * occlusion

    return Head().eval(), Tail().eval()


def load_warp_network(weights: Path) -> Any:
    from ..vendor.ditto.models.modules.warping_network import WarpingNetwork

    network = WarpingNetwork()
    network.load_model(str(weights))
    return network.eval()


def build_warp_ir(paths: DittoPaths, warp: Any | None = None) -> None:
    """Converte a cabeça e a cauda do warp para IR do OpenVINO ao lado dos pesos. Em f32: a conversão para f16 é
    feita pelo próprio OpenVINO ao compilar para a GPU, e guardar f32 deixa o mesmo IR servir à CPU."""
    import openvino as ov
    import torch

    network = warp if warp is not None else load_warp_network(paths.warp_weights)
    head, tail = _head_and_tail_modules(network)
    paths.warp_head_ir.parent.mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        converted_head = ov.convert_model(head, example_input=torch.zeros(*WARP_HEAD_INPUT))
        converted_tail = ov.convert_model(
            tail, example_input=(torch.zeros(*WARP_TAIL_INPUT[0]), torch.zeros(*WARP_TAIL_INPUT[1]))
        )
    ov.save_model(converted_head, str(paths.warp_head_ir), compress_to_fp16=False)
    ov.save_model(converted_tail, str(paths.warp_tail_ir), compress_to_fp16=False)


class HybridWarp:
    """O warp do ditto: torch na CPU para o que o OpenVINO não faz, OpenVINO para as convoluções."""

    def __init__(self, paths: DittoPaths, accelerator: Accelerator, cache_dir: Path, log: Log | None = None):
        import openvino as ov
        import torch

        torch.set_num_threads(TORCH_THREADS)
        self._torch = torch
        self.network = load_warp_network(paths.warp_weights)
        if not paths.has_warp_ir():
            if log:
                log(
                    "IR do warp não encontrado: gerando agora (leva alguns segundos; `dmaker models download "
                    "persona-realista` deixa pronto)"
                )
            build_warp_ir(paths, self.network)
        core = ov.Core()
        self.head = compile_model(core, core.read_model(str(paths.warp_head_ir)), accelerator, cache_dir)
        self.tail = compile_model(core, core.read_model(str(paths.warp_tail_ir)), accelerator, cache_dir)
        self._source_key: bytes | None = None
        self._source_gaussian: Any = None

    def warm_up(self) -> None:
        """A primeira inferência na GPU compila os kernels (minutos sem cache): paga-se aqui, no preparo, e não no
        primeiro quadro, para o tempo por quadro medido ser o de regime."""
        features = np.zeros((1, 32, 16, 64, 64), np.float32)
        keypoints = np.zeros((1, 21, 3), np.float32) + 0.1
        for _ in range(2):
            self(features, keypoints, keypoints + 0.01)

    def __call__(self, feature_3d: np.ndarray, kp_source: np.ndarray, kp_driving: np.ndarray) -> np.ndarray:
        from ..vendor.ditto.models.modules.util import kp2gaussian

        torch = self._torch
        dense_motion = self.network.dense_motion_network
        with torch.inference_mode():
            features = torch.from_numpy(feature_3d)
            source = torch.from_numpy(kp_source)
            driving = torch.from_numpy(kp_driving)
            batch, _, depth, height, width = features.shape
            compressed = torch.nn.functional.relu(dense_motion.norm(dense_motion.compress(features)))
            sparse_motions = dense_motion.create_sparse_motions(compressed, driving, source)
            deformed = dense_motion.create_deformed_feature(compressed, sparse_motions)
            key = kp_source.tobytes()
            if self._source_key != key:  # a gaussiana da foto é fixa: calcula-se uma vez
                self._source_key = key
                self._source_gaussian = kp2gaussian(source, spatial_size=deformed.shape[3:], kp_variance=0.01)
            driving_gaussian = kp2gaussian(driving, spatial_size=deformed.shape[3:], kp_variance=0.01)
            heat = torch.cat(
                [torch.zeros(1, 1, *driving_gaussian.shape[2:]), driving_gaussian - self._source_gaussian],
                dim=1,
            ).unsqueeze(2)
            head_input = (
                torch.cat([heat, deformed], dim=2).reshape(batch, -1, depth, height, width).contiguous()
            )
            head_output = self.head({0: head_input.numpy()})
            mask, occlusion = torch.from_numpy(head_output[0]), torch.from_numpy(head_output[1])
            sparse = sparse_motions.permute(0, 1, 5, 2, 3, 4)
            deformation = (sparse * mask.unsqueeze(2)).sum(1).permute(0, 2, 3, 4, 1)
            warped = self.network.deform_input(features, deformation).reshape(batch, -1, height, width)
            warped = warped.contiguous()
            return self.tail({0: warped.numpy(), 1: occlusion.numpy()})[0]


class OpenVinoDecoder:
    """O decoder (SPADE) do ditto no OpenVINO: características 3D já deformadas em imagem 512 x 512."""

    def __init__(self, decoder_onnx: Path, accelerator: Accelerator, cache_dir: Path):
        import openvino as ov

        core = ov.Core()
        self.compiled = compile_model(core, core.read_model(str(decoder_onnx)), accelerator, cache_dir)

    def warm_up(self) -> None:
        self(np.zeros((1, 256, 64, 64), np.float32))

    def __call__(self, feature: np.ndarray) -> np.ndarray:
        return self.compiled({0: feature})[0]
