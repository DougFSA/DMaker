"""Rotas do estúdio de voz da interface: biblioteca de vozes, clonagem, design e narração em job.

Adaptador fino sobre `pipeline.voices`. As dependências pesadas (biblioteca, ffmpeg, Whisper, sintetizador)
chegam por `VoiceServices`, que os testes trocam por dublês com `app.dependency_overrides`.
A síntese na CPU é lenta, então falar e ouvir a prévia são sempre jobs com progresso por SSE.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import config
from ..media.diarization import SpeakerDiarizer
from ..media.ffmpeg import FFmpegError, FFmpegRunner
from ..media.probe import MediaInfo
from ..pipeline.isolation import IsolationService
from ..pipeline.jobs import Job, JobCancelled, JobManager
from ..pipeline.narration import NarrationCancelled
from ..text.transcribe import Transcriber
from ..text.translate import Translator
from ..voice import design as voice_design
from ..voice.lexicon_store import LexiconStore
from ..voice.library import VoiceLibrary, VoiceNotFoundError
from ..voice.pronunciation import DEFAULT_LANGUAGE, Lexicon, language_code
from ..voice.synth import SpeechSynthesizer

SERVABLE_AUDIO_EXTS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".flac",
    ".mp4",
    ".m4v",
    ".mov",
}  # vídeo toca como áudio no <audio>
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 5 a 8 s de fala cabem em poucos MB; isto só barra arquivo errado
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_SCRIPT_CHARS = 20000  # ~24 minutos de fala: muito além de um vídeo curto, e protege a fila da CPU
VOICE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # o que `slugify` produz; barra "..", "/" e afins

# idiomas oferecidos nos selects; o modelo fala centenas, estes são os que o editor usa no dia a dia
LANGUAGES = [
    {"value": "pt", "label": "Português"},
    {"value": "en", "label": "Inglês"},
    {"value": "es", "label": "Espanhol"},
    {"value": "fr", "label": "Francês"},
    {"value": "de", "label": "Alemão"},
    {"value": "it", "label": "Italiano"},
]

# o vocabulário do VoiceDesign guarda apelidos sem acento (para casar o que se digita); na tela vai com acento
DISPLAY_LABELS = {
    "crianca": "criança",
    "medio": "médio",
    "britanico": "britânico",
    "chines": "chinês",
    "portugues": "português",
    "japones": "japonês",
}

# uma síntese por vez: o modelo ocupa a CPU toda, e duas ao mesmo tempo só deixariam as duas mais lentas
_synthesis_lock = threading.Lock()
QUEUE_POLL_S = 0.25  # de quanto em quanto tempo quem espera na fila confere se foi cancelado


@dataclass
class VoiceServices:
    """Dependências do estúdio de voz; `None` em runner, transcritor e sintetizador usa os reais do pipeline."""

    library: VoiceLibrary
    runner: FFmpegRunner | None = None
    transcriber: Transcriber | None = None
    synthesizer: SpeechSynthesizer | None = None
    lexicons: LexiconStore | None = None  # dicionários de pronúncia; None usa os de assets/
    isolation: IsolationService | None = None  # separador de voz e fundo; None usa o Demucs
    prober: Callable[[Path], MediaInfo] | None = None  # leitor de mídia; None usa o ffprobe
    translator: Translator | None = None  # tradutor da dublagem; None usa o Ollama local
    diarizer: SpeakerDiarizer | None = (
        None  # separação de falantes da dublagem; None usa o sherpa-onnx, se instalado
    )


def get_voice_services() -> VoiceServices:
    return VoiceServices(library=VoiceLibrary())


Services = Annotated[VoiceServices, Depends(get_voice_services)]


class DesignRequest(BaseModel):
    name: str
    gender: str | None = None
    age: str | None = None
    pitch: str | None = None
    accent: str | None = None
    whisper: bool = False
    instruct: str | None = None
    brand: str | None = None
    language: str = "pt"


class SpeakRequest(BaseModel):
    text: str = Field(max_length=MAX_SCRIPT_CHARS)
    voice: str | None = None
    language: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    seed: int | None = None
    instruct: str | None = None
    brand: str | None = None  # marca cujo dicionário de pronúncia vale (padrão: a da voz)


class PronunciationRequest(BaseModel):
    term: str
    spoken: str
    brand: str | None = None
    language: str = DEFAULT_LANGUAGE


def design_options() -> dict[str, Any]:
    """Vocabulário do VoiceDesign no formato dos selects da página: valor canônico e rótulo em português."""

    def entries(table: dict[str, tuple[str, ...]]) -> list[dict[str, str]]:
        return [
            {"value": canonical, "label": DISPLAY_LABELS.get(aliases[0], aliases[0])}
            for canonical, aliases in table.items()
        ]

    return {
        "gender": entries(voice_design.GENDERS),
        "age": entries(voice_design.AGES),
        "pitch": entries(voice_design.PITCHES),
        "accent": entries(voice_design.ACCENTS),
        "languages": LANGUAGES,
    }


def audio_url(path: Path) -> str:
    return "/api/voices/audio?" + urlencode({"path": path.resolve().as_posix()})


def narration_output_path(text: str, **options: Any) -> Path:
    """Arquivo da narração: o nome muda com texto e opções, para vozes diferentes não se sobrescreverem."""
    digest = hashlib.sha1(json.dumps([text, options], sort_keys=True).encode()).hexdigest()[:10]
    return config.OUTPUT_DIR / f"narracao-{digest}.wav"


def is_servable_audio(path: Path) -> bool:
    """Só áudio dentro de output/ ou cache/voice: a página nunca lê arquivo arbitrário do disco por aqui."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return False
    if resolved.suffix.lower() not in SERVABLE_AUDIO_EXTS or not resolved.is_file():
        return False
    return any(
        resolved.is_relative_to(root.resolve()) for root in (config.OUTPUT_DIR, config.VOICE_CACHE_DIR)
    )


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def existing_voice(library: VoiceLibrary, voice_id: str) -> None:
    if not VOICE_ID_PATTERN.match(voice_id):
        raise HTTPException(status_code=404, detail=f"Voz {voice_id!r} não encontrada.")
    try:
        library.get(voice_id)
    except VoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def pronunciation_entries(
    store: LexiconStore, brand: str | None, language: str | None = None
) -> list[dict[str, str]]:
    """Termos que valem para a marca, com idioma e escopo de onde vêm (o da marca esconde o global igual).

    Sem `language`, traz todos os idiomas; cada entrada diz o seu.
    """
    global_by_language = store.by_language()
    brand_by_language = store.by_language(brand) if brand else {}
    codes = sorted({*global_by_language, *brand_by_language})
    if language:
        codes = [code for code in codes if code == language_code(language)]
    entries: list[dict[str, str]] = []
    for code in codes:
        own = brand_by_language.get(code, Lexicon())
        hidden = {term.casefold() for term, _ in own.entries}
        inherited = [
            (term, spoken, "global")
            for term, spoken in global_by_language.get(code, Lexicon()).entries
            if term.casefold() not in hidden
        ]
        owned = [(term, spoken, brand) for term, spoken in own.entries]
        for term, spoken, scope in sorted(inherited + owned, key=lambda item: item[0].casefold()):
            entries.append({"term": term, "spoken": spoken, "scope": scope, "language": code})
    return entries


def _save_upload(upload: UploadFile, folder: Path) -> Path:
    """Grava o arquivo enviado em disco (o ffmpeg lê por caminho), recusando o que passa do limite."""
    suffix = re.sub(r"[^a-z0-9.]", "", Path(upload.filename or "").suffix.lower())[:6] or ".bin"
    destination = folder / f"referencia{suffix}"
    written = 0
    with destination.open("wb") as handle:
        while chunk := upload.file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413, detail="Arquivo grande demais para uma gravação de referência."
                )
            handle.write(chunk)
    if not written:
        raise HTTPException(status_code=400, detail="O arquivo de áudio enviado está vazio.")
    return destination


def _progress_reporter(job: Job):
    """Cada fala vira evento SSE de progresso ("fala i de n"), além do campo lido pela listagem de jobs."""

    def report(done: int, total: int) -> None:
        job.progress = {
            "label": f"fala {done} de {total}",
            "done": done,
            "total": total,
            "percent": int(100 * (done - 1) / total),
        }
        job.emit("progress", **job.progress)

    return report


def _utterance_reporter(job: Job):
    """Cada fala pronta vira o evento SSE `utterance`, com a URL do pedaço (no cache de falas, que é servível)."""

    def report(index: int, total: int, path: Path, duration: float, pause_after: float) -> None:
        job.emit(
            "utterance",
            index=index,
            total=total,
            audio_url=audio_url(path),
            duration_s=round(duration, 3),
            pause_after_s=round(pause_after, 3),
        )

    return report


@contextmanager
def hold_synthesis(
    on_wait: Callable[[str], None], cancelled: Callable[[], bool] = lambda: False
) -> Iterator[None]:
    """Segura a trava de síntese; se outro trabalho a tem, avisa por `on_wait` e espera a vez.

    Quem está esperando na fila pode ser cancelado (`cancelled`) sem nunca ter ocupado a CPU.
    """
    if not _synthesis_lock.acquire(blocking=False):
        on_wait("Aguardando outro trabalho de voz terminar")
        while not _synthesis_lock.acquire(timeout=QUEUE_POLL_S):
            if cancelled():
                raise JobCancelled("Cancelado na fila.", result={"ready": 0, "total": 0})
    try:
        yield
    finally:
        _synthesis_lock.release()


def exclusive_synthesis(job: Job) -> AbstractContextManager[None]:
    """Só um trabalho pesado de voz por vez (síntese, separação, transcrição); os outros esperam na fila."""
    return hold_synthesis(job.log, lambda: job.cancel_requested)


def _run_speech(job: Job, services: VoiceServices, text: str, out: Path, options: dict[str, Any]) -> dict:
    from ..pipeline.voices import speak

    with exclusive_synthesis(job):
        try:
            result = speak(
                text,
                out,
                on_progress=_progress_reporter(job),
                log=job.log,
                library=services.library,
                runner=services.runner,
                synthesizer=services.synthesizer,
                lexicons=services.lexicons,
                on_utterance=_utterance_reporter(job),
                should_stop=lambda: job.cancel_requested,
                **options,
            )
        except NarrationCancelled as stop:
            job.log(f"Parado depois da fala {stop.ready} de {stop.total}; o que já saiu ficou guardado")
            raise JobCancelled(str(stop), result={"ready": stop.ready, "total": stop.total}) from stop
    return {
        "output": str(result.path),
        "audio_url": audio_url(result.path),
        "duration_s": round(result.duration, 2),
        "cues": [{"start": round(s, 2), "end": round(e, 2), "text": t} for s, e, t in result.cues],
    }


def build_voice_router(jobs: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api/voices", tags=["voz"])

    @router.get("")
    def list_voices(services: Services, brand: str | None = None) -> list[dict]:
        from ..pipeline.voices import profile_dict

        return [profile_dict(p) for p in services.library.list(brand=brand)]

    @router.get("/design-options")
    def get_design_options() -> dict:
        return design_options()

    @router.get("/audio")
    def get_audio(path: str, download: bool = False) -> FileResponse:
        target = Path(path)
        if not is_servable_audio(target):
            raise HTTPException(status_code=404, detail="Áudio não encontrado ou fora das pastas permitidas.")
        return FileResponse(target, filename=target.name if download else None)

    @router.post("/clone")
    def clone(
        services: Services,
        name: Annotated[str, Form()],
        audio: Annotated[UploadFile, File()],
        reference_text: Annotated[str | None, Form()] = None,
        brand: Annotated[str | None, Form()] = None,
        language: Annotated[str, Form()] = "pt",
    ) -> dict:
        from ..pipeline.voices import clone_voice, profile_dict

        with tempfile.TemporaryDirectory(prefix="dmaker-voz-") as folder:
            reference = _save_upload(audio, Path(folder))
            try:
                profile = clone_voice(
                    name,
                    reference,
                    reference_text=reference_text or None,
                    brand=brand or None,
                    language=language,
                    library=services.library,
                    runner=services.runner,
                    transcriber=services.transcriber,
                )
            except FFmpegError as exc:
                raise HTTPException(status_code=400, detail="Não foi possível ler o áudio enviado.") from exc
            except (ValueError, FileNotFoundError) as exc:
                raise _bad_request(exc) from exc
        return profile_dict(profile)

    @router.post("/design")
    def design(req: DesignRequest, services: Services) -> dict:
        from ..pipeline.voices import design_voice, profile_dict

        try:
            profile = design_voice(
                req.name,
                req.gender,
                req.age,
                req.pitch,
                req.accent,
                req.whisper,
                req.instruct or None,
                req.brand or None,
                req.language,
                library=services.library,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return profile_dict(profile)

    @router.get("/pronunciation")
    def list_pronunciation(services: Services, brand: str | None = None, language: str | None = None) -> dict:
        store = services.lexicons or LexiconStore()
        try:
            return {"brand": brand, "entries": pronunciation_entries(store, brand or None, language or None)}
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.post("/pronunciation")
    def save_pronunciation(req: PronunciationRequest, services: Services) -> dict:
        store = services.lexicons or LexiconStore()
        try:
            store.add(req.term, req.spoken, req.brand or None, req.language)
            return {"brand": req.brand, "entries": pronunciation_entries(store, req.brand or None)}
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.delete("/pronunciation")
    def remove_pronunciation(
        services: Services, term: str, brand: str | None = None, language: str = DEFAULT_LANGUAGE
    ) -> dict:
        store = services.lexicons or LexiconStore()
        try:
            store.remove(term, brand or None, language)
            return {"brand": brand, "entries": pronunciation_entries(store, brand or None)}
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.delete("/{voice_id}")
    def remove(voice_id: str, services: Services) -> dict:
        existing_voice(services.library, voice_id)
        services.library.remove(voice_id)
        return {"ok": True}

    @router.post("/speak")
    def speak_text(req: SpeakRequest, services: Services) -> dict:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Escreva o texto da narração.")
        if req.voice:
            existing_voice(services.library, req.voice)
        options = {
            "voice_id": req.voice or None,
            "language": req.language or None,
            "speed": req.speed,
            "instruct": req.instruct or None,
            "seed": req.seed,
            "brand": req.brand or None,
        }
        voice = services.library.get(req.voice) if req.voice else None
        spoken_language = req.language or (voice.language if voice else DEFAULT_LANGUAGE)
        try:
            pronunciation = (services.lexicons or LexiconStore()).for_brand(
                req.brand or (voice.brand if voice else None), spoken_language
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        # a pronúncia entra no nome: trocar o dicionário e narrar de novo não pode devolver o arquivo antigo
        out = narration_output_path(text, pronunciation=pronunciation.as_dict(), **options)
        job = jobs.start(
            f"narração ({req.voice or 'voz automática'}, {len(text)} caracteres)",
            lambda job: _run_speech(job, services, text, out, options),
            meta={"kind": "voice", "cancellable": True},
        )
        return {"job_id": job.id}

    @router.post("/{voice_id}/preview")
    def preview(voice_id: str, services: Services) -> dict:
        from ..pipeline.voices import PREVIEW_TEXTS

        existing_voice(services.library, voice_id)
        voice = services.library.get(voice_id)
        text = PREVIEW_TEXTS.get(voice.language, PREVIEW_TEXTS["pt"])
        options = {"voice_id": voice.id, "language": voice.language, "speed": 1.0, "seed": 1}
        out = config.OUTPUT_DIR / f"voz-{voice.id}-amostra.wav"
        job = jobs.start(
            f"prévia da voz {voice.name}",
            lambda job: _run_speech(job, services, text, out, options),
            meta={"kind": "voice", "cancellable": True},
        )
        return {"job_id": job.id}

    return router
