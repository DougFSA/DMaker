"""Marca d'água inaudível na fala sintetizada, para provar que o áudio é voz gerada por IA.

O contrato é o protocolo `Watermarker`: `embed` devolve a fala com a marca e `detect` diz se um áudio a
carrega. O pipeline só conhece o protocolo; a AudioSeal (Meta, MIT, código e pesos), o torch e o download
dos pesos ficam dentro do `AudioSealWatermarker` e só carregam na primeira marca ou verificação.

Invariante: **a marca é a última transformação das amostras da voz sintética.** O que muda andamento ou
dinâmica (acabamento broadcast, `atempo` da dublagem e da correção de fala) roda ANTES dela, fala a fala
(`filtergraph.voice.SpeechFinish`); depois dela só pode vir ganho, mixagem, loudnorm e codificação, que foram
medidos e a marca aguenta. Compressor e mudança de andamento a apagam em qualquer ganho (medido: marcada
crua 0.32 a 0.72; depois do acabamento broadcast 0.00 a 0.15; com `atempo` 1.15 ou 0.90, 0.02 a 0.07).
Quem marca duas vezes a mesma fala, ou transforma a fala depois de marcá-la, quebra a verificação.

Há um segundo requisito: o detector enxerga a fala numa grade de 20 ms (320 amostras a 16 kHz) e a marca
some se a fala sai dessa grade (medido: deslocar a mesma fala 7 amostras a 16 kHz leva a detecção de 1.0 a
0.19, 100 amostras a 0.02). Por isso quem posiciona a fala marcada num arquivo maior (`adelay` da narração e da
dublagem) usa `delay_on_detector_grid`, e o limitador da mixagem compensa o atraso da própria antecipação
(`latency=1`). Um arquivo recodificado fora do DMaker pode perder a grade (medido: 3 amostras a 16 kHz levam
a detecção de 1.00 a 0.22), e por isso a verificação testa 8 alinhamentos (`PHASE_COUNT`).

A fração de quadros sozinha não prova nada: ela é alta em música e em tons puros sem marca (medido: acordes
0.27, tom de 440 Hz 0.90), e um trecho curto de fala humana sem marca chega a 0.82 numa janela de 2 s. O que
separa é a assinatura de 16 bits ("DM"): em áudio sem marca os bits batem por acaso (5 a 8 de 16). Daí o
veredito em três níveis (`Verdict`): "found" exige fração e assinatura; fração sem assinatura é "indication".
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Literal, Protocol

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
# Ganho da marca (alpha da AudioSeal). Com 0.7 a marca fica em -28 dB da energia da fala (1.0, o padrão da
# AudioSeal, -25 dB; 0.45, -32 dB) e sobrevive ao que acontece depois dela: direto 0.99 a 1.00, volume -6 dB
# 0.95 a 1.00, +6 dB 0.66 a 0.91, fundo rosa a -12 dB 0.35 a 0.45, fundo + loudnorm -14 + AAC 192k 0.36 a 0.58
# (frases de 1.3 s a 5.6 s, Kokoro). Com 0.45 só baixar 6 dB já derrubava a frase longa de 0.61 para 0.05 a
# 0.26 e o fundo a -12 dB zerava; com 1.0 tudo acima fica em 0.47 ou mais, ao custo de 3 dB de marca.
EMBED_STRENGTH = 0.7
# Probabilidade = fração dos quadros do áudio em que a rede vê a marca. Sozinha ela NÃO separa marcado de não
# marcado: acordes sem marca dão 0.27, um tom de 440 Hz 0.90 e uma janela de 2 s de fala humana 0.82, tanto quanto
# uma frase curta marcada dentro de um vídeo mixado (0.15 a 0.93). Fala humana em trechos de 30 s fica em 0.00 a
# 0.24 e ruído rosa em 0.00. O limiar só diz "o detector reagiu"; quem confirma é a assinatura (`MIN_MATCHING_BITS`).
DETECTION_THRESHOLD = 0.2
# Bits da assinatura que precisam bater para a marca valer como "encontrada". Sem marca cada bit bate por
# acaso (50%): 15 de 16 ou mais acontece em 17 de 65536 (0.03%), 14 ou mais em 137 de 65536 (0.2%). Medido sem
# marca (tom, acordes, ruído rosa, fala humana, fala sintetizada crua): 3 a 11 de 16. Medido em fala marcada com
# a narração dominando (crua, -6 dB, +6 dB, loudnorm -14, AAC 192k, fundo de acordes): 16 de 16 em todos os casos.
MIN_MATCHING_BITS = 15
# A rede só enxerga a fala na grade de 20 ms (320 amostras a 16 kHz) e um arquivo recodificado pode ter
# perdido a grade. A busca testa 8 alinhamentos, cortando de 0 a 280 amostras do começo em passos de 40
# (2.5 ms). Medido numa fala marcada deslocada de 0 a 319 amostras: a fração de quadros marcados continua
# alta em qualquer deslocamento, mas a assinatura só volta quando o alinhamento cai a menos de ~5 amostras
# de um múltiplo de 320; com passo 40 isso acontece em 18 de 80 deslocamentos, e com passo 5 (8 alinhamentos
# de 0 a 35) em 15 de 80. Os outros viram "indício", nunca "encontrada" nem "não encontrada".
PHASE_STEP = 40
PHASE_COUNT = 8
# Um alinhamento deslocado só entra na escolha com fração a partir daqui. A fração varia de 0.00 a 0.24 de um
# alinhamento para outro em fala humana sem marca, e escolher o maior de 8 a empurraria acima do limiar
# (3 de 6 trechos de fala humana viravam "indício"); a fala marcada, quando cai na grade, chega a 0.79 ou mais.
SHIFTED_THRESHOLD = 0.5
# Um quadro conta como "marcado" quando a probabilidade da rede passa de 0.5 (a mesma regra da AudioSeal).
FRAME_THRESHOLD = 0.5
# Mensagem de 16 bits gravada na marca: "DM" em ASCII (0x44 0x4D). Serve de assinatura do DMaker.
MESSAGE_BITS = (0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 1)
# Entra na chave do cache de falas: mudou a mensagem ou o ganho, incremente o número final.
EMBED_IDENTITY = "audioseal-16bits:dm2"

GENERATOR_CARD = "audioseal_wm_16bits"
DETECTOR_CARD = "audioseal_detector_16bits"


Verdict = Literal["found", "indication", "absent"]  # encontrada | indício, inconclusivo | não encontrada
Origin = Literal[
    "audio", "label"
]  # o que sustenta o veredito: a análise do áudio ou a etiqueta de procedência
Span = tuple[float, float]  # início e fim, em segundos do arquivo


@dataclass(frozen=True)
class WatermarkResult:
    """Veredito de uma verificação em três níveis.

    `probability` e `matched_bits` são sempre da análise do áudio (fração dos quadros em que a rede vê a
    marca; bits da assinatura iguais ao "DM", de 16). Com `origin == "label"` o veredito vem da etiqueta
    de procedência, `spans` são os trechos de voz gerada que ela informa e `audio_verdict` é o que a
    análise do áudio disse (None quando não rodou).
    """

    probability: float
    verdict: Verdict
    matched_bits: int | None = None
    origin: Origin = "audio"
    spans: tuple[Span, ...] = ()
    audio_verdict: Verdict | None = None

    @property
    def detected(self) -> bool:
        """Só "encontrada" conta como detecção: o indício não confirma nada."""
        return self.verdict == "found"


class Watermarker(Protocol):
    identity: (
        str  # entra na chave do cache de falas; vazio quando não marca (as falas antigas continuam valendo)
    )
    provenance: (
        bool  # os arquivos com voz gerada levam a etiqueta de procedência (liga e desliga com a marca)
    )

    def embed(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """Fala mono float32 com a marca, do mesmo tamanho e na mesma taxa."""

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        """Veredito sobre `samples`: fração de quadros marcados e assinatura."""


# ---------- contas puras ----------

DETECTOR_GRID_MS = 20  # passo da rede de detecção: 320 amostras a 16 kHz


def delay_on_detector_grid(seconds: float) -> int:
    """Atraso em ms, arredondado ao múltiplo de 20 mais próximo (erro de até 10 ms, inaudível), para a fala
    marcada entrar no arquivo alinhada à grade do detector; ver o invariante no topo do módulo."""
    return max(0, round(seconds * 1000 / DETECTOR_GRID_MS) * DETECTOR_GRID_MS)


def watermark_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """A marca vale por padrão; `DMAKER_WATERMARK=0` a desliga."""
    value = (environ if environ is not None else os.environ).get(WATERMARK_ENV, "")
    return value.strip().lower() not in _OFF_VALUES


def matching_bits(decoded: Sequence[int]) -> int:
    """Quantos dos 16 bits decodificados são iguais à assinatura do DMaker."""
    return sum(1 for got, want in zip(decoded, MESSAGE_BITS, strict=False) if got == want)


def choose_verdict(
    fraction: float,
    matched_bits: int | None,
    threshold: float = DETECTION_THRESHOLD,
    min_bits: int = MIN_MATCHING_BITS,
) -> Verdict:
    """Os três níveis: sem fração suficiente não há marca; com fração, só a assinatura confirma.

    Música e tons puros fazem a rede reagir (fração alta) sem carregar a mensagem: viram "indício".
    """
    if fraction < threshold:
        return "absent"
    return "found" if matched_bits is not None and matched_bits >= min_bits else "indication"


def weighted_message(bit_logits: np.ndarray, marked: np.ndarray) -> tuple[int, ...]:
    """Bits da mensagem a partir dos logits (bits x quadros), contando só os quadros que a rede viu como marcados.

    A média de todos os quadros mistura silêncio e fala sem marca, que votam ao acaso e arrastam os bits
    de uma fala marcada para o meio; nos quadros marcados o sinal da média é o bit.
    """
    if not marked.any():
        return ()
    mean_logits = bit_logits[:, marked].mean(axis=1)
    return tuple(int(value > 0) for value in mean_logits)


def phase_offsets(count: int = PHASE_COUNT, step: int = PHASE_STEP) -> list[int]:
    """Amostras cortadas do começo em cada tentativa de alinhamento; a primeira (zero) é o áudio como veio."""
    return [index * step for index in range(count)]


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
    """Não marca nada e nunca detecta: é o que vale com a marca desligada ou sem a biblioteca.

    `provenance` diz se os arquivos ainda levam a etiqueta de procedência: sim quando a voz é gerada e só a
    biblioteca falta; não quando o usuário desligou a marca (`DMAKER_WATERMARK=0`, `--no-watermark`).
    """

    identity = ""

    def __init__(self, provenance: bool = False) -> None:
        self.provenance = provenance

    def embed(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        return samples

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        return WatermarkResult(0.0, "absent")


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


@dataclass(frozen=True)
class _Evidence:
    """O que a rede viu num bloco: a fração de quadros marcados, quais são e os logits dos bits da mensagem."""

    fraction: float
    marked: np.ndarray
    bit_logits: np.ndarray


class AudioSealWatermarker:
    """AudioSeal na CPU, carregada uma única vez. O gerador e o detector são independentes: só o que for
    usado é carregado (um `voice verify` não paga o gerador)."""

    identity = EMBED_IDENTITY
    provenance = True

    def __init__(
        self,
        models_dir: Path | None = None,
        threads: int | None = None,
        threshold: float = DETECTION_THRESHOLD,
        strength: float = EMBED_STRENGTH,
        min_bits: int = MIN_MATCHING_BITS,
    ) -> None:
        self.models_dir = models_dir
        self.threads = threads
        self.threshold = threshold
        self.strength = strength
        self.min_bits = min_bits
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

    def preload(self) -> None:
        """Carrega o gerador e o detector, o que baixa os pesos que faltarem (usado pelo gerenciador de modelos)."""
        self._loaded_generator()
        self._loaded_detector()

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

    def _best_block(self, detector: Any, audio: Any, skip: int) -> _Evidence:
        """O bloco de 30 s com mais quadros marcados, vendo o áudio a partir da amostra `skip`.

        Melhor bloco e não a média do arquivo: uma emenda em que só parte é voz sintética ainda aparece, o que
        a média diluiria. Os quadros e os logits da mensagem ficam para decidir os bits só do bloco escolhido.
        """
        import torch

        shifted = audio[..., skip:]
        best = _Evidence(0.0, np.zeros(0, dtype=bool), np.zeros((len(MESSAGE_BITS), 0), dtype=np.float32))
        for start, end in chunk_bounds(shifted.shape[-1], CHUNK_SECONDS * MODEL_RATE, MODEL_RATE):
            block = shifted[..., start:end]
            if detector.normalizer is not None:  # a mesma normalização de volume do `forward` da AudioSeal
                block = detector.normalizer.loudness_normalization(block)
            output = detector.detector(block)[0]  # (2 + bits) x quadros
            marked = (torch.softmax(output[:2], dim=0)[1] > FRAME_THRESHOLD).numpy()
            fraction = float(marked.mean()) if marked.size else 0.0
            if fraction > best.fraction or best.marked.size == 0:
                best = _Evidence(fraction, marked, output[2:].numpy())
        return best

    def _judge(self, evidence: _Evidence) -> WatermarkResult:
        message = weighted_message(evidence.bit_logits, evidence.marked)
        matched = matching_bits(message) if message else None
        verdict = choose_verdict(evidence.fraction, matched, self.threshold, self.min_bits)
        return WatermarkResult(round(evidence.fraction, 4), verdict, matched)

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        """Veredito pelo áudio: fração de quadros marcados e assinatura, no melhor alinhamento.

        Tenta o áudio como veio; se não for "found", tenta os outros alinhamentos e fica com o de maior
        fração (entre os que passam de `SHIFTED_THRESHOLD`). Os bits são decididos só nesse alinhamento,
        depois de escolhido: escolher pela fração (e não pelos bits) mantém o acaso da assinatura em
        17 de 65536, sem multiplicar por 8.
        """
        import torch

        if len(samples) == 0:
            return WatermarkResult(0.0, "absent")
        detector = self._loaded_detector()
        audio = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))[None, None]
        with self._inference_lock, torch.no_grad(), _eager_model():
            audio = _resample(audio, sample_rate, MODEL_RATE)
            first = self._best_block(detector, audio, 0)
            result = self._judge(first)
            if result.verdict == "found":
                return result
            offsets = [skip for skip in phase_offsets()[1:] if skip < audio.shape[-1]]
            shifted = (self._best_block(detector, audio, skip) for skip in offsets)
            candidates = [first, *(item for item in shifted if item.fraction >= SHIFTED_THRESHOLD)]
            return self._judge(max(candidates, key=lambda item: item.fraction))


# ---------- escolha do marcador ----------

_missing_library_warned = False


def audioseal_installed() -> bool:
    return find_spec("audioseal") is not None


def default_watermarker(
    enabled: bool = True, environ: Mapping[str, str] | None = None, installed: bool | None = None
) -> Watermarker:
    """A AudioSeal quando a marca está ligada (`enabled` e `DMAKER_WATERMARK`) e a biblioteca existe; senão
    o `NullWatermarker`, avisando uma vez por processo quando é a biblioteca que falta. Sem a biblioteca a
    etiqueta de procedência continua valendo; desligada de propósito, ela some junto com a marca."""
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
        return NullWatermarker(provenance=True)  # a voz continua gerada: só a marca no áudio fica de fora
    return AudioSealWatermarker()
