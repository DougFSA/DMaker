"""As personas no render: a fala delas, a boca e os clipes desenhados pelo motor do tipo, com cache por conteúdo.

O `PersonaStage` serve aos dois usos da persona (o trecho de tela cheia, em `persona_segment.py`, e a sobreposição num
canto, aqui): sintetiza a fala com a voz da persona (ou usa o áudio dado), acha o tempo de cada palavra, monta a
linha do tempo de visemas e pede o clipe ao motor registrado para o tipo. Tudo que é externo (cadastro, vozes,
transcritor, motor) entra por injeção.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.persona import Persona, PersonaMark, PersonaSpeech, estimate_speech_seconds
from ..domain.spec import PersonaOverlay, PersonaSegment, Project, parse_aspect
from ..domain.timeline import frame_range, persona_segment_duration
from ..filtergraph.common import even
from ..filtergraph.html_layer import ResolvedHtmlLayer
from ..filtergraph.persona import persona_frame_command
from ..filtergraph.pip import pip_origin
from ..media.browser import BrowserUnavailable
from ..media.probe import MediaInfo
from ..persona.engine import PersonaRender, clip_cache_key, engine_for
from ..persona.library import PersonaLibrary
from ..persona.marks import mark_problems
from ..persona.validation import persona_problems
from ..persona.visemes import build_visemes
from ..persona.words import evenly_timed_words
from ..text.captions import Word
from ..visuals.pip import pip_mask
from ..voice.library import VoiceLibrary
from .cache_key import cache_key
from .context import RenderContext
from .sources import Source
from .voiceover import NarrationServiceFactory, PreparedVoiceover, default_service

WordTimer = Callable[[Path, str], list[Word]]
PERSONA_CLIP_VERSION = "pc1"  # muda quando o jeito de compor o clipe com o fundo muda


@dataclass(frozen=True)
class SpokenLine:
    """A fala de uma persona pronta: o arquivo de áudio (None no dry-run de um texto), a duração e as palavras com tempo."""

    path: Path | None
    duration: float
    words: tuple[tuple[float, float, str], ...]


def default_word_timer(ctx: RenderContext) -> WordTimer:
    """O `transcribe_words` do serviço de correção de fala (faster-whisper, com cache em disco)."""
    from .speech_fix import default_speech_fix_service

    service = default_speech_fix_service(ctx.runner, ctx.log)
    return lambda path, language: service.transcribe_words(path, language=language)


class PersonaStage:
    """Tudo o que o render faz por uma persona, com as dependências injetadas."""

    def __init__(
        self,
        library: PersonaLibrary | None = None,
        voices: VoiceLibrary | None = None,
        word_timer: Callable[[RenderContext], WordTimer] = default_word_timer,
        service_factory: NarrationServiceFactory = default_service,
    ) -> None:
        self.library = library or PersonaLibrary()
        self.voices = voices or VoiceLibrary()
        self._word_timer_factory = word_timer
        self._word_timer: WordTimer | None = None
        self._service_factory = service_factory
        self._lines: dict[str, SpokenLine] = {}

    # ---------- a fala ----------

    def line_for(self, ctx: RenderContext, persona: Persona, speech: PersonaSpeech) -> SpokenLine:
        """A fala da persona sintetizada (ou o áudio dado) com a boca já medida; guardada por render."""
        key = cache_key(persona.id, persona.voice, speech.model_dump(mode="json"), ctx.options.dry_run)
        if key not in self._lines:
            self._lines[key] = self._speak(ctx, persona, speech, key)
        return self._lines[key]

    def _speak(self, ctx: RenderContext, persona: Persona, speech: PersonaSpeech, key: str) -> SpokenLine:
        if speech.audio:
            path = ctx.project.resolve(speech.audio)
            if not path.exists():
                raise FileNotFoundError(
                    f"Áudio da fala da persona não encontrado: {speech.audio} (procurado em {path})"
                )
            return self._measured(ctx, path, speech)
        text = (speech.text or "").strip()
        if ctx.options.dry_run:  # simulação: nada de sintetizar (leva minutos na CPU)
            duration = estimate_speech_seconds(text, speech.speed)
            return SpokenLine(None, duration, tuple(evenly_timed_words(text, duration)))
        voice = self.voices.get(persona.voice) if persona.voice else None
        if ctx.narrator is None:
            ctx.narrator = self._service_factory(ctx)
        result = ctx.narrator.render(
            text,
            ctx.job_dir / f"persona_{key}.wav",
            voice,
            language=speech.language,
            speed=speech.speed,
            instruct=speech.instruct,
            seed=speech.seed,
            brand=ctx.project.brand,
        )
        return self._measured(ctx, result.path, speech, result.duration)

    def _measured(
        self, ctx: RenderContext, path: Path, speech: PersonaSpeech, duration: float | None = None
    ) -> SpokenLine:
        if duration is None:
            duration = ctx.prober(path).duration or 0.0
        if self._word_timer is None:
            self._word_timer = self._word_timer_factory(ctx)
        words = [(w.start, w.end, w.text) for w in self._word_timer(path, speech.language)]
        if not words and speech.text:  # o transcritor não achou fala: o texto conhecido reparte o tempo
            words = evenly_timed_words(speech.text, duration)
        return SpokenLine(path, duration, tuple(words))

    # ---------- o clipe ----------

    def clip_for(
        self,
        ctx: RenderContext,
        persona: Persona,
        line: SpokenLine,
        expression: str,
        marks: Sequence[PersonaMark],
        duration: float,
        size: tuple[int, int],
    ) -> tuple[Path, bool]:
        """O clipe da persona em cache (desenhado agora se ainda não existe) e se ele tem alfa."""
        engine = engine_for(persona.kind)
        request = PersonaRender(
            persona=persona,
            visemes=tuple(build_visemes(line.words, duration)),
            expression=expression,
            marks=tuple(marks),
            duration=duration,
            fps=ctx.fps,
            size=size,
        )
        out = ctx.cache_dir / f"{clip_cache_key(engine, request)}_persona.mov"
        if not ctx.options.dry_run and (ctx.options.force or not out.exists()):
            ctx.log(f"persona {persona.name}: desenhando {request.frame_count} quadros ({size[0]}x{size[1]})")
            engine.render(request, out, ctx.runner, ctx.warn)
        return out, engine.produces_alpha

    # ---------- o projeto ----------

    def problems(self, project: Project) -> list[str]:
        return persona_problems(project, self.library.get)

    def check_available(self, ctx: RenderContext) -> None:
        """O motor que não está pronto (o Chromium que falta, por exemplo) falha antes dos mezaninos, não depois."""
        if ctx.options.dry_run:
            return
        kinds = {
            self.library.get(item.persona).kind
            for item in [*ctx.project.timeline, *ctx.project.overlays]
            if isinstance(item, PersonaSegment | PersonaOverlay)
        }
        for kind in sorted(kinds):
            reason = engine_for(kind).unavailable_reason()
            if reason:
                raise BrowserUnavailable(
                    f"O projeto tem persona {kind} e o motor dela não está pronto. {reason}"
                )

    def attach_speech(self, ctx: RenderContext, project: Project, sources: list[Source]) -> list[Source]:
        """As fontes com a fala das personas de tela cheia no lugar: o trecho ganha a duração real do áudio, e as
        marcas são conferidas contra ela."""
        result = list(sources)
        problems: list[str] = []
        for index, segment in enumerate(project.timeline):
            if not isinstance(segment, PersonaSegment):
                continue
            persona = self.library.get(segment.persona)
            line = self.line_for(ctx, persona, segment.speech)
            info = MediaInfo(line.path, line.duration, 0, 0, 0.0, False, True, False) if line.path else None
            result[index] = Source(line.path, info)
            engine = engine_for(persona.kind)
            problems += mark_problems(
                segment.marks,
                segment.expression,
                engine.expressions,
                engine.gestures,
                persona_segment_duration(segment, info),
                f"timeline[{index}]",
                persona.kind,
            )
        for index, overlay in self._overlays(project):
            persona = self.library.get(overlay.persona)
            line = self.line_for(ctx, persona, overlay.speech)
            span = (overlay.end - overlay.start) if overlay.end is not None else line.duration
            engine = engine_for(persona.kind)
            problems += mark_problems(
                overlay.marks,
                overlay.expression,
                engine.expressions,
                engine.gestures,
                span,
                f"overlays[{index}]",
                persona.kind,
            )
        if problems:
            raise ValueError("Persona com problema:\n" + "\n".join(problems))
        return result

    # ---------- a sobreposição ----------

    def voiceovers(self, ctx: RenderContext) -> list[PreparedVoiceover]:
        """A fala de cada persona sobreposta como uma narração do projeto: entra na mixagem e a música abaixa sob ela."""
        prepared = []
        for index, overlay in self._overlays(ctx.project):
            persona = self.library.get(overlay.persona)
            line = self.line_for(ctx, persona, overlay.speech)
            path = line.path or ctx.job_dir / f"persona_overlay_{index}.wav"
            prepared.append(PreparedVoiceover(path, overlay.start, overlay.speech.volume, line.duration))
        return prepared

    def overlay_layers(self, ctx: RenderContext, total: float) -> list[ResolvedHtmlLayer]:
        """O vídeo (com alfa) de cada persona sobreposta, pronto para a montagem pelo mesmo caminho das composições."""
        layers = []
        for _index, overlay in self._overlays(ctx.project):
            layer = self._overlay_layer(ctx, overlay, total)
            if layer is not None:
                layers.append(layer)
        return layers

    @staticmethod
    def _overlays(project: Project) -> list[tuple[int, PersonaOverlay]]:
        return [(i, ov) for i, ov in enumerate(project.overlays) if isinstance(ov, PersonaOverlay)]

    def _overlay_layer(
        self, ctx: RenderContext, overlay: PersonaOverlay, total: float
    ) -> ResolvedHtmlLayer | None:
        persona = self.library.get(overlay.persona)
        line = self.line_for(ctx, persona, overlay.speech)
        start = overlay.start
        end = min(overlay.end if overlay.end is not None else start + line.duration, total)
        first, stop = frame_range(start, end, ctx.fps)
        if stop <= first:
            return None  # cai depois do fim do vídeo
        duration = (stop - first) / ctx.fps
        width = even(ctx.width * overlay.width)
        aspect = 1.0 if overlay.shape == "circle" and overlay.background else parse_aspect(overlay.aspect)
        size = (width, even(width / aspect))
        clip, alpha = self.clip_for(ctx, persona, line, overlay.expression, overlay.marks, duration, size)
        path = clip
        if overlay.background and alpha:
            path = self._framed(ctx, overlay, clip, size, duration)
        left, top = pip_origin(overlay, size[0], size[1], ctx.width, ctx.height, ctx.scale, ctx.preset.safe)
        return ResolvedHtmlLayer(
            path, first / ctx.fps, stop / ctx.fps, str(left), str(top), fade=overlay.fade
        )

    def _framed(
        self, ctx: RenderContext, overlay: PersonaOverlay, clip: Path, size: tuple[int, int], duration: float
    ) -> Path:
        """A persona sobre o fundo de cor, recortada no formato pedido (cache por conteúdo, como o mezanino)."""
        color = ctx.theme.color(overlay.background, "#D9E4F2")
        radius = round(overlay.radius * size[0])
        key = cache_key(
            PERSONA_CLIP_VERSION, clip.name, color, overlay.shape, radius, size, ctx.fps, round(duration, 6)
        )
        out = ctx.cache_dir / f"{key}_personaframe.mov"
        mask = ctx.cache_dir / f"{key}_personamask.png"
        if ctx.options.dry_run:  # o comando só é registrado
            ctx.runner.run(persona_frame_command(clip, mask, color, duration, size, ctx.fps, out))
        elif ctx.options.force or not out.exists():
            pip_mask(size[0], size[1], overlay.shape, radius, 0).save(mask)
            partial = out.with_name(f"{out.stem}.part{out.suffix}")
            try:
                ctx.runner.run(persona_frame_command(clip, mask, color, duration, size, ctx.fps, partial))
                partial.replace(out)
            finally:
                partial.unlink(missing_ok=True)
        return out
