"""Marca d'água inaudível na fala sintetizada, para provar que o áudio é voz gerada por IA.

O contrato é o protocolo `Watermarker`: `embed` devolve a fala com a marca e `detect` diz se um áudio a
carrega. O pipeline só conhece o protocolo; a AudioSeal (Meta, MIT, código e pesos), o torch e o download
dos pesos ficam dentro do `AudioSealWatermarker` e só carregam na primeira marca ou verificação.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .. import config
from ..media.cpu import compute_threads

logger = logging.getLogger("dmaker.voice.watermark")

WATERMARK_ENV = (
    "DMAKER_WATERMARK"  # "0", "false", "no" ou "off" desligam a marca; qualquer outro valor mantém
)
_OFF_VALUES = {"0", "false", "no", "off", "nao", "não"}

MODEL_RATE = 16000  # taxa em que a AudioSeal foi treinada; as outras taxas passam por reamostragem
# A memória de ativação da rede cresce com o tamanho da entrada; blocos de 30 s mantêm cada passada em
# dezenas de MB. A mensagem se repete ao longo do áudio, então marcar e detectar por bloco é equivalente.
CHUNK_SECONDS = 30
# Ganho da marca (alpha da AudioSeal). Com 1.0 a marca fica em -25 dB da energia da fala, audível em
# trechos calmos; 0.45 a deixa abaixo de -30 dB em todas as falas medidas (Kokoro, 1 a 16 s) e ainda
# sobrevive ao AAC 192k. Abaixo de 0.3 a detecção cai a zero.
EMBED_STRENGTH = 0.45
# Probabilidade = fração dos quadros do áudio em que a rede vê a marca. Com o ganho acima, uma fala marcada
# e exportada em AAC 192k fica entre 0.3 e 1.0; fala sem marca, ruído, tom e música ficam abaixo de 0.01.
# O limiar fica nesse vão, longe dos dois lados.
DETECTION_THRESHOLD = 0.2
# Mensagem de 16 bits gravada na marca: "DM" em ASCII (0x44 0x4D). Serve de assinatura do DMaker.
MESSAGE_BITS = (0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 1)
# Entra na chave do cache de falas: mudou a mensagem ou o ganho, incremente o número final.
EMBED_IDENTITY = "audioseal-16bits:dm1"

GENERATOR_CARD = "audioseal_wm_16bits"
DETECTOR_CARD = "audioseal_detector_16bits"


@dataclass(frozen=True)
class WatermarkResult:
    """Veredito de uma verificação: probabilidade de o áudio carregar a marca e se passou do limiar."""

    probability: float
    detected: bool


class Watermarker(Protocol):
    identity: (
        str  # entra na chave do cache de falas; vazio quando não marca (as falas antigas continuam valendo)
    )

    def embed(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """Fala mono float32 com a marca, do mesmo tamanho e na mesma taxa."""

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        """Probabilidade de `samples` carregar a marca."""


# ---------- contas puras ----------


def watermark_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """A marca vale por padrão; `DMAKER_WATERMARK=0` a desliga."""
    value = (environ if environ is not None else os.environ).get(WATERMARK_ENV, "")
    return value.strip().lower() not in _OFF_VALUES


def chunk_bounds(total: int, step: int, min_tail: int) -> list[tuple[int, int]]:
    """Intervalos de até `step` amostras que cobrem `total`; uma cauda menor que `min_tail` é incorporada
    ao bloco anterior, porque a rede marca e detecta mal trechos muito curtos."""
    if total <= 0:
        return []
    starts = list(range(0, total, step))
    if len(starts) > 1 and total - starts[-1] < min_tail:
        starts.pop()
    ends = [*starts[1:], total]
    return list(zip(starts, ends, strict=True))


# ---------- implementações sem modelo ----------


class NullWatermarker:
    """Não marca nada e nunca detecta: é o que vale com a marca desligada ou sem a biblioteca."""

    identity = ""

    def embed(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        return samples

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        return WatermarkResult(0.0, False)


# ---------- AudioSeal ----------


@contextmanager
def _model_cache(models_dir: Path) -> Iterator[None]:
    """Faz o download dos pesos cair em `models_dir/audioseal` (e não em ~/.cache) só durante o carregamento.

    A AudioSeal lê `AUDIOSEAL_CACHE_DIR` (e cria a subpasta "audioseal" nele) e baixa pelo Hugging Face,
    então redireciona-se os dois.
    """
    from huggingface_hub import constants

    directory = models_dir / "audioseal"
    directory.mkdir(parents=True, exist_ok=True)
    previous_hub = constants.HF_HUB_CACHE
    previous_env = os.environ.get("AUDIOSEAL_CACHE_DIR")
    constants.HF_HUB_CACHE = str(directory)
    os.environ["AUDIOSEAL_CACHE_DIR"] = str(models_dir)
    try:
        yield
    finally:
        constants.HF_HUB_CACHE = previous_hub
        if previous_env is None:
            os.environ.pop("AUDIOSEAL_CACHE_DIR", None)
        else:
            os.environ["AUDIOSEAL_CACHE_DIR"] = previous_env


@contextmanager
def _eager_model() -> Iterator[None]:
    """Roda a rede sem `torch.compile`: a AudioSeal compila o codificador na primeira passada, o que custa
    segundos e falha em máquinas sem compilador C++, deixando a fala sem marca."""
    try:
        from audioseal.libs.moshi.utils.compile import no_compile
    except ImportError:  # versão futura sem o atalho: segue sem ele
        no_compile = contextlib.nullcontext
    with no_compile():
        yield


def _resample(samples: Any, source: int, target: int) -> Any:
    if source == target:
        return samples
    from torchaudio.functional import resample

    return resample(samples, source, target)


class AudioSealWatermarker:
    """AudioSeal na CPU, carregada uma única vez. O gerador e o detector são independentes: só o que for
    usado é carregado (um `voice verify` não paga o gerador)."""

    identity = EMBED_IDENTITY

    def __init__(
        self,
        models_dir: Path | None = None,
        threads: int | None = None,
        threshold: float = DETECTION_THRESHOLD,
        strength: float = EMBED_STRENGTH,
    ) -> None:
        self.models_dir = models_dir
        self.threads = threads
        self.threshold = threshold
        self.strength = strength
        self._generator: Any = None
        self._detector: Any = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()  # a rede guarda estado entre chamadas: uma por vez

    # -- carregamento --

    def _load(self, card: str, loader_name: str) -> Any:
        import torch
        from audioseal import AudioSeal

        torch.set_num_threads(self.threads or compute_threads())
        with _model_cache((self.models_dir or config.MODELS_DIR).resolve()):
            model = getattr(AudioSeal, loader_name)(card)
        return model.eval()

    def _loaded_generator(self) -> Any:
        with self._load_lock:
            if self._generator is None:
                self._generator = self._load(GENERATOR_CARD, "load_generator")
            return self._generator

    def _loaded_detector(self) -> Any:
        with self._load_lock:
            if self._detector is None:
                self._detector = self._load(DETECTOR_CARD, "load_detector")
            return self._detector

    # -- marcar --

    def _embed_chunk(self, generator: Any, chunk: Any, sample_rate: int, message: Any) -> Any:
        """Marca um bloco na taxa do modelo e devolve só o resíduo da marca na taxa original: assim as
        frequências altas da fala, acima do que a rede enxerga, ficam intactas."""
        model_input = _resample(chunk, sample_rate, MODEL_RATE)
        marked = generator(model_input, sample_rate=MODEL_RATE, message=message, alpha=self.strength)
        if sample_rate == MODEL_RATE:
            return marked
        import torch

        residue = _resample(marked - model_input, MODEL_RATE, sample_rate)
        residue = torch.nn.functional.pad(residue, (0, max(0, chunk.shape[-1] - residue.shape[-1])))
        return chunk + residue[..., : chunk.shape[-1]]

    def embed(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        import torch

        if len(samples) == 0:
            return samples
        generator = self._loaded_generator()
        message = torch.tensor([MESSAGE_BITS], dtype=torch.int32)
        audio = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))[None, None]
        bounds = chunk_bounds(audio.shape[-1], CHUNK_SECONDS * sample_rate, sample_rate)
        with self._inference_lock, torch.no_grad(), _eager_model():
            pieces = [self._embed_chunk(generator, audio[..., a:b], sample_rate, message) for a, b in bounds]
        return torch.cat(pieces, dim=-1)[0, 0].numpy().astype(np.float32)

    # -- verificar --

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        """Melhor bloco do áudio: uma emenda em que só parte é voz sintética ainda aparece, o que a média
        do arquivo inteiro diluiria."""
        import torch

        if len(samples) == 0:
            return WatermarkResult(0.0, False)
        detector = self._loaded_detector()
        audio = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))[None, None]
        bounds = chunk_bounds(audio.shape[-1], CHUNK_SECONDS * sample_rate, sample_rate)
        best = 0.0
        with self._inference_lock, torch.no_grad(), _eager_model():
            for start, end in bounds:
                model_input = _resample(audio[..., start:end], sample_rate, MODEL_RATE)
                probability, _message = detector.detect_watermark(model_input, sample_rate=MODEL_RATE)
                best = max(best, float(probability.mean()))
        return WatermarkResult(round(best, 4), best >= self.threshold)


# ---------- escolha do marcador ----------

_missing_library_warned = False


def audioseal_installed() -> bool:
    return find_spec("audioseal") is not None


def default_watermarker(
    enabled: bool = True, environ: Mapping[str, str] | None = None, installed: bool | None = None
) -> Watermarker:
    """A AudioSeal quando a marca está ligada (`enabled` e `DMAKER_WATERMARK`) e a biblioteca existe; senão
    o `NullWatermarker`, avisando uma vez por processo quando é a biblioteca que falta."""
    global _missing_library_warned
    if not enabled or not watermark_enabled(environ):
        return NullWatermarker()
    if not (audioseal_installed() if installed is None else installed):
        if not _missing_library_warned:
            _missing_library_warned = True
            logger.warning(
                "A biblioteca audioseal não está instalada: as falas saem SEM marca d'água. "
                "Instale com .venv\\Scripts\\pip install -e .[voice]."
            )
        return NullWatermarker()
    return AudioSealWatermarker()
