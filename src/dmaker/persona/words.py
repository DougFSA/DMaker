"""Palavras com tempo quando o transcritor não devolve nenhuma (função pura)."""

from __future__ import annotations


def evenly_timed_words(text: str, duration: float) -> list[tuple[float, float, str]]:
    """As palavras de `text` espalhadas por `duration`, cada uma pelo tamanho dela (mais o espaço).

    É o plano B da boca: o texto da fala é conhecido, só o tempo de cada palavra não é. O erro é de poucos décimos de
    segundo, bem menos que uma boca parada."""
    tokens = text.split()
    weights = [len(token) + 1 for token in tokens]
    total = sum(weights)
    if not tokens or duration <= 0:
        return []
    words: list[tuple[float, float, str]] = []
    cursor = 0.0
    for token, weight in zip(tokens, weights, strict=True):
        step = duration * weight / total
        words.append((cursor, cursor + step * 0.92, token))  # um respiro curto entre uma palavra e outra
        cursor += step
    return words
