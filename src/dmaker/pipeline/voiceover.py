"""Narração por texto como faixa do projeto: roteiro -> fala sintetizada (com cache) -> faixa pronta para a mixagem."""

from __future__ import annotations

import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..domain.spec import Narration, Project
from ..media.ffmpeg import SubprocessRunner
from ..text.captions import Cue, Word
from ..voice.lexicon_store import LexiconStore
from ..voice.library import VoiceLibrary
from ..voice.synth import SpeechSynthesizer
from .context import RenderContext

if TYPE_CHECKING:  # pragma: no cover
    from .narration import NarrationService

# Ritmo médio da fala em português a velocidade 1: serve só para estimar a duração antes de sintetizar
# (lint e vista da linha do tempo). A duração real vem do áudio sintetizado.
CHARS_PER_SECOND = 14.0
MIN_ESTIMATE_SECONDS = 0.5  # uma narração nunca vira um item de largura zero na linha do tempo

# Falhas que só significam "não sei a duração real": roteiro ou voz sumidos, motor indisponível, wav ilegível.
_UNKNOWN_DURATION_ERRORS = (OSError, ValueError, RuntimeError, EOFError, wave.Error)

NarrationServiceFactory = Callable[[RenderContext], "NarrationService"]


@dataclass(frozen=True)
class PreparedVoiceover:
    """Narração já sintetizada e posicionada: o que a mixagem e as legendas consomem."""

    path: Path
    start: float
    volume: float
    duration: float
    cues: list[tuple[float, float, str]] = field(default_factory=list)  # tempos relativos ao início da fala

    @property
    def end(self) -> float:
        return self.start + self.duration


def narration_text(project: Project, narration: Narration) -> str:
    """Texto a falar: o de `text` ou o conteúdo do roteiro `script` (relativo à pasta do projeto)."""
    if narration.text:
        return narration.text
    assert narration.script is not None  # garantido pelo validador de Narration
    path = project.resolve(narration.script)
    if not path.exists():
        raise FileNotFoundError(f"Roteiro da narração não encontrado: {narration.script}")
    return path.read_text(encoding="utf-8")


def estimate_speech_duration(text: str, speed: float = 1.0) -> float:
    """Duração aproximada da fala de `text`, sem sintetizar (função pura)."""
    return max(len(text.strip()) / CHARS_PER_SECOND / speed, MIN_ESTIMATE_SECONDS)


def estimate_narration_duration(project: Project, narration: Narration) -> float:
    """Estimativa para uma narração do projeto; um roteiro ilegível conta como o mínimo."""
    try:
        text = narration_text(project, narration)
    except FileNotFoundError:
        return MIN_ESTIMATE_SECONDS
    return estimate_speech_duration(text, narration.speed)


def narration_label(narration: Narration, limit: int = 40) -> str:
    """Rótulo curto de uma narração para a linha do tempo: o início do texto ou o nome do roteiro."""
    label = (narration.text or narration.script or "").strip().replace("\n", " ")
    return label if len(label) <= limit else label[: limit - 1].rstrip() + "…"


def overrun_warnings(voiceovers: Sequence[PreparedVoiceover], total: float) -> list[str]:
    """Avisos das narrações que passam do fim do vídeo (o áudio excedente é cortado)."""
    return [
        f"audio.narration[{index}]: termina em {item.end:.1f}s, depois do fim do vídeo ({total:.1f}s); "
        "o final da fala será cortado."
        for index, item in enumerate(voiceovers)
        if item.end > total + 0.05
    ]


def _cue_with_words(start: float, end: float, text: str) -> Cue:
    """Uma fala como cue com tempo por palavra, repartido pelo tamanho de cada palavra.

    O sintetizador só informa o tempo da fala inteira; repartir pelas letras dá ao reagrupamento e ao
    modo karaokê palavras para quebrar em linhas curtas, com erro de poucos décimos de segundo.
    """
    tokens = text.split()
    weights = [len(token) + 1 for token in tokens]  # +1: o espaço/pontuação também leva tempo
    scale = (end - start) / sum(weights) if weights else 0.0
    words, cursor = [], start
    for token, weight in zip(tokens, weights, strict=True):
        words.append(Word(cursor, cursor + weight * scale, token))
        cursor += weight * scale
    return Cue(start, end, text, words)


def narration_cues(voiceovers: Sequence[PreparedVoiceover]) -> list[Cue]:
    """Legendas das narrações no tempo do vídeo final (deslocadas pelo `start` de cada uma)."""
    cues = [
        _cue_with_words(item.start + start, item.start + end, text)
        for item in voiceovers
        for start, end, text in item.cues
    ]
    return sorted(cues, key=lambda cue: cue.start)


def known_voices(project: Project, library: VoiceLibrary | None = None) -> set[str] | None:
    """Ids da biblioteca de vozes, só quando alguma narração do projeto pede uma voz (senão None: nada a conferir)."""
    if not any(narration.voice for narration in project.audio.narration):
        return None
    return {profile.id for profile in (library or VoiceLibrary()).list()}


def default_service(ctx: RenderContext) -> NarrationService:
    """Serviço real: o sintetizador compartilhado do processo (o modelo demora a carregar) e o runner do render."""
    from .narration import NarrationService
    from .voices import shared_synthesizer

    return NarrationService(shared_synthesizer(), ctx.runner, log=ctx.log, lexicons=LexiconStore().for_brand)


class VoiceoverPreparer:
    """Sintetiza as narrações do projeto; o serviço de síntese só é criado quando há narração."""

    def __init__(
        self,
        library: VoiceLibrary | None = None,
        service_factory: NarrationServiceFactory = default_service,
    ) -> None:
        self.library = library or VoiceLibrary()
        self.service_factory = service_factory

    def _service(self, ctx: RenderContext) -> NarrationService:
        if ctx.narrator is None:
            ctx.narrator = self.service_factory(ctx)
        return ctx.narrator

    def prepare(self, ctx: RenderContext) -> list[PreparedVoiceover]:
        narrations = ctx.project.audio.narration
        prepared = []
        for index, narration in enumerate(narrations, 1):
            ctx.log(f"Narração {index} de {len(narrations)}")
            text = narration_text(ctx.project, narration)
            out = ctx.job_dir / f"narration_{index}.wav"
            if ctx.options.dry_run:  # simulação: nada de sintetizar de verdade (leva minutos na CPU)
                duration = estimate_speech_duration(text, narration.speed)
                prepared.append(PreparedVoiceover(out, narration.start, narration.volume, duration))
                continue
            voice = self.library.get(narration.voice) if narration.voice else None
            result = self._service(ctx).render(
                text,
                out,
                voice,
                language=narration.language,
                speed=narration.speed,
                instruct=narration.instruct,
                seed=narration.seed,
                brand=ctx.project.brand,
            )
            prepared.append(
                PreparedVoiceover(
                    result.path, narration.start, narration.volume, result.duration, result.cues
                )
            )
        return prepared

    def cached_durations(self, project: Project, service: NarrationService) -> list[float | None]:
        """Duração real de cada narração que já está inteira no cache (None = ainda não sintetizada)."""
        durations: list[float | None] = []
        for narration in project.audio.narration:
            try:
                text = narration_text(project, narration)
                voice = self.library.get(narration.voice) if narration.voice else None
                duration = service.cached_duration(
                    text,
                    voice,
                    language=narration.language,
                    speed=narration.speed,
                    instruct=narration.instruct,
                    seed=narration.seed,
                    brand=project.brand,
                )
            except _UNKNOWN_DURATION_ERRORS:
                duration = None  # a vista da linha do tempo cai na estimativa em vez de não abrir
            durations.append(duration)
        return durations


def view_narration_durations(
    project: Project,
    library: VoiceLibrary | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    lexicons: LexiconStore | None = None,
) -> list[float | None]:
    """Durações reais das narrações já em cache, para a linha do tempo, sem sintetizar nada.

    O roteador de motores só carrega um modelo na primeira síntese; ler o cache usa só a identidade do
    motor, então a vista abre instantânea mesmo com o OmniVoice ainda frio.
    """
    if not project.audio.narration:
        return []
    from .narration import NarrationService
    from .voices import shared_synthesizer

    service = NarrationService(
        synthesizer or shared_synthesizer(),
        SubprocessRunner(quiet=True),  # nunca é executado: ler o cache não chama o ffmpeg
        lexicons=(lexicons or LexiconStore()).for_brand,
    )
    return VoiceoverPreparer(library).cached_durations(project, service)
