"""A resposta de frequência de um efeito de equalização, como a interface, o MCP e a CLI a entregam.

Serviço fino sobre `filtergraph.audio_effects.frequency_response`: valida o efeito como a spec valida, escolhe as
frequências do gráfico (em oitavas, de 20 Hz a 20 kHz) e devolve `{hz, db}` em listas. Só numpy, sem ffmpeg nem disco:
é rápido o bastante para a interface pedir de novo a cada ajuste de um controle.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..analysis.eq_curve import display_frequencies
from ..domain.audio_effects import parse_effect
from ..filtergraph.audio_effects import frequency_response

DEFAULT_POINTS = 256
MIN_POINTS = 8
MAX_POINTS = 2048


def effect_frequency_response(effect: dict[str, Any], points: int = DEFAULT_POINTS) -> dict[str, list[float]]:
    """O ganho em dB do efeito em `points` frequências em oitavas, de 20 Hz a 20 kHz. Efeito inválido ou sem resposta de
    frequência (os que não são de equalização) é `ValueError` com o motivo."""
    if not MIN_POINTS <= points <= MAX_POINTS:
        raise ValueError(f"pontos do gráfico fora do possível: {points} (use de {MIN_POINTS} a {MAX_POINTS})")
    try:
        parsed = parse_effect(effect)
    except ValidationError as exc:
        raise ValueError(_first_reason(exc)) from exc
    if not parsed.has_response:
        raise ValueError(
            f"o efeito {parsed.type!r} não tem resposta de frequência (só os de equalização têm)"
        )
    hz = display_frequencies(points)
    db = frequency_response(parsed, hz)
    return {"hz": [round(float(value), 2) for value in hz], "db": [round(float(value), 3) for value in db]}


def _first_reason(error: ValidationError) -> str:
    """O primeiro motivo da recusa do Pydantic, em uma linha (campo e mensagem), sem o ruído de endereço de página."""
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"] if part != "type")
    return f"{where}: {first['msg']}" if where else str(first["msg"])
