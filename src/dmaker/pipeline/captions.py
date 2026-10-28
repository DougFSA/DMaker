"""Produção das legendas: transcrição automática (com cache) ou arquivo, correções e reagrupamento."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import Captions, Transition
from ..filtergraph.audio import audio_graph
from ..filtergraph.common import Inputs
from ..filtergraph.timeline import timeline_graph
from ..media.ffmpeg import FFmpegCommand
from ..text.captions import Cue, apply_replacements, from_json, load_captions, regroup, shift, to_json, to_srt
from ..text.transcribe import Transcriber, WhisperTranscriber
from .context import RenderContext
from .segments import PreparedSegment, cache_key
from .sources import Source
from .voicefiles import PreparedVoiceFile
from .voiceover import PreparedVoiceover, narration_cues

TranscriberFactory = Callable[[Captions], Transcriber]

CAPTIONS_CACHE_VERSION = (
    "v2"  # muda quando o formato salvo em captions.auto.json muda (probability por palavra)
)


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

    def produce(
        self,
        ctx: RenderContext,
        sources: list[Source],
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        voiceovers: Sequence[PreparedVoiceover] = (),
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> CaptionResult | None:
        project, options = ctx.project, ctx.options
        captions = project.captions
        if not captions or not captions.enabled or options.no_captions or options.dry_run:
            return None
        vocabulary = list(ctx.theme.captions.get("vocabulary", [])) + list(captions.vocabulary)
        replacements = {**ctx.theme.captions.get("replacements", {}), **captions.replacements}

        producer = self.producers.get(captions.source)
        if producer is None:
            store = project.resolve(captions.source)
            if not store.exists():
                raise FileNotFoundError(f"captions.source não encontrado: {captions.source}")
            cues = load_captions(store)
        else:
            cues, store = producer(
                CaptionInputs(ctx, sources, prepared, transitions, voiceovers, vocabulary, voice_files)
            )
            if cues is None:
                return None

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

    def _audio_key(
        self,
        ctx: RenderContext,
        sources: list[Source],
        vocabulary: list[str],
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> str:
        captions = ctx.project.captions
        assert captions is not None
        parts = [
            (seg.model_dump(mode="json"), str(src.path), src.stat_key())
            for seg, src in zip(ctx.project.timeline, sources, strict=True)
        ]
        key_parts: list[object] = [
            CAPTIONS_CACHE_VERSION,
            parts,
            ctx.project.audio.voice_gain,
            captions.language,
            captions.model,
            vocabulary,
        ]
        if voice_files:  # só entra na chave quando há arquivos: sem eles a chave é a de sempre
            key_parts.append(
                [
                    (str(item.path), item.path.stat().st_mtime_ns, item.path.stat().st_size)
                    + (item.start, item.offset, item.duration, item.volume)
                    for item in voice_files
                ]
            )
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
        key = self._audio_key(ctx, sources, vocabulary, voice_files)
        base = ctx.project.base_dir or ctx.job_dir
        store = base / "captions.auto.json"
        cached = self._load_cached(store, key) if not ctx.options.force else None
        if cached is not None:
            return cached, store

        wav = self._voice_wav(ctx, prepared, transitions, voice_files)
        prompt = (", ".join(vocabulary) + ".") if vocabulary else None
        try:
            transcript = self.transcriber_factory(captions).transcribe(wav, captions.language, prompt)
        except RuntimeError as exc:
            ctx.warn(f"Legendas automáticas puladas: {exc}")
            return None, None
        payload = json.loads(to_json(transcript.cues, captions.language))
        payload.update({"hash": key, "meta": transcript.meta})
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        (base / "captions.auto.srt").write_text(to_srt(transcript.cues), encoding="utf-8")
        return transcript.cues, store

    @staticmethod
    def _load_cached(store: Path, key: str) -> list[Cue] | None:
        if not store.exists():
            return None
        try:
            text = store.read_text(encoding="utf-8")
            if json.loads(text).get("hash") != key:
                return None
            return from_json(text)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

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
