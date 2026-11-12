"""As personas no render: a fala delas, a boca e os clipes desenhados pelo motor do tipo, com cache por conteúdo.

O `PersonaStage` serve aos dois usos da persona (o trecho de tela cheia, em `persona_segment.py`, e a sobreposição num
canto, aqui): sintetiza a fala com a voz da persona (ou usa o áudio dado), acha o tempo de cada palavra, monta a
linha do tempo de visemas e pede o clipe ao motor registrado para o tipo. Tudo que é externo (cadastro, vozes,
transcritor, motor) entra por injeção.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ..domain.persona import Persona, PersonaMark, PersonaSpeech, estimate_speech_seconds
from ..domain.spec import PersonaOverlay, PersonaSegment, Project
from ..domain.timeline import frame_range, persona_segment_duration
from ..filtergraph.html_layer import ResolvedHtmlLayer
from ..filtergraph.persona import persona_frame_command
from ..filtergraph.persona_rect import persona_overlay_rect, persona_size
from ..media.browser import BrowserUnavailable
from ..media.probe import MediaInfo
from ..persona.engine import PersonaRender, clip_cache_key, engine_for
from ..persona.library import PersonaLibrary
from ..persona.marks import mark_problems
from ..persona.validation import persona_problems
from ..persona.visemes import build_visemes
from ..persona.words import evenly_timed_words
from ..text.caption_band import project_caption_band
from ..text.captions import Cue, Word
from ..text.overlays import Canvas
from ..visuals.pip import pip_mask
from ..voice.library import VoiceLibrary
from .cache_key import cache_key
from .context import RenderContext
from .persona_speech_store import load_durations, save_duration, speech_key
from .sources import Source
from .voiceover import NarrationServiceFactory, PreparedVoiceover, default_service

WordTimer = Callable[[Path, str], list[Word]]
PERSONA_CLIP_VERSION = "pc2"  # muda quando o jeito de compor o clipe com o fundo muda


@dataclass(frozen=True)
class SpokenLine:
    """A fala de uma persona pronta: o arquivo de áudio (None no dry-run de um texto), a duração e as palavras com tempo."""

    path: Path | None
    duration: float
    words: tuple[tuple[float, float, str], ...]
    seed: int | None = None  # a semente da fala: o motor realista fixa o desenho com ela


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
        instants: dict[int, float] | None = None,
    ) -> None:
        # `instants` liga o modo do quadro de um instante: trecho -> instante dele em segundos. Nesse modo nada é
        # sintetizado nem transcrito (a boca usa a duração conhecida) e só o quadro pedido é desenhado.
        self.instants = instants
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
            if self.instants is not None and not speech.audio:
                self._lines[key] = self._estimated(ctx, persona, speech)
            else:
                self._lines[key] = self._speak(ctx, persona, speech, key)
            self._lines[key] = replace(self._lines[key], seed=speech.seed)
        return self._lines[key]

    @staticmethod
    def _estimated(ctx: RenderContext, persona: Persona, speech: PersonaSpeech) -> SpokenLine:
        """A fala sem sintetizar: a duração real guardada no projeto, senão a estimada pelo texto, com a boca repartida."""
        text = (speech.text or "").strip()
        duration = load_durations(ctx.project.base_dir).get(speech_key(persona, speech))
        if duration is None:
            duration = estimate_speech_seconds(text, speech.speed)
        return SpokenLine(None, duration, tuple(evenly_timed_words(text, duration)))

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
        save_duration(ctx.project.base_dir, speech_key(persona, speech), result.duration)
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
        framing: str = "full",
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
            framing=framing,
            audio=line.path,
            seed=line.seed,
        )
        out = ctx.cache_dir / f"{clip_cache_key(engine, request)}_persona.mov"
        if not ctx.options.dry_run and (ctx.options.force or not out.exists()):
            ctx.log(f"persona {persona.name}: desenhando {request.frame_count} quadros ({size[0]}x{size[1]})")
            forecast = getattr(
                engine, "forecast", None
            )  # o motor que demora (realista) diz quanto, antes de começar
            if forecast is not None:
                ctx.log(f"persona {persona.name}: {forecast(request)}")
            if getattr(engine, "reports_progress", False):
                engine.render(request, out, ctx.runner, ctx.warn, ctx.log)
            else:
                engine.render(request, out, ctx.runner, ctx.warn)
        return out, engine.produces_alpha

    def still_for(
        self,
        ctx: RenderContext,
        persona: Persona,
        line: SpokenLine,
        expression: str,
        marks: Sequence[PersonaMark],
        duration: float,
        size: tuple[int, int],
        at: float,
        framing: str = "full",
    ) -> Path:
        """O quadro da persona no instante `at` do clipe, como PNG com alfa em cache (desenhado só ele)."""
        engine = engine_for(persona.kind)
        request = PersonaRender(
            persona=persona,
            visemes=tuple(build_visemes(line.words, duration)),
            expression=expression,
            marks=tuple(marks),
            duration=duration,
            fps=ctx.fps,
            size=size,
            framing=framing,
            audio=line.path,
            seed=line.seed,
        )
        out = ctx.cache_dir / f"{clip_cache_key(engine, request)}_{round(at * ctx.fps)}_personastill.png"
        if not ctx.options.dry_run and (ctx.options.force or not out.exists()):
            png = engine.still(request, at, ctx.warn)
            partial = out.with_name(f"{out.stem}.part.png")
            partial.write_bytes(png)
            partial.replace(out)
        return out

    @staticmethod
    def _corner(ctx: RenderContext, overlay: PersonaOverlay) -> tuple[int, int]:
        """O canto de cima e da esquerda da persona sobreposta, pela mesma conta da caixa da interface e do QA
        (`persona_overlay_rect`): com legenda queimada, a persona de baixo sobe para acima dela."""
        canvas = Canvas(ctx.width, ctx.height, ctx.preset.safe, ctx.theme, total=0.0)
        band = project_caption_band(ctx.project, canvas, no_captions=ctx.options.no_captions)
        left, top, _, _ = persona_overlay_rect(
            overlay, ctx.width, ctx.height, ctx.scale, ctx.preset.safe, band
        )
        return left, top

    def overlay_still(
        self, ctx: RenderContext, overlay: PersonaOverlay, frame: int
    ) -> ResolvedHtmlLayer | None:
        """A persona sobreposta só no quadro `frame` do vídeo (None se ela não aparece nele), sem o fundo recortado."""
        persona = self.library.get(overlay.persona)
        line = self.line_for(ctx, persona, overlay.speech)
        end = overlay.end if overlay.end is not None else overlay.start + line.duration
        first, stop = frame_range(overlay.start, end, ctx.fps)
        if not first <= frame < stop:
            return None
        size = persona_size(overlay, ctx.width)
        duration = (stop - first) / ctx.fps
        at = max(frame / ctx.fps - overlay.start, 0.0)
        png = self.still_for(
            ctx, persona, line, overlay.expression, overlay.marks, duration, size, at, "corner"
        )
        left, top = self._corner(ctx, overlay)
        return ResolvedHtmlLayer(png, frame / ctx.fps, (frame + 1) / ctx.fps, str(left), str(top), still=True)

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

    def overlay_cues(self, ctx: RenderContext) -> list[Cue]:
        """A legenda da fala de cada persona sobreposta, no tempo do vídeo (o início da sobreposição mais o da palavra)."""
        cues = []
        for _index, overlay in self._overlays(ctx.project):
            line = self.line_for(ctx, self.library.get(overlay.persona), overlay.speech)
            if not line.words:
                continue
            words = [Word(overlay.start + a, overlay.start + b, text) for a, b, text in line.words]
            cues.append(Cue(words[0].start, words[-1].end, " ".join(word.text for word in words), words))
        return cues

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
        size = persona_size(overlay, ctx.width)
        clip, alpha = self.clip_for(
            ctx, persona, line, overlay.expression, overlay.marks, duration, size, "corner"
        )
        path = clip
        if overlay.background and alpha:
            path = self._framed(ctx, overlay, clip, size, duration)
        left, top = self._corner(ctx, overlay)
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
