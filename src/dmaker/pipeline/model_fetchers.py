"""Funções que baixam cada modelo do registro (`domain.models`), uma por motor.

Todas têm a mesma forma, `(models_dir, variant) -> None`, e reaproveitam o que o motor já tem para garantir
o próprio modelo (o Kokoro confere tamanho e SHA-256), em vez de um downloader paralelo. Os imports ficam
dentro das funções: listar modelos não pode puxar torch nem onnxruntime.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

Fetcher = Callable[[Path, str], None]


def resolve_fetcher(dotted: str) -> Fetcher:
    """`"modulo:funcao"` vira a função, para o registro apontar para ela sem importar o motor."""
    module_name, _, function_name = dotted.partition(":")
    function = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(function):
        raise LookupError(f"Função de download não encontrada: {dotted}")
    return function


def fetch_kokoro(models_dir: Path, variant: str) -> None:
    from ..media.downloads import ensure_file
    from ..voice.kokoro import MODEL_FILES, VOICES_FILE

    folder = models_dir / "kokoro"
    ensure_file(folder, MODEL_FILES[variant])
    ensure_file(folder, VOICES_FILE)


def fetch_audioseal(models_dir: Path, variant: str) -> None:
    """Os pesos da marca d'água (gerador e detector), pelo mesmo caminho que a primeira marca usaria."""
    from ..voice.watermark import AudioSealWatermarker

    AudioSealWatermarker(models_dir=models_dir).preload()


def fetch_diarization(models_dir: Path, variant: str) -> None:
    """Os dois arquivos que a separação de falantes usa, conferidos por tamanho e SHA-256."""
    from ..media.diarization import ensure_models

    ensure_models(models_dir / "diarization")


def fetch_openvoice(models_dir: Path, variant: str) -> None:
    from ..media.downloads import ensure_file
    from ..voice.openvoice_converter import CHECKPOINT, CONFIG

    folder = models_dir / "openvoice"
    ensure_file(folder, CONFIG)
    ensure_file(folder, CHECKPOINT)


def fetch_omnivoice(models_dir: Path, variant: str) -> None:
    """Baixa os arquivos do repositório sem carregar o modelo: carregar custa ~3 GB de memória à toa."""
    from huggingface_hub import snapshot_download

    from ..voice.synth import DEFAULT_MODEL_ID

    snapshot_download(DEFAULT_MODEL_ID, cache_dir=str(models_dir / "omnivoice"))


def fetch_demucs(models_dir: Path, variant: str) -> None:
    from ..media.separation import DemucsSeparator

    DemucsSeparator(model=variant, device="cpu", models_dir=models_dir / "demucs").preload()


def fetch_whisper(models_dir: Path, variant: str) -> None:
    """O mesmo download que o `WhisperModel` faz ao abrir um tamanho, sem abrir o modelo."""
    from faster_whisper.utils import download_model

    download_model(variant, cache_dir=str(models_dir))


def fetch_matting(models_dir: Path, variant: str) -> None:
    from ..media.matting import ensure_model

    ensure_model(variant, models_dir)
