"""Conversor de timbre OpenVoice V2 (MyShell.ai, MIT no código e nos pesos), local e na CPU.

O modelo codifica a fala da fonte num espaço sem timbre, quadro a quadro, e a decodifica com o timbre da
voz alvo. Como cada quadro de entrada vira um quadro de saída, o ritmo, as pausas e a entonação ficam os da
fonte e a duração não muda. O alvo é descrito por um embedding tirado de poucos segundos de referência.
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from .. import config
from ..media.separation import ProgressCallback
from ..media.wavio import read_wav, write_wav
from .levels import speech_only

# Versão fixada do repositório de pesos no Hugging Face (commit): o arquivo só vale com o SHA-256 gravado.
WEIGHTS_REVISION = "f36e7edfe1684461a8343844af60babc2efbb727"
WEIGHTS_URL = f"https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/{WEIGHTS_REVISION}/converter"

# Suavização do ruído do codificador: 0 deixa a voz da fonte vazar, 1 perde detalhe. 0,3 é o valor dos
# exemplos oficiais do OpenVoice para a conversão de timbre.
TAU = 0.3
NOISE_SEED = 0  # o codificador sorteia ruído; com semente fixa a mesma entrada dá sempre a mesma saída
SPEECH_SECONDS_FOR_EMBEDDING = 20.0  # o embedding de timbre estabiliza com poucos segundos de fala


@dataclass(frozen=True)
class RemoteFile:
    name: str
    url: str
    size: int
    sha256: str


CHECKPOINT = RemoteFile(
    "checkpoint.pth",
    f"{WEIGHTS_URL}/checkpoint.pth",
    131320490,
    "9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e",
)
CONFIG = RemoteFile(
    "config.json",
    f"{WEIGHTS_URL}/config.json",
    838,
    "9dfff60350b8c63f2c664efd92a61b2516efb22671466960f0e5dfebd881fa47",
)

Downloader = Callable[[str, Path], None]


def download_file(url: str, destination: Path) -> None:
    """Baixa `url` para `destination` (sem checagem; quem chama confere tamanho e hash)."""
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _is_intact(path: Path, expected: RemoteFile) -> bool:
    """Tamanho primeiro (barato); o hash só quando o tamanho bate."""
    return path.is_file() and path.stat().st_size == expected.size and _sha256(path) == expected.sha256


def ensure_file(directory: Path, expected: RemoteFile, downloader: Downloader = download_file) -> Path:
    """Garante o arquivo íntegro em `directory`, baixando (para um .part, depois renomeado) se faltar."""
    target = directory / expected.name
    if _is_intact(target, expected):
        return target
    directory.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        downloader(expected.url, partial)
        if not _is_intact(partial, expected):
            raise RuntimeError(
                f"O download de {expected.name} veio corrompido (tamanho ou hash diferente do esperado). "
                "Tente de novo."
            )
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _to_namespace(value: Any) -> Any:
    """Configuração JSON como objeto com atributos, que é o que o modelo do OpenVoice lê (`hps.data.x`)."""
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _to_namespace(item) for key, item in value.items()})
    return value


class OpenVoiceConverter:
    """Troca o timbre de uma fala pelo de uma referência. Os pesos (131 MB) baixam na primeira conversão."""

    engine_id = "openvoice:v2"

    def __init__(
        self,
        models_dir: Path | None = None,
        downloader: Downloader = download_file,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._models_dir = models_dir  # None: lê config.MODELS_DIR só na hora do uso
        self.downloader = downloader
        self._model_loader = model_loader or self._load_model
        self._model: Any = None
        self._hps: Any = None
        self._lock = threading.Lock()
        self._embeddings: dict[tuple[str, int, int], Any] = {}

    @property
    def models_dir(self) -> Path:
        return self._models_dir or config.MODELS_DIR / "openvoice"

    # -- carregamento --

    def _load_model(self) -> tuple[Any, Any]:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "PyTorch não instalado. Rode: .venv\\Scripts\\pip install torch torchaudio "
                "--index-url https://download.pytorch.org/whl/cpu e depois .venv\\Scripts\\pip install -e .[voice]"
            ) from exc
        # O código do OpenVoice usa `weight_norm` e `torch.jit.script` antigos do PyTorch, que avisam a cada
        # camada; os avisos são de versões futuras e não mudam o resultado.
        warnings.filterwarnings(
            "ignore", message=".*(weight_norm|torch.jit.script).*", category=FutureWarning
        )
        from .third_party.openvoice.models import SynthesizerTrn

        config_file = ensure_file(self.models_dir, CONFIG, self.downloader)
        checkpoint = ensure_file(self.models_dir, CHECKPOINT, self.downloader)
        hps = _to_namespace(json.loads(config_file.read_text(encoding="utf-8")))
        model = SynthesizerTrn(
            0,  # sem vocabulário: só a conversão de voz, não a síntese de texto
            hps.data.filter_length // 2 + 1,
            n_speakers=hps.data.n_speakers,
            **vars(hps.model),
        )
        # weights_only: o .pth é um pickle, e só tensores devem ser lidos dele
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        model.load_state_dict(state["model"], strict=False)
        model.eval()
        return model, hps

    def _loaded(self) -> tuple[Any, Any]:
        with self._lock:
            if self._model is None:
                self._model, self._hps = self._model_loader()
            return self._model, self._hps

    # -- conversão --

    @staticmethod
    def _spectrogram(samples: np.ndarray, rate: int, hps: Any) -> Any:
        """Espectrograma linear de `samples` (na taxa `rate`), reamostrado para a taxa do modelo."""
        import torch
        import torchaudio.functional

        from .third_party.openvoice.mel_processing import spectrogram_torch

        # `stft(return_complex=False)` é o formato que o modelo foi treinado para ler; o aviso é só de futuro.
        warnings.filterwarnings("ignore", message=".*return_complex.*", category=UserWarning)
        wave = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
        if rate != hps.data.sampling_rate:
            wave = torchaudio.functional.resample(wave, rate, hps.data.sampling_rate)
        return spectrogram_torch(
            wave.unsqueeze(0),
            hps.data.filter_length,
            hps.data.sampling_rate,
            hps.data.hop_length,
            hps.data.win_length,
            center=False,
        )

    def _embedding(self, samples: np.ndarray, rate: int, model: Any, hps: Any) -> Any:
        """Embedding de timbre: o codificador de referência sobre só os trechos com fala."""
        import torch

        spoken = speech_only(samples, rate, SPEECH_SECONDS_FOR_EMBEDDING)
        spectrogram = self._spectrogram(spoken, rate, hps)
        with torch.no_grad():
            return model.ref_enc(spectrogram.transpose(1, 2)).unsqueeze(-1)

    def _target_embedding(self, reference: Path, model: Any, hps: Any) -> Any:
        """Embedding do alvo, guardado por arquivo (caminho, tamanho e data): as conversões em bloco o repetem."""
        stat = reference.stat()
        key = (str(reference.resolve()), stat.st_size, stat.st_mtime_ns)
        if key not in self._embeddings:
            samples, rate = read_wav(reference)
            self._embeddings[key] = self._embedding(samples, rate, model, hps)
        return self._embeddings[key]

    def convert(
        self,
        source_vocals: Path,
        target_reference: Path,
        out: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        import torch

        model, hps = self._loaded()
        if on_progress:
            on_progress(0, 1)
        samples, rate = read_wav(source_vocals)
        source_embedding = self._embedding(samples, rate, model, hps)
        target_embedding = self._target_embedding(target_reference, model, hps)
        spectrogram = self._spectrogram(samples, rate, hps)
        lengths = torch.LongTensor([spectrogram.size(-1)])
        # fork_rng: a semente vale só aqui e devolve o sorteio global como estava (o OmniVoice também semeia)
        with torch.no_grad(), self._lock, torch.random.fork_rng(devices=[]):
            torch.manual_seed(NOISE_SEED)
            converted = model.voice_conversion(
                spectrogram, lengths, sid_src=source_embedding, sid_tgt=target_embedding, tau=TAU
            )[0][0, 0]
        audio = converted.float().numpy()
        # O modelo devolve um quadro de 256 amostras a menos no máximo; completa com silêncio para a duração
        # da saída ser a da entrada (o vídeo depende disso para ficar em sincronia).
        expected = round(len(samples) / rate * hps.data.sampling_rate)
        fitted = np.zeros(expected, dtype=np.float32)
        fitted[: min(expected, len(audio))] = audio[:expected]
        write_wav(out, fitted, hps.data.sampling_rate)
        if on_progress:
            on_progress(1, 1)
        return out
