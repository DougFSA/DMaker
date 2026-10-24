"""Trocar a voz de uma gravação inteira por uma voz da biblioteca, mantendo ritmo, entonação e fundo.

Fluxo: isola voz e fundo (cache) -> prepara a referência da voz escolhida -> converte o stem de voz em blocos
-> iguala o volume ao da voz original -> soma ao fundo, que não passa pelo modelo, e remonta o vídeo ou áudio.
Diferente da dublagem (que traduz e ressintetiza) e da correção de fala (que troca um trecho), aqui todas as
palavras, pausas e a melodia da fala são as da gravação; só o timbre muda. Cada dependência pesada (Demucs,
motor de conversão, sintetizador, ffmpeg) entra por parâmetro.
"""

from __future__ import annotations

import hashlib
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from .. import config
from ..filtergraph.speech_edit import corrected_suffix
from ..filtergraph.voice_swap import voice_swap_command
from ..media.ffmpeg import FFmpegRunner
from ..media.probe import MediaInfo, probe
from ..media.wavio import read_wav, write_wav
from ..voice.conversion import (
    VoiceConverter,
    plan_blocks,
    plan_cuts,
    stitch_blocks,
)
from ..voice.levels import active_rms, gain_to_match_db
from ..voice.library import VoiceLibrary, VoiceProfile
from ..voice.synth import SpeechSynthesizer, VoiceRequest
from ..voice.watermark import Watermarker, default_watermarker
from .isolation import IsolationService

OUTPUT_SUBDIR = "troca-de-voz"
REFERENCES_SUBDIR = "convert-refs"
# ~8 s de fala: o embedding de timbre do motor estabiliza com poucos segundos, e uma referência longa só
# encareceria a síntese. Frases variadas cobrem vogais e consoantes diferentes.
REFERENCE_TEXTS = {
    "pt": "Olá, tudo bem? Eu sou a voz que vai narrar o seu vídeo. Falo com calma e clareza, do começo ao fim.",
    "en": "Hello, how are you? I am the voice that will narrate your video. I speak calmly and clearly, from start to finish.",
}
REFERENCE_SEED = 1  # a mesma voz desenhada gera sempre a mesma referência

ProgressReport = Callable[[str, float], None]  # (etapa, fração de 0 a 1)

# Parte da barra de progresso de cada etapa: separar é o que mais demora quando o cache está frio; a conversão
# vem logo atrás; montar o arquivo final é rápido (o vídeo passa sem recodificar).
STAGE_WEIGHTS = {
    "separação": (0.0, 0.40),
    "referência": (0.40, 0.45),
    "conversão": (0.45, 0.92),
    "montagem": (0.92, 1.0),
}


@dataclass(frozen=True)
class ConversionRequest:
    """O que converter: o arquivo (ou um trecho dele), a voz da biblioteca e onde gravar."""

    src: Path
    voice: str
    start: float | None = None
    end: float | None = None
    out: Path | None = None

    def __post_init__(self) -> None:
        if not self.voice.strip():
            raise ValueError("Escolha a voz que vai falar no lugar da original.")
        if self.start is not None and self.start < 0:
            raise ValueError(f"start ({self.start}) não pode ser negativo.")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError(f"end ({self.end}) precisa ser maior que start ({self.start}).")


@dataclass(frozen=True)
class ConversionResult:
    path: Path
    voice: str
    seconds: float  # duração do que foi convertido
    blocks: int
    gain_db: float  # ajuste de volume que igualou a fala convertida à original
    engine: str
    timings: dict[str, float] = field(default_factory=dict)  # segundos de cada etapa


def default_output_path(request: ConversionRequest, suffix: str) -> Path:
    """Arquivo da conversão: a voz e o trecho entram no nome, para tentativas diferentes não se sobrescreverem."""
    digest = hashlib.sha1(f"{request.voice}|{request.start}|{request.end}".encode()).hexdigest()[:8]
    return config.OUTPUT_DIR / OUTPUT_SUBDIR / f"{request.src.stem}.{request.voice}-{digest}{suffix}"


def stage_progress(report: ProgressReport | None, stage: str) -> Callable[[int, int], None]:
    """Callback (feito, total) de uma etapa que vira fração da barra geral."""
    first, last = STAGE_WEIGHTS[stage]

    def update(done: int, total: int) -> None:
        if report:
            report(stage, first + (last - first) * done / max(total, 1))

    return update


class VoiceConversionService:
    def __init__(
        self,
        converter: VoiceConverter,
        isolation: IsolationService,
        library: VoiceLibrary,
        synthesizer: SpeechSynthesizer,
        runner: FFmpegRunner,
        prober: Callable[[Path], MediaInfo] = probe,
        log: Callable[[str], None] | None = None,
        watermarker: Watermarker | None = None,
    ) -> None:
        """`watermarker` marca a fala convertida, como a narração marca a sintetizada; sem ele vale o padrão
        (AudioSeal, ligada, a menos que `DMAKER_WATERMARK=0`)."""
        self.watermarker = watermarker if watermarker is not None else default_watermarker()
        self.converter = converter
        self.isolation = isolation
        self.library = library
        self.synthesizer = synthesizer
        self.runner = runner
        self.prober = prober
        self.log = log or (lambda message: None)

    # -- referência da voz alvo --

    def target_reference(self, voice: VoiceProfile) -> Path:
        """Gravação de poucos segundos que descreve o timbre: a do clone, ou uma gerada (e guardada) para a
        voz pronta ou desenhada, que não tem gravação."""
        recorded = voice.reference_path
        if recorded is not None and recorded.exists():
            return recorded
        cache = config.VOICE_CACHE_DIR / REFERENCES_SUBDIR
        identity = getattr(self.synthesizer, "cache_identity", None)
        engine = identity(VoiceRequest(text="", voice=voice)) if identity else self.synthesizer.engine_id
        key = hashlib.sha256(f"{voice.fingerprint()}|{engine}".encode()).hexdigest()[:16]
        target = cache / f"{voice.id}-{key}.wav"
        if not target.exists():
            language = voice.language.split("-")[0]
            speech = self.synthesizer.synthesize(
                VoiceRequest(
                    text=REFERENCE_TEXTS.get(language, REFERENCE_TEXTS["en"]),
                    language=voice.language,
                    voice=voice,
                    seed=REFERENCE_SEED,
                )
            )
            partial = target.with_suffix(".tmp.wav")
            write_wav(partial, speech.samples, speech.sample_rate)
            partial.replace(target)
        return target

    # -- conversão em blocos --

    def convert_vocals(
        self,
        vocals: Path,
        reference: Path,
        work: Path,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[np.ndarray, int, int]:
        """Converte o stem de voz inteiro: devolve (amostras, taxa, quantidade de blocos).

        A fala é mono para o modelo; os blocos são cortados nos vales de silêncio e se sobrepõem, e a emenda
        usa um fade complementar, então um arquivo longo não precisa caber de uma vez na memória do modelo.
        """
        samples, rate = read_wav(vocals)
        blocks = plan_blocks(len(samples) / rate, plan_cuts(samples, rate))
        converted: list[np.ndarray] = []
        output_rate = rate
        for index, block in enumerate(blocks):
            piece = work / f"bloco-{index}.wav"
            write_wav(piece, samples[round(block.start * rate) : round(block.end * rate)], rate)
            result, output_rate = read_wav(
                self.converter.convert(piece, reference, work / f"bloco-{index}.convertido.wav")
            )
            converted.append(result)
            if on_progress:
                on_progress(index + 1, len(blocks))
        total = round(len(samples) / rate * output_rate)
        return stitch_blocks(blocks, converted, output_rate, total), output_rate, len(blocks)

    # -- fluxo completo --

    def convert(self, request: ConversionRequest, report: ProgressReport | None = None) -> ConversionResult:
        if not request.src.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {request.src}")
        voice = self.library.get(request.voice)
        info = self.prober(request.src)
        if not info.has_audio:
            raise ValueError(f"{request.src.name} não tem áudio para trocar a voz.")
        out = request.out or default_output_path(
            request, corrected_suffix(request.src.suffix, info.has_video)
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        timings: dict[str, float] = {}

        with timed(timings, "separação"):
            stems = self.isolation.isolate(
                request.src, request.start, request.end, on_progress=stage_progress(report, "separação")
            )
        with timed(timings, "referência"):
            if report:
                report("referência", STAGE_WEIGHTS["referência"][0])
            reference = self.target_reference(voice)
        with tempfile.TemporaryDirectory(prefix="troca-de-voz-") as folder:
            work = Path(folder)
            with timed(timings, "conversão"):
                converted, rate, block_count = self.convert_vocals(
                    stems.vocals, reference, work, stage_progress(report, "conversão")
                )
            with timed(timings, "montagem"):
                # a voz convertida é voz gerada por IA: a marca entra antes de somar ao fundo e sobrevive ao AAC
                converted = self.watermarker.embed(converted, rate)
                original, original_rate = read_wav(stems.vocals)
                gain_db = gain_to_match_db(active_rms(converted, rate), active_rms(original, original_rate))
                duration = len(original) / original_rate
                self.log(f"voz {voice.id}: {block_count} bloco(s), volume {gain_db:+.1f} dB")
                self.runner.run(
                    voice_swap_command(
                        request.src,
                        write_wav(work / "voz-convertida.wav", converted, rate),
                        stems.background,
                        out,
                        duration,
                        gain_db,
                        has_video=info.has_video,
                        cut_start=_cut_start(request),
                    )
                )
        if report:
            report("montagem", 1.0)
        return ConversionResult(
            out, voice.id, duration, block_count, gain_db, self.converter.engine_id, timings
        )


def _cut_start(request: ConversionRequest) -> float | None:
    """Início do trecho quando só uma parte do arquivo é convertida; `None` é o arquivo inteiro."""
    if request.start is None and request.end is None:
        return None
    return request.start or 0.0


@contextmanager
def timed(timings: dict[str, float], stage: str) -> Iterator[None]:
    """Anota em `timings` quantos segundos a etapa levou."""
    started = time.monotonic()
    try:
        yield
    finally:
        timings[stage] = round(time.monotonic() - started, 2)


def default_voice_conversion_service(
    runner: FFmpegRunner,
    log: Callable[[str], None] | None = None,
    library: VoiceLibrary | None = None,
    isolation: IsolationService | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    converter: VoiceConverter | None = None,
    prober: Callable[[Path], MediaInfo] = probe,
    watermarker: Watermarker | None = None,
) -> VoiceConversionService:
    """Serviço de produção: Demucs, OpenVoice V2 e o roteador de vozes; o que vier por parâmetro (testes) vale."""
    from .isolation import default_isolation_service
    from .voices import shared_synthesizer

    return VoiceConversionService(
        converter or shared_converter(),
        isolation or default_isolation_service(runner, log),
        library or VoiceLibrary(),
        synthesizer or shared_synthesizer(),
        runner,
        prober=prober,
        log=log,
        watermarker=watermarker,
    )


@lru_cache(maxsize=1)
def shared_converter() -> VoiceConverter:
    """Um conversor por processo: o modelo fica na memória entre conversões."""
    from ..voice.openvoice_converter import OpenVoiceConverter

    return OpenVoiceConverter()
