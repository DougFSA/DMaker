"""Produção das legendas: transcrição automática (com cache) ou arquivo, correções e reagrupamento."""

from __future__ import annotations

import json
from collections.abc import Callable
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

TranscriberFactory = Callable[[Captions], Transcriber]


def default_transcriber_factory(captions: Captions) -> Transcriber:
    return WhisperTranscriber(model=captions.model, device=captions.device)


@dataclass
class CaptionResult:
    cues: list[Cue]
    file: Path | None


class CaptionPipeline:
    def __init__(self, transcriber_factory: TranscriberFactory = default_transcriber_factory):
        self.transcriber_factory = transcriber_factory

    def produce(
        self,
        ctx: RenderContext,
        sources: list[Source],
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
    ) -> CaptionResult | None:
        project, options = ctx.project, ctx.options
        captions = project.captions
        if not captions or not captions.enabled or options.no_captions or options.dry_run:
            return None
        vocabulary = list(ctx.theme.captions.get("vocabulary", [])) + list(captions.vocabulary)
        replacements = {**ctx.theme.captions.get("replacements", {}), **captions.replacements}

        if captions.source == "auto":
            if project.audio.mute_clips:
                return None
            cues, store = self._auto(ctx, sources, prepared, transitions, vocabulary)
            if cues is None:
                return None
        else:
            store = project.resolve(captions.source)
            if not store.exists():
                raise FileNotFoundError(f"captions.source não encontrado: {captions.source}")
            cues = load_captions(store)

        cues = apply_replacements(cues, replacements)
        if captions.offset:
            cues = shift(cues, captions.offset)
        style = captions.style
        if style.mode == "karaoke" or any(cue.words for cue in cues):
            cues = regroup(cues, style.max_words, style.max_chars)
        return CaptionResult(cues, store)

    # ---------- transcrição automática com cache ----------

    def _audio_key(self, ctx: RenderContext, sources: list[Source], vocabulary: list[str]) -> str:
        captions = ctx.project.captions
        assert captions is not None
        parts = [
            (seg.model_dump(mode="json"), str(src.path), src.stat_key())
            for seg, src in zip(ctx.project.timeline, sources, strict=True)
        ]
        return cache_key(parts, ctx.project.audio.voice_gain, captions.language, captions.model, vocabulary)

    def _auto(
        self,
        ctx: RenderContext,
        sources: list[Source],
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        vocabulary: list[str],
    ) -> tuple[list[Cue] | None, Path | None]:
        captions = ctx.project.captions
        assert captions is not None
        key = self._audio_key(ctx, sources, vocabulary)
        base = ctx.project.base_dir or ctx.job_dir
        store = base / "captions.auto.json"
        cached = self._load_cached(store, key) if not ctx.options.force else None
        if cached is not None:
            return cached, store

        wav = self._voice_wav(ctx, prepared, transitions)
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
        ctx: RenderContext, prepared: list[PreparedSegment], transitions: list[Transition | None]
    ) -> Path:
        """Só a voz da linha do tempo (sem música nem normalização), mono 16 kHz para o modelo."""
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
