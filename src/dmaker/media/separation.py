"""Isolamento vocal: separa a voz do resto (música, ruído, ambiente) com o Demucs htdemucs (MIT, Meta).

O contrato é o protocolo `VocalSeparator`: recebe um WAV estéreo de 44,1 kHz e grava dois arquivos, a
voz (`vocals`) e a soma de todo o resto (`background`). O pipeline só conhece o protocolo; o Demucs, o
torch e o download dos pesos ficam dentro do `DemucsSeparator` e só carregam na primeira separação.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..config import MODELS_DIR
from .cpu import compute_threads
from .wavio import read_wav_channels, write_wav_channels

SAMPLE_RATE = 44100  # taxa em que o htdemucs foi treinado: outra taxa pioraria a separação
CHANNELS = 2
VOCALS = "vocals"
SILENCE_FLOOR = 1e-8  # evita dividir por zero ao normalizar um áudio mudo


VOCALS_FILE = "vocals.wav"
BACKGROUND_FILE = "background.wav"


@dataclass(frozen=True)
class Stems:
    """Os dois arquivos de uma separação: a voz e o fundo (tudo que não é voz)."""

    vocals: Path
    background: Path

    @classmethod
    def in_directory(cls, directory: Path) -> Stems:
        """Onde um separador grava os stems de uma separação (nomes fixos do contrato)."""
        return cls(directory / VOCALS_FILE, directory / BACKGROUND_FILE)

    def exist(self) -> bool:
        return self.vocals.exists() and self.background.exists()


ProgressCallback = Callable[[int, int], None]  # (blocos prontos, blocos no total)


class VocalSeparator(Protocol):
    model_id: str  # entra na chave do cache: outro modelo ou outros parâmetros não reaproveitam stems

    def separate(self, wav: Path, out_dir: Path, on_progress: ProgressCallback | None = None) -> Stems:
        """Separa `wav` (estéreo, 44,1 kHz) e grava `vocals.wav` e `background.wav` em `out_dir`
        (WAV estéreo de 44,1 kHz, 16 bits), devolvendo os dois caminhos."""


# ---------- contas puras ----------


def expected_chunks(
    samples: int, sample_rate: int, segment: float, overlap: float, shifts: int, models: int = 1
) -> int:
    """Quantos blocos o `apply_model` processa: janelas de `segment` s avançando `1 - overlap` por vez,
    repetidas a cada deslocamento (`shifts`) e a cada modelo do conjunto."""
    stride = int((1 - overlap) * int(sample_rate * segment))
    return math.ceil(samples / max(stride, 1)) * max(shifts, 1) * models


def normalize_mix(mix: np.ndarray) -> tuple[np.ndarray, float]:
    """Tira a média e escala pelo desvio padrão do áudio mono: o Demucs foi treinado com a mistura
    nessa escala, então uma gravação baixa ou alta não muda o resultado. Devolve a mistura normalizada
    e o desvio. A média (deslocamento DC, inaudível) não volta: somá-la a cada stem a repetiria no fundo,
    que é a soma de vários."""
    reference = mix.mean(axis=0)
    std = max(float(reference.std()), SILENCE_FLOOR)
    return (mix - float(reference.mean())) / std, std


def split_vocals(estimates: np.ndarray, names: list[str], std: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Desfaz a escala e devolve (voz, fundo), com o fundo igual à soma de todos os outros stems.
    `estimates` tem a forma (stems, canais, amostras)."""
    restored = estimates * std
    index = names.index(VOCALS)
    others = [stem for i, stem in enumerate(restored) if i != index]
    return restored[index], np.sum(others, axis=0)


# ---------- Demucs ----------


@contextmanager
def _hub_cache(directory: Path) -> Iterator[None]:
    """Faz o download dos pesos (Hugging Face, desde o Demucs 4.1) cair em `directory` e não em ~/.cache,
    só durante o carregamento."""
    from huggingface_hub import constants

    previous = constants.HF_HUB_CACHE
    directory.mkdir(parents=True, exist_ok=True)
    constants.HF_HUB_CACHE = str(directory)
    try:
        yield
    finally:
        constants.HF_HUB_CACHE = previous


def _model_segment(model: Any) -> float:
    """Duração (s) da janela de um modelo; num conjunto (`BagOfModels`) vale a do primeiro."""
    inner = model.models[0] if hasattr(model, "models") else model
    return float(inner.segment)


class DemucsSeparator:
    """Demucs htdemucs na CPU (ou na GPU, se houver), carregado uma única vez, na primeira separação.

    O `apply_model` já fatia o áudio em janelas de ~7,8 s com sobreposição, então o cálculo por vez é
    pequeno e constante; só o resultado acumula na memória (cerca de 5x o tamanho do áudio em float32).
    `shifts` e `overlap` trocam qualidade por tempo: `shifts=1` aplica um único deslocamento aleatório
    de até 0,5 s, o que custa o mesmo que não deslocar e evita que as emendas das janelas caiam no
    mesmo ponto; cada `shift` a mais multiplica o tempo e rende só ~0,2 dB de SDR. `overlap=0.25` é o
    padrão do Demucs; 0.1 poupa ~17% do tempo na CPU, mas deixa as emendas entre janelas audíveis.
    """

    def __init__(
        self,
        model: str = "htdemucs",
        device: str = "auto",
        shifts: int = 1,
        overlap: float = 0.25,
        segment: float | None = None,
        models_dir: Path = MODELS_DIR / "demucs",
        threads: int | None = None,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.model = model
        self.device = device
        self.shifts = shifts
        self.overlap = overlap
        self.segment = segment
        self.models_dir = models_dir
        self.threads = threads
        self.model_id = f"demucs:{model}:shifts{shifts}:overlap{overlap:g}" + (
            f":segment{segment:g}" if segment else ""
        )
        self._model_loader = model_loader or self._load_model
        self._model: Any = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()  # o modelo não é seguro para uso concorrente

    # -- carregamento --

    def _load_model(self) -> Any:
        try:
            import torch
            from demucs.pretrained import get_model
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "Demucs não instalado. Rode: .venv\\Scripts\\pip install torch torchaudio "
                "--index-url https://download.pytorch.org/whl/cpu e depois .venv\\Scripts\\pip install -e .[voice]"
            ) from exc

        torch.set_num_threads(self.threads or compute_threads())
        with _hub_cache(self.models_dir):
            model = get_model(self.model)
        return model.eval()

    def _loaded(self) -> Any:
        with self._load_lock:
            if self._model is None:
                self._model = self._model_loader()
            return self._model

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    # -- separação --

    def _estimate(self, model: Any, mix: np.ndarray, on_progress: ProgressCallback | None) -> np.ndarray:
        """Roda o modelo sobre a mistura (canais, amostras) e devolve os stems (stems, canais, amostras)."""
        import torch
        from demucs.apply import apply_model

        total = expected_chunks(
            mix.shape[1],
            int(model.samplerate),
            self.segment or _model_segment(model),
            self.overlap,
            self.shifts,
            len(model.models) if hasattr(model, "models") else 1,
        )
        finished = 0

        def on_chunk(info: dict) -> None:
            nonlocal finished
            if info.get("state") == "end" and on_progress:
                finished += 1
                on_progress(min(finished, total), total)

        if on_progress:
            on_progress(0, total)
        tensor = torch.from_numpy(np.ascontiguousarray(mix))[None]
        stems = apply_model(
            model,
            tensor,
            shifts=self.shifts,
            split=True,
            overlap=self.overlap,
            device=self._resolve_device(),
            segment=self.segment,
            callback=on_chunk,
        )
        return stems[0].cpu().numpy()

    def separate(self, wav: Path, out_dir: Path, on_progress: ProgressCallback | None = None) -> Stems:
        samples, sample_rate = read_wav_channels(wav)
        if sample_rate != SAMPLE_RATE or samples.shape[1] != CHANNELS:
            raise ValueError(
                f"{wav.name}: o isolamento vocal precisa de WAV estéreo de {SAMPLE_RATE} Hz "
                f"(recebi {samples.shape[1]} canal(is) a {sample_rate} Hz)"
            )
        model = self._loaded()
        normalized, std = normalize_mix(samples.T)
        with self._inference_lock:
            estimates = self._estimate(model, normalized, on_progress)
        vocals, background = split_vocals(estimates, list(model.sources), std)
        stems = Stems.in_directory(out_dir)
        write_wav_channels(stems.vocals, vocals.T, SAMPLE_RATE)
        write_wav_channels(stems.background, background.T, SAMPLE_RATE)
        return stems
