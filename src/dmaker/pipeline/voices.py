"""Serviços de voz usados pela CLI e pelo MCP: clonar, projetar, listar e falar.

Cada função recebe as dependências por parâmetro (biblioteca, runner, transcritor, sintetizador) e, quando
não recebe, usa as reais; assim os dois adaptadores ficam finos e os testes injetam dublês.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from .. import config
from ..filtergraph.voice import detection_audio_command
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from ..media.wavio import read_wav
from ..text.transcribe import Transcriber, WhisperTranscriber
from ..voice.design import VoiceDesign, parse_instruct
from ..voice.kokoro import KokoroSynthesizer
from ..voice.lexicon_store import LexiconStore
from ..voice.library import VoiceLibrary, VoiceProfile
from ..voice.provenance import describe_spans, parse_provenance
from ..voice.router import RoutingSynthesizer
from ..voice.synth import OmniVoiceSynthesizer, SpeechSynthesizer
from ..voice.watermark import (
    MESSAGE_BITS,
    MODEL_RATE,
    AudioSealWatermarker,
    Watermarker,
    WatermarkResult,
    audioseal_installed,
    default_watermarker,
)
from .context import Prober
from .narration import DEFAULT_STEPS, NarrationResult, NarrationService, UtteranceListener

PREVIEW_TEXTS = {
    "pt": "Olá, esta é a minha voz. Assim eu soo ao narrar o seu vídeo, com calma e clareza.",
    "en": "Hello, this is my voice. This is how I sound when narrating your video.",
}


def build_synthesizer(device: str = "auto") -> RoutingSynthesizer:
    """Roteador com os dois motores: Kokoro (vozes prontas, rápido) e OmniVoice (clones e vozes projetadas)."""
    return RoutingSynthesizer(
        {"kokoro": KokoroSynthesizer(), "omnivoice": OmniVoiceSynthesizer(device=device)}
    )


@lru_cache(maxsize=1)
def shared_synthesizer() -> RoutingSynthesizer:
    """Um único roteador por processo: os modelos levam segundos a minutos para carregar e ficam na memória."""
    return build_synthesizer()


def profile_dict(profile: VoiceProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "kind": profile.kind,
        "engine": profile.engine,
        "preset": profile.preset,
        "language": profile.language,
        "brand": profile.brand,
        "instruct": profile.instruct,
        "reference": str(profile.reference_path) if profile.reference_path else None,
        "reference_text": profile.reference_text,
        "created": profile.created,
    }


def clone_voice(
    name: str,
    reference_audio: Path,
    reference_text: str | None = None,
    brand: str | None = None,
    language: str = "pt",
    library: VoiceLibrary | None = None,
    runner: FFmpegRunner | None = None,
    transcriber: Transcriber | None = None,
) -> VoiceProfile:
    """Cadastra uma voz a partir de uma gravação; sem texto, o Whisper transcreve a referência."""
    return (library or VoiceLibrary()).save_clone(
        name,
        reference_audio,
        runner or SubprocessRunner(quiet=True),
        transcriber or WhisperTranscriber(),
        reference_text=reference_text,
        brand=brand,
        language=language,
    )


def design_voice(
    name: str,
    gender: str | None = None,
    age: str | None = None,
    pitch: str | None = None,
    accent: str | None = None,
    whisper: bool = False,
    instruct: str | None = None,
    brand: str | None = None,
    language: str = "pt",
    library: VoiceLibrary | None = None,
) -> VoiceProfile:
    """Cadastra uma voz descrita por atributos; `instruct` escrito à mão entra como base, os atributos sobrepõem."""
    base = parse_instruct(instruct) if instruct else VoiceDesign()
    overrides = {"gender": gender, "age": age, "pitch": pitch, "accent": accent}
    changes = {key: value for key, value in overrides.items() if value}
    if whisper:
        changes["whisper"] = True
    design = VoiceDesign.model_validate({**base.model_dump(), **changes})
    return (library or VoiceLibrary()).save_design(name, design.to_instruct(), language=language, brand=brand)


def default_narration_path(text: str) -> Path:
    digest = hashlib.sha1(text.encode()).hexdigest()[:8]
    return config.OUTPUT_DIR / f"narracao-{digest}.wav"


def speak(
    text: str,
    out: Path | None = None,
    voice_id: str | None = None,
    language: str | None = None,
    speed: float = 1.0,
    instruct: str | None = None,
    seed: int | None = None,
    steps: int | None = DEFAULT_STEPS,
    write_srt: bool = False,
    master: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
    library: VoiceLibrary | None = None,
    runner: FFmpegRunner | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    brand: str | None = None,
    lexicons: LexiconStore | None = None,
    watermark: bool = True,
    watermarker: Watermarker | None = None,
    on_utterance: UtteranceListener | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> NarrationResult:
    """Narra `text` com a voz `voice_id` (ou uma voz automática/descrita por `instruct`) e grava o áudio.

    Sem `language`, vale o idioma da voz escolhida (ou português quando não há voz). A pronúncia vem do
    dicionário global mais o da marca `brand` (sem ela, o da marca dona da voz). Toda fala sai com a marca
    d'água inaudível de voz gerada por IA; `watermark=False` (ou `DMAKER_WATERMARK=0`) a desliga.
    `on_utterance` e `should_stop` repassam à narração o aviso de cada fala pronta e o pedido de parada
    entre falas."""
    voice = (library or VoiceLibrary()).get(voice_id) if voice_id else None
    service = NarrationService(
        synthesizer or shared_synthesizer(),
        runner or SubprocessRunner(quiet=True),
        log=log,
        lexicons=(lexicons or LexiconStore()).for_brand,
        watermarker=watermarker or default_watermarker(enabled=watermark),
    )
    return service.render(
        text,
        out or default_narration_path(text),
        voice,
        language=language or (voice.language if voice else "pt"),
        speed=speed,
        instruct=instruct,
        seed=seed,
        on_progress=on_progress,
        write_srt=write_srt,
        steps=steps,
        master=master,
        brand=brand or (voice.brand if voice else None),
        on_utterance=on_utterance,
        should_stop=should_stop,
    )


def preview_voice(
    voice_id: str,
    text: str | None = None,
    out: Path | None = None,
    library: VoiceLibrary | None = None,
    runner: FFmpegRunner | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    log: Callable[[str], None] | None = None,
) -> NarrationResult:
    """Amostra curta da voz para o usuário ouvir antes de usar numa narração longa."""
    library = library or VoiceLibrary()
    voice = library.get(voice_id)
    sample = text or PREVIEW_TEXTS.get(voice.language, PREVIEW_TEXTS["pt"])
    destination = out or config.OUTPUT_DIR / f"voz-{voice.id}-amostra.wav"
    return speak(
        sample,
        destination,
        voice_id=voice.id,
        language=voice.language,
        seed=1,
        library=library,
        runner=runner,
        synthesizer=synthesizer,
        log=log,
    )


def _analyze_audio(
    path: Path, runner: FFmpegRunner | None, watermarker: Watermarker | None
) -> WatermarkResult:
    """Extrai a faixa de áudio pelo ffmpeg e pede ao detector o veredito sobre ela."""
    if watermarker is None:
        if not audioseal_installed():
            raise RuntimeError(
                "A biblioteca audioseal não está instalada. Rode: .venv\\Scripts\\pip install -e .[voice]"
            )
        watermarker = AudioSealWatermarker()
    with tempfile.TemporaryDirectory(prefix="dmaker-marca-") as scratch:
        extracted = Path(scratch) / "audio.wav"
        (runner or SubprocessRunner(quiet=True)).run(detection_audio_command(path, extracted, MODEL_RATE))
        samples, sample_rate = read_wav(extracted)
    return watermarker.detect(samples, sample_rate)


def verify_watermark(
    path: Path,
    runner: FFmpegRunner | None = None,
    watermarker: Watermarker | None = None,
    prober: Prober = probe,
    check_audio: bool = False,
) -> WatermarkResult:
    """Diz se `path` (wav, mp3, m4a, mp4...) carrega voz gerada por IA pelo DMaker, em três níveis.

    Primeiro lê a etiqueta de procedência do contêiner (o que o DMaker grava junto da voz gerada): com ela o
    veredito é "encontrada" e vale para qualquer duração, o que a marca no áudio não garante (ela não acha uma
    frase curta dentro de um vídeo longo). Sem etiqueta, a análise do áudio decide: "encontrada" só quando a
    assinatura bate, "indício" quando o detector reage sem a assinatura (música, tons) e "não encontrada".

    Sem etiqueta a análise do áudio sempre roda. Com etiqueta ela só roda se `check_audio` pedir, como informação
    adicional: leva cerca de meio segundo por segundo de áudio (8 alinhamentos) e a etiqueta já responde. A
    verificação não obedece ao `DMAKER_WATERMARK` (ele só desliga a marcação) e, sem a biblioteca, falha em vez
    de responder "sem marca" quando precisa do áudio.
    """
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    label = parse_provenance(prober(path).format_tags)
    if label is None:
        return _analyze_audio(path, runner, watermarker)
    audio = _analyze_audio(path, runner, watermarker) if check_audio else None
    return WatermarkResult(
        probability=audio.probability if audio else 0.0,
        verdict="found",
        matched_bits=audio.matched_bits if audio else None,
        origin="label",
        spans=label.spans,
        audio_verdict=audio.verdict if audio else None,
    )


VERDICT_LABELS = {"found": "encontrada", "indication": "indício, inconclusivo", "absent": "não encontrada"}


def _audio_sentence(result: WatermarkResult) -> str:
    percent = f"{result.probability * 100:.0f}%"
    bits = f"{result.matched_bits or 0} de {len(MESSAGE_BITS)} bits"
    if result.verdict == "found":
        return (
            f"Marca d'água encontrada ({percent} dos quadros, a assinatura do DMaker confere em {bits}): "
            "este áudio foi gerado por IA pelo DMaker."
        )
    if result.verdict == "indication":
        return (
            f"Indício, inconclusivo ({percent} dos quadros, mas a assinatura do DMaker confere em apenas {bits}): "
            "o detector reagiu, só que música e tons puros podem imitar a marca e só a assinatura a confirma. "
            "Não dá para afirmar que o áudio foi gerado pelo DMaker."
        )
    return (
        f"Marca d'água não encontrada ({percent} dos quadros): nada indica que o áudio tenha sido gerado pelo "
        "DMaker. Se o arquivo foi recodificado fora do DMaker a etiqueta se perdeu, e uma fala curta dentro de "
        "um vídeo longo pode não ser achada pelo áudio."
    )


def watermark_verdict(result: WatermarkResult) -> str:
    """Frase do veredito, a mesma na CLI e no MCP."""
    if result.origin == "audio":
        return _audio_sentence(result)
    where = (
        f"Trechos com voz gerada: {describe_spans(result.spans)}."
        if result.spans
        else "A voz gerada está no arquivo inteiro."
    )
    sentence = f"Etiqueta de procedência encontrada: este arquivo foi gravado pelo DMaker com voz gerada por IA. {where}"
    if result.audio_verdict is not None:
        audio = VERDICT_LABELS[result.audio_verdict]
        sentence += f" Análise do áudio: {audio} ({result.probability * 100:.0f}% dos quadros)."
    return sentence
