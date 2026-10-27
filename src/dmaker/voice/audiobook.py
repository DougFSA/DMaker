"""Saída de um audiobook: nome dos arquivos de cada capítulo e as legendas do áudio completo.

Funções puras: recebem durações e legendas por capítulo e devolvem nomes e tempos; quem grava é o pipeline.
"""

from __future__ import annotations

import re
import unicodedata

CHAPTER_GAP_SECONDS = 1.5  # silêncio entre um capítulo e o seguinte no áudio completo
COMPLETE_SUFFIX = "completo"
MAX_SLUG_CHARS = 60  # nome de arquivo no Windows tem folga, mas título de capítulo pode ser uma frase inteira

Cue = tuple[float, float, str]  # (início, fim, texto) como o NarrationResult entrega


def safe_slug(name: str, fallback: str = "narracao") -> str:
    """Nome livre vira trecho de nome de arquivo: sem acento, minúsculas, hifens; nunca vazio."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:MAX_SLUG_CHARS].strip("-")
    return slug or fallback


def chapter_filename(index: int, title: str, suffix: str) -> str:
    """ "03-o-comeco.wav": o número mantém a ordem do livro mesmo quando dois capítulos têm o mesmo título."""
    return f"{index:02d}-{safe_slug(title, 'capitulo')}.{suffix}"


def complete_filename(title: str, suffix: str) -> str:
    return f"{safe_slug(title)}-{COMPLETE_SUFFIX}.{suffix}"


def merge_chapter_cues(
    chapters: list[tuple[float, list[Cue]]], gap: float = CHAPTER_GAP_SECONDS
) -> tuple[list[Cue], float]:
    """Legendas do áudio completo e a duração dele: cada capítulo entra deslocado pelos anteriores e pelas pausas.

    `chapters` traz (duração, legendas) de cada capítulo, com os tempos relativos ao começo do capítulo.
    """
    merged: list[Cue] = []
    cursor = 0.0
    for index, (duration, cues) in enumerate(chapters):
        merged.extend((start + cursor, end + cursor, text) for start, end, text in cues)
        cursor += duration
        if index < len(chapters) - 1:
            cursor += gap
    return merged, cursor
