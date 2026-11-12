"""A previsão do tempo de render das personas realistas de um projeto, antes de qualquer fala ser sintetizada.

Funções puras: recebem a spec e duas funções (o tipo de uma persona e a duração de um áudio dado) e devolvem números e
texto. O render e o MCP chamam daqui; quem sabe se o computador tem GPU integrada é o motor, que entra por parâmetro.
"""

from __future__ import annotations

from collections.abc import Callable

from ..domain.persona import PersonaSpeech, estimate_speech_seconds
from ..domain.spec import PersonaOverlay, PersonaSegment, Project
from ..media.talking_head import estimate_seconds, format_duration, frame_count

REALISTIC_KIND = "realistic"


def _speech_seconds(speech: PersonaSpeech, audio_seconds: Callable[[str], float | None]) -> float:
    """A duração da fala: a do arquivo dado, ou a estimada pelo tamanho do texto (a mesma régua do QA)."""
    if speech.audio:
        known = audio_seconds(speech.audio)
        if known:
            return known
    return estimate_speech_seconds(speech.text or "", speech.speed)


def realistic_clip_seconds(
    project: Project, kind_of: Callable[[str], str], audio_seconds: Callable[[str], float | None]
) -> list[float]:
    """A duração estimada de cada clipe realista que o render vai desenhar, sem repetir a mesma fala da mesma
    persona (o segundo clipe igual sai do cache do primeiro)."""
    seen: set[tuple[str, str]] = set()
    durations: list[float] = []
    for item in [*project.timeline, *project.overlays]:
        if not isinstance(item, PersonaSegment | PersonaOverlay) or kind_of(item.persona) != REALISTIC_KIND:
            continue
        key = (item.persona, item.speech.model_dump_json())
        if key in seen:
            continue
        seen.add(key)
        speech = _speech_seconds(item.speech, audio_seconds)
        if isinstance(item, PersonaSegment):
            durations.append(item.duration if item.duration is not None else speech + item.tail)
        else:
            durations.append(item.end - item.start if item.end is not None else speech)
    return durations


def total_estimate_seconds(durations: list[float], has_gpu: bool) -> float:
    """A soma das estimativas: cada clipe paga o preparo fixo dele, porque cada um sobe o seu worker."""
    return sum(estimate_seconds(frame_count(duration), has_gpu) for duration in durations)


def forecast_message(durations: list[float], has_gpu: bool) -> str | None:
    """A linha do início do render (ou None se o projeto não tem persona realista). Só dá para saber o que está em
    cache depois de sintetizar a fala, então o número é um teto."""
    if not durations:
        return None
    total = format_duration(total_estimate_seconds(durations, has_gpu))
    clips = f"{len(durations)} clipe" + ("s" if len(durations) > 1 else "")
    where = "GPU integrada" if has_gpu else "só CPU, bem mais lento"
    return (
        f"persona realista: até {total} no total ({clips}, {where}), com o computador livre e se nada estiver "
        "em cache; outros programas pesados aumentam o tempo"
    )
