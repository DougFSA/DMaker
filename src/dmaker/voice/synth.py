"""Síntese de fala: o contrato (`SpeechSynthesizer`) e o motor OmniVoice por trás dele."""

from __future__ import annotations

import hashlib
import os
import threading
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..config import MODELS_DIR, VOICE_CACHE_DIR
from ..media.wavio import read_wav
from .library import VoiceProfile
from .pronunciation import language_code


@dataclass(frozen=True)
class VoiceRequest:
    """Um pedido de fala: texto, idioma e, opcionalmente, a voz e o jeito de falar."""

    text: str
    language: str = "pt"
    voice: VoiceProfile | None = None
    instruct: str | None = None
    speed: float = 1.0
    steps: int | None = None  # None: o motor escolhe o padrão dele (OmniVoice: 16)
    seed: int | None = None
    duration: float | None = None  # segundos que a fala deve durar (OmniVoice); o Kokoro não força duração


@dataclass(frozen=True)
class Speech:
    """Áudio sintetizado: amostras float32 mono entre -1 e 1."""

    samples: np.ndarray
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


class SpeechSynthesizer(Protocol):
    engine_id: str  # entra na chave do cache: trocar de motor ou de modelo não reaproveita falas

    def synthesize(self, request: VoiceRequest) -> Speech: ...


# ---------- OmniVoice ----------

DEFAULT_MODEL_ID = "k2-fsa/OmniVoice"
# Valores de qualidade do VoiceStudio para o OmniVoice: 16 passos é o padrão de narração ("balanced");
# 8 é o rascunho/prévia dele (metade do tempo, mais áspero); 32 é o preset de longa duração.
DEFAULT_STEPS = 16
DRAFT_STEPS = 8
HIGH_QUALITY_STEPS = 32
GUIDANCE_SCALE = 2.0  # força com que a fala segue o texto e a voz; 2.0 é o padrão do modelo e do VoiceStudio
MIN_GPU_MEMORY_BYTES = (
    4 * 1024**3
)  # abaixo disso o modelo não cabe com folga e a CPU acaba sendo mais estável

# Frase de ancoragem de uma voz sem gravação. Curta de propósito (~4 s): o custo de cada fala na CPU
# cresce com o tamanho da referência, e uma âncora longa encarece todas as falas seguintes.
ANCHOR_TEXTS = {"pt": "Olá, tudo bem? Eu sou a voz que vai narrar o seu vídeo."}


def _compute_threads() -> int:
    """Threads de cálculo: os núcleos físicos. Os 'lógicos' do hyper-threading disputam as mesmas unidades
    de ponto flutuante e deixaram a síntese ~15% mais lenta nas medições na CPU deste projeto."""
    try:
        import psutil

        physical = psutil.cpu_count(logical=False)
    except ImportError:
        physical = None
    return physical or os.cpu_count() or 1


def _stable_seed(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


@contextmanager
def _hub_cache(directory: Path) -> Iterator[None]:
    """Faz o download do Hugging Face cair em `directory` (e não em ~/.cache) só durante o carregamento."""
    from huggingface_hub import constants

    previous = constants.HF_HUB_CACHE
    directory.mkdir(parents=True, exist_ok=True)
    constants.HF_HUB_CACHE = str(directory)
    try:
        yield
    finally:
        constants.HF_HUB_CACHE = previous


def _as_tensor(samples: np.ndarray) -> Any:
    import torch

    return torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32)).unsqueeze(0)


class OmniVoiceSynthesizer:
    """Motor local k2-fsa/OmniVoice (Apache-2.0): fala em 600+ idiomas, clona voz e cria voz por descrição.

    O modelo é carregado uma única vez, na primeira síntese. Vozes sem gravação de referência (projetadas
    por descrição ou automáticas) ganham uma "âncora": uma frase gerada uma vez e reaproveitada como
    referência, para o falante não mudar de uma fala para a próxima.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: str = "auto",
        models_dir: Path = MODELS_DIR / "omnivoice",
        prompt_dir: Path = VOICE_CACHE_DIR / "prompts",
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.model_id = model_id
        self.engine_id = f"omnivoice:{model_id}"
        self.device = device
        self.models_dir = models_dir
        self.prompt_dir = prompt_dir
        self._model_loader = model_loader or self._load_model
        self._model: Any = None
        self._device: str | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()  # o modelo não é seguro para uso concorrente
        self._prompts: dict[str, Any] = {}

    # -- carregamento --

    def _resolve_device(self) -> str:
        if self._device is None:
            self._device = self._detect_device()
        return self._device

    def effective_steps(self, request: VoiceRequest) -> int:
        """Passos de síntese: o pedido manda; sem ele, 16 (o padrão do VoiceStudio), em CPU ou GPU."""
        return request.steps if request.steps is not None else DEFAULT_STEPS

    def cache_identity(self, request: VoiceRequest) -> str:
        """Motor, modelo e passos efetivos: com passos diferentes a fala sai diferente."""
        return f"{self.engine_id}:steps{self.effective_steps(request)}"

    def _detect_device(self) -> str:
        if self.device != "auto":
            return self.device
        import torch

        if (
            torch.cuda.is_available()
            and torch.cuda.get_device_properties(0).total_memory >= MIN_GPU_MEMORY_BYTES
        ):
            return "cuda"
        return "cpu"

    def _load_model(self) -> Any:
        # O pydub (usado pelo omnivoice) avisa que não acha o ffmpeg no PATH, mas aqui a referência vai como
        # tensor e o pydub nunca decodifica arquivo; o ffmpeg do DMaker fica em bin/ffmpeg, fora do PATH.
        warnings.filterwarnings("ignore", message="Couldn't find ffmpeg", category=RuntimeWarning)
        try:
            import torch
            from omnivoice import OmniVoice
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "OmniVoice não instalado. Rode: .venv\\Scripts\\pip install torch torchaudio "
                "--index-url https://download.pytorch.org/whl/cpu e depois .venv\\Scripts\\pip install -e .[voice]"
            ) from exc

        device = self._resolve_device()
        dtype = torch.float16 if device == "cuda" else torch.float32  # float16 não é confiável na CPU
        torch.set_num_threads(_compute_threads())
        with _hub_cache(self.models_dir):
            return OmniVoice.from_pretrained(self.model_id, device_map=device, dtype=dtype)

    def _loaded(self) -> Any:
        with self._load_lock:
            if self._model is None:
                self._model = self._model_loader()
            return self._model

    # -- prompts de voz (guardados em memória e em disco) --

    def _prompt_file(self, key: str) -> Path:
        model_tag = hashlib.sha256(self.model_id.encode()).hexdigest()[:6]
        return self.prompt_dir / f"{model_tag}-{key}.pt"

    def _load_from_disk(self, key: str) -> Any | None:
        path = self._prompt_file(key)
        if not path.exists():
            return None
        try:
            from omnivoice import VoiceClonePrompt

            return VoiceClonePrompt.load(str(path))
        except Exception:  # noqa: BLE001 - arquivo corrompido ou de outra versão: refaz o prompt
            return None

    def _save_to_disk(self, key: str, prompt: Any) -> None:
        if not hasattr(prompt, "save"):
            return
        try:
            self.prompt_dir.mkdir(parents=True, exist_ok=True)
            prompt.save(str(self._prompt_file(key)))
        except Exception:  # noqa: BLE001 - guardar o prompt é só otimização
            pass

    def _cached_prompt(self, key: str, build: Callable[[], Any]) -> Any | None:
        """Prompt da memória, do disco ou recém-construído; None se não der (a síntese segue sem ele)."""
        if key in self._prompts:
            return self._prompts[key]
        prompt = self._load_from_disk(key)
        if prompt is None:
            try:
                prompt = build()
            except Exception:  # noqa: BLE001 - a otimização nunca vira erro: o chamador usa a referência direta
                return None
            self._save_to_disk(key, prompt)
        self._prompts[key] = prompt
        return prompt

    # -- geração --

    @staticmethod
    def _seed(seed: int) -> None:
        import torch

        torch.manual_seed(seed)

    @staticmethod
    def _reference_tensor(path: Path) -> tuple[Any, int]:
        """Referência como (tensor, taxa): o pacote leria por caminho via pydub/ffmpeg, que pode faltar no PATH."""
        samples, sample_rate = read_wav(path)
        return _as_tensor(samples), sample_rate

    def _generate(self, model: Any, request: VoiceRequest, **conditioning: Any) -> Speech:
        arguments: dict[str, Any] = {
            "text": request.text,
            "language": language_code(request.language),
            "num_step": self.effective_steps(request),
            "guidance_scale": GUIDANCE_SCALE,
            "denoise": True,  # token <|denoise|> à frente da geração: menos ruído de fundo
            "postprocess_output": True,  # tira silêncio nas pontas, aplica fade e margem
            **conditioning,
        }
        if request.duration is not None:
            arguments["duration"] = request.duration  # o modelo manda a duração e ignora a velocidade
        elif request.speed != 1.0:
            arguments["speed"] = request.speed
        if request.seed is not None:
            self._seed(
                request.seed
            )  # logo antes de gerar: a âncora ter sido criada agora ou antes não muda o resultado
        audio = model.generate(**arguments)[0]
        return Speech(np.asarray(audio, dtype=np.float32).reshape(-1), int(model.sampling_rate))

    def _clone(self, model: Any, request: VoiceRequest, voice: VoiceProfile) -> Speech:
        path = voice.reference_path
        if path is None or not path.exists():
            raise FileNotFoundError(f"A voz {voice.id!r} não tem o arquivo de referência.")
        if not voice.reference_text:
            raise ValueError(
                f"A voz {voice.id!r} não tem o texto da referência. Clone de novo informando o texto "
                "(ou com o faster-whisper instalado, para transcrever)."
            )
        reference_audio = self._reference_tensor(path)
        reference_text = voice.reference_text
        prompt = self._cached_prompt(
            voice.fingerprint(),
            lambda: model.create_voice_clone_prompt(
                ref_audio=reference_audio, ref_text=reference_text, preprocess_prompt=True
            ),
        )
        if prompt is not None:
            try:
                return self._generate(model, request, voice_clone_prompt=prompt)
            except Exception:  # noqa: BLE001 - tenta de novo com a referência direta
                pass
        return self._generate(model, request, ref_audio=reference_audio, ref_text=reference_text)

    def _anchor(self, model: Any, request: VoiceRequest, instruct: str | None) -> Any | None:
        """Prompt de uma voz sem gravação: gera a frase de ancoragem uma vez e a usa como referência."""
        language = language_code(request.language)
        key = hashlib.sha256(f"anchor|{instruct or ''}|{language}".encode()).hexdigest()[:16]
        anchor_text = ANCHOR_TEXTS.get(language, request.text)

        def build() -> Any:
            self._seed(_stable_seed(key))  # a mesma descrição soa igual em qualquer sessão
            anchor_request = VoiceRequest(text=anchor_text, language=language, steps=request.steps)
            anchor = self._generate(model, anchor_request, **({"instruct": instruct} if instruct else {}))
            wave = (_as_tensor(anchor.samples), anchor.sample_rate)
            return model.create_voice_clone_prompt(
                ref_audio=wave, ref_text=anchor_text, preprocess_prompt=True
            )

        return self._cached_prompt(key, build)

    def _designed(self, model: Any, request: VoiceRequest, instruct: str | None) -> Speech:
        prompt = self._anchor(model, request, instruct)
        if prompt is not None:
            try:
                return self._generate(model, request, voice_clone_prompt=prompt)
            except Exception:  # noqa: BLE001 - sem a âncora a voz muda a cada fala, mas a fala sai
                pass
        return self._generate(model, request, **({"instruct": instruct} if instruct else {}))

    def synthesize(self, request: VoiceRequest) -> Speech:
        model = self._loaded()
        voice = request.voice
        with self._inference_lock:
            if voice is not None and voice.kind == "clone":
                return self._clone(model, request, voice)
            instruct = request.instruct or (voice.instruct if voice else None)
            return self._designed(model, request, instruct)
