"""Transcrição de fala em cues com tempo por palavra.

`Transcriber` é o protocolo que o pipeline usa; `WhisperTranscriber` implementa com faster-whisper
(open source, roda local). Testes injetam um transcritor falso.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..config import MODELS_DIR
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner
from .captions import Cue, Word


@dataclass
class Transcript:
    cues: list[Cue]
    meta: dict = field(default_factory=dict)


class Transcriber(Protocol):
    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript: ...


def extract_audio_wav(runner: FFmpegRunner, src: Path, dst: Path) -> Path:
    """Áudio mono 16 kHz, o formato que os modelos de fala esperam."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    runner.run(FFmpegCommand(args, label="áudio para transcrição"))
    return dst


@dataclass
class WhisperTranscriber:
    """faster-whisper. device "cpu" (padrão; "auto" causa falha de segmentação em máquinas sem CUDA) ou "cuda"."""

    model: str = "small"
    device: str = "cpu"
    compute_type: str | None = None

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "faster-whisper não instalado. Rode: .venv\\Scripts\\pip install -e .[captions]"
            ) from exc

        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        compute_type = self.compute_type or ("float16" if self.device == "cuda" else "int8")
        threads = max(1, min(os.cpu_count() or 4, 8))
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model = WhisperModel(
            self.model,
            device=self.device,
            compute_type=compute_type,
            download_root=str(MODELS_DIR),
            cpu_threads=threads,
        )
        segments, info = model.transcribe(
            str(wav),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
            initial_prompt=initial_prompt,
        )
        cues: list[Cue] = []
        for seg in segments:
            words = [
                Word(float(w.start), float(w.end), w.word.strip())
                for w in (seg.words or [])
                if w.word.strip()
            ]
            text = seg.text.strip()
            if text:
                cues.append(Cue(float(seg.start), float(seg.end), text, words))
        meta = {
            "language": info.language,
            "language_probability": float(info.language_probability),
            "model": self.model,
        }
        return Transcript(cues, meta)
