"""Narração em arquivo: roteiro -> falas sintetizadas (com cache) -> um áudio com as pausas e os tempos de cada fala."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import VOICE_CACHE_DIR
from ..filtergraph.voice import narration_concat_command
from ..media.ffmpeg import FFmpegRunner
from ..media.wavio import wav_duration, write_wav
from ..text.captions import Cue, to_srt
from ..voice.library import VoiceProfile
from ..voice.postprocess import POSTPROCESS_VERSION, finish_speech
from ..voice.script import Utterance, normalize_for_speech, parse_script
from ..voice.synth import SpeechSynthesizer, VoiceRequest

DEFAULT_STEPS: int | None = None  # passos de síntese: None deixa cada motor escolher o seu padrão


@dataclass(frozen=True)
class NarrationResult:
    path: Path
    duration: float
    cues: list[tuple[float, float, str]] = field(default_factory=list)  # (início, fim, texto) de cada fala
    srt_path: Path | None = None


def cue_timeline(spans: list[tuple[float, Utterance]]) -> tuple[list[tuple[float, float, str]], float]:
    """Início e fim de cada fala na narração montada (fala + pausa depois) e a duração total.

    `spans` traz a duração real de cada fala; função pura, para o cálculo ser testável sem áudio.
    """
    cues: list[tuple[float, float, str]] = []
    cursor = 0.0
    for duration, utterance in spans:
        cues.append((cursor, cursor + duration, utterance.text))
        cursor += duration + utterance.pause_after
    total = cursor - (spans[-1][1].pause_after if spans else 0.0)
    return cues, total


class NarrationService:
    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        runner: FFmpegRunner,
        cache_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.synthesizer = synthesizer
        self.runner = runner
        self.cache_dir = cache_dir or VOICE_CACHE_DIR
        self.log = log or (lambda _message: None)

    def cache_key(self, request: VoiceRequest) -> str:
        """Tudo que muda o som da fala entra na chave; o que não muda reaproveita o arquivo."""
        voice = request.voice.fingerprint() if request.voice else "-"
        identity = getattr(self.synthesizer, "cache_identity", None)
        parts = [
            identity(request) if identity else self.synthesizer.engine_id,
            voice,
            request.instruct or "",
            POSTPROCESS_VERSION,
            request.text,
            request.language,
            f"{request.speed:g}",
            "" if request.steps is None else str(request.steps),
            "" if request.seed is None else str(request.seed),
        ]
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()

    def _cache_path(self, request: VoiceRequest) -> Path:
        return self.cache_dir / f"{self.cache_key(request)}.wav"

    def _speak(self, request: VoiceRequest) -> tuple[Path, float]:
        """Arquivo da fala (do cache ou recém-sintetizado) e a duração dele."""
        path = self._cache_path(request)
        if not path.exists():
            speech = self.synthesizer.synthesize(request)
            write_wav(path, finish_speech(speech.samples, speech.sample_rate), speech.sample_rate)
        return path, wav_duration(path)

    @staticmethod
    def _request(
        utterance: Utterance,
        voice: VoiceProfile | None,
        language: str,
        speed: float,
        instruct: str | None,
        seed: int | None,
        steps: int | None,
    ) -> VoiceRequest:
        return VoiceRequest(
            text=normalize_for_speech(utterance.text, language),
            language=language,
            voice=voice,
            instruct=instruct,
            speed=speed,
            steps=steps,
            seed=seed,
        )

    def cached_duration(
        self,
        text: str,
        voice: VoiceProfile | None,
        language: str = "pt",
        speed: float = 1.0,
        instruct: str | None = None,
        seed: int | None = None,
        steps: int | None = DEFAULT_STEPS,
    ) -> float | None:
        """Duração da narração quando todas as falas já estão no cache; None se alguma faltar.

        Serve para mostrar o tempo real na linha do tempo sem pagar uma síntese.
        """
        utterances = parse_script(text)
        spans: list[tuple[float, Utterance]] = []
        for utterance in utterances:
            path = self._cache_path(self._request(utterance, voice, language, speed, instruct, seed, steps))
            if not path.exists():
                return None
            spans.append((wav_duration(path), utterance))
        return cue_timeline(spans)[1] if spans else None

    def render(
        self,
        text: str,
        out: Path,
        voice: VoiceProfile | None,
        language: str = "pt",
        speed: float = 1.0,
        instruct: str | None = None,
        seed: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        write_srt: bool = False,
        steps: int | None = DEFAULT_STEPS,
        master: bool = True,
    ) -> NarrationResult:
        utterances = parse_script(text)
        if not utterances:
            raise ValueError("O texto da narração está vazio.")
        parts: list[tuple[Path, float]] = []
        spans: list[tuple[float, Utterance]] = []
        for index, utterance in enumerate(utterances, 1):
            self.log(f"Fala {index} de {len(utterances)}")
            if on_progress:
                on_progress(index, len(utterances))
            request = self._request(utterance, voice, language, speed, instruct, seed, steps)
            path, duration = self._speak(request)
            parts.append((path, utterance.pause_after))
            spans.append((duration, utterance))

        cues, total = cue_timeline(spans)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.log("Montando a narração")
        self.runner.run(narration_concat_command(parts, out, total=total, master=master))
        srt_path = self._write_srt(out, cues) if write_srt else None
        return NarrationResult(out, total, cues, srt_path)

    @staticmethod
    def _write_srt(out: Path, cues: list[tuple[float, float, str]]) -> Path:
        srt_path = out.with_suffix(".srt")
        srt_path.write_text(to_srt([Cue(start, end, text) for start, end, text in cues]), encoding="utf-8")
        return srt_path
