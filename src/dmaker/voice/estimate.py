"""Tempo estimado da fila de narração, a partir da velocidade que a própria máquina mostrou.

Funções puras. Enquanto não há medida, vale um chute inicial por motor e por qualidade; depois, a média das
últimas falas sintetizadas (segundos de processamento por caractere) substitui o chute.
"""

from __future__ import annotations

from collections.abc import Iterable

# Chute inicial, em segundos de processamento por caractere do texto falado. Vem da medida na CPU desta
# máquina: o OmniVoice a 16 passos custa ~20 s por segundo de áudio e a fala corre a ~14 caracteres por
# segundo, logo 20 / 14 ~ 1,4 s por caractere; a 8 passos (rascunho) é metade. O Kokoro faz ~3 s por segundo
# de áudio (~0,2 s por caractere) e não muda com os passos.
DEFAULT_SECONDS_PER_CHAR: dict[tuple[str, bool], float] = {
    ("omnivoice", False): 1.4,
    ("omnivoice", True): 0.7,
    ("kokoro", False): 0.2,
    ("kokoro", True): 0.2,
}
FALLBACK_SECONDS_PER_CHAR = 1.4  # motor que não está na tabela: assume o mais lento
MAX_SAMPLES = 40  # quantas falas recentes entram na média; mais que isso ficaria preso a um texto antigo

Sample = tuple[int, float]  # (caracteres falados, segundos de processamento)


def speed_key(engine: str, draft: bool) -> str:
    """Chave das medidas: motor e qualidade andam em velocidades muito diferentes, então não se misturam."""
    return f"{engine}:{'draft' if draft else 'final'}"


def default_seconds_per_char(engine: str, draft: bool) -> float:
    return DEFAULT_SECONDS_PER_CHAR.get((engine, draft), FALLBACK_SECONDS_PER_CHAR)


def seconds_per_char(samples: Iterable[Sample], fallback: float) -> float:
    """Média ponderada pelos caracteres das últimas medidas; sem medida válida, devolve o chute `fallback`."""
    valid = [(chars, seconds) for chars, seconds in samples if chars > 0 and seconds > 0]
    recent = valid[-MAX_SAMPLES:]
    total_chars = sum(chars for chars, _ in recent)
    if not total_chars:
        return fallback
    return sum(seconds for _, seconds in recent) / total_chars


def remaining_seconds(chars_left: int, per_char: float) -> float:
    return max(0, chars_left) * per_char


def append_samples(samples: Iterable[Sample], new: Iterable[Sample]) -> list[Sample]:
    """Junta as medidas novas às antigas guardando só as `MAX_SAMPLES` mais recentes."""
    return [*samples, *new][-MAX_SAMPLES:]


def format_duration(seconds: float) -> str:
    """ "2 h 05 min", "12 min" ou "40 s": duração longa em unidade que se lê de relance."""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"
