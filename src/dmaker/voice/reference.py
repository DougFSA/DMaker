"""Escolha do trecho de referência de uma voz clonada: a janela de 15 s com mais fala.

Segue o VoiceStudio: o modelo só alinha uma transcrição a até 20 s de áudio, então uma gravação maior é
cortada em janelas de 15 s, cada janela é transcrita e vence a que tem mais fala (empate: mais energia).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..media.wavio import read_wav, write_wav
from ..text.captions import Word
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


# ---------- referência a partir de palavras com tempo ----------

MIN_SPAN_SECONDS = (
    3.0  # abaixo disso o clone fica instável (limiar do VoiceStudio para referência por trecho)
)
IDEAL_SPAN_SECONDS = 8.0  # longo o bastante para a prosódia, curto o bastante para a síntese não encarecer
MAX_GAP_SECONDS = 0.6  # pausa maior que esta quebra a fala em dois blocos: a referência é um bloco só
AVOID_MARGIN_SECONDS = 0.2  # folga em volta do trecho a corrigir, onde a fala já está contaminada
NEAR_BUCKET_SECONDS = 2.0  # distâncias dentro da mesma faixa de 2 s contam como igualmente perto


@dataclass(frozen=True)
class ReferenceSpan:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def _runs(words: list[Word], avoid: tuple[float, float] | None) -> list[list[Word]]:
    """Blocos de fala contínua (sem pausa grande) que não tocam a zona a evitar (`None`: nenhuma)."""
    runs: list[list[Word]] = [[]]
    for word in words:
        touches = avoid is not None and (
            word.end > avoid[0] - AVOID_MARGIN_SECONDS and word.start < avoid[1] + AVOID_MARGIN_SECONDS
        )
        if touches or (runs[-1] and word.start - runs[-1][-1].end > MAX_GAP_SECONDS):
            runs.append([])
        if not touches:
            runs[-1].append(word)
    return [run for run in runs if run]


def choose_reference_span(words: list[Word], avoid_start: float, avoid_end: float) -> ReferenceSpan | None:
    """Trecho de fala contínua de 3 a 15 s, o mais perto de 8 s, longe do trecho a corrigir.

    É a referência do clone temporário do falante: precisa ser a voz dele (por isso fora do trecho errado,
    que pode estar truncado ou ruidoso) e ter as palavras exatas, que o modelo usa para alinhar a voz.
    Empate de duração: maior confiança do Whisper, depois o mais perto do trecho (mesmo som de sala).
    """
    anchor = (avoid_start + avoid_end) / 2

    def score(duration: float, confidence: float, distance: float) -> tuple[float, ...]:
        return (round(abs(duration - IDEAL_SPAN_SECONDS) * 2) / 2, -confidence, distance)

    return _best_span(_runs(words, (avoid_start, avoid_end)), anchor, score)


def choose_reference_near(
    words: list[Word], around: tuple[float, float] | None = None
) -> ReferenceSpan | None:
    """Trecho de fala contínua de 3 a 15 s que cobre ou fica mais perto de `around`, a voz de quem fala ali.

    Na dublagem a referência de cada fala é a própria fala (ou a vizinha, se ela for curta demais): num vídeo
    com vários falantes, a proximidade vale mais que a duração ideal, e só dentro de cada faixa de 2 s de
    distância a duração mais perto de 8 s desempata. Sem `around`, vale o melhor trecho do arquivo todo
    (modo de um falante só): duração ideal, depois confiança.
    """
    anchor = None if around is None else (around[0] + around[1]) / 2

    def score(duration: float, confidence: float, distance: float) -> tuple[float, ...]:
        closeness = 0.0 if anchor is None else float(round(distance / NEAR_BUCKET_SECONDS))
        return (closeness, round(abs(duration - IDEAL_SPAN_SECONDS) * 2) / 2, -confidence, distance)

    return _best_span(_runs(words, None), anchor if anchor is not None else 0.0, score)


def _best_span(
    runs: list[list[Word]],
    anchor: float,
    score: Callable[[float, float, float], tuple[float, ...]],
) -> ReferenceSpan | None:
    """O trecho de 3 a 15 s de menor `score(duração, confiança, distância ao âncora)` entre os blocos."""
    best: tuple[tuple[float, ...], ReferenceSpan] | None = None
    for run in runs:
        for first in range(len(run)):
            for last in range(first, len(run)):
                duration = run[last].end - run[first].start
                if duration > WINDOW_SECONDS:
                    break
                if duration < MIN_SPAN_SECONDS:
                    continue
                span = run[first : last + 1]
                confidence = sum(0.5 if w.probability is None else w.probability for w in span) / len(span)
                distance = abs((span[0].start + span[-1].end) / 2 - anchor)
                candidate = score(duration, confidence, distance)
                if best is None or candidate < best[0]:
                    best = (
                        candidate,
                        ReferenceSpan(span[0].start, span[-1].end, " ".join(w.text for w in span)),
                    )
    return best[1] if best else None
