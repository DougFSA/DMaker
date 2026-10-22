"""Escolha do trecho de referência de uma voz clonada: a janela de 15 s com mais fala.

Segue o VoiceStudio: o modelo só alinha uma transcrição a até 20 s de áudio, então uma gravação maior é
cortada em janelas de 15 s, cada janela é transcrita e vence a que tem mais fala (empate: mais energia).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..media.wavio import read_wav, write_wav
from ..text.transcribe import Transcriber

KEEP_WHOLE_SECONDS = 20.0  # até aqui a referência inteira vale (o modelo alinha a transcrição)
WINDOW_SECONDS = 15.0
MAX_WINDOWS = 8  # limita o custo de transcrição: gravações maiores que 2 min são cortadas no começo


def speech_score(text: str) -> int:
    """Quanto há de fala num texto: letras e dígitos, sem pontuação nem espaços."""
    return len(re.sub(r"[^\w]+", "", text or "", flags=re.UNICODE))


def split_windows(samples: np.ndarray, sample_rate: int) -> list[np.ndarray]:
    """Janelas consecutivas de 15 s (a última pode ser mais curta), no máximo `MAX_WINDOWS`."""
    size = int(WINDOW_SECONDS * sample_rate)
    windows = [samples[start : start + size] for start in range(0, len(samples), size)]
    return [window for window in windows[:MAX_WINDOWS] if len(window)]


def choose_window(scores: list[int], energies: list[float]) -> int | None:
    """Índice da janela com mais fala; no empate, a de maior energia. None se nenhuma tem fala."""
    best: int | None = None
    for index, score in enumerate(scores):
        if score <= 0:
            continue
        if best is None or (score, energies[index]) > (scores[best], energies[best]):
            best = index
    return best


def select_best_window(wav: Path, transcriber: Transcriber, language: str) -> str:
    """Reescreve `wav` só com a melhor janela de 15 s e devolve o texto dela."""
    samples, sample_rate = read_wav(wav)
    windows = split_windows(samples, sample_rate)
    texts: list[str] = []
    window_file = wav.with_name(f".{wav.stem}-janela.wav")
    try:
        for window in windows:
            write_wav(window_file, window, sample_rate)
            transcript = transcriber.transcribe(window_file, language)
            texts.append(" ".join(cue.text.strip() for cue in transcript.cues).strip())
    finally:
        window_file.unlink(missing_ok=True)
    scores = [speech_score(text) for text in texts]
    energies = [float(np.sum(np.square(window, dtype=np.float64))) for window in windows]
    best = choose_window(scores, energies)
    if best is None:
        raise ValueError("Não encontrei fala na gravação de referência; use uma gravação com a voz limpa.")
    write_wav(wav, windows[best], sample_rate)
    return texts[best]
