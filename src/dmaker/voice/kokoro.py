"""Motor rápido Kokoro-82M (Apache-2.0) via `kokoro-onnx` sobre o onnxruntime, com as vozes prontas pt-BR."""

from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import MODELS_DIR
from .library import VoiceProfile
from .synth import Speech, VoiceRequest

RELEASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
DEFAULT_PRESET = "pf_dora"
MIN_SPEED, MAX_SPEED = 0.5, 2.0  # faixa que o modelo aceita

# Idioma da requisição -> código que o espeak-ng usa para transcrever o texto em fonemas.
PHONEMIZER_LANGUAGES = {
    "pt": "pt-br",
    "en": "en-us",
    "es": "es",
    "fr": "fr-fr",
    "it": "it",
    "ja": "ja",
    "zh": "cmn",
    "hi": "hi",
}


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size: int
    sha256: str


# Versão fixada (release `model-files-v1.0`): tamanho e SHA-256 conferidos a cada download.
VOICES_FILE = RemoteFile(
    "voices-v1.0.bin", 28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
)
MODEL_FILES = {
    "fp32": RemoteFile(
        "kokoro-v1.0.onnx", 325532387, "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"
    ),
    "int8": RemoteFile(
        "kokoro-v1.0.int8.onnx", 92361271, "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"
    ),
}

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
    return path.exists() and path.stat().st_size == expected.size and _sha256(path) == expected.sha256


def ensure_file(directory: Path, expected: RemoteFile, downloader: Downloader = download_file) -> Path:
    """Garante o arquivo íntegro em `directory`, baixando (para um .part, depois renomeado) se faltar."""
    target = directory / expected.name
    if _is_intact(target, expected):
        return target
    directory.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        downloader(f"{RELEASE_URL}/{expected.name}", partial)
        if not _is_intact(partial, expected):
            raise RuntimeError(
                f"O download de {expected.name} veio corrompido (tamanho ou hash diferente do esperado). "
                "Tente de novo."
            )
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _compute_threads() -> int:
    """Núcleos físicos: os lógicos do hyper-threading não aceleram a convolução do vocoder."""
    try:
        import psutil

        physical = psutil.cpu_count(logical=False)
    except ImportError:
        physical = None
    return physical or os.cpu_count() or 1


class KokoroSynthesizer:
    """Fala com as vozes prontas do Kokoro. Ignora `instruct`, `steps` e `seed` (o modelo é determinístico).

    `variant` escolhe o modelo: "fp32" (padrão, o mais rápido nas medições na CPU deste projeto) ou "int8"
    (menor, 92 MB). O modelo e as vozes baixam para `models_dir` na primeira síntese.
    """

    def __init__(
        self,
        variant: str = "fp32",
        models_dir: Path = MODELS_DIR / "kokoro",
        downloader: Downloader = download_file,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        if variant not in MODEL_FILES:
            raise ValueError(f"Variante {variant!r} desconhecida; use {' ou '.join(MODEL_FILES)}.")
        self.variant = variant
        self.engine_id = f"kokoro:v1.0-{variant}"
        self.models_dir = models_dir
        self.downloader = downloader
        self._model_loader = model_loader or self._load_model
        self._model: Any = None
        self._lock = threading.Lock()

    def cache_identity(self, request: VoiceRequest) -> str:
        return self.engine_id

    def _load_model(self) -> Any:
        try:
            import onnxruntime
            from kokoro_onnx import Kokoro
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "kokoro-onnx não instalado. Rode: .venv\\Scripts\\pip install -e .[voice]"
            ) from exc

        model = ensure_file(self.models_dir, MODEL_FILES[self.variant], self.downloader)
        voices = ensure_file(self.models_dir, VOICES_FILE, self.downloader)
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = _compute_threads()
        session = onnxruntime.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        return Kokoro.from_session(session, str(voices))

    def _loaded(self) -> Any:
        with self._lock:
            if self._model is None:
                self._model = self._model_loader()
            return self._model

    @staticmethod
    def _preset_name(voice: VoiceProfile | None) -> str:
        if voice is None:
            return DEFAULT_PRESET
        if voice.engine != "kokoro" or not voice.preset:
            raise ValueError(f"A voz {voice.id!r} não é uma voz pronta do Kokoro.")
        return voice.preset

    def synthesize(self, request: VoiceRequest) -> Speech:
        if not MIN_SPEED <= request.speed <= MAX_SPEED:
            raise ValueError(f"A velocidade deve ficar entre {MIN_SPEED:g} e {MAX_SPEED:g} no Kokoro.")
        model = self._loaded()
        language = PHONEMIZER_LANGUAGES.get(request.language.split("-")[0].split("_")[0].lower(), "pt-br")
        with self._lock:
            samples, sample_rate = model.create(
                request.text, self._preset_name(request.voice), speed=request.speed, lang=language
            )
        return Speech(np.asarray(samples, dtype=np.float32).reshape(-1), int(sample_rate))
