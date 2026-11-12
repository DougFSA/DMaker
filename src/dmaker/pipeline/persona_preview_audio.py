"""A fala das personas na prévia de áudio da linha do tempo: só a que já foi sintetizada, sem esperar uma síntese.

O render sintetiza a fala com a voz da persona (`PersonaStage`); a prévia do editor não pode esperar minutos de síntese a
cada edição. Aqui ela pede ao cache da narração a mesma fala (o mesmo texto, voz e ajustes) e, se ela ainda não existe,
avisa e segue sem ela, como faz com a narração do projeto.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..domain.persona import Persona, PersonaSpeech
from ..domain.spec import PersonaOverlay, PersonaSegment, Project
from ..persona.library import PersonaLibrary, PersonaNotFoundError
from ..voice.library import VoiceLibrary
from .context import Prober, RenderContext
from .narration import NarrationService
from .voiceover import PreparedVoiceover


@dataclass(frozen=True)
class HeardSpeech:
    """A fala de uma persona pronta para a mixagem: o arquivo e a duração."""

    path: Path
    duration: float


class PersonaHearing:
    """Acha (no cache) a fala de cada persona do projeto, com as dependências injetadas."""

    def __init__(
        self,
        library: PersonaLibrary,
        voices: VoiceLibrary,
        narrator: Callable[[], NarrationService],
        prober: Prober,
    ) -> None:
        self.library = library
        self.voices = voices
        self._narrator = narrator
        self._prober = prober

    def _persona(self, persona_id: str) -> Persona | None:
        try:
            return self.library.get(persona_id)
        except PersonaNotFoundError:
            return None  # a validação do projeto é quem acusa a persona que não existe

    @staticmethod
    def _settings(project: Project, speech: PersonaSpeech) -> dict:
        return {
            "language": speech.language,
            "speed": speech.speed,
            "instruct": speech.instruct,
            "seed": speech.seed,
            "brand": project.brand,
        }

    def _cached_duration(self, project: Project, persona: Persona, speech: PersonaSpeech) -> float | None:
        if speech.audio or not speech.text:
            return None
        voice = self.voices.get(persona.voice) if persona.voice else None
        return self._narrator().cached_duration(speech.text.strip(), voice, **self._settings(project, speech))

    def key_part(self, project: Project) -> list:
        """O que a mixagem ouve das personas: a fala, a voz e a duração já sintetizada (que muda quando a síntese acontece)."""
        part = []
        for item in [*project.timeline, *project.overlays]:
            if not isinstance(item, PersonaSegment | PersonaOverlay):
                continue
            persona = self._persona(item.persona)
            if persona is None:
                continue
            try:
                heard = self._cached_duration(project, persona, item.speech)
            except (OSError, ValueError):
                heard = None
            part.append([persona.id, persona.voice, item.speech.model_dump(mode="json"), heard])
        return part

    def hear(
        self, ctx: RenderContext, persona_id: str, speech: PersonaSpeech, where: str
    ) -> HeardSpeech | None:
        """A fala pronta para ouvir, ou None (com o aviso) quando ainda não foi sintetizada."""
        persona = self._persona(persona_id)
        if persona is None:
            return None
        try:
            if speech.audio:
                path = ctx.project.resolve(speech.audio)
                if not path.is_file():
                    ctx.warn(f"A fala da persona em {where} não entrou na prévia: {speech.audio} não existe.")
                    return None
                return HeardSpeech(path, self._prober(path).duration or 0.0)
            if self._cached_duration(ctx.project, persona, speech) is None:
                ctx.warn(
                    f"A fala da persona {persona.name} em {where} ainda não foi sintetizada e fica fora da prévia."
                )
                return None
            voice = self.voices.get(persona.voice) if persona.voice else None
            safe = where.replace("[", "_").replace("]", "")
            result = self._narrator().render(
                (speech.text or "").strip(),
                ctx.job_dir / f"persona_{safe}.wav",
                voice,
                **self._settings(ctx.project, speech),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            ctx.warn(f"A fala da persona em {where} não entrou na prévia: {exc}")
            return None
        return HeardSpeech(result.path, result.duration)

    def overlay_voiceovers(self, ctx: RenderContext) -> list[PreparedVoiceover]:
        """A fala de cada persona sobreposta como uma narração do projeto, na posição da sobreposição."""
        prepared = []
        for index, overlay in enumerate(ctx.project.overlays):
            if not isinstance(overlay, PersonaOverlay):
                continue
            heard = self.hear(ctx, overlay.persona, overlay.speech, f"overlays[{index}]")
            if heard is not None:
                prepared.append(
                    PreparedVoiceover(heard.path, overlay.start, overlay.speech.volume, heard.duration)
                )
        return prepared
