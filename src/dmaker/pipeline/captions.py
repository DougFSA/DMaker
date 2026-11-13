"""Produção das legendas: transcrição automática (com cache) ou arquivo, correções e reagrupamento."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import Captions, Transition
from ..filtergraph.audio import audio_graph
from ..filtergraph.common import Inputs
from ..filtergraph.timeline import timeline_graph
from ..media.ffmpeg import FFmpegCommand
from ..text.captions import Cue, apply_replacements, load_captions, regroup, shift, to_srt
from ..text.transcribe import Transcriber, WhisperTranscriber
from .context import RenderContext
from .segments import PreparedSegment, cache_key
from .sources import Source
from .transcript_cache import (
    TranscriptKeys,
    TranscriptStore,
    speech_layout,
    transcript_keys,
    transcript_record,
    was_edited,
)
from .voicefiles import PreparedVoiceFile
from .voiceover import PreparedVoiceover, narration_cues

TranscriberFactory = Callable[[Captions], Transcriber]


def default_transcriber_factory(captions: Captions) -> Transcriber:
    return WhisperTranscriber(model=captions.model, device=captions.device)


@dataclass
class CaptionResult:
    cues: list[Cue]
    file: Path | None


@dataclass
class CaptionInputs:
    """O que uma fonte de legendas pode precisar do render em curso."""

    ctx: RenderContext
    sources: list[Source]
    prepared: list[PreparedSegment]
    transitions: list[Transition | None]
    voiceovers: Sequence[PreparedVoiceover]
    vocabulary: list[str]
    voice_files: Sequence[PreparedVoiceFile] = ()


CueProducer = Callable[[CaptionInputs], tuple[list[Cue] | None, Path | None]]


class CaptionPipeline:
    """Cada valor de `captions.source` é um produtor de cues; qualquer outro valor é um arquivo de legendas.
    Uma fonte nova entra em `producers`, sem mexer em `produce`."""

    def __init__(self, transcriber_factory: TranscriberFactory = default_transcriber_factory):
        self.transcriber_factory = transcriber_factory
        self.producers: dict[str, CueProducer] = {
            "auto": self._from_transcription,
            "narration": self._from_narration,
        }
        # o que já existe sem gerar nada (o quadro de um instante não chama o Whisper nem sintetiza voz)
        self.cached_producers: dict[str, CueProducer] = {
            "auto": self._from_cached_transcription,
            "narration": lambda inputs: (None, None),
        }

    def produce(
        self,
        ctx: RenderContext,
        sources: list[Source],
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        voiceovers: Sequence[PreparedVoiceover] = (),
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> CaptionResult | None:
        return self._produce(self.producers, ctx, sources, prepared, transitions, voiceovers, voice_files)

    def produce_cached(
        self, ctx: RenderContext, sources: list[Source], voice_files: Sequence[PreparedVoiceFile] = ()
    ) -> CaptionResult | None:
        """As legendas que já existem, sem gerar nenhuma: o arquivo de legendas ou a transcrição automática em cache
        (None se ela ainda não existe ou se a fonte é a narração, que só existe depois de sintetizada)."""
        return self._produce(self.cached_producers, ctx, sources, [], [], (), voice_files)

    def _produce(
        self,
        producers: dict[str, CueProducer],
        ctx: RenderContext,
        sources: list[Source],
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        voiceovers: Sequence[PreparedVoiceover],
        voice_files: Sequence[PreparedVoiceFile],
    ) -> CaptionResult | None:
        project, options = ctx.project, ctx.options
        captions = project.captions
        if not captions or not captions.enabled or options.no_captions or options.dry_run:
            return None
        vocabulary = list(ctx.theme.captions.get("vocabulary", [])) + list(captions.vocabulary)
        replacements = {**ctx.theme.captions.get("replacements", {}), **captions.replacements}

        producer = producers.get(captions.source)
        if producer is None:
            store = project.resolve(captions.source)
            if not store.exists():
                raise FileNotFoundError(f"captions.source não encontrado: {captions.source}")
            cues = load_captions(store)
        else:
            cues, store = producer(
                CaptionInputs(ctx, sources, prepared, transitions, voiceovers, vocabulary, voice_files)
            )
            persona_cues = ctx.personas.overlay_cues(ctx) if ctx.personas is not None else []
            if cues is None and not persona_cues:
                return None
            # a fala das personas no canto não passa pelo Whisper (o áudio não está nos trechos): vem da própria fala
            cues = sorted([*(cues or []), *persona_cues], key=lambda cue: cue.start)

        cues = apply_replacements(cues, replacements)
        if captions.offset:
            cues = shift(cues, captions.offset)
        style = captions.style
        if style.mode == "karaoke" or any(cue.words for cue in cues):
            cues = regroup(cues, style.max_words, style.max_chars)
        return CaptionResult(cues, store)

    # ---------- texto das narrações ----------

    @staticmethod
    def _from_narration(inputs: CaptionInputs) -> tuple[list[Cue] | None, Path | None]:
        """As legendas são o próprio texto falado, com os tempos da síntese: sem Whisper."""
        if not inputs.voiceovers:
            return None, None
        cues = narration_cues(inputs.voiceovers)
        store = inputs.ctx.job_dir / "captions.narration.srt"
        store.write_text(to_srt(cues), encoding="utf-8")
        return cues, store

    # ---------- transcrição automática com cache ----------

    def _from_transcription(self, inputs: CaptionInputs) -> tuple[list[Cue] | None, Path | None]:
        # clipes mudos não têm voz, mas um áudio de `audio.voiceover` continua falando por cima deles
        if inputs.ctx.project.audio.mute_clips and not inputs.voice_files:
            return None, None
        return self._auto(
            inputs.ctx,
            inputs.sources,
            inputs.prepared,
            inputs.transitions,
            inputs.vocabulary,
            inputs.voice_files,
        )

    def _from_cached_transcription(self, inputs: CaptionInputs) -> tuple[list[Cue] | None, Path | None]:
        """A transcrição que o render anterior deixou em `captions.auto.json`, se ela ainda vale para o projeto
        (deslocada junto com os clipes, se só mudou o lugar deles). Só lê: quem regrava é o render."""
        ctx = inputs.ctx
        if ctx.project.audio.mute_clips and not inputs.voice_files:
            return None, None
        keys = self._transcript_keys(ctx, inputs.sources, inputs.vocabulary, inputs.voice_files)
        store = self._store(ctx)
        found = store.lookup(keys)
        return (found[0].cues, store.path) if found is not None else (None, None)

    @staticmethod
    def _store(ctx: RenderContext) -> TranscriptStore:
        return TranscriptStore((ctx.project.base_dir or ctx.job_dir) / "captions.auto.json")

    def _transcript_keys(
        self,
        ctx: RenderContext,
        sources: list[Source],
        vocabulary: list[str],
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> TranscriptKeys:
        """A chave depende só do que muda a fala ouvida pelo modelo (ver `transcript_cache`), mais o modelo e o
        vocabulário que ele recebe."""
        captions = ctx.project.captions
        assert captions is not None
        settings: list[object] = [
            ctx.project.audio.voice_gain,
            ctx.project.audio.mute_clips,
            captions.language,
            captions.model,
            vocabulary,
        ]
        if voice_files:
            settings.append(self._voice_file_parts(voice_files))
        return transcript_keys(
            speech_layout(ctx.project.timeline, sources),
            settings,
            movable=not voice_files,  # a voz de `audio.voiceover` toca em instante fixo, não anda com os clipes
            legacy=self._legacy_key(ctx, sources, vocabulary, voice_files),
        )

    @staticmethod
    def _voice_file_parts(voice_files: Sequence[PreparedVoiceFile]) -> list[tuple]:
        return [
            (str(item.path), item.path.stat().st_mtime_ns, item.path.stat().st_size)
            + (item.start, item.offset, item.duration, item.volume)
            for item in voice_files
        ]

    def _legacy_key(
        self,
        ctx: RenderContext,
        sources: list[Source],
        vocabulary: list[str],
        voice_files: Sequence[PreparedVoiceFile],
    ) -> str:
        """A chave do formato v2 (a linha do tempo inteira), só para aceitar sem transcrever de novo o arquivo
        gravado antes da v3, com as correções que ele tiver. O render seguinte já o regrava no formato novo."""
        captions = ctx.project.captions
        assert captions is not None
        parts = [
            (seg.model_dump(mode="json"), str(src.path), src.stat_key())
            for seg, src in zip(ctx.project.timeline, sources, strict=True)
        ]
        key_parts: list[object] = [
            "v2",
            parts,
            ctx.project.audio.voice_gain,
            captions.language,
            captions.model,
            vocabulary,
        ]
        if voice_files:
            key_parts.append(self._voice_file_parts(voice_files))
        return cache_key(*key_parts)

    def _auto(
        self,
        ctx: RenderContext,
        sources: list[Source],
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        vocabulary: list[str],
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> tuple[list[Cue] | None, Path | None]:
        captions = ctx.project.captions
        assert captions is not None
        keys = self._transcript_keys(ctx, sources, vocabulary, voice_files)
        store = self._store(ctx)
        found = store.lookup(keys) if not ctx.options.force else None
        if found is not None:
            cached, data = found
            if cached.rewrite:  # deslocadas ou de antes da v3: regrava com a chave atual, sem perder a edição
                ctx.log(
                    "legendas: a fala só mudou de lugar na linha do tempo; as legendas guardadas andaram junto"
                )
                record = transcript_record(
                    cached.cues,
                    data.get("language", captions.language),
                    keys,
                    data.get("meta"),
                    edited=was_edited(data),
                )
                store.save(record, cached.cues)
            return cached.cues, store.path

        wav = self._voice_wav(ctx, prepared, transitions, voice_files)
        prompt = (", ".join(vocabulary) + ".") if vocabulary else None
        try:
            transcript = self.transcriber_factory(captions).transcribe(wav, captions.language, prompt)
        except RuntimeError as exc:
            ctx.warn(f"Legendas automáticas puladas: {exc}")
            return None, None
        backup = store.keep_edited()
        if backup is not None:
            ctx.warn(
                f"A fala da linha do tempo mudou e a transcrição foi refeita; as legendas editadas que estavam em "
                f"{store.path.name} ficaram guardadas em {backup.name}. Reaplique as correções com fix_captions."
            )
        store.save(
            transcript_record(transcript.cues, captions.language, keys, transcript.meta, edited=False),
            transcript.cues,
        )
        return transcript.cues, store.path

    @staticmethod
    def _voice_wav(
        ctx: RenderContext,
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> Path:
        """Só a voz da linha do tempo (sem música nem normalização), mono 16 kHz para o modelo. Os arquivos
        de `audio.voiceover` entram por cima, nos instantes em que tocam no vídeo."""
        inputs = Inputs()
        for item in prepared:
            inputs.add(item.mezzanine)
        graph = timeline_graph(
            len(prepared), [p.duration for p in prepared], transitions, ctx.fps, want_video=False
        )
        lines = list(graph.lines)
        aout = audio_graph(
            lines,
            inputs,
            graph.audio,
            ctx.project.audio,
            None,
            graph.total,
            include_music=False,
            include_norm=False,
            voice_files=voice_files,
            include_master=False,  # a transcrição ouve a voz, não o tratamento do master
        )
        wav = ctx.job_dir / "voice.wav"
        args = inputs.args + [
            "-filter_complex",
            ";".join(lines),
            "-map",
            aout,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ]
        ctx.runner.run(FFmpegCommand(args, label="áudio para transcrição", total=graph.total))
        return wav
